# retrieve — turn structured constraints into product candidates

## Purpose

`retrieve` runs after `understand` has written `SessionState`: **hard prune + recall fusion + structured scoring**. It does not choose the question or how many products to show. Buying truncates near 150 hits; Browsing keeps up to 500.

The catalog index is process-wide. Filtering and candidate fusion read the index and the session exclusion set each turn.

## Submodules

Each subdirectory has its own README. Each `.py` file starts with Purpose / Input / Output.

`from_slots.py` maps `typed_constraints` (else ranking strings) to groups, BM25 terms, and budget. Those pairs are not stored on session.

| Package | Role | Docs |
|---|---|---|
| `catalog/` | SQLite FTS5 + response-signature index. `CatalogRetriever` is the only database facade. | [catalog/README.md](catalog/README.md) |
| `filtering/` | Exact path: `category ∩ each constraint's response signature`. Missing signal → drop the exact pool; never empty-intersect. | [filtering/README.md](filtering/README.md) |
| `candidates/` | Score the exact pool when possible; otherwise query rewrite + BM25 ∪ search-signature. | [candidates/README.md](candidates/README.md) |

## Collaboration

```text
ProductFilter.apply(state)
    └─ exact_pool_for_state(retriever, state)
         from_slots.constraint_groups(state)
         typed slots → (attribute, values), search aliases
         else ranking_constraints strings, response_only signatures
         hit → set[parent_asin]
         any signal missing from the index → None

CandidateOrganizer.apply(state, exact)
    ├─ Buying (or unset track): exact non-empty → score_candidates[:limit]
    └─ Browsing, or exact empty: rewrite_query → retriever.search(..., hard_required=False)
```

`catalog` has no session dependency. `filtering` / `candidates` read the index only through public `CatalogRetriever` methods.

## Core variables

- `SearchHit`: `parent_asin`, `score`, lexical/structured/prior, `required_coverage`
- `ResponseSignature`: protocol fingerprint (response vs search values)
- `exact: set[str] | None`: exact intersection; `None` means BM25 is required
- query string: category + slot search values (or ranking_constraints) + current message + profile tags
- required groups: `from_slots.constraint_groups` (OR inside a group, AND across groups)

## Core code

- Index facade: `CatalogRetriever` in `catalog/retriever.py`
- Slot mapping: `constraint_groups` / `required_and_budget` in `from_slots.py`
- Exact intersection: `exact_pool_for_state` in `filtering/exact_pool.py`
- Fusion entry: `retrieve_candidates` in `candidates/retrieve.py`
- Signature build: `build_response_signature` in `catalog/signatures.py`
