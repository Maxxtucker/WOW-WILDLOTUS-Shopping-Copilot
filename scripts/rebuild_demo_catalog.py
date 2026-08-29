#!/usr/bin/env python3
"""Rebuild data/catalog.demo.jsonl from contest catalog + catalog_images."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "data" / "catalog.jsonl"
IMAGES = ROOT / "data" / "catalog_images.jsonl"
OUTPUT = ROOT / "data" / "catalog.demo.jsonl"


def load_images() -> dict[str, str]:
    mapping: dict[str, str] = {}
    with IMAGES.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            asin = row.get("parent_asin")
            url = row.get("main_image_url")
            if asin and isinstance(url, str) and url.startswith("http"):
                mapping[str(asin)] = url
    return mapping


def score(product: dict) -> int:
    title = (product.get("title") or "").lower()
    cats = [str(c).lower() for c in (product.get("categories") or [])]
    feats = " ".join(str(x) for x in (product.get("features") or [])).lower()
    blob = f"{title} {' '.join(cats)} {feats}"
    value = 0
    if "running" in blob:
        value += 5
    if any("running" in c for c in cats):
        value += 4
    if "shoe" in blob:
        value += 3
    brands = (
        "asics",
        "nike",
        "brooks",
        "saucony",
        "hoka",
        "new balance",
        "adidas",
        "salomon",
        "skechers",
        "puma",
        "reebok",
    )
    if any(brand in title for brand in brands):
        value += 2
    if "cushion" in blob or "breath" in blob or "mesh" in blob:
        value += 1
    if "toddler" in blob or ("kid" in blob and "women" not in title):
        value -= 5
    if "sock" in title:
        value -= 3
    if "jogger" in title and "shoe" not in title:
        value -= 2
    price = product.get("price")
    if isinstance(price, (int, float)) and 40 <= float(price) <= 150:
        value += 2
    if isinstance(price, (int, float)) and float(price) < 50:
        value += 1
    return value


def bucket(price: float) -> str:
    if price < 50:
        return "cheap"
    if price < 100:
        return "mid"
    return "high"


def main() -> None:
    images = load_images()
    candidates: list[tuple[int, float, dict]] = []
    with CATALOG.open(encoding="utf-8") as handle:
        for line in handle:
            product = json.loads(line)
            asin = str(product.get("parent_asin") or "")
            if asin not in images:
                continue
            price = product.get("price")
            if not isinstance(price, (int, float)):
                continue
            ranked = score(product)
            if ranked < 6:
                continue
            row = dict(product)
            row["main_image_url"] = images[asin]
            candidates.append((ranked, float(price), row))

    candidates.sort(key=lambda item: (-item[0], item[1]))

    picked: list[dict] = []
    stores: set[str] = set()
    counts = {"cheap": 0, "mid": 0, "high": 0}
    for ranked, price, product in candidates:
        store = str(product.get("store") or product["parent_asin"]).lower()
        kind = bucket(price)
        if store in stores and len(picked) < 10:
            continue
        if counts[kind] >= 5 and len(picked) < 10:
            continue
        stores.add(store)
        counts[kind] += 1
        picked.append(product)
        if len(picked) >= 12:
            break

    if sum(1 for item in picked if float(item["price"]) < 50) < 2:
        have = {item["parent_asin"] for item in picked}
        for ranked, price, product in candidates:
            if product["parent_asin"] in have:
                continue
            if price < 50:
                picked.append(product)
                have.add(product["parent_asin"])
            if sum(1 for item in picked if float(item["price"]) < 50) >= 2:
                break
        picked = picked[:12]

    OUTPUT.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in picked),
        encoding="utf-8",
    )
    print(f"Wrote {OUTPUT} ({len(picked)} products)")
    for product in picked:
        title = (product.get("title") or "")[:72]
        print(f"{product['parent_asin']}\t{product['price']}\t{title}")


if __name__ == "__main__":
    main()
