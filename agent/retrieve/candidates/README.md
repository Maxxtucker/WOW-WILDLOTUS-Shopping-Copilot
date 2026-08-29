# retrieve/candidates — score the router pool or BM25

## Purpose

Pipeline stage after the intention router. Score the router's exact ASIN set, or BM25 when that set is `None`. Buying / browsing / override share this skeleton. Weights and caps come from `routing.py`.

## Files

| File | Role |
|---|---|
| `query.py` | category + slot search values (or active_constraints) + current message + profile tags → BM25 query. |
| `routing.py` | `routing_for(intention)`: SearchWeights and limit. |
| `retrieve.py` | `CandidateOrganizer` / `retrieve_candidates`. |

## Collaboration

```text
exact is not None (any intention, including empty set):
    retriever.score_candidates(exact)[:150 or 500]
    do not BM25 the full catalog
exact is None:
    rewrite_query → retriever.search(..., hard_required=False)
```

`excluded_asins` are dropped in scoring/search. This package does not choose the question or slate length. `intention` is router-labeled session state, not an evaluator scenario label.

## Core variables

- Input: `SessionState`, `exact: set[str] | None`
- Output: `list[SearchHit]` (Buying/override cap 150, Browsing 500)
- Query string: see `rewrite_query` (typed search values when slots exist)
- Required: hard groups from `from_slots.required_and_budget` (OR inside an attribute, AND across; plus hard budget interval). Soft slots go to `preferred`.

## Core code

- Fusion entry: `retrieve_candidates` in `retrieve.py`
- Routing: `routing_for` in `routing.py`
- Rewrite: `rewrite_query` in `query.py`
