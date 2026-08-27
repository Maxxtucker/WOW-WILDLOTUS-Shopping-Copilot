# retrieve/candidates — exact pool and BM25 fusion

## Purpose

Pipeline stage 5. Fold filter results into at most 500 `SearchHit`s. Score the exact pool when possible; otherwise rewrite the query and call `CatalogRetriever.search`.

## Files

| File | Role |
|---|---|
| `query.py` | category + constraints + current message + profile tags → BM25 query. |
| `retrieve.py` | `CandidateOrganizer` / `retrieve_candidates`: exact first, else fuse. |

## Collaboration

```text
exact non-empty → retriever.score_candidates(exact)[:500]
exact empty or scored empty → rewrite_query → retriever.search(..., hard_required=False)
```

`excluded_asins` are dropped in scoring/search. This package does not choose the question or slate length.

## Core variables

- Input: `SessionState`, `exact: set[str] | None`
- Output: `list[SearchHit]` (cap 500, aligned with planner `max_planning_candidates`)
- Query string: see `rewrite_query`

## Core code

- Fusion entry: `retrieve_candidates` in `retrieve.py`
- Rewrite: `rewrite_query` in `query.py`
