#!/usr/bin/env python3
"""Export product_slots as a wide CSV: one row per ASIN, ten attribute columns."""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PARENT = ROOT.parent
PROJECT = (
    _PARENT
    if (_PARENT / "evaluator").is_dir() and (_PARENT / "starter").is_dir()
    else ROOT
)
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from src.domain import ALLOWED_ATTRIBUTES
from src.retrieve.catalog.slots_sidecar import DEFAULT_SLOTS_RELATIVE

MISSING = "None"
VALUE_SEP = "|"
WIDE_COLUMNS = ("parent_asin", *ALLOWED_ATTRIBUTES)


def _join(values: list[str]) -> str:
    if not values:
        return MISSING
    return VALUE_SEP.join(values)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=PROJECT / DEFAULT_SLOTS_RELATIVE,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT / "data" / "product_slots.csv",
    )
    parser.add_argument(
        "--meta-output",
        type=Path,
        default=PROJECT / "data" / "product_slots_meta.csv",
    )
    args = parser.parse_args()
    if not args.sqlite.is_file():
        raise SystemExit(
            f"Sidecar not found: {args.sqlite}. Run python extract_slots.py first."
        )

    connection = sqlite3.connect(str(args.sqlite))
    args.output.parent.mkdir(parents=True, exist_ok=True)

    meta_rows = list(connection.execute("SELECT key, value FROM meta ORDER BY key"))
    with args.meta_output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("key", "value"))
        writer.writerows(meta_rows)

    by_asin: dict[str, dict[str, list[str]]] = {}
    seen: dict[str, dict[str, set[str]]] = {}
    for parent_asin, attribute, canonical in connection.execute(
        "SELECT parent_asin, attribute, canonical FROM product_slots "
        "ORDER BY parent_asin, attribute, canonical"
    ):
        if attribute not in ALLOWED_ATTRIBUTES:
            continue
        columns = by_asin.setdefault(parent_asin, {name: [] for name in ALLOWED_ATTRIBUTES})
        used = seen.setdefault(parent_asin, {name: set() for name in ALLOWED_ATTRIBUTES})
        value = str(canonical or "").strip()
        if not value or value in used[attribute]:
            continue
        used[attribute].add(value)
        columns[attribute].append(value)

    connection.close()

    written = 0
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(WIDE_COLUMNS)
        for parent_asin in sorted(by_asin):
            columns = by_asin[parent_asin]
            writer.writerow(
                (
                    parent_asin,
                    *(_join(columns[name]) for name in ALLOWED_ATTRIBUTES),
                )
            )
            written += 1

    print(f"Wrote {written} product rows to {args.output}")
    print(f"Wrote meta to {args.meta_output}")


if __name__ == "__main__":
    main()
