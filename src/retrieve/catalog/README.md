# retrieve/catalog — catalog index and recall facade

## Purpose

Process-wide SQLite infrastructure. No session dependency. `CatalogRetriever` is the only place retrieve executes SQL; the intention-router probe, candidates, and decide call its public methods.

Index build derives catalog-native response and search signatures from every product. `protocol_copy.py` owns the normalization, field-weight, and attribute-classification helpers used by that index and does not import `agent.domain`.

## Files

| File | Role |
|---|---|
| `types.py` | `SearchHit`, `ResponseSignature`, scoring weights. |
| `protocol_copy.py` | Index-side normalization and attribute helpers; `INDEX_VERSION = agent-retrieval-v4`. |
| `signatures.py` | Build response signatures from product metadata; normalize constraints/budget. |
| `index_path.py` | `AGENT_INDEX_PATH` / `AGENT_CACHE_DIR` → on-disk path. |
| `index.py` | Schema, fingerprint, FTS + signature tables from JSONL. |
| `slots_sidecar.py` | ATTACH precomputed `product_slots` / `product_text` / `slot_stats`. Version `catalog-slots-v4`. |
| `scoring.py` | Structured scores for a given ASIN pool (no recall). Hard numeric filter, rarity, soft `text_fit`. |
| `profile_embed.py` | Preference-tag cosine vs product surfaces for diagnostics. Never BM25; current final-score contribution is disabled. |
| `search.py` | FTS5 BM25 ∪ signature hits, then scoring. |
| `retriever.py` | Facade: open DB, exact lookup, `predict_reply`, `search`. |

`CatalogRetriever` is composed with mixins: `IndexMixin` + `ScoringMixin` + `SearchMixin`.

## Collaboration

```text
Agent.__init__
    resolve_index_path → CatalogRetriever(catalog, index_path)
        fingerprint unchanged: open existing SQLite
        else: index.build writes products / product_fts / signature_values
        ATTACH product_slots sidecar when fingerprint matches

At query time
    intent_router probe: retriever.signature_candidates(...)
    candidates: retriever.score_candidates(exact) or search(..., hard_required=False)
    decide: retriever.predict_reply / answer_signature
```

## Core variables

- `SearchHit`: `parent_asin`, `score`, lexical/structured/prior, `required_coverage`
- `ResponseSignature`: conservative answer values versus broader search aliases; `expected_reply(attribute, disclosed)`
- `signature_values.kind`: `response` for answer modeling, `search` for broader retrieval aliases

`score_candidates()` computes:

```text
final =
    1.15 * w_lex * lexical
  + 0.003 * structured
  + rating_prior + popularity_prior
  + w_text * max(title_fit, 0.7*details_fit, 0.5*description_fit)
```

The structured subtotal contains required matches/misses, preferred matches,
category, budget, dimension, and exclusion terms. Profile fit is still
computed and exposed in `score_breakdown`, but `profile_weighted` is always
zero and does not enter `final`.

## Core code

- Facade: `CatalogRetriever` in `retriever.py`
- Signatures: `build_response_signature` in `signatures.py`
- Exact inverted index: `retriever.signature_candidates`
- Build: `index.py`

## FTS matching

`product_fts` uses FTS5 `porter unicode61 remove_diacritics 2`. Query tokens
remain in their original form after stopword removal; FTS applies the Porter
stemmer consistently to both indexed content and MATCH terms. This improves
singular/plural matches such as `shoe` and `shoes`, but Porter can over-stem
terms such as `plus`, `earrings`, `running`, and `clothing`.
