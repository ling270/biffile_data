"""Metadata management for large file storage."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class ChunkInfo:
    """Describes a single chunk of a stored file."""

    index: int
    chunk_id: str
    size: int
    checksum: str


@dataclass
class FileMetadata:
    """Full metadata record for a stored file."""

    file_id: str
    original_name: str
    total_size: int
    chunk_size: int
    chunks: List[ChunkInfo] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    content_type: Optional[str] = None

    # ------------------------------------------------------------------ #
    # serialisation
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FileMetadata":
        chunks = [ChunkInfo(**c) for c in d.pop("chunks", [])]
        meta = cls(**d)
        meta.chunks = chunks
        return meta

    def save(self, meta_dir: str) -> None:
        os.makedirs(meta_dir, exist_ok=True)
        path = os.path.join(meta_dir, f"{self.file_id}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(self.to_dict(), fh, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, meta_dir: str, file_id: str) -> "FileMetadata":
        path = os.path.join(meta_dir, f"{file_id}.json")
        if not os.path.exists(path):
            raise FileNotFoundError(f"No metadata for file_id={file_id!r}")
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    @classmethod
    def list_all(cls, meta_dir: str) -> List["FileMetadata"]:
        if not os.path.isdir(meta_dir):
            return []
        result = []
        for fname in sorted(os.listdir(meta_dir)):
            if fname.endswith(".json"):
                file_id = fname[:-5]
                result.append(cls.load(meta_dir, file_id))
        return result
