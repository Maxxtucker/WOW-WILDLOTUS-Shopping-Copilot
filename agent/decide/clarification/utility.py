"""Purpose: contribution of one hit to official TechnicalScore.

Input: turn in [1, 10], rank >= 1.
Output: 0.50 + 0.30/rank + 0.02*(11-turn).
Role: planner utility unit; misses do not go through here (utility 0).
"""


def hit_utility(turn: int, rank: int) -> float:
    """Exact per-session contribution to the official technical composite."""

    return 0.50 + 0.30 / rank + 0.02 * (11 - turn)
