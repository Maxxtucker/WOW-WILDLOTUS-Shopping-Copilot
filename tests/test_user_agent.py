from __future__ import annotations

import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from evaluator.user_agent import OpenAICompatibleClient, ScenarioUserAgent


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


class ScenarioUserAgentTest(unittest.TestCase):
    def test_mode_one_matches_template_behavior(self) -> None:
        buyer = ScenarioUserAgent(mode=1)
        disclosed: set[str] = set()
        buyer.reset("s", sample(), "Men Shoes")

        self.assertEqual(
            buyer.initial_message("s", disclosed),
            "I'm looking for Men Shoes. A key requirement is: leather.",
        )
        self.assertEqual(disclosed, {"leather"})
        self.assertEqual(
            buyer.customer_reply("s", "feature", disclosed, False),
            ("For that, what matters is: Rubber sole.", False),
        )

        compatibility_disclosed: set[str] = set()
        self.assertEqual(
            buyer.initial_message(sample(), "Men Shoes", compatibility_disclosed),
            "I'm looking for Men Shoes. A key requirement is: leather.",
        )
        self.assertEqual(
            buyer.customer_reply(sample(), "feature", compatibility_disclosed, False),
            ("For that, what matters is: Rubber sole.", False),
        )

    def test_mode_two_keeps_exact_semantic_values(self) -> None:
        client = FakeClient([
            {"message": "I'm looking for Men Shoes; the key requirement is: leather."},
            {"message": "For me, what matters is: Rubber sole."},
        ])
        buyer = ScenarioUserAgent(mode=2, client=client)
        disclosed: set[str] = set()
        buyer.reset("s", sample(), "Men Shoes")

        initial = buyer.initial_message("s", disclosed)
        reply = buyer.customer_reply("s", "feature", disclosed, False)

        self.assertEqual(
            initial,
            "I'm looking for Men Shoes; the key requirement is: leather.",
        )
        self.assertEqual(reply, ("For me, what matters is: Rubber sole.", False))
        self.assertEqual(disclosed, {"leather", "Rubber sole"})
        self.assertEqual([payload["mode"] for payload in client.payloads], [2, 2])
        self.assertTrue(all("Mode 2" in prompt for prompt in client.prompts))

    def test_mode_two_rejects_semantic_drift(self) -> None:
        client = FakeClient([
            {"message": "I need Men Shoes; cotton is essential."},
            {"message": "For me, what matters is: cotton."},
        ])
        buyer = ScenarioUserAgent(mode=2, client=client)
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

    def test_mode_three_accepts_policy_variant_message(self) -> None:
        client = FakeClient([
            {"message": "I am shopping for Men Shoes and need leather."},
            {"message": "I care most about Rubber sole right now."},
        ])
        buyer = ScenarioUserAgent(mode=3, client=client)
        disclosed: set[str] = set()
        buyer.reset("s", sample(), "Men Shoes")

        self.assertEqual(
            buyer.initial_message("s", disclosed),
            "I am shopping for Men Shoes and need leather.",
        )
        self.assertEqual(
            buyer.customer_reply("s", "feature", disclosed, False),
            ("I care most about Rubber sole right now.", False),
        )

    def test_mode_four_can_mark_boundary_reply(self) -> None:
        client = FakeClient([
            {"message": "I am looking for Men Shoes, but I am undecided."},
            {"message": "I have no preference for feature; use your judgment.", "boundary_used": True},
        ])
        buyer = ScenarioUserAgent(mode=4, client=client)
        disclosed: set[str] = set()
        boundary = False
        buyer.reset("s", {**sample("boundary")}, "Men Shoes")

        buyer.initial_message("s", disclosed)
        message, boundary = buyer.customer_reply("s", "feature", disclosed, boundary)

        self.assertEqual(message, "I have no preference for feature; use your judgment.")
        self.assertTrue(boundary)

    def test_environment_defaults_support_dashscope_and_openai(self) -> None:
        no_dotenv = str(Path(__file__).with_name("__missing_test_dotenv__"))
        with patch.dict(
            os.environ,
            {"DASHSCOPE_API_KEY": "ds-key", "CONVERGE_DOTENV_PATH": no_dotenv},
            clear=True,
        ):
            client = OpenAICompatibleClient.from_environment()
            self.assertIsNotNone(client)
            assert client is not None
            self.assertEqual(client.api_key, "ds-key")
            self.assertIn("dashscope.aliyuncs.com", client.base_url)
            self.assertEqual(client.model, "qwen-plus")

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "openai-key",
                "CONVERGE_LLM_PROVIDER": "openai",
                "CONVERGE_DOTENV_PATH": no_dotenv,
            },
            clear=True,
        ):
            client = OpenAICompatibleClient.from_environment()
            self.assertIsNotNone(client)
            assert client is not None
            self.assertEqual(client.api_key, "openai-key")
            self.assertEqual(client.base_url, "https://api.openai.com/v1")

        with patch.dict(
                os.environ,
            {
                "DEEPSEEK_API_KEY": "deepseek-key",
                "CONVERGE_LLM_PROVIDER": "dp",
                "CONVERGE_DOTENV_PATH": no_dotenv,
            },
            clear=True,
        ):
            client = OpenAICompatibleClient.from_environment()
            self.assertIsNotNone(client)
            assert client is not None
            self.assertEqual(client.api_key, "deepseek-key")
            self.assertEqual(client.base_url, "https://api.deepseek.com/v1")
            self.assertEqual(client.model, "deepseek-chat")

    def test_environment_reads_dotenv_without_overwriting_process_vars(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dotenv = Path(directory) / ".env"
            dotenv.write_text(
                "DEEPSEEK_API_KEY=dotenv-key\n"
                "CONVERGE_LLM_PROVIDER=deepseek\n"
                "CONVERGE_LLM_MODEL=deepseek-chat\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"CONVERGE_DOTENV_PATH": str(dotenv)},
                clear=True,
            ):
                client = OpenAICompatibleClient.from_environment()
                self.assertIsNotNone(client)
                assert client is not None
                self.assertEqual(client.api_key, "dotenv-key")
                self.assertEqual(client.base_url, "https://api.deepseek.com/v1")

            with patch.dict(
                os.environ,
                {
                    "CONVERGE_DOTENV_PATH": str(dotenv),
                    "DEEPSEEK_API_KEY": "process-key",
                    "CONVERGE_LLM_PROVIDER": "deepseek",
                },
                clear=True,
            ):
                client = OpenAICompatibleClient.from_environment()
                self.assertIsNotNone(client)
                assert client is not None
                self.assertEqual(client.api_key, "process-key")


if __name__ == "__main__":
    unittest.main()
