"""Purpose: intention-detection package.

Input: SessionState plus a stripped message.
Output: scenario_hint, gate_open, intent_version, legacy_hints; turn-1 buying also writes the first constraint.
Role: scenario routing; does not extract `what matters is` constraints. See README.md.
"""

from .detector import (
    IntentionDetector,
    apply_override,
    apply_override_message,
    apply_turn1_template,
)

__all__ = [
    "IntentionDetector",
    "apply_override",
    "apply_override_message",
    "apply_turn1_template",
]
