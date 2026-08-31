"""Purpose: optional semantic reranking, then RankedCandidate posterior.

Input: SearchHit list plus current SessionState and catalog access.
Output: RankedCandidate list.
Role: pipeline stage 6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...progress import emit, skip_nodes
from .belief import BELIEF_TEMPERATURE, belief_from_hits, belief_temperature
from .normalize import RankedCandidate, normalize_probabilities
from .semantic import (
    DEFAULT_MODEL,
    QwenSemanticReranker,
    RerankerConfig,
    build_product_document,
    build_shopping_query,
    semantic_belief,
)

if TYPE_CHECKING:
    from ...retrieve.catalog.retriever import CatalogRetriever
    from ...retrieve.catalog.types import SearchHit
    from ...understand.state.session import SessionState


class Ranker:
    """Stage 6: Qwen head reranking with deterministic score fallback."""

    def __init__(
        self,
        retriever: CatalogRetriever | None = None,
        semantic: QwenSemanticReranker | None = None,
    ) -> None:
        self.retriever = retriever
        self.semantic = semantic or QwenSemanticReranker()

    def apply(
        self,
        hits: list[SearchHit],
        state: SessionState | None = None,
    ) -> list[RankedCandidate]:
        if state is not None and self.retriever is not None:
            emit("retrieve", "qwen_rerank", "running")
            semantic = self.semantic.belief(state, hits, self.retriever)
            if semantic is not None:
                semantic_trace = self.semantic.last_trace
                emit(
                    "retrieve",
                    "qwen_rerank",
                    "completed",
                    {
                        "input": {
                            "hits": len(hits),
                            "semantic_head_limit": 50,
                            "intention": state.intention,
                        },
                        "output": {
                            "reranked_weights": len(semantic),
                            "path": "semantic",
                            "model": self.semantic.config.model,
                        },
                    },
                )
                emit(
                    "retrieve",
                    "semantic_logits",
                    "completed",
                    {
                        "input": {
                            "head_size": semantic_trace.get(
                                "head_size", min(len(hits), 50)
                            ),
                            "transform": "sigmoid(raw cross-encoder logit)",
                        },
                        "output": {
                            "top": semantic_trace.get("semantic_scores", []),
                        },
                    },
                )
                emit(
                    "retrieve",
                    "semantic_blend",
                    "completed",
                    {
                        "input": {
                            "semantic_weight": semantic_trace.get(
                                "semantic_weight",
                                self.semantic.config.browsing_weight
                                if state.intention == "browsing"
                                else self.semantic.config.buying_weight,
                            ),
                            "base_rank_prior": "1/log2(rank+1)",
                        },
                        "output": {
                            "top": semantic_trace.get("combined", []),
                        },
                    },
                )
                emit(
                    "retrieve",
                    "semantic_weights",
                    "completed",
                    {
                        "input": {
                            "temperature": semantic_trace.get(
                                "temperature", self.semantic.config.temperature
                            ),
                        },
                        "output": {
                            "top": semantic_trace.get("head_weights", []),
                        },
                    },
                )
                emit(
                    "retrieve",
                    "semantic_tail",
                    "completed",
                    {
                        "input": {
                            "tail_size": semantic_trace.get(
                                "tail_size", max(0, len(hits) - 50)
                            ),
                            "anchor_scale": 0.95,
                            "decay_denominator": semantic_trace.get(
                                "tail_decay_denominator", 80.0
                            ),
                        },
                        "output": {
                            "first_tail_weight": semantic_trace.get(
                                "tail_anchor"
                            ),
                        },
                    },
                )
                skip_nodes(
                    "retrieve",
                    "belief_temperature",
                    "belief_hits",
                    why="semantic reranker produced weights",
                )
                emit("retrieve", "normalize", "running")
                ranked = normalize_probabilities(semantic)
                emit(
                    "retrieve",
                    "normalize",
                    "completed",
                    {
                        "input": {
                            "path": "qwen",
                            "positive_weights": len(semantic),
                        },
                        "output": {
                            "count": len(ranked),
                            "top": [
                                {
                                    "parent_asin": item.parent_asin,
                                    "probability": round(float(item.probability), 6),
                                }
                                for item in ranked[:5]
                            ],
                        },
                        "count": len(ranked),
                    },
                )
                return ranked
            emit(
                "retrieve",
                "qwen_rerank",
                "skipped",
                {
                    "why": "reranker unavailable, disabled, or returned no weights",
                    "output": {"error": self.semantic.last_error},
                },
            )
        else:
            skip_nodes(
                "retrieve",
                "qwen_rerank",
                why="no session or catalog for semantic head",
            )
        skip_nodes(
            "retrieve",
            "semantic_logits",
            "semantic_blend",
            "semantic_weights",
            "semantic_tail",
            why="semantic reranker did not produce weights",
        )

        temperature, fused = belief_temperature(hits)
        emit(
            "retrieve",
            "belief_temperature",
            "completed",
            {
                "input": {
                    "hits": len(hits),
                    "score_min": (
                        None if not hits else round(min(hit.score for hit in hits), 8)
                    ),
                    "score_max": (
                        None if not hits else round(max(hit.score for hit in hits), 8)
                    ),
                    "contains_rrf_scores": fused,
                },
                "output": {
                    "temperature": temperature,
                    "mode": "adaptive RRF scale" if fused else "fixed structured scale",
                },
            },
        )
        emit("retrieve", "belief_hits", "running")
        weights = belief_from_hits(hits)
        emit(
            "retrieve",
            "belief_hits",
            "completed",
            {
                "input": {
                    "hits": len(hits),
                    "temperature": temperature,
                    "adaptive": fused,
                },
                "output": {
                    "weighted": len(weights),
                    "path": "deterministic score belief",
                },
            },
        )
        emit("retrieve", "normalize", "running")
        ranked = normalize_probabilities(weights)
        emit(
            "retrieve",
            "normalize",
            "completed",
            {
                "input": {
                    "path": "belief",
                    "positive_weights": len(weights),
                },
                "output": {
                    "count": len(ranked),
                    "top": [
                        {
                            "parent_asin": item.parent_asin,
                            "probability": round(float(item.probability), 6),
                        }
                        for item in ranked[:5]
                    ],
                },
                "count": len(ranked),
            },
        )
        return ranked


__all__ = [
    "BELIEF_TEMPERATURE",
    "DEFAULT_MODEL",
    "QwenSemanticReranker",
    "RankedCandidate",
    "Ranker",
    "RerankerConfig",
    "belief_from_hits",
    "belief_temperature",
    "build_product_document",
    "build_shopping_query",
    "normalize_probabilities",
    "semantic_belief",
]
