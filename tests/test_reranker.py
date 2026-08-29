"""Tests for optional semantic reranking without loading model weights."""

from __future__ import annotations

import unittest
import os
import sys
from unittest.mock import patch

from agent.decide.ranking import QwenSemanticReranker, Ranker, RerankerConfig
from agent.decide.ranking.semantic import build_product_document, build_shopping_query
from agent.retrieve.catalog.types import SearchHit
from agent.understand.observation.slots.types import ConstraintSlot
from agent.understand.state import SessionState


def _hit(parent_asin: str, score: float) -> SearchHit:
    return SearchHit(parent_asin, score, score, 0.0, 0.0, 1.0)


class _FakeModel:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.last_pairs: list[tuple[str, str]] = []

    def predict(
        self,
        inputs: list[tuple[str, str]],
        *,
        batch_size: int,
        show_progress_bar: bool,
        activation_fn: object,
    ) -> list[float]:
        self.last_pairs = list(inputs)
        return self.scores[: len(inputs)]


class _FakeRetriever:
    def __init__(self) -> None:
        self.products = {
            "POPULAR": {
                "title": "Popular formal leather shoe",
                "categories": ["Shoes"],
                "features": ["stiff formal upper"],
                "description": ["office footwear"],
                "details": {"Material": "Leather"},
                "price": 90,
                "store": "Example",
            },
            "SOFT": {
                "title": "Lightweight trail running shoe",
                "categories": ["Shoes", "Running"],
                "features": ["lightweight", "cushioned for long walks"],
                "description": ["comfortable outdoor running shoe"],
                "details": {"Use": "Trail running"},
                "price": 80,
                "store": "Example",
            },
        }

    def get_product(self, parent_asin: str) -> dict[str, object] | None:
        return self.products.get(parent_asin)


class SemanticRerankerTest(unittest.TestCase):
    def _config(self, **changes: object) -> RerankerConfig:
        values: dict[str, object] = {
            "mode": "required",
            "local_files_only": True,
            "top_n": 2,
            "batch_size": 2,
            "max_length": 512,
            "buying_weight": 0.35,
            "browsing_weight": 0.8,
            "temperature": 0.2,
        }
        values.update(changes)
        return RerankerConfig(**values)

    def test_query_separates_hard_soft_and_profile_tags(self) -> None:
        state = SessionState("s", {"preference_tags": ["comfort", "fit"]})
        state.category = "running shoes"
        state.latest_message = "forget formal shoes"
        state.typed_constraints = [
            ConstraintSlot(attribute="color", surface="black", canonical="black"),
            ConstraintSlot(
                attribute="feature",
                surface="lightweight",
                canonical="lightweight",
                is_hard=False,
            ),
        ]
        query = build_shopping_query(state)
        self.assertIn("Category: running shoes", query)
        self.assertIn("Required: color=black", query)
        self.assertIn("Preferred: feature=lightweight", query)
        self.assertIn("comfort, fit", query)
        self.assertNotIn("formal", query)

    def test_qwen_scores_reorder_only_the_retrieved_head(self) -> None:
        state = SessionState("s", {"preference_tags": ["comfort"]})
        state.category = "running shoes"
        state.intention = "browsing"
        state.typed_constraints = [
            ConstraintSlot(
                attribute="feature",
                surface="lightweight",
                canonical="lightweight",
                is_hard=False,
            )
        ]
        model = _FakeModel([-6.0, 6.0])
        retriever = _FakeRetriever()
        semantic = QwenSemanticReranker(self._config(), model=model)
        ranked = Ranker(retriever, semantic).apply(
            [_hit("POPULAR", 10.0), _hit("SOFT", 9.0)],
            state,
        )
        self.assertEqual(ranked[0].parent_asin, "SOFT")
        self.assertEqual(len(model.last_pairs), 2)
        self.assertIn("Lightweight trail running shoe", model.last_pairs[1][1])

    def test_off_mode_preserves_deterministic_ranking(self) -> None:
        state = SessionState("s", {})
        semantic = QwenSemanticReranker(
            self._config(mode="off"),
            model=_FakeModel([6.0, -6.0]),
        )
        ranked = Ranker(_FakeRetriever(), semantic).apply(
            [_hit("POPULAR", 2.0), _hit("SOFT", 1.0)],
            state,
        )
        self.assertEqual(ranked[0].parent_asin, "POPULAR")

    def test_product_document_uses_catalog_fields(self) -> None:
        document = build_product_document(_FakeRetriever().products["SOFT"])
        self.assertIn("Features: lightweight", document)
        self.assertIn("Price: 80", document)

    def test_local_only_enforces_hugging_face_offline_mode(self) -> None:
        reranker = QwenSemanticReranker(self._config(mode="auto"))
        with (
            patch.dict(
                os.environ,
                {"HF_HUB_OFFLINE": "0", "TRANSFORMERS_OFFLINE": "0"},
            ),
            patch.dict(sys.modules, {"sentence_transformers": None}),
        ):
            self.assertIsNone(reranker._ensure_model())
            self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
            self.assertEqual(os.environ["TRANSFORMERS_OFFLINE"], "1")


if __name__ == "__main__":
    unittest.main()
