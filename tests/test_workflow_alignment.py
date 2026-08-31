"""UI schema, progress constants, inspector copy, and README mermaid stay aligned."""

from __future__ import annotations

import unittest
from pathlib import Path

from agent.progress import STAGE_NODES
from demo.node_catalog import NODE_CATALOG
from demo.progress_ui import NODE_SPECS, empty_circuit_state
from demo.workflow_schema import (
    NODE_FIELDS,
    NODE_METADATA,
    STAGE_ORDER,
    WORKFLOW_SCHEMA,
    extract_marked_mermaid,
    mermaid_flowchart,
    workflow_graph_props,
)

ROOT = Path(__file__).resolve().parents[1]

STAGE_README = {
    "understand": ROOT / "agent" / "understand" / "README.md",
    "router": ROOT / "agent" / "intent_router" / "README.md",
    "retrieve": ROOT / "agent" / "retrieve" / "README.md",
    "decide": ROOT / "agent" / "decide" / "README.md",
}

EXTRA_MARKED_DOCS = (
    ROOT / "agent" / "README.md",
    ROOT / "docs" / "architecture" / "agent_pipeline.md",
)

INSPECTOR_SECTIONS = (
    "Node Task",
    "Design Rationale",
    "Implementation",
    "This turn · real trace",
)


class WorkflowContractTest(unittest.TestCase):
    def test_progress_nodes_match_schema(self) -> None:
        self.assertEqual(tuple(STAGE_NODES), STAGE_ORDER)
        for stage in STAGE_ORDER:
            self.assertEqual(
                set(STAGE_NODES[stage]),
                set(WORKFLOW_SCHEMA[stage]["nodes"]),
                stage,
            )

    def test_catalog_and_circuit_use_the_same_nodes(self) -> None:
        schema_ids = set(NODE_METADATA)
        self.assertEqual(set(NODE_CATALOG), schema_ids)
        self.assertEqual({node_id for node_id, _stage, _label in NODE_SPECS}, schema_ids)
        circuit = empty_circuit_state()
        self.assertEqual(set(circuit["nodes"]), schema_ids)
        self.assertEqual(circuit["graphOrder"], list(STAGE_ORDER))
        self.assertEqual(set(circuit["graphs"]), set(STAGE_ORDER))

    def test_every_node_has_exactly_the_four_static_fields(self) -> None:
        for node_id, metadata in NODE_METADATA.items():
            self.assertEqual(set(metadata), set(NODE_FIELDS), node_id)
            for field in NODE_FIELDS:
                self.assertTrue(str(metadata[field]).strip(), (node_id, field))
            self.assertNotIn("this_turn", metadata)
            self.assertNotIn("contract", metadata)
            catalog = NODE_CATALOG[node_id]
            self.assertEqual(catalog["task"], metadata["task"])
            self.assertEqual(catalog["rationale"], metadata["rationale"])
            self.assertEqual(catalog["implementation"], metadata["implementation"])

    def test_graph_edges_and_positions_are_valid(self) -> None:
        props = workflow_graph_props()
        for stage in STAGE_ORDER:
            graph = WORKFLOW_SCHEMA[stage]
            nodes = graph["nodes"]
            self.assertEqual(set(graph["positions"]), set(nodes))
            for edge in graph["edges"]:
                self.assertIn(len(edge), {2, 3}, edge)
                self.assertIn(edge[0], nodes)
                self.assertIn(edge[1], nodes)
            ui_edges = props[stage]["edges"]
            self.assertEqual(len(ui_edges), len(graph["edges"]))
            for ui_edge, schema_edge in zip(ui_edges, graph["edges"], strict=True):
                self.assertEqual(list(ui_edge), list(schema_edge[:2]))

    def test_duplicate_catalog_extension_is_gone(self) -> None:
        self.assertFalse((ROOT / "demo" / "node_catalog_ext.py").exists())

    def test_inspector_keeps_only_the_four_modules_in_order(self) -> None:
        source = (ROOT / "demo" / "public" / "elements" / "NodeInspector.jsx").read_text(
            encoding="utf-8"
        )
        indexes = [source.find(f'Section title="{title}"') for title in INSPECTOR_SECTIONS]
        self.assertTrue(all(index >= 0 for index in indexes), indexes)
        self.assertEqual(indexes, sorted(indexes))
        self.assertNotIn('title="Contract"', source)
        self.assertNotIn("this_turn", source)

    def test_circuit_consumes_schema_graphs_instead_of_hardcoded_layouts(self) -> None:
        source = (ROOT / "demo" / "public" / "elements" / "PipelineCircuit.jsx").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("const GRAPHS", source)
        self.assertIn("graphs: rawGraphs", source)
        self.assertIn("graph.viewBox", source)
        self.assertIn("data-graph-canvas", source)
        self.assertIn("fitToView", source)
        self.assertIn("consumeCanvasCache", source)
        self.assertIn("__convergePipelineViewport", source)
        self.assertIn("userAdjusted", source)
        self.assertIn("Scroll to zoom", source)


class WorkflowMermaidTest(unittest.TestCase):
    def test_stage_readme_mermaid_matches_schema(self) -> None:
        for stage, path in STAGE_README.items():
            markdown = path.read_text(encoding="utf-8")
            self.assertEqual(
                extract_marked_mermaid(markdown, stage),
                mermaid_flowchart(stage),
                stage,
            )

    def test_architecture_and_agent_readme_mermaid_match_schema(self) -> None:
        for path in EXTRA_MARKED_DOCS:
            markdown = path.read_text(encoding="utf-8")
            for stage in STAGE_ORDER:
                self.assertEqual(
                    extract_marked_mermaid(markdown, stage),
                    mermaid_flowchart(stage),
                    f"{path.name}:{stage}",
                )


if __name__ == "__main__":
    unittest.main()
