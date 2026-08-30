# retrieve — exact recall, hybrid recovery, and structured scoring

## Purpose

`retrieve` runs after the intention router has committed `SessionState` and an
optional exact ASIN set. Hard intersection already happened in the router. This
layer scores a non-empty exact set. When that set is under 150, it keeps those
hard hits first and pads with hybrid BM25 plus catalog signature recall
(`hard_required=False`) so the library is at least 300 (browsing still 500).
When the exact set is already at least 150, the legacy hybrid fill is skipped.
For a live conversation, the resulting strict list is still fused with two
safety routes: relaxed structured recall without hard numeric filtering, and
raw active-intent BM25 that does not consume NLU slots. Weighted reciprocal-rank
fusion rewards cross-route agreement while preventing one uncertain slot from
becoming an irreversible recall decision. An empty or missing exact set uses
hybrid recovery before the same fusion. This layer does not choose the question
or how many products to show.

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
    ├─ strict: score exact, or hybrid recovery when exact is missing
    ├─ relaxed: structured search with uncertain hard filters disabled
    ├─ raw: active-intent text BM25 with no NLU-derived slots
    └─ weighted RRF(strict, relaxed, raw) to 300/500

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
- `current_intent_text`: at most four active-intent utterances; reset on override
- RRF weights: strict 1.40, relaxed 0.90, raw text 1.10; constant 60
- before turn 5, relaxed/raw routes may recover an early displayed ASIN because
  a still-latent Override means the next call is not definitive miss evidence

## Core code

- Index facade: `CatalogRetriever` in `catalog/retriever.py`
- Slot mapping: `constraint_groups` / `required_and_budget` in `from_slots.py`
- Hard intersection: `exact_pool_for_state` in `intent_router/exact_pool.py`
- Scoring entry: `retrieve_candidates` in `candidates/retrieve.py`
- Signature build: `build_response_signature` in `catalog/signatures.py`
