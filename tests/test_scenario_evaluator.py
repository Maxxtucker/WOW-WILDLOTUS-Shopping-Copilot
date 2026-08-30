from __future__ import annotations

import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from evaluator.scenario_evaluator import OpenAICompatibleClient, ScenarioEvaluator


def sample(scenario: str = "buying") -> dict:
    return {
        "scenario_type": scenario,
        "user_profile": {"preference_tags": ["walking"]},
        "intent_card": {
            "hard_constraints": ["leather", "Rubber sole"],
            "soft_preferences": ["color: black"],
        },
        "behavior": {
            "override": {
                "old_value": "I prefer an old style.",
                "new_value": "leather",
                "turn": 3,
            }
        },
    }


class FakeClient:
    def __init__(self, replies: list[dict]) -> None:
        self.replies = iter(replies)
        self.prompts: list[str] = []
        self.payloads: list[dict] = []

    def complete(self, prompt: str, payload: dict):
        self.prompts.append(prompt)
        self.payloads.append(payload)
        return next(self.replies), {"prompt_tokens": 1, "completion_tokens": 2}


class ScenarioEvaluatorTest(unittest.TestCase):
    def test_mode_one_is_exact_original_and_does_not_call_client(self) -> None:
        client = FakeClient([])
        buyer = ScenarioEvaluator(mode=1, client=client)
        disclosed: set[str] = set()
        buyer.reset("s", sample(), "Men Shoes")
        self.assertEqual(
            buyer.initial_message("s", disclosed),
            "I'm looking for Men Shoes. A key requirement is: leather.",
        )
        self.assertEqual(
            buyer.customer_reply("s", "feature", disclosed, False),
            ("For that, what matters is: Rubber sole.", False),
        )
        self.assertEqual(client.payloads, [])

    def test_compatibility_interface_remains(self) -> None:
        buyer = ScenarioEvaluator(mode=1)
        disclosed: set[str] = set()
        self.assertEqual(
            buyer.initial_message(sample(), "Men Shoes", disclosed),
            "I'm looking for Men Shoes. A key requirement is: leather.",
        )
        self.assertEqual(
            buyer.customer_reply(sample(), "feature", disclosed, False),
            ("For that, what matters is: Rubber sole.", False),
        )

    def test_mode_two_sends_protected_keywords_and_rewrites_outer_language(self) -> None:
        client = FakeClient([
            {"message": "I would like Men Shoes; the key requirement is: leather."},
            {"message": "For me, the important part is Rubber sole."},
        ])
        buyer = ScenarioEvaluator(mode=2, client=client)
        disclosed: set[str] = set()
        buyer.reset("s", sample(), "Men Shoes")
        self.assertEqual(
            buyer.initial_message("s", disclosed),
            "I would like Men Shoes; the key requirement is: leather.",
        )
        reply, boundary = buyer.customer_reply("s", "feature", disclosed, False)
        self.assertEqual(reply, "For me, the important part is Rubber sole.")
        self.assertFalse(boundary)
        self.assertEqual(client.payloads[0]["protected_keywords"], ["Men Shoes", "leather"])
        self.assertEqual(client.payloads[1]["protected_keywords"], ["Rubber sole"])
        self.assertTrue(all("protected_keywords" in payload for payload in client.payloads))

    def test_mode_two_rejects_missing_or_changed_protected_keyword(self) -> None:
        client = FakeClient([
            {"message": "I need men's footwear; hide is essential."},
            {"message": "I prefer cotton instead."},
        ])
        buyer = ScenarioEvaluator(mode=2, client=client)
        disclosed: set[str] = set()
        buyer.reset("s", sample(), "Men Shoes")
        self.assertEqual(
            buyer.initial_message("s", disclosed),
            "I want to find Men Shoes, and my main requirement is: leather.",
        )
        self.assertEqual(
            buyer.customer_reply("s", "feature", disclosed, False),
            ("The important points for me are: Rubber sole.", False),
        )

    def test_mode_three_accepts_synonyms_and_rewrites_whole_sentence(self) -> None:
        client = FakeClient([
            {"message": "I'm shopping for men's footwear, and genuine hide is what I need."},
            {"message": "The bottom part made of rubber is important for me."},
        ])
        buyer = ScenarioEvaluator(mode=3, client=client)
        disclosed: set[str] = set()
        buyer.reset("s", sample(), "Men Shoes")
        self.assertEqual(
            buyer.initial_message("s", disclosed),
            "I'm shopping for men's footwear, and genuine hide is what I need.",
        )
        self.assertEqual(
            buyer.customer_reply("s", "feature", disclosed, False),
            ("The bottom part made of rubber is important for me.", False),
        )

    def test_mode_three_rejects_semantic_reversal_and_falls_back_to_synonym(self) -> None:
        client = FakeClient([
            {"message": "I'm shopping for men's footwear, but I do not want leather."},
        ])
        buyer = ScenarioEvaluator(mode=3, client=client)
        disclosed: set[str] = set()
        buyer.reset("s", sample(), "Men Shoes")
        message = buyer.initial_message("s", disclosed)
        self.assertIn("genuine hide", message)
        self.assertNotIn("do not want", message)

    def test_mode_four_accepts_poor_english_or_circumlocution(self) -> None:
        client = FakeClient([
            {"message": "I am look for men's footwear, and I need the thing which comes from real animal skin, okay."},
            {"message": "For the bottom part, I want the thing made from rubber, but my English not very good."},
        ])
        buyer = ScenarioEvaluator(mode=4, client=client)
        disclosed: set[str] = set()
        buyer.reset("s", sample(), "Men Shoes")
        self.assertEqual(
            buyer.initial_message("s", disclosed),
            "I am look for men's footwear, and I need the thing which comes from real animal skin, okay.",
        )
        self.assertEqual(
            buyer.customer_reply("s", "feature", disclosed, False),
            ("For the bottom part, I want the thing made from rubber, but my English not very good.", False),
        )

    def test_mode_four_rejects_intent_change_and_uses_semantic_fallback(self) -> None:
        client = FakeClient([
            {"message": "I am look for men's footwear, but I do not want leather."},
        ])
        buyer = ScenarioEvaluator(mode=4, client=client)
        disclosed: set[str] = set()
        buyer.reset("s", sample(), "Men Shoes")
        message = buyer.initial_message("s", disclosed)
        self.assertIn("comes from real animal skin", message)
        self.assertNotIn("do not want", message)

    def test_boundary_return_contract_is_preserved(self) -> None:
        client = FakeClient([
            {"message": "I don't have a preference for feature; you decide for me."},
        ])
        buyer = ScenarioEvaluator(mode=3, client=client)
        message, boundary = buyer.customer_reply(sample("boundary"), "feature", set(), False)
        self.assertEqual(message, "I don't have a preference for feature; you decide for me.")
        self.assertTrue(boundary)

    def test_synonym_reply_updates_original_disclosed_value(self) -> None:
        client = FakeClient([
            {"message": "The bottom part made of rubber is important for me."},
        ])
        buyer = ScenarioEvaluator(mode=3, client=client)
        disclosed = {"leather"}
        buyer.customer_reply(sample(), "feature", disclosed, False)
        self.assertIn("Rubber sole", disclosed)

    def test_mode_two_requires_protected_keyword_exact_case(self) -> None:
        client = FakeClient([
            {"message": "I want men shoes, and leather is required."},
        ])
        buyer = ScenarioEvaluator(mode=2, client=client)
        message = buyer.initial_message(sample(), "Men Shoes", set())
        self.assertEqual(
            message,
            "I want to find Men Shoes, and my main requirement is: leather.",
        )

    def test_mode_four_rejects_plain_fluent_synonym_without_poor_english_signal(self) -> None:
        client = FakeClient([
            {"message": "I'm shopping for men's footwear, and genuine hide is what I need."},
        ])
        buyer = ScenarioEvaluator(mode=4, client=client)
        message = buyer.initial_message(sample(), "Men Shoes", set())
        self.assertTrue(message.startswith("I am look for"))

    def test_mode_four_browsing_does_not_leak_hidden_constraint(self) -> None:
        client = FakeClient([{}])
        buyer = ScenarioEvaluator(mode=4, client=client)
        message = buyer.initial_message(sample("browsing"), "Watch Bands", set())
        self.assertIn("still checking", message)
        self.assertNotIn("leather", message.casefold())
        self.assertNotIn("animal skin", message.casefold())

    def test_environment_defaults_and_dotenv(self) -> None:
        no_dotenv = str(Path(__file__).with_name("__missing_test_dotenv__"))
        cases = [
            ({"DASHSCOPE_API_KEY": "ds-key"}, "ds-key", "dashscope.aliyuncs.com", "qwen-plus"),
            ({"OPENAI_API_KEY": "openai-key", "CONVERGE_LLM_PROVIDER": "openai"}, "openai-key", "api.openai.com", "gpt-4o-mini"),
            ({"DEEPSEEK_API_KEY": "deepseek-key", "CONVERGE_LLM_PROVIDER": "dp"}, "deepseek-key", "api.deepseek.com", "deepseek-chat"),
        ]
        for environment, expected_key, expected_host, expected_model in cases:
            with self.subTest(expected_key=expected_key), patch.dict(
                os.environ, {**environment, "CONVERGE_DOTENV_PATH": no_dotenv}, clear=True,
            ):
                client = OpenAICompatibleClient.from_environment()
                self.assertIsNotNone(client)
                assert client is not None
                self.assertEqual(client.api_key, expected_key)
                self.assertIn(expected_host, client.base_url)
                self.assertEqual(client.model, expected_model)

        with tempfile.TemporaryDirectory() as directory:
            dotenv = Path(directory) / ".env"
            dotenv.write_text("DEEPSEEK_API_KEY=dotenv-key\nCONVERGE_LLM_PROVIDER=deepseek\n", encoding="utf-8")
            with patch.dict(os.environ, {"CONVERGE_DOTENV_PATH": str(dotenv)}, clear=True):
                client = OpenAICompatibleClient.from_environment()
                self.assertIsNotNone(client)
                assert client is not None
                self.assertEqual(client.api_key, "dotenv-key")


if __name__ == "__main__":
    unittest.main()
