"""Command-line interface for biffile_data."""

from __future__ import annotations

import argparse
import datetime
import io
import os
import sys

from biffile_data.storage import LargeFileStore
from biffile_data.utils import human_readable_size


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="biffile",
        description="biffile_data — large file data storage",
    )
    parser.add_argument(
        "--store",
        "-s",
        default=os.path.join(os.path.expanduser("~"), ".biffile_store"),
        help="Path to the store root directory (default: ~/.biffile_store)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=8 * 1024 * 1024,
        help="Chunk size in bytes (default: 8 MiB)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # put
    put_p = sub.add_parser("put", help="Store a file")
    put_p.add_argument("file", help="Path to the file to store")
    put_p.add_argument("--name", help="Override the stored filename")
    put_p.add_argument("--type", dest="content_type", help="MIME type to record")

    # get
    get_p = sub.add_parser("get", help="Retrieve a stored file")
    get_p.add_argument("file_id", help="File ID returned by 'put'")
    get_p.add_argument("dest", help="Destination path")
    get_p.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip checksum verification",
    )

    # info
    info_p = sub.add_parser("info", help="Show metadata for a stored file")
    info_p.add_argument("file_id", help="File ID returned by 'put'")

    # list
    sub.add_parser("list", help="List all stored files")

    # delete
    del_p = sub.add_parser("delete", help="Delete a stored file")
    del_p.add_argument("file_id", help="File ID to delete")
    del_p.add_argument(
        "--purge-chunks",
        action="store_true",
        help="Also remove orphaned chunk data",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    store = LargeFileStore(args.store, chunk_size=args.chunk_size)

    if args.command == "put":
        try:
            file_id = store.put(
                args.file,
                original_name=args.name,
                content_type=args.content_type,
                progress_callback=_print_progress,
            )
            print()  # newline after progress
            print(f"Stored: {file_id}")
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    elif args.command == "get":
        try:
            dest = store.get(
                args.file_id,
                args.dest,
                progress_callback=_print_progress,
                verify=not args.no_verify,
            )
            print()
            print(f"Retrieved: {dest}")
        except (FileNotFoundError, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    elif args.command == "info":
        try:
            meta = store.info(args.file_id)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"file_id      : {meta.file_id}")
        print(f"name         : {meta.original_name}")
        print(f"size         : {human_readable_size(meta.total_size)} ({meta.total_size} bytes)")
        print(f"chunk_size   : {human_readable_size(meta.chunk_size)}")
        print(f"chunks       : {len(meta.chunks)}")
        print(f"content_type : {meta.content_type or '—'}")
        print(f"created_at   : {datetime.datetime.fromtimestamp(meta.created_at).isoformat()}")

    elif args.command == "list":
        files = store.list()
        if not files:
            print("(store is empty)")
        else:
            fmt = "{:<34} {:>12}  {}"
            print(fmt.format("FILE ID", "SIZE", "NAME"))
            print("-" * 70)
            for m in files:
                print(fmt.format(m.file_id, human_readable_size(m.total_size), m.original_name))

    elif args.command == "delete":
        try:
            store.delete(args.file_id, remove_orphan_chunks=args.purge_chunks)
            print(f"Deleted: {args.file_id}")
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    return 0


def _print_progress(written: int, total: int) -> None:
    if total:
        pct = written * 100 // total
        bar = "#" * (pct // 2)
        print(f"\r[{bar:<50}] {pct:3d}%  {human_readable_size(written)}/{human_readable_size(total)}", end="", flush=True)


if __name__ == "__main__":
    sys.exit(main())
