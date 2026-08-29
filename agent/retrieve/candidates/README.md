# retrieve/candidates — score the router pool or BM25

## Purpose

Pipeline stage after the intention router. Score the router's exact ASIN set,
or use hybrid BM25/signature recall when that set is unavailable or empty.
Buying / browsing / override share this skeleton. Weights and caps come from
`routing.py`.

## Files

| File | Role |
|---|---|
| `query.py` | current category + committed slot search values → BM25 query; raw message is fallback-only. |
| `routing.py` | `routing_for(intention)`: SearchWeights and limit. |
| `retrieve.py` | `CandidateOrganizer` / `retrieve_candidates`. |

## Collaboration

```text
exact is non-empty:
    BM25 tie-break inside exact pool
    retriever.score_candidates(exact)[:150 or 500]
exact is None or empty:
    rewrite_query → retriever.search(..., hard_required=False)
```

`excluded_asins` are dropped in scoring/search. This package does not choose the question or slate length. `intention` is router-labeled session state, not an evaluator scenario label.

## Core variables

- Input: `SessionState`, `exact: set[str] | None`
- Output: `list[SearchHit]` (Buying/override cap 150, Browsing 500)
- Query string: see `rewrite_query` (typed search values when slots exist)
- Required: hard groups from `from_slots.required_and_budget` (OR inside an attribute, AND across).
- Preferred: soft slot groups use OR semantics inside one attribute and never prune candidates.
- Buying/override treats a known out-of-range price as a hard failure. Missing prices remain eligible because absence is not evidence of failure.
- `preference_tags` are not copied into BM25 as literal product words; the optional semantic ranker uses them only as weak personalization evidence.

## Core code

- Fusion entry: `retrieve_candidates` in `retrieve.py`
- Routing: `routing_for` in `routing.py`
- Rewrite: `rewrite_query` in `query.py`
