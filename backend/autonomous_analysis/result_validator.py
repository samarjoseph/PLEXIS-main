import re
import math
from typing import Dict, Any, List

from autonomous_analysis.contracts import InvestigationResult, NumericalGrounding

class ResultValidator:
    def validate(self, result: InvestigationResult) -> InvestigationResult:
        if result.status == "failed":
            return result
            
        try:
            if not result.result_data:
                raise ValueError("result_data is empty")
                
            self._check_nan_inf(result.result_data)
            self._check_pct_counts(result.result_data)
            
            grounding = self._extract_grounding(result.result_data)
            result.grounding = grounding
            
        except Exception as e:
            result.status = "failed"
            result.error = str(e)
            
        return result

    def _check_nan_inf(self, data: Any):
        if isinstance(data, dict):
            for v in data.values():
                self._check_nan_inf(v)
        elif isinstance(data, list):
            for v in data:
                self._check_nan_inf(v)
        elif isinstance(data, float):
            if math.isnan(data):
                raise ValueError("NaN value found in result_data")
            if math.isinf(data):
                raise ValueError("Inf value found in result_data")

    def _check_pct_counts(self, data: Any, key: str = ""):
        if isinstance(data, dict):
            for k, v in data.items():
                self._check_pct_counts(v, k)
        elif isinstance(data, list):
            for v in data:
                self._check_pct_counts(v, key)
        elif isinstance(data, (int, float)):
            if key.endswith("_pct") or "percentage" in key.lower():
                if not (0 <= data <= 100):
                    raise ValueError(f"Percentage {key} out of bounds: {data}")
            if key.endswith("_count"):
                if data < 0:
                    raise ValueError(f"Count {key} is negative: {data}")

    def _extract_grounding(self, data: dict) -> NumericalGrounding:
        values = []
        percentages = []
        
        def _walk(d: Any, k: str = ""):
            if isinstance(d, dict):
                for key, val in d.items():
                    _walk(val, key)
            elif isinstance(d, list):
                for val in d:
                    _walk(val, k)
            elif isinstance(d, (int, float)) and not isinstance(d, bool):
                values.append(float(d))
                if k.endswith("_pct") or "percentage" in k.lower():
                    percentages.append(float(d))
                    
        _walk(data)
        
        return NumericalGrounding(
            values=values, 
            percentages=percentages, 
            tolerance=0.01
        )

    def check_interpretation(self, interpretation: str, grounding: NumericalGrounding) -> bool:
        if not interpretation or not grounding:
            return True
            
        numbers = re.findall(r'\b(\d+(?:\.\d+)?)%?\b', interpretation)
        for num_str in numbers:
            num = float(num_str)
            if num > 0.1:
                # Assuming grounding has is_supported method as specified in prompt
                if hasattr(grounding, 'is_supported') and not grounding.is_supported(num):
                    return False
        return True

result_validator = ResultValidator()
