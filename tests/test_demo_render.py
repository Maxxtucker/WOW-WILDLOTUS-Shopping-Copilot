"""Demo reply text stays on the Chainlit bubble. No Ollama."""

from __future__ import annotations

import unittest


from demo.node_catalog import NODE_CATALOG
from demo.render import format_assistant_text, shelf_props, visible_reply_content


class VisibleReplyContentTest(unittest.TestCase):
    def test_keeps_official_message_and_card_titles(self) -> None:
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
        self.assertIn("Danner Men's TrailTrek", text)
        self.assertNotEqual(text.strip(), "")

    def test_never_collapses_to_whitespace(self) -> None:
        text = visible_reply_content({"message": "Here is a match."}, [])
        self.assertEqual(text.strip(), "Here is a match.")

    def test_empty_result_still_has_fallback(self) -> None:
        text = visible_reply_content({}, [])
        self.assertTrue(text.strip())
        self.assertIn("couldn't find", format_assistant_text({}, []))


<<<<<<< HEAD
=======
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
    def test_node_catalog_uses_product_focused_sections(self) -> None:
        casefold = NODE_CATALOG["casefold"]
        self.assertIn("purpose", casefold)
        self.assertIn("why", casefold)
        self.assertIn("this_turn", casefold)
        self.assertIn("how_it_works", casefold)
        self.assertEqual(casefold["label"], "Normalize text")
        self.assertIn("capitalization", casefold["why"].lower())

    def test_retrieve_nodes_read_like_search_story(self) -> None:
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
            self.assertIn("purpose", node)
            self.assertIn("why", node)
            self.assertIn("this_turn", node)
            self.assertIn("how_it_works", node)

        self.assertEqual(slot_groups["label"], "Separate requirements from preferences")
        self.assertEqual(query["label"], "Build the retrieval query")
        self.assertEqual(routing["label"], "Choose retrieval breadth")
        self.assertEqual(exact["label"], "Rank within the exact-match pool")
        self.assertEqual(hybrid["label"], "Recover broader candidates")
        self.assertEqual(cap_hits["label"], "Merge and cap candidates")
        self.assertEqual(rerank["label"], "Semantic rerank")
        self.assertEqual(belief["label"], "Convert scores to ranking confidence")
        self.assertEqual(normalize["label"], "Normalize ranking weights")


>>>>>>> 317e5cb (improve agent pipeline UI explanations)
if __name__ == "__main__":
    unittest.main()
