# retrieve — turn structured constraints into product candidates

## Purpose

`retrieve` runs after `understand` has written `SessionState`: **hard prune + recall fusion + structured scoring**. It does not choose the question or how many products to show. It returns at most 500 `SearchHit`s.

The catalog index is process-wide. Filtering and candidate fusion read the index and the session exclusion set each turn.

## Submodules

Each subdirectory has its own README. Each `.py` file starts with Purpose / Input / Output.

| Package | Role | Docs |
|---|---|---|
| `catalog/` | SQLite FTS5 + response-signature index. `CatalogRetriever` is the only database facade. | [catalog/README.md](catalog/README.md) |
| `filtering/` | Exact path: `category ∩ each constraint's response signature`. Missing signal → drop the exact pool; never empty-intersect. | [filtering/README.md](filtering/README.md) |
| `candidates/` | Score the exact pool when possible; otherwise query rewrite + BM25 ∪ search-signature. | [candidates/README.md](candidates/README.md) |

## Collaboration

```text
ProductFilter.apply(state)
    └─ exact_pool(retriever, category, ranking_constraints)
         hit → set[parent_asin]
         any signal missing from the index → None

CandidateOrganizer.apply(state, exact)
    ├─ exact non-empty: score_candidates(exact)[:500]
    └─ else: rewrite_query → retriever.search(..., hard_required=False)
```

`catalog` has no session dependency. `filtering` / `candidates` read the index only through public `CatalogRetriever` methods.

## Core variables

- `SearchHit`: `parent_asin`, `score`, lexical/structured/prior, `required_coverage`
- `ResponseSignature`: protocol fingerprint (response vs search values)
- `exact: set[str] | None`: exact intersection; `None` means BM25 is required
- query string: category + constraints + current message + profile tags

## Core code

- Index facade: `CatalogRetriever` in `catalog/retriever.py`
- Exact intersection: `exact_pool` in `filtering/exact_pool.py`
- Fusion entry: `retrieve_candidates` in `candidates/retrieve.py`
- Signature build: `build_response_signature` in `catalog/signatures.py`
