"""Purpose: sidecar SQLite constants, fingerprint, and ATTACH for precomputed slots.

Input: catalog path and optional AGENT_SLOTS_PATH.
Output: path / attached flag. Does not extract or rewrite catalog rows.
Role: Agent only reads a one-shot preprocess database. Missing or stale
sidecars degrade to signature_values; they never trigger extraction.
"""

from __future__ import annotations

import os
import sqlite3
import warnings
from pathlib import Path

SIDECAR_VERSION = "catalog-slots-v1"
DEFAULT_SLOTS_RELATIVE = Path(".cache") / "catalog_preprocess" / "product_slots.sqlite3"


def catalog_fingerprint(catalog_path: str | Path) -> str:
    catalog = Path(catalog_path)
    stat = catalog.stat()
    return f"{catalog.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"


def resolve_slots_path(catalog_path: str | Path | None = None) -> Path | None:
    """Return the preprocess sidecar path, or None when slots are disabled.

    ``AGENT_SLOTS_PATH=:none:`` skips ATTACH. Any other explicit path is used
    as-is. Otherwise prefer ``.cache/catalog_preprocess/product_slots.sqlite3``
    under the working directory, then next to the catalog repo root.
    """

    configured = os.environ.get("AGENT_SLOTS_PATH")
    if configured == ":none:":
        return None
    if configured:
        return Path(configured)
    cwd_path = Path.cwd() / DEFAULT_SLOTS_RELATIVE
    if cwd_path.is_file():
        return cwd_path
    if catalog_path is not None:
        repo_guess = Path(catalog_path).resolve().parent.parent / DEFAULT_SLOTS_RELATIVE
        if repo_guess.is_file():
            return repo_guess
    return cwd_path


def sidecar_is_current(slots_path: Path, fingerprint: str) -> bool:
    if not slots_path.is_file():
        return False
    try:
        connection = sqlite3.connect(str(slots_path.resolve()))
    except sqlite3.Error:
        return False
    try:
        rows = dict(connection.execute("SELECT key, value FROM meta"))
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        return (
            rows.get("version") == SIDECAR_VERSION
            and rows.get("catalog_fingerprint") == fingerprint
            and "product_slots" in tables
        )
    except sqlite3.Error:
        return False
    finally:
        connection.close()


def attach_product_slots(
    connection: sqlite3.Connection,
    catalog_path: str | Path,
    *,
    slots_path: str | Path | None = None,
) -> Path | None:
    """ATTACH the preprocess sidecar as ``slots``. Return the path if attached."""

    env_path = os.environ.get("AGENT_SLOTS_PATH")
    explicit = slots_path is not None or (
        env_path not in (None, "", ":none:")
    )
    path = Path(slots_path) if slots_path is not None else resolve_slots_path(catalog_path)
    if path is None:
        return None
    if not path.is_file():
        if explicit:
            warnings.warn(
                f"product_slots sidecar not found ({path}). "
                "Rerun python scripts/extract_catalog_slots.py. "
                "Exact lookup will use signature_values only.",
                RuntimeWarning,
                stacklevel=2,
            )
        return None
    fingerprint = catalog_fingerprint(catalog_path)
    if not sidecar_is_current(path, fingerprint):
        if explicit:
            warnings.warn(
                f"product_slots sidecar is stale ({path}). "
                "Rerun python scripts/extract_catalog_slots.py. "
                "Exact lookup will use signature_values only.",
                RuntimeWarning,
                stacklevel=2,
            )
        return None
    try:
        connection.execute("ATTACH DATABASE ? AS slots", (str(path.resolve()),))
    except sqlite3.Error as exc:
        warnings.warn(
            f"Could not ATTACH product_slots sidecar {path}: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return None
    return path
