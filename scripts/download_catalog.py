#!/usr/bin/env python3
"""Download, verify, and decompress the official participant catalog."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG_URL = (
    "https://github.com/TechJam2026/techjam-conversational-search/"
    "releases/download/participant-kit/catalog.jsonl.gz"
)
CATALOG_SHA256 = "07fd142631fd6b03e2b4d09988c3eb7d53720e9d57010c79db48eeaada50a8f8"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "catalog.jsonl")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--keep-gzip", action="store_true")
    args = parser.parse_args()

    output = args.output
    if output.exists() and not args.force:
        print(f"Catalog already exists: {output}")
        return
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="converge-download-") as directory:
        archive = Path(directory) / "catalog.jsonl.gz"
        print(f"Downloading {CATALOG_URL}")
        request = urllib.request.Request(
            CATALOG_URL,
            headers={"User-Agent": "Converge-TechJam2026/1.0"},
        )
        with urllib.request.urlopen(request) as response, archive.open("wb") as target:
            shutil.copyfileobj(response, target)
        actual = digest(archive)
        if actual != CATALOG_SHA256:
            raise SystemExit(
                f"SHA-256 mismatch: expected {CATALOG_SHA256}, received {actual}"
            )
        print("SHA-256 verified")

        temporary_output = output.with_suffix(output.suffix + ".part")
        with gzip.open(archive, "rb") as source, temporary_output.open("wb") as target:
            shutil.copyfileobj(source, target)
        temporary_output.replace(output)
        if args.keep_gzip:
            shutil.copy2(archive, output.with_suffix(output.suffix + ".gz"))

    row_count = sum(1 for line in output.open("rb") if line.strip())
    if row_count != 50_000:
        output.unlink(missing_ok=True)
        raise SystemExit(f"Unexpected row count: {row_count}; expected 50000")
    print(f"Ready: {output} ({row_count} products)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Download cancelled", file=sys.stderr)
        raise SystemExit(130)
