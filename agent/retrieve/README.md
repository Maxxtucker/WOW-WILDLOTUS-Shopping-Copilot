# retrieve — score the router pool (soft preferred), else BM25

## Purpose

`retrieve` runs after the intention router has committed `SessionState` and an optional exact ASIN set. Hard intersection already happened in the router. This layer **scores** that set (soft slots preferred, not prune) or BM25 when `exact is None`. It does not choose the question or how many products to show. Buying and override truncate near 150 hits; Browsing keeps up to 500.

The catalog index is process-wide. Candidates read the index and the session exclusion set each turn.

## Submodules

Each subdirectory has its own README. Each `.py` file starts with Purpose / Input / Output.

`from_slots.py` maps hard/soft `typed_constraints` (else `active_constraints`) to scoring groups, BM25 terms, and budget. Those pairs are not stored on session. The router probe also reads `exact_pool_groups` from here.

| Package | Role | Docs |
|---|---|---|
| `catalog/` | SQLite FTS5 + response-signature index. `CatalogRetriever` is the only database facade. | [catalog/README.md](catalog/README.md) |
| `candidates/` | Score the router exact set; if `None`, query rewrite + BM25. | [candidates/README.md](candidates/README.md) |

## Collaboration

```text
IntentRouter.apply(state, retriever)
    probe exact_pool_for_state (once on override, twice otherwise)
    exact → CandidateOrganizer.apply(state, exact)

CandidateOrganizer.apply(state, exact)
    ├─ exact is not None: score_candidates(exact)[:limit]   (buying, browsing, override)
    └─ exact is None: rewrite_query → retriever.search(..., hard_required=False)
```

`catalog` has no session dependency. `candidates` read the index only through public `CatalogRetriever` methods.

## Core variables

- `SearchHit`: `parent_asin`, `score`, lexical/structured/prior, `required_coverage`
- `ResponseSignature`: protocol fingerprint (response vs search values)
- `exact: set[str] | None`: router hard intersection; `None` means BM25 (`None` is not count 0). An empty set is scored as empty, not BM25.
- query string: category + slot search values (or active_constraints) + current message + profile tags
- required groups: hard slots only (`from_slots.constraint_groups`); same-attribute values OR, attributes AND
- preferred: soft slots plus profile tags; missing soft does not drop a candidate

## Core code

- Index facade: `CatalogRetriever` in `catalog/retriever.py`
- Slot mapping: `constraint_groups` / `required_and_budget` in `from_slots.py`
- Hard intersection: `exact_pool_for_state` in `intent_router/exact_pool.py`
- Scoring entry: `retrieve_candidates` in `candidates/retrieve.py`
- Signature build: `build_response_signature` in `catalog/signatures.py`
