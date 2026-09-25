"""Dataset fingerprint generation."""
import hashlib
from typing import List

def file_fingerprint(file_path: str) -> str:
    hasher = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def schema_fingerprint(columns: List[str], dtypes: List[str]) -> str:
    hasher = hashlib.sha256()
    schema = sorted(zip(columns, dtypes))
    schema_str = str(schema).encode('utf-8')
    hasher.update(schema_str)
    return hasher.hexdigest()
