"""Purpose: Plan result, and NO_ADDITIONAL sentinel when the simulator has no more information.

Input: constructed inside the planner.
Output: recommendations, ask_attribute, expected_value, reason.
Role: contract between clarifier and response.
"""

from __future__ import annotations

from dataclasses import dataclass

NO_ADDITIONAL = ("__no_additional__",)


@dataclass(frozen=True)
class Plan:
    recommendations: tuple[str, ...]
    ask_attribute: str | None
    expected_value: float
    reason: str
