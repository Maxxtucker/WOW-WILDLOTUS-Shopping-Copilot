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

from .profile_embed import profile_fits
from .protocol_copy import normalize_text, tokenize
from .signatures import coerce_budget, coerce_constraints, signature_similarity
from .types import (
    BudgetInput,
    ConstraintInput,
    DimensionSpec,
    ResponseSignature,
    SearchHit,
    SearchWeights,
)

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

    def _load_dimension_extras(
        self: CatalogRetriever, parent_asins: Iterable[str]
    ) -> dict[str, dict[str, float | None]]:
        if not getattr(self, "_slots_attached", False):
            return {}
        values = tuple(dict.fromkeys(str(value) for value in parent_asins if value))
        best_box: dict[str, tuple[int, dict[str, float | None]]] = {}
        best_weight: dict[str, tuple[int, float]] = {}
        for offset in range(0, len(values), 400):
            chunk = values[offset : offset + 400]
            placeholders = ",".join("?" for _ in chunk)
            with self._lock:
                rows = self.connection.execute(
                    "SELECT parent_asin, source, extras_json FROM slots.product_slots "
                    f"WHERE attribute = 'size' AND parent_asin IN ({placeholders})",
                    chunk,
                ).fetchall()
            for row in rows:
                raw = row["extras_json"]
                if not raw:
                    continue
                extras = json.loads(str(raw))
                if not isinstance(extras, dict) or extras.get("kind") != "dimension":
                    continue
                parent_asin = str(row["parent_asin"])
                rank = _dimension_source_rank(
                    str(extras.get("source_key") or ""), str(row["source"] or "")
                )
                parsed = _dimension_axes(extras)
                if any(parsed[name] is not None for name in ("length", "width", "height")):
                    previous = best_box.get(parent_asin)
                    if previous is None or rank < previous[0]:
                        best_box[parent_asin] = (rank, parsed)
                weight = parsed.get("weight")
                if weight is not None:
                    previous_w = best_weight.get(parent_asin)
                    if previous_w is None or rank < previous_w[0]:
                        best_weight[parent_asin] = (rank, weight)
        merged: dict[str, dict[str, float | None]] = {}
        for parent_asin, (_rank, axes) in best_box.items():
            merged[parent_asin] = dict(axes)
        for parent_asin, (_rank, weight) in best_weight.items():
            row = merged.setdefault(
                parent_asin,
                {"length": None, "width": None, "height": None, "weight": None},
            )
            row["weight"] = weight
        return merged

    def _load_product_text(
        self: CatalogRetriever, parent_asins: Iterable[str]
    ) -> dict[str, dict[str, str]]:
        if not getattr(self, "_slots_attached", False):
            return {}
        values = tuple(dict.fromkeys(str(value) for value in parent_asins if value))
        result: dict[str, dict[str, str]] = {}
        for offset in range(0, len(values), 400):
            chunk = values[offset : offset + 400]
            placeholders = ",".join("?" for _ in chunk)
            with self._lock:
                rows = self.connection.execute(
                    "SELECT parent_asin, field, surface, canonical FROM slots.product_text "
                    f"WHERE parent_asin IN ({placeholders})",
                    chunk,
                ).fetchall()
            for row in rows:
                parent_asin = str(row["parent_asin"])
                field = str(row["field"])
                bucket = result.setdefault(parent_asin, {})
                bucket[field] = str(row["canonical"] or "")
                bucket[f"{field}_surface"] = str(row["surface"] or "")
        return result

    def _load_slot_rarity(
        self: CatalogRetriever,
        pairs: Sequence[tuple[str, str]],
    ) -> tuple[dict[tuple[str, str], float], float]:
        if not getattr(self, "_slots_attached", False) or not pairs:
            return {}, 1.0
        attributes = tuple(dict.fromkeys(attribute for attribute, _value in pairs))
        placeholders = ",".join("?" for _ in attributes)
        max_idf = 1.0
        lookup: dict[tuple[str, str], float] = {}
        with self._lock:
            try:
                raw_max = self.connection.execute(
                    "SELECT value FROM slots.meta WHERE key = 'max_idf'"
                ).fetchone()
                if raw_max is not None:
                    max_idf = max(float(raw_max[0]), 1e-9)
            except sqlite3.Error:
                max_idf = 1.0
            try:
                rows = self.connection.execute(
                    "SELECT attribute, canonical, idf FROM slots.slot_stats "
                    f"WHERE attribute IN ({placeholders})",
                    attributes,
                ).fetchall()
            except sqlite3.Error:
                return {}, max_idf
        for row in rows:
            lookup[(str(row["attribute"]), normalize_text(row["canonical"]))] = float(
                row["idf"]
            )
        return lookup, max_idf

    def filter_hard_numeric(
        self: CatalogRetriever,
        parent_asins: Iterable[str],
        *,
        budget: BudgetInput = None,
        dimensions: DimensionSpec | None = None,
        hard_budget: bool = False,
        hard_dimension: bool = False,
        allow_missing: bool = False,
    ) -> set[str]:
        """Keep ASINs that pass hard budget and/or hard L/W/H/weight.

        ``allow_missing=True`` treats a missing price or dimension axis as
        unknown (keep). A present value outside the interval is still dropped.
        """

        values = {str(item) for item in parent_asins if item}
        if not values or (not hard_budget and not hard_dimension):
            return values
        rows = self._load_candidate_rows(values)
        dim_map = (
            self._load_dimension_extras(rows)
            if hard_dimension and dimensions is not None
            else {}
        )
        budget_range = coerce_budget(budget) if hard_budget else None
        kept: set[str] = set()
        for parent_asin, row in rows.items():
            if hard_budget and budget_range is not None:
                price = None if row["price"] is None else float(row["price"])
                if price is None:
                    if not allow_missing:
                        continue
                elif not self._budget_in_range(price, budget_range):
                    continue
            if hard_dimension and dimensions is not None:
                if not _dimension_matches(
                    dim_map.get(parent_asin),
                    dimensions,
                    allow_missing=allow_missing,
                ):
                    continue
            kept.add(parent_asin)
        return kept

    @staticmethod
    def _budget_in_range(
        price: float | None,
        budget: tuple[float | None, float | None] | None,
    ) -> bool:
        if price is None or budget is None:
            return False
        minimum, maximum = budget
        return (minimum is None or price >= minimum) and (
            maximum is None or price <= maximum
        )

    @staticmethod
    def _budget_fit(
        price: float | None,
        budget: tuple[float | None, float | None] | None,
    ) -> float:
        if price is None or budget is None:
            return 0.0
        minimum, maximum = budget
        if (minimum is None or price >= minimum) and (
            maximum is None or price <= maximum
        ):
            return 1.0
        return 0.0

    def score_candidates(
        self: CatalogRetriever,
        parent_asins: Iterable[str],
        *,
        lexical_scores: Mapping[str, float] | None = None,
        required: ConstraintInput = None,
        required_groups: Sequence[tuple[str, Sequence[str]]] | None = None,
        preferred: ConstraintInput = None,
        preferred_groups: Sequence[tuple[str, Sequence[str]]] | None = None,
        excluded: ConstraintInput = None,
        categories: Iterable[str] = (),
        budget: BudgetInput = None,
        exclude_asins: Iterable[str] = (),
        weights: SearchWeights | None = None,
        hard_exclusions: bool = True,
        hard_budget: bool = False,
        dimensions: DimensionSpec | None = None,
        hard_dimension: bool = False,
        in_exact_pool: bool = False,
        text_query: str = "",
        profile_tags: Sequence[str] = (),
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
        if preferred_groups is not None:
            preferred_or = tuple(
                (str(attribute), tuple(str(value) for value in values if str(value).strip()))
                for attribute, values in preferred_groups
                if values
            )
        else:
            preferred_or = tuple(
                (attribute, (value,)) for attribute, value in coerce_constraints(preferred)
            )
        excluded_pairs = coerce_constraints(excluded)
        category_pairs = tuple(("category", str(value)) for value in categories if str(value).strip())
        budget_range = coerce_budget(budget)
        excluded_ids = {str(value) for value in exclude_asins}
        lexical = lexical_scores or {}
        rows = self._load_candidate_rows(parent_asins)
        dim_map = (
            self._load_dimension_extras(rows) if dimensions is not None else {}
        )
        need_text = bool(text_query.strip()) or bool(profile_tags)
        text_map = self._load_product_text(rows) if need_text else {}
        rarity_pairs = [
            (attribute, value)
            for attribute, values in (*required_or, *preferred_or)
            for value in values
        ]
        rarity_pairs.extend(category_pairs)
        rarity_lookup, max_idf = self._load_slot_rarity(rarity_pairs)
        soft_tokens = set(tokenize(text_query)) if text_query.strip() else set()
        profile_docs = {
            parent_asin: {
                "title": fields.get("title_surface") or "",
                "details": fields.get("details_surface") or "",
                "description": fields.get("description_surface") or "",
            }
            for parent_asin, fields in text_map.items()
        }
        profile_scores = profile_fits(profile_tags, profile_docs)
        hits: list[SearchHit] = []

        def _rarity(attribute: str, value: str) -> float:
            key = (attribute, normalize_text(value))
            idf = rarity_lookup.get(key)
            if idf is None:
                return 1.0
            return 0.5 + 0.5 * min(1.0, max(0.0, idf / max_idf))

        def _group_rarity(attribute: str, values: Sequence[str]) -> float:
            return max((_rarity(attribute, value) for value in values), default=1.0)

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
                    rarity = (
                        1.0 if in_exact_pool else _rarity(attribute, matched_value)
                    )
                    structured_score += scoring.required * similarity * rarity
                elif not in_exact_pool:
                    structured_score += scoring.missing_required * _group_rarity(
                        attribute, values
                    )
            if required_or:
                required_coverage = sum(required_similarities) / len(required_similarities)
                reasons.append(f"required_coverage={required_coverage:.2f}")
            else:
                required_coverage = 1.0

            for attribute, values in preferred_or:
                similarity = 0.0
                matched_value = None
                for value in values:
                    value_score = signature_similarity(
                        attribute, value, signature.search_values.get(attribute, ())
                    )
                    if value_score > similarity:
                        similarity = value_score
                        matched_value = value
                if similarity > 0 and matched_value is not None:
                    matched.append(f"preferred:{attribute}={matched_value}")
                    structured_score += (
                        scoring.preferred
                        * similarity
                        * _rarity(attribute, matched_value)
                    )

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
            category_value = None
            for attribute, value in category_pairs:
                hit = signature_similarity(
                    attribute, value, signature.search_values.get(attribute, ())
                )
                if hit > category_match:
                    category_match = hit
                    category_value = value
            if category_match:
                rarity = (
                    1.0
                    if in_exact_pool or category_value is None
                    else _rarity("category", category_value)
                )
                structured_score += scoring.category * category_match * rarity
                matched.append("category")

            price = None if row["price"] is None else float(row["price"])
            if hard_budget and budget_range is not None:
                if not self._budget_in_range(price, budget_range):
                    continue
            budget_fit = self._budget_fit(price, budget_range)
            structured_score += scoring.budget * budget_fit
            if budget_fit:
                reasons.append(f"budget_fit={budget_fit:.2f}")

            if dimensions is not None:
                dim_ok = _dimension_matches(dim_map.get(parent_asin), dimensions)
                if hard_dimension and not dim_ok:
                    continue
                dim_fit = 1.0 if dim_ok else 0.0
                structured_score += scoring.dimension * dim_fit
                if dim_ok:
                    matched.append("size")
                    reasons.append("dimension_fit=1.00")

            rating = 0.0 if row["average_rating"] is None else float(row["average_rating"])
            rating_count = max(0, int(row["rating_number"]))
            prior_score = (
                scoring.rating * max(0.0, min(1.0, rating / 5.0))
                + scoring.popularity
                * math.log1p(rating_count)
                / math.log1p(self._max_rating_count)
            )
            lexical_score = float(lexical.get(parent_asin, 0.0))
            text_fit = _text_fit(text_map.get(parent_asin), soft_tokens)
            if text_fit:
                reasons.append(f"text_fit={text_fit:.2f}")
            profile_fit = float(profile_scores.get(parent_asin, 0.0))
            if profile_fit:
                reasons.append(f"profile_fit={profile_fit:.2f}")
            score = (
                scoring.lexical * lexical_score
                + structured_score
                + prior_score
                + scoring.text * text_fit
                + scoring.profile * profile_fit
            )
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


_EQ_ABS_IN = 0.25
_EQ_ABS_LB = 0.05
_EQ_REL = 0.10


def _text_fit(
    fields: Mapping[str, str] | None, soft_tokens: set[str]
) -> float:
    if not fields or not soft_tokens:
        return 0.0

    def cover(blob: str) -> float:
        tokens = set(tokenize(blob))
        if not tokens:
            return 0.0
        return len(soft_tokens & tokens) / len(soft_tokens)

    return max(
        cover(fields.get("title") or ""),
        0.7 * cover(fields.get("details") or ""),
        0.5 * cover(fields.get("description") or ""),
    )


def _dimension_source_rank(source_key: str, source: str) -> int:
    blob = f"{source_key} {source}".casefold()
    if "package" in blob:
        return 2
    if "product" in blob or "item" in blob:
        return 0
    return 1


def _dimension_axes(extras: Mapping[str, object]) -> dict[str, float | None]:
    def _num(key: str) -> float | None:
        raw = extras.get(key)
        if raw in (None, ""):
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    return {
        "length": _num("length"),
        "width": _num("width"),
        "height": _num("height"),
        "weight": _num("weight"),
    }


def _dimension_matches(
    axes: Mapping[str, float | None] | None,
    query: DimensionSpec,
    *,
    allow_missing: bool = False,
) -> bool:
    if axes is None:
        return allow_missing
    stated = False
    for name in ("length", "width", "height", "weight"):
        wanted = getattr(query, name)
        if wanted is None:
            continue
        stated = True
        have = axes.get(name)
        if have is None:
            if allow_missing:
                continue
            return False
        floor = _EQ_ABS_LB if name == "weight" else _EQ_ABS_IN
        tol = max(floor, abs(wanted) * _EQ_REL)
        op = query.op or "eq"
        if op == "lte":
            if have > wanted + tol:
                return False
        elif op == "gte":
            if have < wanted - tol:
                return False
        elif abs(have - wanted) > tol:
            return False
    return stated
