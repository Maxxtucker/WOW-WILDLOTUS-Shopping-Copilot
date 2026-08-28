# retrieve/candidates — exact pool and BM25 fusion

## Purpose

Pipeline stage 5. Fold filter results into a truncated `SearchHit` list. Buying scores the exact pool first; Browsing always unions BM25. Weights and caps come from `routing.py`.

## Files

| File | Role |
|---|---|
| `query.py` | category + slot search values (or ranking_constraints) + current message + profile tags → BM25 query. |
| `routing.py` | `routing_for(track)`: SearchWeights, limit, exact-first flag. |
| `retrieve.py` | `CandidateOrganizer` / `retrieve_candidates`. |

## Collaboration

```text
Buying / unset track:
    exact non-empty → retriever.score_candidates(exact)[:150 or 500]
    exact empty or scored empty → rewrite_query → retriever.search(..., hard_required=False)
Browsing:
    rewrite_query → retriever.search(..., hard_required=False, limit=500)
```

`excluded_asins` are dropped in scoring/search. This package does not choose the question or slate length. `track` is language-inferred session state, not an evaluator scenario label.

## Core variables

- Input: `SessionState`, `exact: set[str] | None`
- Output: `list[SearchHit]` (Buying cap 150, otherwise 500)
- Query string: see `rewrite_query` (typed search values when slots exist)
- Required: `from_slots.required_and_budget` (groups: OR inside, AND across; plus budget interval)

## Core code

- Fusion entry: `retrieve_candidates` in `retrieve.py`
- Routing: `routing_for` in `routing.py`
- Rewrite: `rewrite_query` in `query.py`
