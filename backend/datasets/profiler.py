"""Dataset profiling module."""
import logging
import pandas as pd
from typing import Dict, List, Any

logger = logging.getLogger(__name__)

class DatasetProfiler:
    def format_memory(self, bytes_size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_size < 1024.0:
                return f"{bytes_size:.1f} {unit}"
            bytes_size /= 1024.0
        return f"{bytes_size:.1f} PB"

    def get_column_types(self, df: pd.DataFrame) -> List[Dict[str, str]]:
        type_mapping = {
            'int64': 'integer',
            'float64': 'decimal',
            'object': 'text',
            'datetime64': 'datetime',
            'bool': 'boolean',
            'category': 'category'
        }
        types = []
        for col, dtype in df.dtypes.items():
            dtype_str = str(dtype)
            friendly_type = 'text'
            for key, val in type_mapping.items():
                if dtype_str.startswith(key) or key in dtype_str:
                    friendly_type = val
                    break
            types.append({'name': str(col), 'dtype': friendly_type})
        return types

    def profile(self, df: pd.DataFrame) -> Dict[str, Any]:
        return {
            'rows': int(len(df)),
            'columns': int(len(df.columns)),
            'memory_usage': self.format_memory(int(df.memory_usage(deep=True).sum())),
            'column_types': self.get_column_types(df)
        }

dataset_profiler = DatasetProfiler()
