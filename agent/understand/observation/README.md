# understand/observation — extract this turn into turn_delta

## Purpose

The only place inside `understand` allowed to compose extractors. Catalog features may legally contain `instead` / `forget`; those strings stay in the extract. **Intention routing does not live here** and does not use regex.

`pipeline` calls `StateDetector.apply` only for observation. The intention router commits constraints afterward.

Understand defaults to local NLU (`understand_mode="nlu"`). `hybrid_extract` calls the model (including on protocol-like phrasing), retries a failed extract three times, then falls back to regex. `understand_mode="regex"` skips the model. Mode lives in `understand/mode.py`; Agent nlu startup starts Ollama via `runtime.py`. Design note: [docs/architecture/understand_nlu.md](../../../docs/architecture/understand_nlu.md).

## Files

| File | Role |
|---|---|
| `classify.py` | `extract_category` / `extract_constraints` / `extract_new_need` (regex extract; no override routing). |
| `patterns.py` | Looking-for / exploring / leftover / override regexes for extract only. |
| `schema.py` | `ObservationExtract`, span grounding. Optional extract `track` is unused by the router. |
| `slots/` | Typed slots. Design: [slots/README.md](slots/README.md). One handler per attribute; `pipeline.py` dispatches. |
| `rewrite.py` | Casefold plus parallel color/material longest-match rewrite. Optional LLM word-class gates (both sides color words, or both material words). Same-span hits become `color material`. |
| `category_merch.py` | Detect Amazon promo / merchandising category labels. |
| `category_tree.py` | Load the fold-pruned 3-level tree (promo children omitted). Walk L1 roots, then concat selected children per layer. A layer with no children, or an empty id list, does not start another category LLM round. |
| `category_scope.py` | Drop L2+ branches that add kids/gender/age the shopper did not state. |
| `category_cap.py` | After identity emit, if this turn still has more than five unique category tags, keep five that cover the item (`fold_category` match, three retries, then sidecar `df`). |
| `llm_nlu.py` | Ollama JSON client. HTTP only. Rewrite gates, layered category JSON, category cap, then a separate attribute JSON. No override keys. |
| `disclosure.py` | After category+attribute, void the delta when the original utterance disclosed neither a category nor any attribute direction. |
| `runtime.py` | Ping Ollama, spawn `serve` if needed, load the configured model. No pull. |
| `hybrid.py` | NLU up to three attempts when mode is nlu; else regex. |
| `coordinator.py` | `observe`: store `turn_delta`. Does not apply constraints, override, or intention. |

## Collaboration

```text
every turn:
    hybrid_extract
        nlu mode → up to 3 complete attempts
            each complete attempt:
                rewrite (+ word-class gates)
                layered category LLM + category cap
                one attribute LLM
                field-local grounding repairs, at most 3
                disclosure judgment
        regex mode, or all 3 complete attempts fail → classify.py
    colon_fallback      → last-resort constraint parse (regex path, no constraints yet)
    state.turn_delta    → extract, or None when empty
```

There is no `if turn == 1` branch and no evaluator Buying / Browsing / Boundary label.

## Core variables

No independent state. New shopping evidence is written only to
`SessionState.turn_delta`; committed category and constraints remain unchanged
until Intent Router accepts accumulation or replacement. The coordinator also
writes the per-turn `disclosure_empty` control flag.

NLU settings persist in `scripts/nlu.env`. Agent nlu mode loads that file. Interactive console:

```powershell
. .\scripts\load_nlu_env.ps1
python scripts/nlu_console.py
```

`python scripts/nlu_probe.py --live` loads the same file. Keys: `AGENT_NLU_MODEL`, `AGENT_NLU_HOST`, `AGENT_NLU_TIMEOUT`, optional `AGENT_UNDERSTAND_MODE`, optional `AGENT_NLU_ENABLED=0` to force regex when mode is not pinned.

The console loads `data/catalog.jsonl` by default and runs production `TurnPipeline` (understand → router → retrieve → rank → decide). It prints each stage and the agent reply, with catalog titles on the slate. `/pool` dumps the last exact-pool sample. `--no-retrieve` keeps extract + override writeback only.

## Core code

`observe` in `coordinator.py`. Commit is `agent/intent_router`.

Typed NLU slots (cite vs classify, size kinds, alias policy): [slots/README.md](slots/README.md).
