"""
Plexis Storage Manager — Account-Aware Router and Key Builder.

Enforces:
- Explicit routing by storage account identifier ('primary', 'secondary', or custom).
- Safe server-controlled object key generation without user-controlled paths.
- Strict isolation between Account A and Account B.
- No silent cross-account fallbacks on missing keys.
"""
from __future__ import annotations

import os
import re
import uuid
import logging
from typing import Optional, Dict, Any, BinaryIO

from config import Config
from storage.contracts import (
    StorageAccountConfig,
    StorageObjectMetadata,
    StorageResult,
    StorageError,
    StorageObjectNotFoundError,
    StorageAccountNotConfiguredError,
)
from storage.r2_client import R2Client

logger = logging.getLogger(__name__)


class StorageManager:
    """
    Central storage service managing multiple storage accounts and key conventions.
    """

    PRIMARY_ALIAS = "primary"
    SECONDARY_ALIAS = "secondary"

    def __init__(self):
        self._clients: Dict[str, R2Client] = {}
        self._init_accounts()

    def _init_accounts(self) -> None:
        """Initialize primary and secondary account clients from Config."""
        # Account A (Primary)
        primary_cfg = StorageAccountConfig(
            account_id=Config.R2_ACCOUNT_ID,
            access_key_id=Config.R2_ACCESS_KEY_ID,
            secret_access_key=Config.R2_SECRET_ACCESS_KEY,
            bucket_name=Config.R2_BUCKET_NAME,
            endpoint_url=Config.R2_ENDPOINT_URL or None,
            account_alias=self.PRIMARY_ALIAS,
        )
        self._clients[self.PRIMARY_ALIAS] = R2Client(primary_cfg)
        self._clients["a"] = self._clients[self.PRIMARY_ALIAS]
        self._clients["account_a"] = self._clients[self.PRIMARY_ALIAS]

        # Account B (Secondary — Optional)
        if Config.R2_B_ACCESS_KEY_ID or Config.R2_B_BUCKET_NAME or Config.R2_B_ACCOUNT_ID:
            secondary_cfg = StorageAccountConfig(
                account_id=Config.R2_B_ACCOUNT_ID,
                access_key_id=Config.R2_B_ACCESS_KEY_ID,
                secret_access_key=Config.R2_B_SECRET_ACCESS_KEY,
                bucket_name=Config.R2_B_BUCKET_NAME,
                endpoint_url=Config.R2_B_ENDPOINT_URL or None,
                account_alias=self.SECONDARY_ALIAS,
            )
            self._clients[self.SECONDARY_ALIAS] = R2Client(secondary_cfg)
            self._clients["b"] = self._clients[self.SECONDARY_ALIAS]
            self._clients["account_b"] = self._clients[self.SECONDARY_ALIAS]
            logger.info("[StorageManager] Initialized dual storage accounts (primary and secondary).")
        else:
            logger.info("[StorageManager] Initialized single storage account (primary).")

    def get_client(self, account_identifier: Optional[str] = None) -> R2Client:
        """
        Resolve client for the given account identifier.
        Strict: Does NOT silently fallback to another account if the requested account is missing.
        """
        acc_key = (account_identifier or self.PRIMARY_ALIAS).lower().strip()
        client = self._clients.get(acc_key)
        if not client:
            raise StorageAccountNotConfiguredError(
                f"Storage account '{account_identifier}' is not configured on this server."
            )
        return client

    def is_account_configured(self, account_identifier: str) -> bool:
        """Check if an account identifier is registered and has cloud/local client."""
        return (account_identifier or "").lower().strip() in self._clients

    # -------------------------------------------------------------------------
    # Server-Controlled Key Builders
    # -------------------------------------------------------------------------

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize a filename so it cannot traverse directories or break object keys."""
        base = os.path.basename(filename) if hasattr(os, 'path') else filename
        clean = re.sub(r'[^a-zA-Z0-9._-]', '_', base)
        return clean[:100] or "dataset.csv"

    def build_original_key(self, user_id: str | uuid.UUID, dataset_id: str | uuid.UUID, filename: str) -> str:
        """Generate safe key for an original uploaded dataset file."""
        safe_fn = self.sanitize_filename(filename)
        return f"users/{user_id}/datasets/{dataset_id}/original/{safe_fn}"

    def build_snapshot_key(self, user_id: str | uuid.UUID, dataset_id: str | uuid.UUID, revision: int, ext: str = "parquet") -> str:
        """Generate safe key for a dataset revision snapshot."""
        return f"users/{user_id}/datasets/{dataset_id}/snapshots/rev_{revision:06d}.{ext}"

    def build_history_segment_key(self, user_id: str | uuid.UUID, dataset_id: str | uuid.UUID, segment_id: str) -> str:
        """Generate safe key for a compacted action history segment."""
        clean_seg = re.sub(r'[^a-zA-Z0-9._-]', '_', str(segment_id))
        return f"users/{user_id}/datasets/{dataset_id}/history/segment_{clean_seg}.jsonl"

    # -------------------------------------------------------------------------
    # Routed Storage Operations
    # -------------------------------------------------------------------------

    def put_object(
        self,
        key: str,
        data: bytes | BinaryIO,
        account_identifier: Optional[str] = None,
        content_type: str = "application/octet-stream",
        metadata: Optional[Dict[str, str]] = None,
    ) -> StorageResult:
        """Store an object in the specified storage account."""
        client = self.get_client(account_identifier)
        return client.put_object(key=key, data=data, content_type=content_type, metadata=metadata)

    def get_object(self, key: str, account_identifier: Optional[str] = None) -> bytes:
        """Download an object from the specified storage account."""
        client = self.get_client(account_identifier)
        return client.get_object(key=key)

    def get_object_stream(self, key: str, account_identifier: Optional[str] = None) -> BinaryIO:
        """Stream an object from the specified storage account."""
        client = self.get_client(account_identifier)
        return client.get_object_stream(key=key)

    def head_object(self, key: str, account_identifier: Optional[str] = None) -> Optional[StorageObjectMetadata]:
        """Check metadata for an object in the specified storage account."""
        client = self.get_client(account_identifier)
        return client.head_object(key=key)

    def object_exists(self, key: str, account_identifier: Optional[str] = None) -> bool:
        """Check object existence in the specified storage account."""
        client = self.get_client(account_identifier)
        return client.object_exists(key=key)

    def delete_object(self, key: str, account_identifier: Optional[str] = None) -> bool:
        """Delete an object from the specified storage account."""
        client = self.get_client(account_identifier)
        return client.delete_object(key=key)

    def upload_file(
        self,
        key: str,
        source_local_path: str,
        account_identifier: Optional[str] = None,
        content_type: str = "application/octet-stream",
        metadata: Optional[Dict[str, str]] = None,
    ) -> StorageResult:
        """Upload a file from local filesystem to the specified storage account."""
        client = self.get_client(account_identifier)
        return client.upload_file(key=key, source_local_path=source_local_path, content_type=content_type, metadata=metadata)

    def download_file(self, key: str, target_local_path: str, account_identifier: Optional[str] = None) -> None:
        """Download an object to a local filesystem destination."""
        client = self.get_client(account_identifier)
        client.download_file(key=key, target_local_path=target_local_path)


# Global singleton instance
storage_manager = StorageManager()
