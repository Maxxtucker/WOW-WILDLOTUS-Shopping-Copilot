"""Test-package defaults that keep model-backed integration explicit."""

from __future__ import annotations

import os


# Unit tests inject semantic scores where needed. Never load cached model
# weights merely because a developer has run the optional integration test.
os.environ.setdefault("AGENT_RERANKER_MODE", "off")
