"""Tests for LargeFileStore."""

from __future__ import annotations

import hashlib
import os
import tempfile

import pytest

from biffile_data.storage import LargeFileStore
from biffile_data.utils import sha256_of_bytes, sha256_of_file


# ------------------------------------------------------------------ #
# helpers
# ------------------------------------------------------------------ #

def _make_file(directory: str, size: int, name: str = "test.bin") -> str:
    """Write *size* bytes of deterministic content and return the path."""
    path = os.path.join(directory, name)
    # Use a pattern so we can verify the content later.
    chunk = b"abcdefghijklmnopqrstuvwxyz0123456789"
    with open(path, "wb") as fh:
        written = 0
        while written < size:
            to_write = min(len(chunk), size - written)
            fh.write(chunk[:to_write])
            written += to_write
    return path


# ------------------------------------------------------------------ #
# fixtures
# ------------------------------------------------------------------ #

@pytest.fixture()
def tmp_store(tmp_path):
    """Return a LargeFileStore backed by a fresh temp directory."""
    return LargeFileStore(str(tmp_path / "store"), chunk_size=1024)


@pytest.fixture()
def tmp_src(tmp_path):
    """Return a temp directory for source / destination files."""
    d = str(tmp_path / "files")
    os.makedirs(d)
    return d


# ------------------------------------------------------------------ #
# basic put / get round-trip
# ------------------------------------------------------------------ #

class TestPutGet:
    def test_small_file_round_trip(self, tmp_store, tmp_src):
        src = _make_file(tmp_src, 512)
        original_hash = sha256_of_file(src)

        file_id = tmp_store.put(src)
        assert file_id  # non-empty string

        dest = os.path.join(tmp_src, "recovered.bin")
        tmp_store.get(file_id, dest)

        assert sha256_of_file(dest) == original_hash

    def test_exact_chunk_size_file(self, tmp_store, tmp_src):
        """A file that is exactly one chunk long."""
        src = _make_file(tmp_src, 1024)
        original_hash = sha256_of_file(src)

        file_id = tmp_store.put(src)
        dest = os.path.join(tmp_src, "recovered.bin")
        tmp_store.get(file_id, dest)

        assert sha256_of_file(dest) == original_hash

    def test_multi_chunk_file(self, tmp_store, tmp_src):
        """A file that spans several chunks (chunk_size=1024, file=5 KiB)."""
        src = _make_file(tmp_src, 5 * 1024)
        original_hash = sha256_of_file(src)

        file_id = tmp_store.put(src)

        meta = tmp_store.info(file_id)
        assert len(meta.chunks) == 5

        dest = os.path.join(tmp_src, "recovered.bin")
        tmp_store.get(file_id, dest)
        assert sha256_of_file(dest) == original_hash

    def test_empty_file(self, tmp_store, tmp_src):
        src = _make_file(tmp_src, 0)
        file_id = tmp_store.put(src)

        dest = os.path.join(tmp_src, "recovered.bin")
        tmp_store.get(file_id, dest)

        assert os.path.getsize(dest) == 0

    def test_put_missing_source_raises(self, tmp_store):
        with pytest.raises(FileNotFoundError):
            tmp_store.put("/nonexistent/path/file.bin")

    def test_get_unknown_file_id_raises(self, tmp_store, tmp_src):
        with pytest.raises(FileNotFoundError):
            tmp_store.get("deadbeef" * 4, os.path.join(tmp_src, "out.bin"))


# ------------------------------------------------------------------ #
# metadata
# ------------------------------------------------------------------ #

class TestMetadata:
    def test_metadata_recorded(self, tmp_store, tmp_src):
        src = _make_file(tmp_src, 2048, "data.bin")
        file_id = tmp_store.put(src, original_name="custom.bin", content_type="application/octet-stream")

        meta = tmp_store.info(file_id)
        assert meta.file_id == file_id
        assert meta.original_name == "custom.bin"
        assert meta.total_size == 2048
        assert meta.chunk_size == 1024
        assert meta.content_type == "application/octet-stream"
        assert len(meta.chunks) == 2

    def test_list_files(self, tmp_store, tmp_src):
        ids = set()
        for i in range(3):
            src = _make_file(tmp_src, 512, f"file{i}.bin")
            ids.add(tmp_store.put(src))

        listed = {m.file_id for m in tmp_store.list()}
        assert ids == listed

    def test_list_empty_store(self, tmp_store):
        assert tmp_store.list() == []


