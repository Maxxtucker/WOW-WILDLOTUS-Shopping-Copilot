"""Eval dock must reuse the live Chainlit app module, not import it twice."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from demo.eval_ui import _live_app


class LiveAppTest(unittest.TestCase):
    def test_live_app_prefers_chainlit_loaded_name(self) -> None:
        target = Path(__file__).resolve().parents[1] / "demo" / "chainlit_app.py"
        fake = SimpleNamespace(__file__=str(target), get_agent=object())
        sys.modules["chainlit_app.py"] = fake
        try:
            self.assertIs(_live_app(), fake)
        finally:
            sys.modules.pop("chainlit_app.py", None)


if __name__ == "__main__":
    unittest.main()
