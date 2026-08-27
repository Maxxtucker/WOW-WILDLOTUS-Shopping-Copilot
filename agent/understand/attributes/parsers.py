"""Purpose: simulator reply phrasing (what matters is / no preference / no additional).

Input: message string.
Output: regex Match; capture writes it as a constraint or no_preference.
Role: kept separate from intention templates so reply parse and scenario routing stay apart.
"""

from __future__ import annotations

import re

MATTERS_RE = re.compile(r"what matters is:\s*(.+?)\.?$", re.IGNORECASE)
NO_ADDITIONAL_RE = re.compile(
    r"(?:no|an) additional preference for\s+([a-z_]+)",
    re.IGNORECASE,
)
NO_PREFERENCE_RE = re.compile(
    r"(?:no|a) preference for\s+([a-z_]+)",
    re.IGNORECASE,
)
