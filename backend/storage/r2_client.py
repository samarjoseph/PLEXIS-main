"""
Plexis S3 / Cloudflare R2 Client Implementation.

Provides uniform object storage operations via boto3.
Falls back to local file emulation if credentials are not configured,
enabling development and testing without live cloud infrastructure.
"""
from __future__ import annotations

import io
import os
import shutil
import mimetypes
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, BinaryIO, Generator

from storage.contracts import (
    StorageAccountConfig,
    StorageObjectMetadata,
    StorageResult,
    StorageError,
    StorageObjectNotFoundError,
    StoragePermissionError,
    StorageTimeoutError,
)

logger = logging.getLogger(__name__)


class R2Client:
    """
    Client for interacting with Cloudflare R2 or S3-compatible object stores.
    One instance per configured account.
    """

    def __init__(self, config: StorageAccountConfig):
        self.config = config
        self.account_alias = config.account_alias
        self._s3_client = None
        self._local_fallback_dir = None

        if self.config.is_configured:
            self._init_s3_client()
        else:
            self._init_local_fallback()

    def _init_s3_client(self) -> None:
        """Initialize boto3 S3 client with Cloudflare R2 settings."""
        try:
            import boto3
            import botocore.client
            from botocore.config import Config as BotoConfig

            endpoint_url = self.config.get_endpoint_url()
            boto_config = BotoConfig(
                signature_version="s3v4",
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=10,
                read_timeout=60,
            )

            self._s3_client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=self.config.access_key_id,
                aws_secret_access_key=self.config.secret_access_key,
                config=boto_config,
            )
            logger.info(
                "[R2Client] Initialized S3 client for account '%s' (bucket: %s, endpoint: %s)",
                self.account_alias,
                self.config.bucket_name,
                endpoint_url,
            )
        except Exception as exc:
            logger.warning(
                "[R2Client] Failed to initialize S3 client for '%s' (%s). Falling back to local storage.",
                self.account_alias,
                exc,
            )
            self._init_local_fallback()

    def _init_local_fallback(self) -> None:
        """Initialize local filesystem emulation for development/testing."""
        from config import Config
        base_dir = os.path.join(Config.UPLOAD_FOLDER, "r2_emulated", self.account_alias)
        os.makedirs(base_dir, exist_ok=True)
        self._local_fallback_dir = base_dir
        self._s3_client = None
        logger.info(
            "[R2Client] Running in local filesystem fallback mode for account '%s' at '%s'",
            self.account_alias,
            self._local_fallback_dir,
        )

    @property
    def is_cloud(self) -> bool:
        """Return True if connected to real S3/R2 cloud storage."""
        return self._s3_client is not None

    def _handle_client_error(self, exc: Exception, key: str) -> None:
        """Map botocore ClientError to typed StorageError."""
        err_code = ""
        msg = str(exc)
        if hasattr(exc, "response") and isinstance(exc.response, dict):
            err_code = exc.response.get("Error", {}).get("Code", "")
            msg = exc.response.get("Error", {}).get("Message", msg)

        if err_code in ("NoSuchKey", "404", "NotFound"):
            raise StorageObjectNotFoundError(f"Object '{key}' not found in bucket '{self.config.bucket_name}'") from exc
        if err_code in ("AccessDenied", "403", "InvalidAccessKeyId", "SignatureDoesNotMatch"):
            raise StoragePermissionError(f"Permission denied for object '{key}' on account '{self.account_alias}': {msg}") from exc
        if "timed out" in msg.lower() or "timeout" in msg.lower():
            raise StorageTimeoutError(f"Timeout accessing object '{key}': {msg}") from exc

        raise StorageError(f"Storage operation failed on account '{self.account_alias}' for key '{key}': {msg}") from exc

    # -------------------------------------------------------------------------
    # Core Operations
    # -------------------------------------------------------------------------

    def put_object(
        self,
        key: str,
        data: bytes | BinaryIO,
        content_type: str = "application/octet-stream",
        metadata: Optional[Dict[str, str]] = None,
    ) -> StorageResult:
        """Upload raw bytes or file-like object to R2."""
        safe_key = key.lstrip("/")
        meta_dict = metadata or {}

        if self._s3_client:
            try:
                body = data
                size = 0
                if isinstance(data, (bytes, bytearray)):
                    size = len(data)
                elif hasattr(data, "seek") and hasattr(data, "tell"):
                    data.seek(0, os.SEEK_END)
                    size = data.tell()
                    data.seek(0)

                resp = self._s3_client.put_object(
                    Bucket=self.config.bucket_name,
                    Key=safe_key,
                    Body=body,
                    ContentType=content_type,
                    Metadata=meta_dict,
                )
                return StorageResult(
                    key=safe_key,
                    account_alias=self.account_alias,
                    size_bytes=size,
                    etag=resp.get("ETag", "").strip('"'),
                    version_id=resp.get("VersionId"),
                    success=True,
                )
            except Exception as e:
                self._handle_client_error(e, safe_key)

        # Local Fallback
        local_path = os.path.join(self._local_fallback_dir, safe_key)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        if isinstance(data, (bytes, bytearray)):
            with open(local_path, "wb") as f:
                f.write(data)
            size = len(data)
        else:
            with open(local_path, "wb") as f:
                shutil.copyfileobj(data, f)
            size = os.path.getsize(local_path)

        return StorageResult(
            key=safe_key,
            account_alias=self.account_alias,
            size_bytes=size,
            etag="local-mock-etag",
            success=True,
        )

    def get_object(self, key: str) -> bytes:
        """Download complete object content as bytes."""
        safe_key = key.lstrip("/")
        if self._s3_client:
            try:
                resp = self._s3_client.get_object(Bucket=self.config.bucket_name, Key=safe_key)
                return resp["Body"].read()
            except Exception as e:
                self._handle_client_error(e, safe_key)

        local_path = os.path.join(self._local_fallback_dir, safe_key)
        if not os.path.exists(local_path):
            raise StorageObjectNotFoundError(f"Object '{safe_key}' not found in local store.")
        with open(local_path, "rb") as f:
            return f.read()

    def get_object_stream(self, key: str) -> BinaryIO:
        """Get a readable binary stream for the object."""
        safe_key = key.lstrip("/")
        if self._s3_client:
            try:
                resp = self._s3_client.get_object(Bucket=self.config.bucket_name, Key=safe_key)
                return resp["Body"]
            except Exception as e:
                self._handle_client_error(e, safe_key)

        local_path = os.path.join(self._local_fallback_dir, safe_key)
        if not os.path.exists(local_path):
            raise StorageObjectNotFoundError(f"Object '{safe_key}' not found in local store.")
        return open(local_path, "rb")

    def head_object(self, key: str) -> Optional[StorageObjectMetadata]:
        """Fetch metadata for an object without downloading body."""
        safe_key = key.lstrip("/")
        if self._s3_client:
            try:
                resp = self._s3_client.head_object(Bucket=self.config.bucket_name, Key=safe_key)
                return StorageObjectMetadata(
                    key=safe_key,
                    account_alias=self.account_alias,
                    size_bytes=resp.get("ContentLength", 0),
                    content_type=resp.get("ContentType", "application/octet-stream"),
                    etag=resp.get("ETag", "").strip('"'),
                    last_modified=resp.get("LastModified"),
                    user_metadata=resp.get("Metadata", {}),
                )
            except Exception as e:
                err_code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
                if err_code in ("404", "NoSuchKey", "NotFound"):
                    return None
                self._handle_client_error(e, safe_key)

        local_path = os.path.join(self._local_fallback_dir, safe_key)
        if not os.path.exists(local_path):
            return None
        stat = os.stat(local_path)
        guessed_type, _ = mimetypes.guess_type(local_path)
        return StorageObjectMetadata(
            key=safe_key,
            account_alias=self.account_alias,
            size_bytes=stat.st_size,
            content_type=guessed_type or "application/octet-stream",
            last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        )

    def object_exists(self, key: str) -> bool:
        """Check if an object exists in this account's bucket."""
        return self.head_object(key) is not None

    def delete_object(self, key: str) -> bool:
        """Delete an object from this account's bucket."""
        safe_key = key.lstrip("/")
        if self._s3_client:
            try:
                self._s3_client.delete_object(Bucket=self.config.bucket_name, Key=safe_key)
                return True
            except Exception as e:
                self._handle_client_error(e, safe_key)

        local_path = os.path.join(self._local_fallback_dir, safe_key)
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
                return True
            except OSError as err:
                logger.error("[R2Client] Error deleting local file %s: %s", local_path, err)
                return False
        return True

    def download_file(self, key: str, target_local_path: str) -> None:
        """Download object directly to a local file path."""
        safe_key = key.lstrip("/")
        os.makedirs(os.path.dirname(os.path.abspath(target_local_path)), exist_ok=True)
        if self._s3_client:
            try:
                self._s3_client.download_file(self.config.bucket_name, safe_key, target_local_path)
                return
            except Exception as e:
                self._handle_client_error(e, safe_key)

        local_path = os.path.join(self._local_fallback_dir, safe_key)
        if not os.path.exists(local_path):
            raise StorageObjectNotFoundError(f"Object '{safe_key}' not found in local store.")
        shutil.copyfile(local_path, target_local_path)

    def upload_file(
        self,
        key: str,
        source_local_path: str,
        content_type: str = "application/octet-stream",
        metadata: Optional[Dict[str, str]] = None,
    ) -> StorageResult:
        """Upload a local file path directly to R2."""
        safe_key = key.lstrip("/")
        if not os.path.exists(source_local_path):
            raise StorageError(f"Local source file '{source_local_path}' does not exist.")

        size = os.path.getsize(source_local_path)
        if self._s3_client:
            try:
                extra_args = {"ContentType": content_type}
                if metadata:
                    extra_args["Metadata"] = metadata
                self._s3_client.upload_file(
                    Filename=source_local_path,
                    Bucket=self.config.bucket_name,
                    Key=safe_key,
                    ExtraArgs=extra_args,
                )
                return StorageResult(
                    key=safe_key,
                    account_alias=self.account_alias,
                    size_bytes=size,
                    success=True,
                )
            except Exception as e:
                self._handle_client_error(e, safe_key)

        # Local Fallback
        target_path = os.path.join(self._local_fallback_dir, safe_key)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.copyfile(source_local_path, target_path)
        return StorageResult(
            key=safe_key,
            account_alias=self.account_alias,
            size_bytes=size,
            etag="local-mock-etag",
            success=True,
        )
