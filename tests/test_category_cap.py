"""Category cap safety net: fold match, retries, and sidecar df fallback.

Live Ollama is never required. Public-set labels are not read.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from agent.progress import progress_listener
from agent.understand.observation.category_cap import (
    CATEGORY_CAP_ATTEMPTS,
    cap_category_canonicals,
    cap_category_payload,
    fallback_category_tags,
)
from agent.understand.observation.category_tree import CategoryNode
from agent.understand.observation.llm_nlu import OllamaNluClient


FAT_TAGS = (
    "jeans",
    "dress",
    "shirt",
    "shorts",
    "sock",
    "bodysuit",
    "polo",
    "skirt",
)
FAT_MESSAGE = "jeans dress shirt shorts sock bodysuit polo skirt for women"


def _fat_nodes() -> tuple[CategoryNode, ...]:
    women = CategoryNode(id="Women", label="Women", catalog_tags=("woman",))
    clothing = CategoryNode(id="clothing", label="Clothing", catalog_tags=FAT_TAGS)
    return women, clothing


class CategoryCapUnitTest(unittest.TestCase):
    def test_at_most_five_skips_llm(self) -> None:
        calls: list[object] = []
        events: list[dict] = []

        def complete(*_args, **_kwargs):
            calls.append(1)
            return {"ids": ["jeans", "dress", "shirt", "shorts", "sock"]}

        with progress_listener(events.append):
            kept = cap_category_canonicals(
                "women bodysuit",
                ("woman", "bodysuit"),
                complete=complete,
                product_counts={},
            )
        self.assertEqual(kept, ("woman", "bodysuit"))
        self.assertEqual(calls, [])
        self.assertTrue(
            any(
                event["node"] == "category_cap" and event["status"] == "skipped"
                for event in events
            )
        )

    def test_valid_five_keeps_model_ids(self) -> None:
        kept = cap_category_canonicals(
            FAT_MESSAGE,
            FAT_TAGS,
            complete=lambda *_args, **_kwargs: {
                "ids": ["bodysuit", "jeans", "dress", "shirt", "shorts"]
            },
            product_counts={},
        )
        self.assertEqual(kept, ("bodysuit", "jeans", "dress", "shirt", "shorts"))

    def test_fold_match_writes_pool_originals(self) -> None:
        pool = FAT_TAGS + ("t shirt",)
        message = FAT_MESSAGE + " t-shirt"
        kept = cap_category_canonicals(
            message,
            pool,
            complete=lambda *_args, **_kwargs: {
                "ids": ["Bodysuits", "T-Shirt", "Jeans", "Dress", "Shirt"]
            },
            product_counts={},
        )
        self.assertEqual(kept, ("bodysuit", "t shirt", "jeans", "dress", "shirt"))

    def test_invalid_then_valid_uses_second_attempt(self) -> None:
        payloads = [
            {"ids": ["not-a-tag", "jeans", "dress", "shirt", "shorts"]},
            {"ids": ["bodysuit", "jeans", "dress", "shirt", "shorts"]},
        ]
        events: list[dict] = []

        def complete(*_args, **_kwargs):
            return payloads.pop(0)

        with progress_listener(events.append):
            kept = cap_category_canonicals(
                FAT_MESSAGE,
                FAT_TAGS,
                complete=complete,
                product_counts={},
            )
        self.assertEqual(kept, ("bodysuit", "jeans", "dress", "shirt", "shorts"))
        attempts = [
            event["detail"]["attempt"]
            for event in events
            if event["node"] == "category_cap" and event["status"] == "error"
        ]
        self.assertEqual(attempts, [1])
        completed = next(
            event
            for event in events
            if event["node"] == "category_cap" and event["status"] == "completed"
        )
        self.assertEqual(completed["detail"]["attempt"], 2)

    def test_missing_grounded_item_retries(self) -> None:
        payloads = [
            {"ids": ["jeans", "dress", "shirt", "shorts", "polo"]},
            {"ids": ["bodysuit", "jeans", "dress", "shirt", "shorts"]},
        ]

        def complete(*_args, **_kwargs):
            return payloads.pop(0)

        kept = cap_category_canonicals(
            "I need a bodysuit",
            FAT_TAGS,
            complete=complete,
            product_counts={},
        )
        self.assertIn("bodysuit", kept)

    def test_duplicate_fold_is_invalid(self) -> None:
        calls = {"n": 0}

        def complete(*_args, **_kwargs):
            calls["n"] += 1
            return {"ids": ["bodysuit", "Bodysuits", "jeans", "dress", "shirt"]}

        kept = cap_category_canonicals(
            FAT_MESSAGE,
            FAT_TAGS,
            complete=complete,
            product_counts={"jeans": 9, "dress": 8, "shirt": 7, "shorts": 6, "sock": 1},
        )
        self.assertEqual(calls["n"], CATEGORY_CAP_ATTEMPTS)
        self.assertEqual(len(kept), 5)
        self.assertEqual(kept, ("jeans", "dress", "shirt", "shorts", "sock"))

    def test_three_failures_use_df_fallback(self) -> None:
        events: list[dict] = []

        def complete(*_args, **_kwargs):
            return None

        counts = {
            "jeans": 50,
            "dress": 40,
            "shirt": 30,
            "shorts": 20,
            "sock": 10,
            "polo": 5,
            "skirt": 4,
            "bodysuit": 2,
        }
        with progress_listener(events.append):
            kept = cap_category_canonicals(
                FAT_MESSAGE,
                FAT_TAGS,
                complete=complete,
                product_counts=counts,
            )
        self.assertEqual(len(kept), 5)
        # All eight tags are grounded, so fallback ranks those by df.
        self.assertEqual(kept, ("jeans", "dress", "shirt", "shorts", "sock"))
        errors = [
            event
            for event in events
            if event["node"] == "category_cap" and event["status"] == "error"
        ]
        self.assertEqual(len(errors), CATEGORY_CAP_ATTEMPTS)
        completed = next(
            event
            for event in events
            if event["node"] == "category_cap" and event["status"] == "completed"
        )
        self.assertEqual(completed["detail"].get("why"), "slot_stats.df")

    def test_zero_df_fills_five_in_stable_order(self) -> None:
        message = "looking for clothing"
        pool = ("zebra", "yak", "xray", "willow", "violet", "umber")
        kept = cap_category_canonicals(
            message,
            pool,
            complete=lambda *_args, **_kwargs: None,
            product_counts={},
        )
        self.assertEqual(kept, ("umber", "violet", "willow", "xray", "yak"))

    def test_payload_rows_trim_to_kept(self) -> None:
        rows = [
            {"surface": "women", "is_hard": True, "canonical": ["woman"]},
            {"surface": "clothing", "is_hard": True, "canonical": list(FAT_TAGS)},
        ]
        kept_ids = ["bodysuit", "jeans", "dress", "shirt", "shorts"]
        trimmed = cap_category_payload(
            FAT_MESSAGE,
            rows,
            complete=lambda *_args, **_kwargs: {"ids": kept_ids},
            product_counts={},
        )
        tags = [tag for row in trimmed for tag in row["canonical"]]
        self.assertEqual(set(tags), set(kept_ids))
        self.assertTrue(all(row["canonical"] for row in trimmed))
        self.assertNotIn("woman", tags)


class CategoryCapInspectTest(unittest.TestCase):
    def test_inspect_writes_capped_category_slots(self) -> None:
        client = OllamaNluClient()
        picks = _fat_nodes()
        cap_ids = ["bodysuit", "jeans", "dress", "shirt", "shorts"]

        def complete(_user, *, system=None, **_kwargs):
            text = system or ""
            if "filter catalog category tags" in text:
                return {"ids": cap_ids}
            if text.startswith("You judge whether this shopper utterance discloses"):
                return {"empty": False}
            if "Do not emit category" in text:
                return {"constraints": [], "empty": False}
            return {"keep": []}

        with (
            patch.object(client, "_category_picks", return_value=picks),
            patch.object(client, "_complete", side_effect=complete) as mocked,
        ):
            _raw, extract = client.inspect(FAT_MESSAGE)
        self.assertGreaterEqual(mocked.call_count, 2)
        assert extract is not None
        tags: set[str] = set()
        for slot in extract.slots:
            if slot.attribute == "category" and slot.canonical:
                tags.update(slot.canonical)
        self.assertEqual(tags, set(cap_ids))
        self.assertTrue(tags.isdisjoint({"polo", "skirt", "sock", "woman"}))

    def test_inspect_skips_cap_when_identity_is_small(self) -> None:
        client = OllamaNluClient()
        women = CategoryNode(id="Women", label="Women", catalog_tags=("woman",))
        clothing = CategoryNode(
            id="clothing",
            label="Clothing",
            catalog_tags=("clothing", "jeans", "bra", "trench", "sock", "bodysuit"),
        )
        events: list[dict] = []
        with (
            patch.object(client, "_category_picks", return_value=(women, clothing)),
            patch.object(
                client,
                "_complete",
                side_effect=lambda _user, *, system=None, **_k: (
                    {"empty": False}
                    if (system or "").startswith(
                        "You judge whether this shopper utterance discloses"
                    )
                    else {"constraints": [], "empty": False}
                ),
            ) as mocked,
            progress_listener(events.append),
        ):
            _raw, extract = client.inspect("Women Bodysuits")
        self.assertEqual(mocked.call_count, 2)
        assert extract is not None
        tags: set[str] = set()
        for slot in extract.slots:
            if slot.attribute == "category" and slot.canonical:
                tags.update(slot.canonical)
        self.assertEqual(tags, {"woman", "bodysuit"})
        self.assertTrue(
            any(
                event["node"] == "category_cap" and event["status"] == "skipped"
                for event in events
            )
        )


class FallbackRankTest(unittest.TestCase):
    def test_grounded_forced_then_df(self) -> None:
        pool = ("rare", "common", "mid", "other", "extra", "spare")
        kept = fallback_category_tags(
            pool,
            ("rare",),
            {"common": 100, "mid": 50, "other": 40, "extra": 30, "spare": 20, "rare": 1},
        )
        self.assertEqual(kept[0], "rare")
        self.assertEqual(kept[1:], ("common", "mid", "other", "extra"))


if __name__ == "__main__":
    unittest.main()
