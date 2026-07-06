#!/usr/bin/env python
"""Download the TPDC Birds 525 FTP dataset with resume support."""

from __future__ import annotations

import argparse
import ftplib
import getpass
import os
import posixpath
import sys
import time
from pathlib import Path


DEFAULT_HOSTS = ["ftp2.tpdc.ac.cn", "ftp3.tpdc.ac.cn"]
DEFAULT_REMOTE_ROOT = "/BIRDS-525-SPECIES-IMAGE-CLASSIFICATION-main"
DEFAULT_DEST = Path("datasets") / "BIRDS-525-SPECIES-IMAGE-CLASSIFICATION-main"
FTP_RETRY_ERRORS = ftplib.all_errors + (OSError,)


class Downloader:
    def __init__(
        self,
        hosts: list[str],
        port: int,
        user: str,
        password: str,
        retries: int,
        timeout: int,
    ) -> None:
        self.hosts = hosts
        self.port = port
        self.user = user
        self.password = password
        self.retries = retries
        self.timeout = timeout
        self.ftp: ftplib.FTP | None = None
        self.current_host = ""
        self.host_index = 0

    def close(self) -> None:
        if self.ftp is None:
            return
        try:
            self.ftp.quit()
        except ftplib.all_errors:
            try:
                self.ftp.close()
            except ftplib.all_errors:
                pass
        finally:
            self.ftp = None

    def connect(self, prefer_next_host: bool = False) -> ftplib.FTP:
        self.close()
        last_error: Exception | None = None
        if prefer_next_host:
            self.host_index = (self.host_index + 1) % len(self.hosts)

        for offset in range(len(self.hosts)):
            index = (self.host_index + offset) % len(self.hosts)
            host = self.hosts[index]
            try:
                ftp = ftplib.FTP(timeout=self.timeout)
                ftp.connect(host, self.port, timeout=self.timeout)
                ftp.login(self.user, self.password)
                ftp.set_pasv(True)
                self.ftp = ftp
                self.current_host = host
                self.host_index = index
                return ftp
            except FTP_RETRY_ERRORS as exc:
                last_error = exc
        raise RuntimeError(f"Could not connect to any FTP host: {last_error}") from last_error

    def get_ftp(self) -> ftplib.FTP:
        if self.ftp is None:
            return self.connect()
        return self.ftp

    def mlsd(self, remote_dir: str) -> list[tuple[str, dict[str, str]]]:
        for attempt in range(1, self.retries + 1):
            try:
                ftp = self.get_ftp()
                return [
                    (name, facts)
                    for name, facts in ftp.mlsd(remote_dir)
                    if name not in {".", ".."}
                ]
            except FTP_RETRY_ERRORS as exc:
                if attempt == self.retries:
                    raise
                print(f"List failed, reconnecting: {remote_dir} ({exc})", file=sys.stderr)
                self.connect(prefer_next_host=True)
                time.sleep(min(attempt, 5))
        return []

    def download_file(self, remote_path: str, local_path: Path, remote_size: int) -> str:
        local_path.parent.mkdir(parents=True, exist_ok=True)

        if local_path.exists() and local_path.stat().st_size == remote_size:
            return "skip"

        part_path = local_path.with_name(local_path.name + ".part")
        if local_path.exists() and not part_path.exists():
            if local_path.stat().st_size < remote_size:
                local_path.replace(part_path)
            else:
                local_path.unlink()

        for attempt in range(1, self.retries + 1):
            offset = part_path.stat().st_size if part_path.exists() else 0
            mode = "ab" if offset else "wb"
            try:
                ftp = self.get_ftp()
                with part_path.open(mode) as fh:
                    ftp.retrbinary(f"RETR {remote_path}", fh.write, rest=offset or None)

                if part_path.stat().st_size != remote_size:
                    raise IOError(
                        f"size mismatch for {remote_path}: "
                        f"{part_path.stat().st_size} != {remote_size}"
                    )
                part_path.replace(local_path)
                return "resume" if offset else "download"
            except FTP_RETRY_ERRORS as exc:
                if attempt == self.retries:
                    raise
                print(f"Download failed, retrying: {remote_path} ({exc})", file=sys.stderr)
                self.connect(prefer_next_host=True)
                time.sleep(min(attempt, 5))

        return "failed"


