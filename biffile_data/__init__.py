"""
biffile_data — large file data storage library.

Quick start::

    from biffile_data import LargeFileStore

    store = LargeFileStore("/path/to/store")
    file_id = store.put("my_large_file.bin")
    store.get(file_id, "recovered_file.bin")
"""

from biffile_data.storage import LargeFileStore
from biffile_data.metadata import FileMetadata

__all__ = ["LargeFileStore", "FileMetadata"]
__version__ = "0.1.0"
