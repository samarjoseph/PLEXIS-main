"""Schema profiling module."""
import logging
import pandas as pd
from typing import List, Dict, Any
from datasets.profiler import dataset_profiler

logger = logging.getLogger(__name__)

class SchemaProfiler:
    def profile(self, df: pd.DataFrame) -> List[Dict[str, Any]]:
        profiles = []
        col_types = {item['name']: item['dtype'] for item in dataset_profiler.get_column_types(df)}
        
        for col in df.columns:
            total = len(df)
            null_count = int(df[col].isna().sum())
            unique_count = int(df[col].nunique(dropna=True))
            
            # Get up to 5 non-null sample values
            sample_series = df[col].dropna().head(5)
            sample_values = [str(x) for x in sample_series.tolist()]
            
            null_percentage = 0.0
            if total > 0:
                null_percentage = round((null_count / total) * 100, 2)
                
            profiles.append({
                'name': str(col),
                'dtype': col_types.get(str(col), 'text'),
                'null_count': null_count,
                'null_percentage': float(null_percentage),
                'unique_count': unique_count,
                'sample_values': sample_values
            })
        return profiles

schema_profiler = SchemaProfiler()
