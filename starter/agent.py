"""Competition entry point.

The official evaluator imports ``starter.agent.Agent``.  The implementation is
kept in the ``converge`` package so its components can be tested independently.
"""

from converge.agent import Agent

__all__ = ["Agent"]
