"""Purpose: export Agent.

Input: evaluator constructs Agent(catalog_path) via starter.agent.
Output: Agent class with reset / respond.
Role: `from agent import Agent`. Implementation is orchestrator.py.
"""

from .orchestrator import Agent

__all__ = ["Agent"]
