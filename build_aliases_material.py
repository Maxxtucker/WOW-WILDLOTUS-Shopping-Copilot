#!/usr/bin/env python3
"""Build material_aliases.json from the textile fiber database plus leather extras."""

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

from preprocess.eval_maps import (
    EVAL_MATERIALS,
    FIBER_TO_EVAL,
    LEATHER_ALIASES,
    MATERIAL_TYPOS,
)
from preprocess.text import fold_key

FIBERS_URL = (
    "https://raw.githubusercontent.com/kobo-labs-open-source/"
    "textile-fiber-database/main/data/fibers.json"
)
FTC_URL = (
    "https://raw.githubusercontent.com/kobo-labs-open-source/"
    "textile-fiber-database/main/data/ftc-fiber-names.json"
)


def _eval_for_fiber(fiber_id: str, *names: str) -> str:
    key = fold_key(fiber_id).replace(" ", "-")
    if key in FIBER_TO_EVAL:
        return FIBER_TO_EVAL[key]
    for name in names:
        folded = fold_key(name)
        compact = folded.replace(" ", "-")
        if folded in FIBER_TO_EVAL:
            return FIBER_TO_EVAL[folded]
        if compact in FIBER_TO_EVAL:
            return FIBER_TO_EVAL[compact]
        if folded in EVAL_MATERIALS:
            return folded
        if "viscose" in folded or "lyocell" in folded or "modal" in folded:
            return "rayon"
    return "fabric"


def _add(aliases: dict[str, dict[str, str]], name: object, eval_material: str, fiber: str) -> None:
    key = fold_key(name)
    if not key or eval_material not in EVAL_MATERIALS:
        return
    if key not in aliases:
        aliases[key] = {"fiber": fiber, "eval": eval_material}


def _load_json(url: str) -> object:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "src" / "assets" / "aliases" / "material_aliases.json",
    )
    args = parser.parse_args()

    print(f"Downloading {FIBERS_URL}", file=sys.stderr)
    fibers = _load_json(FIBERS_URL)
    print(f"Downloading {FTC_URL}", file=sys.stderr)
    ftc = _load_json(FTC_URL)

    aliases: dict[str, dict[str, str]] = {}
    for material in EVAL_MATERIALS:
        _add(aliases, material, material, material)

    if isinstance(fibers, list):
        for item in fibers:
            if not isinstance(item, dict):
                continue
            fiber_id = str(item.get("id") or "")
            names = [
                fiber_id,
                item.get("name"),
                item.get("ftcName"),
                item.get("euName"),
            ]
            mapped = _eval_for_fiber(fiber_id, *[str(name) for name in names if name])
            for name in names:
                if name:
                    _add(aliases, name, mapped, fiber_id or fold_key(name))
            for extra in item.get("commonBlends") or []:
                if isinstance(extra, str):
                    extra_mapped = _eval_for_fiber(extra, extra)
                    _add(aliases, extra, extra_mapped, extra)

    ftc_rows = ftc.get("fibers") if isinstance(ftc, dict) else ftc
    if isinstance(ftc_rows, list):
        for item in ftc_rows:
            if not isinstance(item, dict):
                continue
            ftc_name = str(item.get("ftcName") or "")
            eu_name = str(item.get("euName") or "")
            mapped = _eval_for_fiber(fold_key(ftc_name), ftc_name, eu_name)
            _add(aliases, ftc_name, mapped, fold_key(ftc_name))
            # "Viscose (bamboo)" → take first token group before parenthesis.
            for piece in eu_name.replace("(", ",").replace(")", ",").split(","):
                _add(aliases, piece, mapped, fold_key(ftc_name))

    for name, mapped in LEATHER_ALIASES.items():
        _add(aliases, name, mapped, "leather")
    for name, mapped in MATERIAL_TYPOS.items():
        _add(aliases, name, mapped, mapped)
    for name in (
        "satin",
        "chiffon",
        "canvas",
        "fleece",
        "mesh",
        "linen",
        "hemp",
        "acrylic",
        "acetate",
        "knit",
        "jersey",
        "denim",
    ):
        _add(aliases, name, "fabric", name)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(sorted(aliases.items()))
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(payload)} aliases to {args.output}")


if __name__ == "__main__":
    main()
