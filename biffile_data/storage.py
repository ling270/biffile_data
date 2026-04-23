"""Core storage engine for biffile_data.

Architecture
------------
A ``LargeFileStore`` manages a root directory with this layout::

    <root>/
        chunks/
            <chunk_id[:2]>/
                <chunk_id>       ← raw binary chunk data
        meta/
            <file_id>.json       ← FileMetadata JSON

Files are split into fixed-size chunks on write and reassembled on read.
Every chunk is content-addressed by its SHA-256 digest, giving natural
deduplication within a single store.
"""

from __future__ import annotations

import os
import time
from typing import Callable, Iterator, Optional

from biffile_data.metadata import ChunkInfo, FileMetadata
from biffile_data.utils import ensure_dir, new_id, sha256_of_bytes

DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB


class LargeFileStore:
    """A content-addressed store for large files.

    Parameters
    ----------
    root:
        Path to the root directory of the store (created if it does not
        exist).
    chunk_size:
        Size in bytes for each chunk written to disk.  Defaults to 8 MiB.
    """

    def __init__(self, root: str, chunk_size: int = DEFAULT_CHUNK_SIZE) -> None:
        self.root = os.path.abspath(root)
        self.chunk_size = chunk_size
        self._meta_dir = ensure_dir(os.path.join(self.root, "meta"))
        self._chunk_dir = ensure_dir(os.path.join(self.root, "chunks"))

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #

    def put(
        self,
        source_path: str,
        original_name: Optional[str] = None,
        content_type: Optional[str] = None,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> str:
        """Store the file at *source_path* and return its ``file_id``.

        Parameters
        ----------
        source_path:
            Absolute or relative path to the file to store.
        original_name:
            Name to record in the metadata.  Defaults to the basename of
            *source_path*.
        content_type:
            Optional MIME type to store in metadata.
        progress_callback:
            Optional ``(bytes_written, total_bytes)`` callable invoked
            after each chunk is flushed to disk.

        Returns
        -------
        str
            A unique ``file_id`` that can be passed to :meth:`get` or
            :meth:`delete`.
        """
        source_path = os.path.abspath(source_path)
        if not os.path.isfile(source_path):
            raise FileNotFoundError(f"Source file not found: {source_path!r}")

        total_size = os.path.getsize(source_path)
        file_id = new_id()
        name = original_name or os.path.basename(source_path)

        meta = FileMetadata(
            file_id=file_id,
            original_name=name,
            total_size=total_size,
            chunk_size=self.chunk_size,
            content_type=content_type,
        )

        bytes_written = 0
        with open(source_path, "rb") as fh:
            index = 0
            while True:
                data = fh.read(self.chunk_size)
                if not data:
                    break
                chunk_id = self._write_chunk(data)
                meta.chunks.append(
                    ChunkInfo(
                        index=index,
                        chunk_id=chunk_id,
                        size=len(data),
                        checksum=sha256_of_bytes(data),
                    )
                )
                bytes_written += len(data)
                index += 1
                if progress_callback:
                    progress_callback(bytes_written, total_size)

        meta.save(self._meta_dir)
        return file_id

    def get(
        self,
        file_id: str,
        dest_path: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        verify: bool = True,
    ) -> str:
        """Retrieve a stored file, writing it to *dest_path*.

        Parameters
        ----------
        file_id:
            The identifier returned by :meth:`put`.
        dest_path:
            Path where the recovered file will be written.  Parent
            directories are created automatically.
        progress_callback:
            Optional ``(bytes_written, total_bytes)`` callable invoked
            after each chunk is flushed to disk.
        verify:
            When ``True`` (default) each chunk's SHA-256 checksum is
            verified before writing.

        Returns
        -------
        str
            Absolute path of the written file.
        """
        meta = FileMetadata.load(self._meta_dir, file_id)
        dest_path = os.path.abspath(dest_path)
        ensure_dir(os.path.dirname(dest_path))

        bytes_written = 0
        with open(dest_path, "wb") as fh:
            for chunk_info in sorted(meta.chunks, key=lambda c: c.index):
                data = self._read_chunk(chunk_info.chunk_id)
                if verify:
                    actual = sha256_of_bytes(data)
                    if actual != chunk_info.checksum:
                        raise ValueError(
                            f"Checksum mismatch for chunk {chunk_info.chunk_id}: "
                            f"expected {chunk_info.checksum}, got {actual}"
                        )
                fh.write(data)
                bytes_written += len(data)
                if progress_callback:
                    progress_callback(bytes_written, meta.total_size)

        return dest_path

    def stream(self, file_id: str, verify: bool = True) -> Iterator[bytes]:
        """Yield chunks of a stored file without writing to disk.

        Parameters
        ----------
        file_id:
            The identifier returned by :meth:`put`.
        verify:
            When ``True`` (default) each chunk's checksum is verified.

        Yields
        ------
        bytes
            Raw chunk data in order.
        """
        meta = FileMetadata.load(self._meta_dir, file_id)
        for chunk_info in sorted(meta.chunks, key=lambda c: c.index):
            data = self._read_chunk(chunk_info.chunk_id)
            if verify:
                actual = sha256_of_bytes(data)
                if actual != chunk_info.checksum:
                    raise ValueError(
                        f"Checksum mismatch for chunk {chunk_info.chunk_id}: "
                        f"expected {chunk_info.checksum}, got {actual}"
                    )
            yield data

    def info(self, file_id: str) -> FileMetadata:
        """Return the :class:`~biffile_data.metadata.FileMetadata` for *file_id*."""
        return FileMetadata.load(self._meta_dir, file_id)

    def list(self) -> list[FileMetadata]:
        """Return metadata for every file in the store."""
        return FileMetadata.list_all(self._meta_dir)

    def delete(self, file_id: str, *, remove_orphan_chunks: bool = False) -> None:
        """Remove a file record from the store.

        Parameters
        ----------
        file_id:
            The identifier of the file to delete.
        remove_orphan_chunks:
            When ``True``, chunks that are no longer referenced by any
            file in the store are also deleted from disk.
        """
        meta = FileMetadata.load(self._meta_dir, file_id)
        chunk_ids_to_remove = {c.chunk_id for c in meta.chunks}

        meta_path = os.path.join(self._meta_dir, f"{file_id}.json")
        os.remove(meta_path)

        if remove_orphan_chunks:
            referenced = self._all_referenced_chunk_ids()
            for chunk_id in chunk_ids_to_remove - referenced:
                self._remove_chunk(chunk_id)

    # ------------------------------------------------------------------ #
    # internal helpers
    # ------------------------------------------------------------------ #

    def _chunk_path(self, chunk_id: str) -> str:
        prefix = chunk_id[:2]
        return os.path.join(self._chunk_dir, prefix, chunk_id)

    def _write_chunk(self, data: bytes) -> str:
        chunk_id = sha256_of_bytes(data)
        path = self._chunk_path(chunk_id)
        if not os.path.exists(path):
            ensure_dir(os.path.dirname(path))
            with open(path, "wb") as fh:
                fh.write(data)
        return chunk_id

    def _read_chunk(self, chunk_id: str) -> bytes:
        path = self._chunk_path(chunk_id)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Chunk not found: {chunk_id!r}")
        with open(path, "rb") as fh:
            return fh.read()

    def _remove_chunk(self, chunk_id: str) -> None:
        path = self._chunk_path(chunk_id)
        if os.path.exists(path):
            os.remove(path)

    def _all_referenced_chunk_ids(self) -> set[str]:
        ids: set[str] = set()
        for meta in self.list():
            for c in meta.chunks:
                ids.add(c.chunk_id)
        return ids
