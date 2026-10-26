"""
Plexis Storage Abstraction — Contracts and Exceptions
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Dict, Any, BinaryIO


class StorageError(Exception):
    """Base exception for all storage operations."""
    pass


class StorageObjectNotFoundError(StorageError):
    """Raised when the requested object key is not found in the storage bucket."""
    pass


class StorageAccountNotConfiguredError(StorageError):
    """Raised when attempting an operation on an unconfigured storage account."""
    pass


class StoragePermissionError(StorageError):
    """Raised on 401/403 or signature mismatch from storage provider."""
    pass


class StorageTimeoutError(StorageError):
    """Raised when a storage request times out."""
    pass


@dataclass
class StorageAccountConfig:
    """Configuration for an S3-compatible / Cloudflare R2 account."""
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket_name: str
    endpoint_url: Optional[str] = None
    account_alias: str = "primary"

    @property
    def is_configured(self) -> bool:
        """Return True if credentials and bucket are provided."""
        return bool(self.access_key_id and self.secret_access_key and self.bucket_name)

    def get_endpoint_url(self) -> str:
        """Resolve endpoint URL: custom override or standard Cloudflare R2 endpoint."""
        if self.endpoint_url:
            return self.endpoint_url.rstrip("/")
        if self.account_id:
            return f"https://{self.account_id}.r2.cloudflarestorage.com"
        return ""


@dataclass
class StorageObjectMetadata:
    """Metadata describing a stored object."""
    key: str
    account_alias: str
    size_bytes: int
    content_type: str = "application/octet-stream"
    etag: Optional[str] = None
    last_modified: Optional[datetime] = None
    user_metadata: Dict[str, str] = field(default_factory=dict)


@dataclass
class StorageResult:
    """Result of a storage write operation."""
    key: str
    account_alias: str
    size_bytes: int
    etag: Optional[str] = None
    version_id: Optional[str] = None
    success: bool = True
