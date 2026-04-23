"""Utility helpers for biffile_data."""

from __future__ import annotations

import hashlib
import os
import uuid


def sha256_of_bytes(data: bytes) -> str:
    """Return the hex-encoded SHA-256 digest of *data*."""
    return hashlib.sha256(data).hexdigest()


def sha256_of_file(path: str, buf_size: int = 1 << 20) -> str:
    """Return the hex-encoded SHA-256 digest of the file at *path*."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(buf_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def new_id() -> str:
    """Return a new random UUID string (no hyphens)."""
    return uuid.uuid4().hex


def ensure_dir(path: str) -> str:
    """Create *path* (and parents) if it does not exist; return *path*."""
    os.makedirs(path, exist_ok=True)
    return path


def human_readable_size(num_bytes: int) -> str:
    """Return a human-readable representation of *num_bytes*."""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"
