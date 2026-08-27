"""Purpose: observation-coordinator package.

Input: SessionState, this turn's message.
Output: SessionState written in the fixed order.
Role: the only parse-order entry inside understand. See README.md.
"""

from .coordinator import ObservationCoordinator, observe

__all__ = ["ObservationCoordinator", "observe"]
