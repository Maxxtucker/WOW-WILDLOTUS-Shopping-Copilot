"""Purpose: choose the SQLite path from catalog fingerprint and environment variables.

Input: catalog_path; env AGENT_INDEX_PATH / AGENT_CACHE_DIR.
Output: Path, an explicit string path, or None (:memory:).
Role: keep the large index off the Python heap; reuse cache when the catalog is unchanged.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


def resolve_index_path(catalog_path: str | Path) -> str | Path | None:
    """Return the persistent index location for this catalog.

    ``AGENT_INDEX_PATH=:memory:`` disables on-disk caching.  Any other
    explicit path is used as-is.  The default cache lives in the OS temp
    directory (or ``AGENT_CACHE_DIR``) and is invalidated when the catalog
    size or mtime changes.  ``CONVERGE_INDEX_PATH`` / ``CONVERGE_CACHE_DIR``
    remain accepted aliases.
    """

    catalog = Path(catalog_path)
    configured_index = os.environ.get("AGENT_INDEX_PATH") or os.environ.get(
        "CONVERGE_INDEX_PATH"
    )
    if configured_index == ":memory:":
        return None
    if configured_index:
        return configured_index
    # Keep the large FTS/signature index off the Python/SQLite heap on
    # memory-constrained runners.  The OS temp cache is disposable and
    # keyed by the immutable catalog fingerprint; it never modifies the
    # competition data and is automatically validated by the retriever.
    stat = catalog.stat()
    fingerprint = (
        f"{catalog.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    ).encode("utf-8")
    cache_key = hashlib.sha256(fingerprint).hexdigest()[:16]
    cache_root = Path(
        os.environ.get("AGENT_CACHE_DIR")
        or os.environ.get("CONVERGE_CACHE_DIR")
        or tempfile.gettempdir()
    ) / "agent-techjam2026"
    return cache_root / f"catalog-{cache_key}.sqlite3"
