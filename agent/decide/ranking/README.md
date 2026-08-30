# decide/ranking — optional semantic reranking → coarse posterior

## Purpose

Pipeline stage 6. Rerank the retrieved candidate head with an optional local
cross-encoder, then turn ranking weights into `RankedCandidate.probability` for
the planner. These probabilities are ranking beliefs, not calibrated purchase
probabilities.

The semantic model is deliberately a **reranker**, not a catalog retriever. It
only sees candidates already recalled by exact attributes and BM25, so it can
improve soft matches such as use case, style, or comfort without scanning all
50,000 products on every turn.

## Files

| File | Role |
|---|---|
| `belief.py` | `exp((s - max)/0.12)` unnormalized weights. |
| `normalize.py` | Normalize positive weights, sort by score, define `RankedCandidate`. |
| `semantic.py` | Lazy Qwen CrossEncoder loading, structured query/product text, semantic fusion, and safe fallback. |
| `__init__.py` | `Ranker.apply`: semantic path when available, deterministic path otherwise. |

## Collaboration

```text
Ranker.apply(hits, state)
    ├─ Qwen available: rerank first N → fuse with retrieval order → normalize
    └─ unavailable/off: belief_from_hits → normalize
Clarifier reads probability and parent_asin order only
```

## Core variables

- `BELIEF_TEMPERATURE = 0.12`
- default model: `Qwen/Qwen3-Reranker-0.6B`
- default reranked head: 50 candidates
- Buying semantic weight: 0.35; Browsing semantic weight: 0.55
- `RankedCandidate`: `parent_asin`, raw `score` (weight), `probability`

## Runtime configuration

Settings live in `scripts/reranker.env`. Default `auto` mode and
`AGENT_RERANKER_LOCAL_FILES_ONLY=1` mean the Agent never downloads weights in a
competition request. If dependencies or cached weights are unavailable, it
uses the catalog ranking unchanged. `required` mode is useful for benchmarking
because model failures become visible errors.

Install the optional runtime separately:

```bash
python3 -m pip install -r requirements-reranker.txt
```

Download/cache the model before evaluation, then restore local-only mode. Pin
`AGENT_RERANKER_REVISION` to a Hugging Face commit for a reproducible submission.

The semantic query contains only committed current-state constraints. Hard and
soft constraints are labeled separately. Aggregate profile preference tags are
included as weak tie-breakers and never replace the current request.

## Core code

- `belief_from_hits` in `belief.py`
- `QwenSemanticReranker` / `semantic_belief` in `semantic.py`
- `normalize_probabilities` in `normalize.py`

Multi-route RRF scores use an adaptive bounded temperature before
normalization. RRF scores are much smaller than structured catalog scores;
using the structured-score temperature would make a 300–500 item library look
almost uniform and would systematically push Dynamic Slating toward wide
slates. This transform is a confidence heuristic, not a claim that retrieval
scores are calibrated purchase probabilities.
- `Ranker.apply` (this package's `__init__.py`)
