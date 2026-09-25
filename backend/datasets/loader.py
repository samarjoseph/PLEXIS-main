"""Dataset loader module."""
import os
import time
import logging
import pandas as pd
from typing import Optional
from core.errors import ValidationError

logger = logging.getLogger(__name__)

class DatasetLoader:
    def load(self, file_path: str) -> pd.DataFrame:
        if not os.path.exists(file_path):
            raise ValidationError(f"File not found: {file_path}")
            
        _, ext = os.path.splitext(file_path)
        ext = ext.lower()
        
        start_time = time.time()
        
        try:
            if ext == '.csv':
                try:
                    df = pd.read_csv(file_path, encoding='utf-8')
                except UnicodeDecodeError:
                    df = pd.read_csv(file_path, encoding='latin-1')
            elif ext in ('.xlsx', '.xls'):
                df = pd.read_excel(file_path, engine='openpyxl')
            else:
                raise ValidationError(f"Unsupported file extension: {ext}")
                
            # Clean up
            df.columns = df.columns.str.strip()
            df = df.dropna(how='all')
            df = df.dropna(axis=1, how='all')
            
            # Infer datetime
            for col in df.columns:
                if df[col].dtype == 'object':
                    try:
                        converted = pd.to_datetime(df[col], errors='ignore', infer_datetime_format=True)
                        if pd.api.types.is_datetime64_any_dtype(converted):
                            df[col] = converted
                    except Exception:
                        pass
                        
            load_time = time.time() - start_time
            logger.info(f"Loaded {file_path} in {load_time:.2f}s, shape: {df.shape}")
            
            return df
            
        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            logger.error(f"Failed to load dataset {file_path}: {e}")
            raise ValidationError(f"Failed to load dataset: {str(e)}")

dataset_loader = DatasetLoader()
