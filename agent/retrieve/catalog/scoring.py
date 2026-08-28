"""Purpose: structured scores for a given ASIN pool (constraint coverage + category + rating/popularity).

Input: iterable of parent_asin, required/preferred, exclude_asins, lexical scores.
Output: SearchHit list sorted by score.
Role: shared ranker for the exact path and the BM25 path; does not recall.
"""

from __future__ import annotations

import json
import math
import sqlite3
import zlib
from collections.abc import Iterable, Mapping, Sequence
from typing import TYPE_CHECKING

from .signatures import coerce_budget, coerce_constraints, signature_similarity
from .types import BudgetInput, ConstraintInput, ResponseSignature, SearchHit, SearchWeights

if TYPE_CHECKING:
    from .retriever import CatalogRetriever


class ScoringMixin:
    """Score catalog rows without performing retrieval."""

    def _load_candidate_rows(
        self: CatalogRetriever, parent_asins: Iterable[str]
    ) -> dict[str, sqlite3.Row]:
        values = tuple(dict.fromkeys(str(value) for value in parent_asins if value))
        result: dict[str, sqlite3.Row] = {}
        for offset in range(0, len(values), 400):
            chunk = values[offset : offset + 400]
            placeholders = ",".join("?" for _ in chunk)
            with self._lock:
                rows = self.connection.execute(
                    "SELECT parent_asin, price, average_rating, rating_number, "
                    f"signature_json FROM products WHERE parent_asin IN ({placeholders})",
                    chunk,
                ).fetchall()
            result.update({str(row["parent_asin"]): row for row in rows})
        return result

    @staticmethod
    def _budget_fit(
        price: float | None,
        budget: tuple[float | None, float | None] | None,
    ) -> float:
        if price is None or budget is None:
            return 0.0
        minimum, maximum = budget
        if (minimum is None or price >= minimum) and (maximum is None or price <= maximum):
            return 1.0
        boundary = minimum if minimum is not None and price < minimum else maximum
        if boundary is None:
            return 0.0
        scale = max(10.0, abs(boundary) * 0.25)
        return max(-1.0, 1.0 - abs(price - boundary) / scale)

    def score_candidates(
        self: CatalogRetriever,
        parent_asins: Iterable[str],
        *,
        lexical_scores: Mapping[str, float] | None = None,
        required: ConstraintInput = None,
        required_groups: Sequence[tuple[str, Sequence[str]]] | None = None,
        preferred: ConstraintInput = None,
        excluded: ConstraintInput = None,
        categories: Iterable[str] = (),
        budget: BudgetInput = None,
        exclude_asins: Iterable[str] = (),
        weights: SearchWeights | None = None,
        hard_exclusions: bool = True,
    ) -> list[SearchHit]:
        """Score a supplied candidate pool without performing retrieval."""

        scoring = weights or SearchWeights()
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
        excluded_pairs = coerce_constraints(excluded)
        category_pairs = tuple(("category", str(value)) for value in categories if str(value).strip())
        budget_range = coerce_budget(budget)
        excluded_ids = {str(value) for value in exclude_asins}
        lexical = lexical_scores or {}
        rows = self._load_candidate_rows(parent_asins)
        hits: list[SearchHit] = []

        for parent_asin, row in rows.items():
            if parent_asin in excluded_ids:
                continue
            payload = json.loads(
                zlib.decompress(bytes(row["signature_json"])).decode("utf-8")
            )
            signature = ResponseSignature.from_dict(payload)
            reasons: list[str] = []
            matched: list[str] = []
            structured_score = 0.0

            required_similarities: list[float] = []
            for attribute, values in required_or:
                similarity = 0.0
                matched_value = None
                for value in values:
                    score = signature_similarity(
                        attribute, value, signature.search_values.get(attribute, ())
                    )
                    if score > similarity:
                        similarity = score
                        matched_value = value
                required_similarities.append(similarity)
                if similarity > 0 and matched_value is not None:
                    matched.append(f"required:{attribute}={matched_value}")
                structured_score += scoring.required * similarity
            if required_or:
                missing = sum(1 for value in required_similarities if value == 0.0)
                structured_score += scoring.missing_required * missing
                required_coverage = sum(required_similarities) / len(required_similarities)
                reasons.append(f"required_coverage={required_coverage:.2f}")
            else:
                required_coverage = 1.0

            for attribute, value in preferred_pairs:
                similarity = signature_similarity(
                    attribute, value, signature.search_values.get(attribute, ())
                )
                if similarity > 0:
                    matched.append(f"preferred:{attribute}={value}")
                structured_score += scoring.preferred * similarity

            excluded_match = 0.0
            for attribute, value in excluded_pairs:
                similarity = signature_similarity(
                    attribute, value, signature.search_values.get(attribute, ())
                )
                excluded_match = max(excluded_match, similarity)
            if hard_exclusions and excluded_match >= 0.9:
                continue
            structured_score += scoring.excluded * excluded_match
            if excluded_match:
                reasons.append(f"excluded_match={excluded_match:.2f}")

            category_match = 0.0
            for attribute, value in category_pairs:
                category_match = max(
                    category_match,
                    signature_similarity(
                        attribute, value, signature.search_values.get(attribute, ())
                    ),
                )
            structured_score += scoring.category * category_match
            if category_match:
                matched.append("category")

            price = None if row["price"] is None else float(row["price"])
            budget_fit = self._budget_fit(price, budget_range)
            structured_score += scoring.budget * budget_fit
            if budget_fit:
                reasons.append(f"budget_fit={budget_fit:.2f}")

            rating = 0.0 if row["average_rating"] is None else float(row["average_rating"])
            rating_count = max(0, int(row["rating_number"]))
            prior_score = (
                scoring.rating * max(0.0, min(1.0, rating / 5.0))
                + scoring.popularity
                * math.log1p(rating_count)
                / math.log1p(self._max_rating_count)
            )
            lexical_score = float(lexical.get(parent_asin, 0.0))
            score = scoring.lexical * lexical_score + structured_score + prior_score
            hits.append(
                SearchHit(
                    parent_asin=parent_asin,
                    score=round(score, 8),
                    lexical_score=round(lexical_score, 8),
                    structured_score=round(structured_score, 8),
                    prior_score=round(prior_score, 8),
                    required_coverage=round(required_coverage, 8),
                    matched_constraints=tuple(matched),
                    reasons=tuple(reasons),
                )
            )

        hits.sort(
            key=lambda item: (
                -item.score,
                -item.required_coverage,
                -item.lexical_score,
                item.parent_asin,
            )
        )
        return hits
