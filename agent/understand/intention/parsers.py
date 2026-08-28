"""Purpose: official looking-for phrasing and override regex templates.

Input: raw message string.
Output: regex Match; observation.classify interprets category / constraint / override.
Role: patterns only, no state writes, so phrasing can be edited in isolation.
"""

from __future__ import annotations

import re

KEY_REQUIREMENT_RE = re.compile(
    r"^I['’]m looking for (.+?)\.\s*A key requirement is:\s*(.+?)\.?$",
    re.IGNORECASE,
)
EXPLORING_RE = re.compile(
    r"^I['’]m looking for (.+?),\s*but I['’]m still exploring\.?$",
    re.IGNORECASE,
)
INITIAL_OTHER_RE = re.compile(r"^I['’]m looking for (.+?)\.\s*(.+?)\.?$", re.IGNORECASE)
OVERRIDE_RE = re.compile(
    r"(?:actually[, ]+)?(?:ignore|forget|replace).+?(?:what I need is|need|requirement is)\s*:\s*(.+?)\.?$",
    re.IGNORECASE,
)
OVERRIDE_SIGNAL_RE = re.compile(
    r"\b(?:actually|ignore|disregard|forget|changed?\s+my\s+mind|instead|"
    r"no\s+longer|rather|new\s+plan|new\s+requirement)\b",
    re.IGNORECASE,
)
OVERRIDE_VALUE_RE = re.compile(
    r"(?:what\s+i\s+(?:need|want)\s+is|i\s+(?:now\s+)?(?:need|want)|"
    r"new\s+requirement\s+is|instead[, ]+(?:i\s+)?(?:need|want))"
    r"\s*:?\s*(.+?)\.?$",
    re.IGNORECASE,
)
GENERIC_CATEGORY_RE = re.compile(
    r"(?:looking|shopping)\s+for\s+(.+?)(?:[.,;]|$)",
    re.IGNORECASE,
)
