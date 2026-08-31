"""Demo reply text stays on the Chainlit bubble. No Ollama."""

from __future__ import annotations

import unittest


from demo.node_catalog import NODE_CATALOG
from demo.render import format_assistant_text, shelf_props, visible_reply_content
from demo.workflow_schema import NODE_FIELDS, NODE_METADATA, STAGE_ORDER


class VisibleReplyContentTest(unittest.TestCase):
    def test_keeps_official_message_without_card_titles(self) -> None:
        result = {
            "message": (
                "I narrowed this to 1 high-confidence option. "
                "What other requirements matter most to you?"
            ),
            "recommendations": ["B01I33SAEI"],
        }
        cards = [{"title": "Danner Men's TrailTrek", "price": 120.0}]
        text = visible_reply_content(result, cards)
        self.assertIn("high-confidence option", text)
        self.assertNotIn("Danner Men's TrailTrek", text)
        self.assertNotEqual(text.strip(), "")

    def test_appends_clarify_without_product_list(self) -> None:
        text = visible_reply_content(
            {"message": "Here is a match."},
            [{"title": "Hidden Boot", "price": 10}],
            clarify_prompt="What color do you want?",
        )
        self.assertIn("Here is a match.", text)
        self.assertIn("What color do you want?", text)
        self.assertNotIn("Hidden Boot", text)

    def test_never_collapses_to_whitespace(self) -> None:
        text = visible_reply_content({"message": "Here is a match."}, [])
        self.assertEqual(text.strip(), "Here is a match.")

    def test_empty_result_still_has_fallback(self) -> None:
        text = visible_reply_content({}, [])
        self.assertTrue(text.strip())
        self.assertIn("couldn't find", format_assistant_text({}, []))


class ShelfPropsTest(unittest.TestCase):
    def test_sends_cards_and_legacy_hero_others(self) -> None:
        cards = [
            {"parent_asin": "A", "title": "Boot"},
            {"parent_asin": "B", "title": "Hat"},
        ]
        props = shelf_props(cards)
        self.assertEqual(props["cards"], cards)
        self.assertEqual(props["hero"], cards[0])
        self.assertEqual(props["others"], [cards[1]])



class NodeCatalogCopyTest(unittest.TestCase):
    def test_node_catalog_exposes_exactly_the_three_static_sections(self) -> None:
        casefold = NODE_CATALOG["casefold"]
        self.assertTrue(NODE_FIELDS.issubset(casefold))
        self.assertNotIn("this_turn", casefold)
        self.assertNotIn("function", casefold)
        self.assertEqual(
            casefold["label"], "Create case-insensitive working text"
        )
        self.assertIn("capitalization", casefold["rationale"].lower())

    def test_every_node_has_complete_self_explaining_metadata(self) -> None:
        self.assertEqual(STAGE_ORDER, ("understand", "router", "retrieve", "decide"))
        self.assertEqual(set(NODE_CATALOG), set(NODE_METADATA))
        for node_id, node in NODE_METADATA.items():
            self.assertEqual(set(node), set(NODE_FIELDS), node_id)
            for field in NODE_FIELDS:
                self.assertTrue(str(node[field]).strip(), (node_id, field))

    def test_retrieve_titles_read_like_the_real_search_story(self) -> None:
        slot_groups = NODE_CATALOG["slot_groups"]
        query = NODE_CATALOG["rewrite_query"]
        routing = NODE_CATALOG["routing"]
        exact = NODE_CATALOG["lexical_in_pool"]
        hybrid = NODE_CATALOG["hybrid_search"]
        cap_hits = NODE_CATALOG["cap_hits"]
        rerank = NODE_CATALOG["qwen_rerank"]
        belief = NODE_CATALOG["belief_hits"]
        normalize = NODE_CATALOG["normalize"]

        for node in (slot_groups, query, routing, exact, hybrid, cap_hits, rerank, belief, normalize):
            self.assertTrue(NODE_FIELDS.issubset(node))
            self.assertNotIn("this_turn", node)

        self.assertEqual(slot_groups["label"], "Build hard and soft scoring groups")
        self.assertEqual(query["label"], "Build the active-intent lexical query")
        self.assertEqual(routing["label"], "Load route weights and limits")
        self.assertEqual(exact["label"], "Restrict BM25 scores to the seed pool")
        self.assertEqual(hybrid["label"], "Recover or fill candidates permissively")
        self.assertEqual(cap_hits["label"], "Assemble the bounded base library")
        self.assertEqual(rerank["label"], "Try the optional Qwen semantic head")
        self.assertEqual(belief["label"], "Convert deterministic scores to weights")
        self.assertEqual(normalize["label"], "Normalize ranking probability mass")


if __name__ == "__main__":
    unittest.main()