# ------------------------------------------------------------------ #
# streaming
# ------------------------------------------------------------------ #

class TestStream:
    def test_stream_reassembles_correctly(self, tmp_store, tmp_src):
        src = _make_file(tmp_src, 3 * 1024)
        original_hash = sha256_of_file(src)

        file_id = tmp_store.put(src)

        assembled = b"".join(tmp_store.stream(file_id))
        assert hashlib.sha256(assembled).hexdigest() == original_hash


# ------------------------------------------------------------------ #
# deduplication
# ------------------------------------------------------------------ #

class TestDeduplication:
    def test_identical_chunks_stored_once(self, tmp_store, tmp_src):
        """Two files with identical content must share chunk files on disk."""
        src1 = _make_file(tmp_src, 1024, "a.bin")
        src2 = _make_file(tmp_src, 1024, "b.bin")

        id1 = tmp_store.put(src1)
        id2 = tmp_store.put(src2)

        meta1 = tmp_store.info(id1)
        meta2 = tmp_store.info(id2)

        assert meta1.chunks[0].chunk_id == meta2.chunks[0].chunk_id


# ------------------------------------------------------------------ #
# delete
# ------------------------------------------------------------------ #

class TestDelete:
    def test_delete_removes_metadata(self, tmp_store, tmp_src):
        src = _make_file(tmp_src, 512)
        file_id = tmp_store.put(src)

        tmp_store.delete(file_id)
        assert tmp_store.list() == []

    def test_delete_purge_chunks(self, tmp_store, tmp_src):
        src = _make_file(tmp_src, 1024)
        file_id = tmp_store.put(src)
        chunk_id = tmp_store.info(file_id).chunks[0].chunk_id

        tmp_store.delete(file_id, remove_orphan_chunks=True)

        chunk_path = tmp_store._chunk_path(chunk_id)
        assert not os.path.exists(chunk_path)

    def test_delete_shared_chunk_not_removed(self, tmp_store, tmp_src):
        """A chunk shared by two files must survive if only one is deleted."""
        src1 = _make_file(tmp_src, 1024, "a.bin")
        src2 = _make_file(tmp_src, 1024, "b.bin")
        id1 = tmp_store.put(src1)
        id2 = tmp_store.put(src2)

        shared_chunk_id = tmp_store.info(id1).chunks[0].chunk_id

        tmp_store.delete(id1, remove_orphan_chunks=True)

        chunk_path = tmp_store._chunk_path(shared_chunk_id)
        assert os.path.exists(chunk_path)

    def test_delete_unknown_raises(self, tmp_store):
        with pytest.raises(FileNotFoundError):
            tmp_store.delete("unknown_id")


# ------------------------------------------------------------------ #
# checksum verification
# ------------------------------------------------------------------ #

class TestChecksumVerification:
    def test_corrupted_chunk_raises(self, tmp_store, tmp_src):
        src = _make_file(tmp_src, 1024)
        file_id = tmp_store.put(src)

        chunk_id = tmp_store.info(file_id).chunks[0].chunk_id
        chunk_path = tmp_store._chunk_path(chunk_id)

        # Corrupt the chunk.
        with open(chunk_path, "r+b") as fh:
            fh.seek(0)
            fh.write(b"\x00" * 16)

        dest = os.path.join(tmp_src, "out.bin")
        with pytest.raises(ValueError, match="Checksum mismatch"):
            tmp_store.get(file_id, dest)


# ------------------------------------------------------------------ #
# progress callback
# ------------------------------------------------------------------ #

class TestProgressCallback:
    def test_callback_called_for_each_chunk(self, tmp_store, tmp_src):
        src = _make_file(tmp_src, 3 * 1024)
        file_id = tmp_store.put(src)

        calls: list[tuple[int, int]] = []
        dest = os.path.join(tmp_src, "out.bin")
        tmp_store.get(file_id, dest, progress_callback=lambda w, t: calls.append((w, t)))

        assert len(calls) == 3
        assert calls[-1][0] == 3 * 1024
