"""Detailed column profiling module."""
import logging
import pandas as pd
from typing import Dict, Any
from datasets.profiler import dataset_profiler

logger = logging.getLogger(__name__)

class ColumnProfiler:
    def profile(self, df: pd.DataFrame, column_name: str) -> Dict[str, Any]:
        if column_name not in df.columns:
            return {}
            
        col_series = df[column_name]
        col_types = {item['name']: item['dtype'] for item in dataset_profiler.get_column_types(df)}
        friendly_type = col_types.get(str(column_name), 'text')
        
        # Determine category based on friendly type
        if friendly_type in ['integer', 'decimal']:
            category = 'numeric'
        elif friendly_type in ['datetime']:
            category = 'datetime'
        elif friendly_type in ['boolean']:
            category = 'boolean'
        else:
            category = 'categorical'
            
        if category == 'numeric':
            return {
                'type': 'numeric',
                'min': float(col_series.min()) if not pd.isna(col_series.min()) else None,
                'max': float(col_series.max()) if not pd.isna(col_series.max()) else None,
                'mean': float(col_series.mean()) if not pd.isna(col_series.mean()) else None,
                'median': float(col_series.median()) if not pd.isna(col_series.median()) else None,
                'std': float(col_series.std()) if not pd.isna(col_series.std()) else None,
                'q25': float(col_series.quantile(0.25)) if not pd.isna(col_series.quantile(0.25)) else None,
                'q75': float(col_series.quantile(0.75)) if not pd.isna(col_series.quantile(0.75)) else None,
            }
        elif category == 'categorical':
            val_counts = col_series.value_counts(dropna=True).head(10)
            top_values = [(str(k), int(v)) for k, v in val_counts.items()]
            return {
                'type': 'categorical',
                'cardinality': int(col_series.nunique(dropna=True)),
                'top_values': top_values,
            }
        elif category == 'datetime':
            return {
                'type': 'datetime',
                'min_date': col_series.min().isoformat() if not pd.isna(col_series.min()) else None,
                'max_date': col_series.max().isoformat() if not pd.isna(col_series.max()) else None,
                'range_days': int((col_series.max() - col_series.min()).days) if not pd.isna(col_series.max()) and not pd.isna(col_series.min()) else None
            }
        elif category == 'boolean':
            return {
                'type': 'boolean',
                'true_count': int((col_series == True).sum()),
                'false_count': int((col_series == False).sum()),
                'null_count': int(col_series.isna().sum())
            }
            
        return {}

    def profile_all(self, df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        return {str(col): self.profile(df, str(col)) for col in df.columns}

column_profiler = ColumnProfiler()
