"""Purpose: intention package: conversion-gate writeback on override.

Input: SessionState plus an optional new constraint.
Output: gate_open, intent_version, legacy_hints.
Role: does not extract category or `what matters is`. See README.md.
"""

from .detector import apply_override

__all__ = ["apply_override"]
