"""Purpose: export Agent.

Input: evaluator constructs Agent(catalog_path) via starter.agent or
submission/agent.py.
Output: Agent class with reset / respond.
Role: `from src import Agent`. Kit shim and contest entry re-export it.
"""

from .orchestrator import Agent

__all__ = ["Agent"]
