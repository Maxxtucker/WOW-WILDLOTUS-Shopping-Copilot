"""Official contest entry. Exports ``Agent`` with ``reset`` / ``respond``.

The kit harness still imports ``starter.agent.Agent``. Organizers who unpack
this folder can ``from agent import Agent`` with PYTHONPATH pointing here.
"""

from src.orchestrator import Agent

__all__ = ["Agent"]
