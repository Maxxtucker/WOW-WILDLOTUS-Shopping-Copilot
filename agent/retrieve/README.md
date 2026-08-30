# retrieve — exact recall, hybrid recovery, and structured scoring

## Purpose

`retrieve` runs after the intention router has committed `SessionState` and an
optional exact ASIN set. Hard intersection already happened in the router. This
layer scores a non-empty exact set. When that set is under 150, it keeps those
hard hits first and pads with hybrid BM25 plus catalog signature recall
(`hard_required=False`) so the library is at least 300 (browsing still 500).
When the exact set is already at least 150, hybrid is skipped. An empty or
missing exact set uses hybrid only, also to at least 300. It does not choose
the question or how many products to show. Hard vs soft budget and object
dimensions come from typed slots, not from intention.

The catalog index is process-wide. Candidates read the index and the session exclusion set each turn.

## Submodules

Each subdirectory has its own README. Each `.py` file starts with Purpose / Input / Output.

`from_slots.py` maps hard/soft `typed_constraints` (else `active_constraints`) to scoring groups, BM25 terms, and budget. Those pairs are not stored on session. The router probe also reads `exact_pool_groups` from here.

| Package | Role | Docs |
|---|---|---|
| `catalog/` | SQLite FTS5 + response-signature index. `CatalogRetriever` is the only database facade. | [catalog/README.md](catalog/README.md) |
| `candidates/` | Score the router exact set; fill with hybrid to 300 when under 150. | [candidates/README.md](candidates/README.md) |

## Collaboration

```text
IntentRouter.apply(state, retriever)
    probe exact_pool_for_state (once on override, twice otherwise)
    exact → CandidateOrganizer.apply(state, exact)

CandidateOrganizer.apply(state, exact)
    ├─ exact is non-empty and ≥150: BM25 tie-break + structured score[:limit]
    ├─ exact is non-empty and <150: hard hits first, then hybrid fill to 300/500
    └─ exact is None/empty: hybrid search(..., hard_required=False) to 300/500

Ranker.apply(hits, state)
    ├─ optional Qwen rerank of first 50
    └─ deterministic fallback when the model is off/unavailable
```

`catalog` has no session dependency. `candidates` read the index only through public `CatalogRetriever` methods.

## Core variables

- `SearchHit`: `parent_asin`, `score`, lexical/structured/prior, `required_coverage`
- `ResponseSignature`: normalized catalog values used by structured lookup
- `exact: set[str] | None`: router hard intersection; a missing or empty result activates hybrid recall recovery
- query string: current category + committed slot search values; current message only when no state was extracted
- required groups: hard slots only (`from_slots.constraint_groups`); same-attribute values OR, attributes AND
- preferred: soft slots only; missing soft does not drop a candidate
- profile preference tags: retrieve surface cosine and optional semantic-ranker tie-breakers; never BM25 terms or hard filters
- `candidate_count`: size of the router exact set after numeric hard filters

## Core code

- Index facade: `CatalogRetriever` in `catalog/retriever.py`
- Slot mapping: `constraint_groups` / `required_and_budget` in `from_slots.py`
- Hard intersection: `exact_pool_for_state` in `intent_router/exact_pool.py`
- Scoring entry: `retrieve_candidates` in `candidates/retrieve.py`
- Signature build: `build_response_signature` in `catalog/signatures.py`
