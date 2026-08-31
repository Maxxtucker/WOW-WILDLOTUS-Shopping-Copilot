"""NLU-independent safety recall and weighted reciprocal-rank fusion.

The strict route remains authoritative evidence. Relaxed structured recall and
raw active-intent BM25 prevent one uncertain slot interpretation from becoming
an irreversible recall decision.
"""

from __future__ import annotations

from collections.abc import Sequence

from ...progress import progress_enabled
from ..catalog.types import SearchHit

RRF_CONSTANT = 60.0
STRICT_WEIGHT = 1.40
RELAXED_WEIGHT = 0.90
RAW_TEXT_WEIGHT = 1.25


def fuse_routes(
    routes: Sequence[tuple[str, float, Sequence[SearchHit]]],
    *,
    limit: int,
) -> list[SearchHit]:
    """Fuse ranked routes while retaining inspectable hit components."""

    include_breakdown = progress_enabled()
    scores: dict[str, float] = {}
    contributions: dict[str, dict[str, float]] = {}
    best: dict[str, SearchHit] = {}
    source_names: dict[str, list[str]] = {}
    first_seen: dict[str, int] = {}
    serial = 0
    for route_name, weight, hits in routes:
        seen_in_route: set[str] = set()
        for rank, hit in enumerate(hits, start=1):
            asin = hit.parent_asin
            if asin in seen_in_route:
                continue
            seen_in_route.add(asin)
            if asin not in first_seen:
                first_seen[asin] = serial
                serial += 1
            contribution = weight / (RRF_CONSTANT + rank)
            scores[asin] = scores.get(asin, 0.0) + contribution
            if include_breakdown:
                contributions.setdefault(asin, {})[route_name] = contribution
            source_names.setdefault(asin, []).append(route_name)
            previous = best.get(asin)
            if previous is None or hit.score > previous.score:
                best[asin] = hit

    ordered = sorted(
        scores,
        key=lambda asin: (-scores[asin], first_seen[asin], asin),
    )[: max(0, int(limit))]
    result: list[SearchHit] = []
    for asin in ordered:
        hit = best[asin]
        routes_reason = "route:" + "+".join(dict.fromkeys(source_names[asin]))
        breakdown = dict(hit.score_breakdown)
        if include_breakdown:
            for route_name, contribution in contributions.get(asin, {}).items():
                breakdown[f"rrf_{route_name}"] = round(contribution, 8)
            breakdown["rrf_total"] = round(scores[asin], 8)
        result.append(
            SearchHit(
                parent_asin=asin,
                score=scores[asin],
                lexical_score=hit.lexical_score,
                structured_score=hit.structured_score,
                prior_score=hit.prior_score,
                required_coverage=hit.required_coverage,
                matched_constraints=hit.matched_constraints,
                reasons=(*hit.reasons, routes_reason),
                score_breakdown=breakdown,
            )
        )
    return result


def route_membership(hits: Sequence[SearchHit]) -> dict[str, int]:
    """Count fused result membership by diagnostic route label."""

    counts: dict[str, int] = {}
    for hit in hits:
        for reason in hit.reasons:
            if not reason.startswith("route:"):
                continue
            for name in reason.removeprefix("route:").split("+"):
                counts[name] = counts.get(name, 0) + 1
    return counts
