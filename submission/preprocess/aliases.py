"""Purpose: load committed color/material alias JSON produced by the build scripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ALIASES_DIR = Path(__file__).resolve().parents[1] / "src" / "assets" / "aliases"


def alias_path(name: str) -> Path:
    return ALIASES_DIR / name


def load_alias_map(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(
            f"Alias file not found: {path}. Run python build_aliases_color.py "
            "and python build_aliases_material.py first (writes "
            "submission/src/assets/aliases/)."
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Alias file is not an object: {path}")
    result: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        result[key] = value
    return result


def load_color_aliases(path: Path | None = None) -> dict[str, dict[str, Any]]:
    return load_alias_map(path or alias_path("color_aliases.json"))


def load_material_aliases(path: Path | None = None) -> dict[str, dict[str, Any]]:
    return load_alias_map(path or alias_path("material_aliases.json"))
