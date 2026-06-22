"""Blob storage on a local volume.

Files are stored under ``{data_dir}/blobs/<file-id>`` where ``file-id`` is an
opaque UUID. The original filename is kept only in the database and surfaced
via ``Content-Disposition`` at download time — it never appears in a URL or on
disk path.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from fastapi import UploadFile

from .config import settings

BLOB_DIR = Path(settings.data_dir) / "blobs"

CHUNK = 1024 * 1024  # 1 MiB


class UploadTooLarge(Exception):
    def __init__(self, limit: int):
        super().__init__(f"upload exceeds limit of {limit} bytes")
        self.limit = limit


def _path_for(file_id: str) -> Path:
    return BLOB_DIR / file_id


def ensure_dirs() -> None:
    BLOB_DIR.mkdir(parents=True, exist_ok=True)


async def save_upload(upload: UploadFile, file_id: str, max_bytes: int) -> tuple[int, str]:
    """Stream ``upload`` to disk, enforcing ``max_bytes``.

    Returns ``(size_bytes, sha256_hex)``. Raises :class:`UploadTooLarge` (after
    cleaning up the partial file) if the size limit is exceeded.
    """
    ensure_dirs()
    dest = _path_for(file_id)
    hasher = hashlib.sha256()
    size = 0
    try:
        with open(dest, "wb") as out:
            while True:
                chunk = await upload.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise UploadTooLarge(max_bytes)
                hasher.update(chunk)
                out.write(chunk)
    except UploadTooLarge:
        dest.unlink(missing_ok=True)
        raise
    return size, hasher.hexdigest()


def blob_path(file_id: str) -> Path | None:
    p = _path_for(file_id)
    return p if p.exists() else None


def delete_blob(file_id: str) -> None:
    _path_for(file_id).unlink(missing_ok=True)


def disk_usage_bytes() -> int:
    ensure_dirs()
    return sum(f.stat().st_size for f in BLOB_DIR.glob("*") if f.is_file())
