"""Purpose: FTS5 BM25 recall fused with signature hits, then scored.

Input: query text, constraints, category, limit.
Output: truncated SearchHit list.
Role: robust fallback when exact intersection fails; hard_required=False does not prune empty on paraphrase.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING

from .protocol_copy import SEARCH_FIELDS, tokenize
from .signatures import coerce_constraints
from .types import BudgetInput, ConstraintInput, SearchHit, SearchWeights

if TYPE_CHECKING:
    from .retriever import CatalogRetriever


class SearchMixin:
    """Recall candidates, then score them."""

    def _fts_candidates(self: CatalogRetriever, text: str, limit: int) -> dict[str, float]:
        terms = tokenize(text, limit=48)
        if not terms or limit <= 0:
            return {}
        expression = " OR ".join(f'"{term.replace(chr(34), "")}"' for term in terms)
        weights = [0.0] + [self.field_weights[field_name] for field_name in SEARCH_FIELDS]
        placeholders = ", ".join("?" for _ in weights)
        sql = (
            "SELECT parent_asin, bm25(product_fts, "
            f"{placeholders}) AS raw_score FROM product_fts "
            "WHERE product_fts MATCH ? ORDER BY raw_score ASC LIMIT ?"
        )
        with self._lock:
            rows = self.connection.execute(
                sql, (*weights, expression, max(0, int(limit)))
            ).fetchall()
        return {
            str(row["parent_asin"]): math.log1p(max(0.0, -float(row["raw_score"])))
            for row in rows
        }

    def _popular_candidates(self: CatalogRetriever, limit: int) -> tuple[str, ...]:
        with self._lock:
            rows = self.connection.execute(
                "SELECT parent_asin FROM products "
                "ORDER BY rating_number DESC, average_rating DESC, parent_asin ASC LIMIT ?",
                (max(0, int(limit)),),
            ).fetchall()
        return tuple(str(row["parent_asin"]) for row in rows)

    def search(
        self: CatalogRetriever,
        text: str = "",
        *,
        required: ConstraintInput = None,
        required_groups: Sequence[tuple[str, Sequence[str]]] | None = None,
        preferred: ConstraintInput = None,
        excluded: ConstraintInput = None,
        categories: Iterable[str] = (),
        budget: BudgetInput = None,
        exclude_asins: Iterable[str] = (),
        limit: int = 200,
        candidate_limit: int = 600,
        weights: SearchWeights | None = None,
        hard_required: bool = False,
        hard_exclusions: bool = True,
    ) -> list[SearchHit]:
        """Retrieve and rank products.

        Exact signature candidates are unioned with fielded BM25 candidates.
        ``hard_required=True`` intersects only those required constraints that
        have at least one exact catalog match; unknown/paraphrased constraints
        therefore still fall back safely to BM25 and soft matching.
        """

        if limit <= 0:
            return []
        candidate_limit = max(limit, candidate_limit)
        if required_groups is not None:
            required_or = tuple(
                (str(attribute), tuple(str(value) for value in values if str(value).strip()))
                for attribute, values in required_groups
                if values
            )
        else:
            required_or = tuple(
                (attribute, (value,)) for attribute, value in coerce_constraints(required)
            )
        preferred_pairs = coerce_constraints(preferred)
        category_values = tuple(str(value) for value in categories if str(value).strip())

        query_parts = [text]
        query_parts.extend(value for _, values in required_or for value in values)
        query_parts.extend(value for _, value in preferred_pairs)
        query_parts.extend(category_values)
        lexical = self._fts_candidates(" ".join(query_parts), candidate_limit)
        candidates: dict[str, None] = dict.fromkeys(lexical)

        exact_required_sets: list[set[str]] = []
        for attribute, values in required_or:
            group_hits: set[str] = set()
            for value in values:
                matches = set(
                    self.signature_candidates(
                        attribute,
                        value,
                        limit=max(candidate_limit * 3, 2_000),
                    )
                )
                group_hits.update(matches)
                for parent_asin in matches:
                    candidates.setdefault(parent_asin, None)
            if group_hits:
                exact_required_sets.append(group_hits)
        for attribute, value in preferred_pairs:
            matches = set(
                self.signature_candidates(
                    attribute,
                    value,
                    limit=max(candidate_limit * 3, 2_000),
                )
            )
            for parent_asin in matches:
                candidates.setdefault(parent_asin, None)
        for value in category_values:
            matches = set(
                self.signature_candidates(
                    "category",
                    value,
                    limit=max(candidate_limit * 3, 2_000),
                )
            )
            for parent_asin in matches:
                candidates.setdefault(parent_asin, None)

        if hard_required and exact_required_sets:
            allowed = set.intersection(*exact_required_sets)
            for parent_asin in allowed:
                candidates.setdefault(parent_asin, None)
            candidates = {
                parent_asin: None
                for parent_asin in candidates
                if parent_asin in allowed
            }

        if not candidates:
            candidates = dict.fromkeys(self._popular_candidates(candidate_limit))

        hits = self.score_candidates(
            candidates,
            lexical_scores=lexical,
            required_groups=required_or,
            preferred=preferred_pairs,
            excluded=excluded,
            categories=category_values,
            budget=budget,
            exclude_asins=exclude_asins,
            weights=weights,
            hard_exclusions=hard_exclusions,
        )
        return hits[:limit]

    def retrieve(self: CatalogRetriever, *args: object, **kwargs: object) -> list[str]:
        """Convenience wrapper returning only ranked ``parent_asin`` values."""

        return [hit.parent_asin for hit in self.search(*args, **kwargs)]

    @staticmethod
    def calibrated_distribution(
        hits: Sequence[SearchHit],
        *,
        temperature: float = 1.0,
        tail_mass: float = 0.05,
    ) -> dict[str, float]:
        """Convert candidate scores into a softmax belief with reserved tail mass."""

        if not hits:
            return {}
        if temperature <= 0 or not math.isfinite(temperature):
            raise ValueError("temperature must be a finite positive number")
        tail = max(0.0, min(0.99, float(tail_mass)))
        maximum = max(hit.score for hit in hits)
        values = [math.exp((hit.score - maximum) / temperature) for hit in hits]
        total = sum(values)
        scale = (1.0 - tail) / total
        return {
            hit.parent_asin: value * scale for hit, value in zip(hits, values, strict=True)
        }
