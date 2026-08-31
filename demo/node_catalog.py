"""Compatibility exports for canonical workflow inspector metadata.

New callers should use ``demo.workflow_schema`` directly. The three aliases
below preserve the former demo-facing names without creating a second
metadata contract.
"""

from __future__ import annotations

from demo.workflow_schema import NODE_METADATA, STAGE_BLURBS

NODE_CATALOG: dict[str, dict[str, str]] = {
    node_id: {
        **metadata,
        "purpose": metadata["task"],
        "why": metadata["rationale"],
        "how_it_works": metadata["implementation"],
    }
    for node_id, metadata in NODE_METADATA.items()
}

__all__ = ["NODE_CATALOG", "STAGE_BLURBS"]
