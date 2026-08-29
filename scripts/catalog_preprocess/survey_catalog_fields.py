#!/usr/bin/env python3
"""Read-only catalog survey: details keys, category L2, composition-line coverage."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

COMPOSITION_RE = re.compile(
    r"\d+(?:\.\d+)?\s*%\s*[A-Za-z][A-Za-z \-/]+",
    re.IGNORECASE,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "data" / "catalog.jsonl")
    parser.add_argument("--top", type=int, default=40)
    args = parser.parse_args()
    if not args.catalog.is_file():
        raise SystemExit(f"Catalog not found: {args.catalog}")

    details_keys: Counter[str] = Counter()
    details_key_folded: Counter[str] = Counter()
    category_l2: Counter[str] = Counter()
    category_len: Counter[int] = Counter()
    products = 0
    with_price = 0
    with_store = 0
    with_composition = 0
    empty_features = 0
    colorish_details = 0
    materialish_details = 0

    with args.catalog.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            product = json.loads(line)
            products += 1
            if product.get("price") not in (None, ""):
                with_price += 1
            if product.get("store") not in (None, ""):
                with_store += 1
            features = product.get("features") or []
            if not features:
                empty_features += 1
            blob = " ".join(str(item) for item in features if item not in (None, ""))
            if COMPOSITION_RE.search(blob):
                with_composition += 1
            categories = product.get("categories") or []
            if isinstance(categories, list):
                category_len[len(categories)] += 1
                if len(categories) >= 2:
                    category_l2[str(categories[1])] += 1
            details = product.get("details")
            if isinstance(details, dict):
                for key in details:
                    details_keys[str(key)] += 1
                    folded = re.sub(r"\s+", " ", str(key).casefold().strip())
                    details_key_folded[folded] += 1
                    if "color" in folded or "colour" in folded:
                        colorish_details += 1
                    if "material" in folded or "fabric" in folded or "fiber" in folded:
                        materialish_details += 1

    print(f"products\t{products}")
    print(f"with_price\t{with_price}")
    print(f"with_store\t{with_store}")
    print(f"empty_features\t{empty_features}")
    print(f"composition_in_features\t{with_composition}")
    print(f"details_colorish_keys\t{colorish_details}")
    print(f"details_materialish_keys\t{materialish_details}")
    print("\n# details keys")
    for key, count in details_keys.most_common(args.top):
        print(f"{count}\t{key}")
    print("\n# category[1]")
    for key, count in category_l2.most_common(args.top):
        print(f"{count}\t{key}")
    print("\n# category path length")
    for length, count in sorted(category_len.items()):
        print(f"{count}\tlen={length}")


if __name__ == "__main__":
    main()
