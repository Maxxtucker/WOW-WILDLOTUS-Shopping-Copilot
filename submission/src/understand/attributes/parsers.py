"""Purpose: simulator phrasing for locked constraints (`what matters is`).

Input: message string.
Output: regex Match; classify turns it into constraint strings.
Role: kept next to lookup so semicolon restore and the matters payload stay together.
"""

from __future__ import annotations

import re

MATTERS_RE = re.compile(r"what matters is:\s*(.+?)\.?$", re.IGNORECASE)
