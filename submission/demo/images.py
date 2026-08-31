"""Load side-car catalog image URLs for the Chainlit demo."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.paths import DATA_DIR

_DEFAULT_PATH = DATA_DIR / "catalog_images.jsonl"


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
    if img is None and images:
        first = images[0]
        img = first if isinstance(first, dict) else None
    if not img:
        return None
    for key in ("large", "hi_res", "thumb"):
        value = img.get(key)
        if isinstance(value, str) and value.strip().startswith("http"):
            return value.strip()
    return None


def load_image_index(path: Path | None = None) -> dict[str, str]:
    """Load parent_asin → main_image_url from catalog_images.jsonl."""

    target = path or _DEFAULT_PATH
    if not target.is_file():
        return {}
    mapping: dict[str, str] = {}
    with target.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            asin = str(row.get("parent_asin") or "").strip()
            url = row.get("main_image_url")
            if asin and isinstance(url, str) and url.startswith("http"):
                mapping[asin] = url
    return mapping


def resolve_image_url(
    product: dict[str, Any] | None,
    parent_asin: str,
    image_index: dict[str, str] | None = None,
) -> str | None:
    """Resolve a display URL from product fields or the side-car index."""

    p = product or {}
    for key in ("main_image_url", "image_url"):
        value = p.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    from_images = get_main_image_url(p.get("images"))
    if from_images:
        return from_images
    if image_index:
        return image_index.get(parent_asin)
    return None
