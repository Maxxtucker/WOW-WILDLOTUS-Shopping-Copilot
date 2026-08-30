"""Demo reply text stays on the Chainlit bubble. No Ollama."""

from __future__ import annotations

import unittest

from demo.render import format_assistant_text, shelf_props, visible_reply_content


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


if __name__ == "__main__":
    unittest.main()
