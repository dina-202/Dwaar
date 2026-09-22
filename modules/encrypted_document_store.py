"""Authenticated encrypted local document storage for Dwaar.

This is a pilot/single-node DocumentStore implementation. The encryption key
is injected by the caller and is never persisted by this module.
"""

from __future__ import annotations

import os
import re
import tempfile
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


_MAGIC = b"DWAAR1\x00"
_NONCE_BYTES = 12
_KEY_PATTERN = re.compile(r"^objects/[0-9a-f]{32}$")
_DEFAULT_MAX_BYTES = 20 * 1024 * 1024


class DocumentStoreError(RuntimeError):
    pass


class DocumentNotFoundError(DocumentStoreError):
    pass


class DocumentIntegrityError(DocumentStoreError):
    pass


class DocumentAlreadyExistsError(DocumentStoreError):
    pass


def generate_storage_key() -> str:
    """Generate an opaque application-owned document storage key."""
    return "objects/" + uuid.uuid4().hex


class EncryptedLocalDocumentStore:
    """AES-256-GCM encrypted store rooted outside application static files."""

    def __init__(
        self,
        root_dir: str,
        key: bytes,
        max_bytes: int = _DEFAULT_MAX_BYTES,
    ):
        if not isinstance(root_dir, str) or not root_dir.strip():
            raise ValueError("root_dir must be a non-empty string")
        if not isinstance(key, bytes) or len(key) != 32:
            raise ValueError("key must be exactly 32 bytes for AES-256-GCM")
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or max_bytes <= 0
        ):
            raise ValueError("max_bytes must be a positive integer")

        self._root = Path(root_dir).resolve()
        self._key = key
        self._max_bytes = max_bytes
        self._root.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._root, 0o700)
        except OSError:
            # Some platforms/filesystems do not implement POSIX modes.
            pass

    @property
    def root_dir(self) -> str:
        return str(self._root)

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    @staticmethod
    def _validate_storage_key(storage_key: str) -> str:
        if not isinstance(storage_key, str) or not _KEY_PATTERN.fullmatch(
            storage_key
        ):
            raise ValueError(
                "storage_key must use Dwaar's opaque objects/<uuidhex> format"
            )
        return storage_key

    def _path(self, storage_key: str) -> Path:
        validated = self._validate_storage_key(storage_key)
        object_id = validated.split("/", 1)[1]
        # No user-controlled path fragment is used beyond the strict 32-hex ID.
        return self._root / f"{object_id}.dwaar"

    def put(self, storage_key: str, payload: bytes) -> None:
        path = self._path(storage_key)
        if not isinstance(payload, bytes):
            raise TypeError("payload must be bytes")
        if not payload:
            raise ValueError("payload must not be empty")
        if len(payload) > self._max_bytes:
            raise ValueError("payload exceeds configured document size limit")
        if path.exists():
            raise DocumentAlreadyExistsError(
                "document storage key already exists"
            )

        nonce = os.urandom(_NONCE_BYTES)
        aesgcm = AESGCM(self._key)
        ciphertext = aesgcm.encrypt(
            nonce,
            payload,
            storage_key.encode("utf-8"),
        )
        encoded = _MAGIC + nonce + ciphertext

        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self._root,
                prefix=".tmp-",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                try:
                    os.chmod(temp_path, 0o600)
                except OSError:
                    pass
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())

            # Atomically publish without overwrite. Hard-link creation
            # fails if another writer already claimed the same storage key.
            try:
                os.link(temp_path, path)
            except FileExistsError as error:
                raise DocumentAlreadyExistsError(
                    "document storage key already exists"
                ) from error
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def get(self, storage_key: str) -> bytes:
        path = self._path(storage_key)
        try:
            encoded = path.read_bytes()
        except FileNotFoundError as error:
            raise DocumentNotFoundError("document does not exist") from error

        minimum_length = len(_MAGIC) + _NONCE_BYTES + 16
        if len(encoded) < minimum_length or not encoded.startswith(_MAGIC):
            raise DocumentIntegrityError(
                "stored document envelope is invalid"
            )

        nonce_start = len(_MAGIC)
        nonce_end = nonce_start + _NONCE_BYTES
        nonce = encoded[nonce_start:nonce_end]
        ciphertext = encoded[nonce_end:]

        try:
            return AESGCM(self._key).decrypt(
                nonce,
                ciphertext,
                storage_key.encode("utf-8"),
            )
        except InvalidTag as error:
            raise DocumentIntegrityError(
                "stored document authentication failed"
            ) from error

    def delete(self, storage_key: str) -> None:
        path = self._path(storage_key)
        try:
            path.unlink()
        except FileNotFoundError as error:
            raise DocumentNotFoundError("document does not exist") from error

    def exists(self, storage_key: str) -> bool:
        return self._path(storage_key).is_file()
