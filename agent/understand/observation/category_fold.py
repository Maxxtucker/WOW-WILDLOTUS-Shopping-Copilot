"""Purpose: reuse preprocess fold_category as the category identity key.

Input: a category label, tree id, or catalog tag.
Output: the same folded string the sidecar and category tree already store.
Role: one import site so understand does not copy fold rules.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from catalog_preprocess.text import fold_category

__all__ = ["fold_category"]
