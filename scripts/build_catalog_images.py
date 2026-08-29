#!/usr/bin/env python3
"""Build data/catalog_images.jsonl from Amazon Reviews 2023 item metadata.

Joins the frozen contest catalog (50k parent_asin) to Clothing_Shoes_and_Jewelry
item metadata from https://amazon-reviews-2023.github.io/ and writes:

    {"parent_asin": "...", "main_image_url": "https://m.media-amazon.com/..."}

Does not modify data/catalog.jsonl.

Example:

    python scripts/build_catalog_images.py
    python scripts/build_catalog_images.py --meta-gz data/releases/meta_Clothing_Shoes_and_Jewelry.jsonl.gz
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import urllib.request
from pathlib import Path

META_URL = (
    "https://mcauleylab.ucsd.edu/public_datasets/data/amazon_2023/"
    "raw/meta_categories/meta_Clothing_Shoes_and_Jewelry.jsonl.gz"
)
DEFAULT_META_GZ = Path("data/releases/meta_Clothing_Shoes_and_Jewelry.jsonl.gz")
DEFAULT_CATALOG = Path("data/catalog.jsonl")
DEFAULT_OUTPUT = Path("data/catalog_images.jsonl")


def get_main_image_url(images: object) -> str | None:
    """Prefer MAIN variant; URL order large → hi_res → thumb."""

    if not isinstance(images, list) or not images:
        return None
    main = next(
        (
            img
            for img in images
            if isinstance(img, dict) and img.get("variant") == "MAIN"
        ),
        None,
    )
    img = main if isinstance(main, dict) else None
    if img is None:
        first = images[0]
        img = first if isinstance(first, dict) else None
    if not img:
        return None
    for key in ("large", "hi_res", "thumb"):
        value = img.get(key)
        if isinstance(value, str) and value.strip().startswith("http"):
            return value.strip()
    return None


def load_catalog_asins(catalog_path: Path) -> set[str]:
    asins: set[str] = set()
    with catalog_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(
                    f"Invalid JSON in {catalog_path} line {line_number}"
                ) from exc
            asin = str(row.get("parent_asin") or "").strip()
            if asin:
                asins.add(asin)
    if not asins:
        raise SystemExit(f"No parent_asin values in {catalog_path}")
    return asins


def download_meta(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    print(f"Downloading metadata (large file):\n  {url}")
    print(f"  → {destination}")
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Converge-TechJam2026/1.0"},
    )
    with urllib.request.urlopen(request) as response, temporary.open("wb") as target:
        total = response.headers.get("Content-Length")
        total_n = int(total) if total and total.isdigit() else None
        copied = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            target.write(chunk)
            copied += len(chunk)
            if total_n:
                pct = 100.0 * copied / total_n
                print(
                    f"\r  {copied / 1e9:.2f} / {total_n / 1e9:.2f} GB ({pct:5.1f}%)",
                    end="",
                    flush=True,
                )
            else:
                print(f"\r  {copied / 1e9:.2f} GB", end="", flush=True)
    print()
    temporary.replace(destination)
    print(f"Saved {destination} ({destination.stat().st_size / 1e9:.2f} GB)")


def extract_images(
    meta_gz: Path,
    needed: set[str],
) -> dict[str, str]:
    """Stream gzip metadata; keep first MAIN image URL per needed ASIN."""

    remaining = set(needed)
    found: dict[str, str] = {}
    scanned = 0
    print(f"Scanning {meta_gz} for {len(needed)} catalog ASINs…")
    with gzip.open(meta_gz, "rt", encoding="utf-8") as handle:
        for line in handle:
            scanned += 1
            if scanned % 200_000 == 0:
                print(
                    f"  scanned {scanned:,} meta rows; "
                    f"matched {len(found):,}; remaining {len(remaining):,}",
                    flush=True,
                )
            if not remaining:
                break
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            asin = str(row.get("parent_asin") or "").strip()
            if asin not in remaining:
                continue
            url = get_main_image_url(row.get("images"))
            if url:
                found[asin] = url
            remaining.discard(asin)
    print(
        f"Done scan: {scanned:,} rows, {len(found):,} with images, "
        f"{len(needed) - len(found):,} missing"
    )
    return found


def write_catalog_images(
    catalog_path: Path,
    image_map: dict[str, str],
    output_path: Path,
) -> tuple[int, int]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".part")
    written = 0
    with_image = 0
    with catalog_path.open(encoding="utf-8") as source, temporary.open(
        "w", encoding="utf-8", newline="\n"
    ) as target:
        for line in source:
            if not line.strip():
                continue
            row = json.loads(line)
            asin = str(row.get("parent_asin") or "").strip()
            if not asin:
                continue
            url = image_map.get(asin)
            payload = {"parent_asin": asin, "main_image_url": url}
            target.write(json.dumps(payload, ensure_ascii=False) + "\n")
            written += 1
            if url:
                with_image += 1
    temporary.replace(output_path)
    return written, with_image


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--meta-gz",
        type=Path,
        default=DEFAULT_META_GZ,
        help="Local path to meta_Clothing_Shoes_and_Jewelry.jsonl.gz",
    )
    parser.add_argument(
        "--meta-url",
        default=META_URL,
        help="Download URL when --meta-gz is missing",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Force re-download of the metadata gzip",
    )
    args = parser.parse_args()

    if not args.catalog.is_file():
        raise SystemExit(f"Catalog not found: {args.catalog}")

    needed = load_catalog_asins(args.catalog)
    print(f"Catalog ASINs: {len(needed):,}")

    if args.download or not args.meta_gz.is_file():
        download_meta(args.meta_url, args.meta_gz)
    else:
        print(f"Using existing metadata: {args.meta_gz}")

    image_map = extract_images(args.meta_gz, needed)
    written, with_image = write_catalog_images(args.catalog, image_map, args.output)
    coverage = 100.0 * with_image / written if written else 0.0
    print(f"Wrote {args.output}")
    print(f"  rows={written:,}  with_image={with_image:,}  coverage={coverage:.1f}%")
    if with_image == 0:
        raise SystemExit("No images matched; check metadata path / category")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Cancelled", file=sys.stderr)
        raise SystemExit(130)
