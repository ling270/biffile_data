"""Tests for FileMetadata serialisation."""

from __future__ import annotations

import os
import time

import pytest

from biffile_data.metadata import ChunkInfo, FileMetadata


@pytest.fixture()
def tmp_meta_dir(tmp_path):
    d = str(tmp_path / "meta")
    os.makedirs(d)
    return d


def _sample_meta(file_id: str = "abc123") -> FileMetadata:
    return FileMetadata(
        file_id=file_id,
        original_name="large_file.bin",
        total_size=10 * 1024 * 1024,
        chunk_size=8 * 1024 * 1024,
        chunks=[
            ChunkInfo(index=0, chunk_id="deadbeef01", size=8 * 1024 * 1024, checksum="aaa"),
            ChunkInfo(index=1, chunk_id="deadbeef02", size=2 * 1024 * 1024, checksum="bbb"),
        ],
        content_type="application/octet-stream",
    )


class TestSerialization:
    def test_round_trip(self, tmp_meta_dir):
        meta = _sample_meta()
        meta.save(tmp_meta_dir)
        loaded = FileMetadata.load(tmp_meta_dir, meta.file_id)

        assert loaded.file_id == meta.file_id
        assert loaded.original_name == meta.original_name
        assert loaded.total_size == meta.total_size
        assert loaded.chunk_size == meta.chunk_size
        assert loaded.content_type == meta.content_type
        assert len(loaded.chunks) == 2
        assert loaded.chunks[0].chunk_id == "deadbeef01"
        assert loaded.chunks[1].checksum == "bbb"

    def test_load_missing_raises(self, tmp_meta_dir):
        with pytest.raises(FileNotFoundError):
            FileMetadata.load(tmp_meta_dir, "nonexistent")

    def test_list_all_empty(self, tmp_meta_dir):
        assert FileMetadata.list_all(tmp_meta_dir) == []

    def test_list_all_multiple(self, tmp_meta_dir):
        ids = {"id1", "id2", "id3"}
        for fid in ids:
            _sample_meta(fid).save(tmp_meta_dir)

        listed = {m.file_id for m in FileMetadata.list_all(tmp_meta_dir)}
        assert listed == ids

    def test_to_dict_from_dict(self):
        meta = _sample_meta()
        d = meta.to_dict()
        restored = FileMetadata.from_dict(d)
        assert restored.file_id == meta.file_id
        assert len(restored.chunks) == 2


class TestTimestamps:
    def test_created_at_set(self):
        before = time.time()
        meta = _sample_meta()
        after = time.time()
        assert before <= meta.created_at <= after
