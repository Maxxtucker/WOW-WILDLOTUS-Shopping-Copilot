#!/usr/bin/env python3
"""Build color_aliases.json: messy name → 20 base_color → evaluator 11 colors."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PARENT = ROOT.parent
_PROJECT = (
    _PARENT
    if (_PARENT / "evaluator").is_dir() and (_PARENT / "starter").is_dir()
    else ROOT
)
if str(_PROJECT) not in sys.path:
    sys.path.insert(0, str(_PROJECT))

from preprocess.eval_maps import BASE_TO_EVAL, EVAL_COLORS
from preprocess.text import fold_key

HF_PARQUET_URL = (
    "https://huggingface.co/datasets/NacerKr/colors-normalized/resolve/main/"
    "data/colors_normalized.parquet"
)
FASHION_EXTRAS: dict[str, str] = {
    "navy": "indigo",
    "navy blue": "indigo",
    "midnight": "indigo",
    "burgundy": "brown",
    "maroon": "red",
    "khaki": "tan",
    "ivory": "beige",
    "cream": "beige",
    "off white": "beige",
    "charcoal": "gray",
    "silver": "gray",
    "champagne": "beige",
    "nude": "beige",
    "olive": "green",
    "mint": "green",
    "coral": "orange",
    "lavender": "purple",
    "lilac": "purple",
}


def _load_parquet(url: str) -> list[dict[str, str]]:
    import pandas as pd

    frame = pd.read_parquet(url)
    rows: list[dict[str, str]] = []
    for record in frame.itertuples(index=False):
        name = str(getattr(record, "name", "") or "")
        language = str(getattr(record, "language", "") or "en")
        base = str(getattr(record, "base_color", "") or "")
        if name and base:
            rows.append({"name": name, "language": language, "base_color": base})
    return rows


def _put(
    aliases: dict[str, dict[str, str]],
    name: str,
    base: str,
    *,
    language: str,
    prefer_en: bool,
) -> None:
    key = fold_key(name)
    mapped = BASE_TO_EVAL.get(base)
    if not key or mapped is None:
        return
    existing = aliases.get(key)
    if existing is not None:
        if prefer_en and existing.get("language") == "en" and language != "en":
            return
        if prefer_en and language == "en" and existing.get("language") != "en":
            pass
        elif existing.get("language") == "en" and language != "en":
            return
    aliases[key] = {"base": base, "eval": mapped, "language": language}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "src" / "assets" / "aliases" / "color_aliases.json",
    )
    parser.add_argument("--url", default=HF_PARQUET_URL)
    args = parser.parse_args()

    print(f"Downloading {args.url}", file=sys.stderr)
    urllib.request.urlcleanup()
    rows = _load_parquet(args.url)
    aliases: dict[str, dict[str, str]] = {}
    for color in EVAL_COLORS:
        aliases[color] = {"base": color, "eval": color, "language": "en"}
    aliases["grey"] = {"base": "gray", "eval": "gray", "language": "en"}
    for record in rows:
        _put(
            aliases,
            record["name"],
            record["base_color"],
            language=record["language"],
            prefer_en=True,
        )
    for name, base in FASHION_EXTRAS.items():
        if fold_key(name) not in aliases:
            _put(aliases, name, base, language="en", prefer_en=True)

    compact = {
        key: {"base": value["base"], "eval": value["eval"]}
        for key, value in sorted(aliases.items())
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(compact, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(compact)} aliases to {args.output}")


if __name__ == "__main__":
    main()
