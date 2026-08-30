# retrieve/candidates — score the router pool or BM25

## Purpose

Pipeline stage after the intention router. Score the router's exact ASIN set.
When the strict set is below 150, a non-empty match-or-unknown lenient superset
becomes the score pool. If the selected pool is still under 150, keep its hits
first and fill with hybrid BM25/signature recall to `max(routing.limit, 300)`.
Fill disables hard required, budget, and dimension filtering: hard and soft
constraint matches, plus budget/dimension fits, rank new candidates instead.
If the selected pool is already at least 150, skip hybrid. Unavailable or empty
strict and lenient sets use hybrid only, also to at least 300. Buying / browsing
/ override share this skeleton. Weights and caps come from `routing.py`.

## Files

| File | Role |
|---|---|
| `query.py` | current category + committed slot search values → BM25 query; raw message is fallback-only. |
| `routing.py` | `routing_for(intention)`: SearchWeights and limit. |
| `retrieve.py` | `CandidateOrganizer` / `retrieve_candidates`. |

## Collaboration

```text
strict exact <150 and lenient non-empty:
    score the lenient superset as the exact pool
strict exact otherwise:
    score the strict set as the exact pool
selected exact pool ≥150:
    BM25 tie-break inside exact pool
    retriever.score_candidates(exact)[:150 or 500]
selected exact pool <150:
    score_candidates(exact) first (hard segment stays in front)
    then search(..., hard_required=False, hard_budget=False,
                hard_dimension=False) excluding selected exact ASINs
    fill until 300 (buying) or 500 (browsing); do not re-sort
no selected exact pool:
    rewrite_query → retriever.search(..., hard_required=False) to 300/500
```

`excluded_asins` are dropped in scoring/search. This package does not choose the question or slate length. `intention` is router-labeled session state, not an evaluator scenario label.

## Core variables

- Input: `SessionState`, `exact: set[str] | None`, and optional `exact_lenient`
- Output: `list[SearchHit]` (library at least 300 when exact is small; browsing 500)
- Query string: see `rewrite_query` (typed search values when slots exist)
- Required: hard groups from `from_slots.required_and_budget` (OR inside an attribute, AND across).
- Preferred: soft slot groups use OR semantics inside one attribute and never prune candidates.
- Hard budget slots drop missing-price and out-of-range products. Soft budget never drops; missing and out-of-range get no budget bonus. No budget slot means no price filter.
- `preference_tags` are not copied into BM25 as literal product words. Retrieve may score them against `product_text` surfaces with an optional bi-encoder; the later semantic ranker can also use them as weak personalization.
- Buying `text=0.5`; `text_fit` uses soft slots only. Path A hard required hits do not multiply IDF.

## Core code

- Fusion entry: `retrieve_candidates` in `retrieve.py`
- Routing: `routing_for` in `routing.py`
- Rewrite: `rewrite_query` in `query.py`
