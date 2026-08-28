# understand/observation — fixed parse order

## Purpose

The only place inside `understand` allowed to compose extractors. Catalog features may legally contain `instead` / `forget`; apply locked constraints before testing override.

`pipeline` calls `StateDetector.apply` only. It does not call extractors separately.

Understand defaults to local NLU (`understand_mode="nlu"`). `hybrid_extract` calls the model (including on protocol-like phrasing), retries a failed extract three times, then falls back to regex. `understand_mode="regex"` skips the model. Mode lives in `understand/mode.py`; Agent nlu startup starts Ollama via `runtime.py`. Design note: [docs/architecture/understand_nlu.md](../../../docs/architecture/understand_nlu.md).

## Files

| File | Role |
|---|---|
| `classify.py` | `extract_category` / `extract_constraints` / `parse_override` (regex; no state writes). |
| `schema.py` | `ObservationExtract`, span grounding, track inference. |
| `slots/` | Typed slots. Design: [slots/README.md](slots/README.md). One handler per attribute; `pipeline.py` dispatches. |
| `llm_nlu.py` | Ollama JSON client. HTTP only. |
| `runtime.py` | Ping Ollama, spawn `serve` if needed, load the configured model. No pull. |
| `hybrid.py` | NLU up to three attempts when mode is nlu; else regex. |
| `coordinator.py` | `observe`: apply hits in a fixed order every turn, then write `track`. |

## Collaboration

```text
every turn:
    hybrid_extract
        nlu mode → llm_nlu.py (3 attempts)
        regex mode, or all attempts None → classify.py
    extract_constraints → write active_constraints (and stop if any, unless LLM also set override)
    extract_category    → category; leftover hint closes the conversion gate
    parse_override      → clear legacy, open gate
    colon_fallback      → last-resort constraint parse (regex path)
    write track         → buying if locked constraints; browsing if vague/explore
```

There is no `if turn == 1` branch and no evaluator Buying / Browsing / Boundary label.

## Core variables

No independent state. Reads and writes the passed-in `SessionState`, including `track`.

NLU settings persist in `scripts/nlu.env`. Agent nlu mode loads that file. Interactive console:

```powershell
. .\scripts\load_nlu_env.ps1
python scripts/nlu_console.py
```

`python scripts/nlu_probe.py --live` loads the same file. Keys: `AGENT_NLU_MODEL`, `AGENT_NLU_HOST`, `AGENT_NLU_TIMEOUT`, optional `AGENT_UNDERSTAND_MODE`, optional `AGENT_NLU_ENABLED=0` to force regex when mode is not pinned.

## Core code

`observe` in `coordinator.py`. The order is a correctness constraint, not style.

Typed NLU slots (cite vs classify, size kinds, alias policy): [slots/README.md](slots/README.md).
