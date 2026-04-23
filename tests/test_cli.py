"""Tests for CLI (biffile_data.cli)."""

from __future__ import annotations

import io
import os
import sys

import pytest

from biffile_data.cli import main


def _make_file(directory: str, size: int, name: str = "test.bin") -> str:
    path = os.path.join(directory, name)
    with open(path, "wb") as fh:
        fh.write(b"x" * size)
    return path


@pytest.fixture()
def store_dir(tmp_path):
    return str(tmp_path / "store")


@pytest.fixture()
def files_dir(tmp_path):
    d = str(tmp_path / "files")
    os.makedirs(d)
    return d


class TestCLI:
    def test_put_and_get(self, store_dir, files_dir):
        src = _make_file(files_dir, 2048)
        dest = os.path.join(files_dir, "out.bin")

        # put
        file_id_holder: list[str] = []

        def capture(text, *_):
            file_id_holder.append(text)

        # Redirect stdout so we can capture the file_id
        old_stdout = sys.stdout
        sys.stdout = buf = io.StringIO()
        rc = main(["--store", store_dir, "put", src])
        sys.stdout = old_stdout
        assert rc == 0

        output = buf.getvalue()
        file_id = output.strip().split()[-1]

        # get
        rc2 = main(["--store", store_dir, "get", file_id, dest])
        assert rc2 == 0
        assert os.path.exists(dest)
        with open(dest, "rb") as fh:
            assert fh.read() == b"x" * 2048

    def test_list_empty(self, store_dir, capsys):
        rc = main(["--store", store_dir, "list"])
        assert rc == 0
        captured = capsys.readouterr()
        assert "empty" in captured.out

    def test_put_missing_file(self, store_dir):
        rc = main(["--store", store_dir, "put", "/nonexistent/file.bin"])
        assert rc == 1

    def test_get_unknown_id(self, store_dir, files_dir):
        rc = main(["--store", store_dir, "get", "unknownid", os.path.join(files_dir, "x.bin")])
        assert rc == 1

    def test_delete(self, store_dir, files_dir):
        src = _make_file(files_dir, 512)
        old_stdout = sys.stdout
        sys.stdout = buf = io.StringIO()
        main(["--store", store_dir, "put", src])
        sys.stdout = old_stdout
        file_id = buf.getvalue().strip().split()[-1]

        rc = main(["--store", store_dir, "delete", file_id])
        assert rc == 0

        rc2 = main(["--store", store_dir, "delete", file_id])
        assert rc2 == 1
