"""
Plexis Object Storage Package.
"""
from storage.contracts import (
    StorageAccountConfig,
    StorageObjectMetadata,
    StorageResult,
    StorageError,
    StorageObjectNotFoundError,
    StorageAccountNotConfiguredError,
    StoragePermissionError,
    StorageTimeoutError,
)
from storage.r2_client import R2Client
from storage.manager import storage_manager, StorageManager

__all__ = [
    "storage_manager",
    "StorageManager",
    "R2Client",
    "StorageAccountConfig",
    "StorageObjectMetadata",
    "StorageResult",
    "StorageError",
    "StorageObjectNotFoundError",
    "StorageAccountNotConfiguredError",
    "StoragePermissionError",
    "StorageTimeoutError",
]