def remote_join(*parts: str) -> str:
    return posixpath.join(*parts).replace("\\", "/")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download BIRDS-525-SPECIES-IMAGE-CLASSIFICATION-main from TPDC FTP."
    )
    parser.add_argument(
        "--host",
        action="append",
        dest="hosts",
        help="FTP host. Repeat to add fallbacks. Defaults to ftp2 and ftp3.",
    )
    parser.add_argument("--port", type=int, default=6201)
    parser.add_argument(
        "--user",
        default=os.environ.get("TPDC_FTP_USER", "download_29604448"),
        help="FTP username. Can also be set with TPDC_FTP_USER.",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("TPDC_FTP_PASSWORD"),
        help="FTP password. Prefer TPDC_FTP_PASSWORD or interactive input.",
    )
    parser.add_argument("--remote-root", default=DEFAULT_REMOTE_ROOT)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument(
        "--split",
        action="append",
        choices=["train", "valid", "test"],
        help="Download only one split. Repeat for multiple splits.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only list totals.")
    parser.add_argument("--max-files", type=int, help="Stop after N files, useful for testing.")
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=60)
    return parser.parse_args()


def walk_files(
    downloader: Downloader,
    remote_dir: str,
    rel_dir: Path,
):
    for name, facts in downloader.mlsd(remote_dir):
        entry_type = facts.get("type")
        remote_path = remote_join(remote_dir, name)
        rel_path = rel_dir / name

        if entry_type == "dir":
            yield from walk_files(downloader, remote_path, rel_path)
        elif entry_type == "file":
            size = int(facts.get("size") or 0)
            yield remote_path, rel_path, size


def main() -> int:
    args = parse_args()
    password = args.password or getpass.getpass("TPDC FTP password: ")
    hosts = args.hosts or DEFAULT_HOSTS

    downloader = Downloader(
        hosts=hosts,
        port=args.port,
        user=args.user,
        password=password,
        retries=args.retries,
        timeout=args.timeout,
    )

    remote_roots: list[tuple[str, Path]]
    if args.split:
        remote_roots = [
            (remote_join(args.remote_root, split), Path(split))
            for split in args.split
        ]
    else:
        remote_roots = [(args.remote_root, Path("."))]

    total_files = 0
    total_bytes = 0
    downloaded = 0
    skipped = 0
    resumed = 0
    started = time.time()

    try:
        downloader.connect()
        print(f"Connected to {downloader.current_host}:{args.port}")

        for remote_root, rel_root in remote_roots:
            print(f"Scanning {remote_root}")
            for remote_path, rel_path, size in walk_files(downloader, remote_root, rel_root):
                total_files += 1
                total_bytes += size

                if args.dry_run:
                    if total_files % 1000 == 0:
                        print(
                            f"Found {total_files:,} files, "
                            f"{total_bytes / 1024 ** 3:.2f} GiB"
                        )
                else:
                    result = downloader.download_file(remote_path, args.dest / rel_path, size)
                    if result == "skip":
                        skipped += 1
                    elif result == "resume":
                        resumed += 1
                    elif result == "download":
                        downloaded += 1

                    if total_files % 100 == 0:
                        elapsed = max(time.time() - started, 1)
                        mib = total_bytes / 1024 ** 2
                        print(
                            f"{total_files:,} files seen | "
                            f"{downloaded:,} downloaded | "
                            f"{resumed:,} resumed | "
                            f"{skipped:,} skipped | "
                            f"{mib / elapsed:.2f} MiB/s listed"
                        )

                if args.max_files and total_files >= args.max_files:
                    break
            if args.max_files and total_files >= args.max_files:
                break
    finally:
        downloader.close()

    print(
        f"Done: {total_files:,} files, {total_bytes / 1024 ** 3:.2f} GiB "
        f"in {time.time() - started:.1f}s"
    )
    if not args.dry_run:
        print(f"Downloaded: {downloaded:,}, resumed: {resumed:,}, skipped: {skipped:,}")
        print(f"Saved to: {args.dest.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
