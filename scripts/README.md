# Scripts and local setup

This directory is the operator surface for a fresh clone: install extras, fetch
the frozen catalog, build the slot sidecar, and launch the demo or evaluators.
Agent runtime code lives in `agent/`. Do not copy evaluator test-generation
logic into these scripts.

## One-command path

From the repository root, inside a venv is best but not required for `--check`.

**Windows**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
```

Creates `.venv`, installs `requirements-demo.txt` (`chainlit==2.12.0`), downloads
`data/catalog.jsonl` if missing, builds `.cache/catalog_preprocess/product_slots.sqlite3`,
checks Ollama, warms the FTS index, and starts Chainlit on port 8006 with
`cwd=demo` and `CHAINLIT_APP_ROOT=demo` (`demo/.chainlit/config.toml`). Do not run
`chainlit` from the repository root. Close leftover `http://localhost:8005` tabs
(that origin caches the old Chainlit shell).

Later launches:

```powershell
.\scripts\run_demo.ps1
```

**macOS / Linux**

```bash
bash scripts/setup.sh
bash scripts/run_demo.sh
```

**Any platform, already-activated venv**

```bash
python scripts/bootstrap.py --check
python scripts/bootstrap.py --extras demo --run demo
```

`bootstrap.py` is stdlib-only so it can run before extras are installed.

### What the first run does

1. Verifies Python 3.10+ and SQLite FTS5.
2. `pip install -r` the selected extras file.
3. Copies `.env.example` to `.env` when `.env` is missing (Scenario Buyer keys
   only; the core Agent does not need them).
4. Downloads and SHA-256-checks the 50k catalog.
5. Builds the product-slot sidecar (a few minutes).
6. Starts Ollama if needed and pulls `qwen3.5:4b` from `scripts/nlu.env`.
7. Builds or reuses the FTS/signature index on first `--run demo` / `--run eval`
   (several minutes the first time).
8. Optionally launches Chainlit from `demo/` (canonical config
   `demo/.chainlit/config.toml` plus `demo/public/`), the public evaluator,
   tests, or the NLU console.

Without Ollama, the Agent still starts; Understand falls back to regex after
failed NLU attempts. Live shopping quality needs the local model.

## Requirements files

All files sit at the repository root. Official scoring uses the core file only.

| File | Installs | Needed for |
|---|---|---|
| `requirements.txt` | nothing (stdlib Agent) | evaluator, `starter.agent.Agent` |
| `requirements-demo.txt` | `chainlit==2.12.0` | Chainlit UI and demo unit tests |
| `requirements-reranker.txt` | sentence-transformers, transformers | optional Qwen head reranker (large PyTorch download) |
| `requirements-preprocess.txt` | pandas, pyarrow | rebuilding color aliases from Hugging Face |
| `requirements-dev.txt` | the three extras above | a full local workstation |

```bash
python -m pip install -r requirements-demo.txt
python -m pip install -r requirements-dev.txt
```

`requirements.txt` is intentionally empty of packages (stdlib Agent). Bootstrap skips it.

`--extras demo,reranker` on `bootstrap.py` is the same as installing those two
files. `--extras all` (or `dev`) installs `requirements-dev.txt`.

## Environment files

| File | Loaded by | Purpose |
|---|---|---|
| `scripts/nlu.env` | `Agent()` NLU startup, `load_nlu_env.ps1` / `.sh` | Ollama host, model, timeout |
| `scripts/reranker.env` | optional semantic ranker | Qwen reranker mode and weights |
| `.env.example` → `.env` | Scenario evaluator | remote Buyer LLM for modes 2–4 |

PowerShell: `. .\scripts\load_nlu_env.ps1`  
bash: `source scripts/load_nlu_env.sh`

`Agent(..., understand_mode="regex")` and `AGENT_UNDERSTAND_MODE=regex` skip
`nlu.env`. Never commit filled `.env` secrets.

## Script catalog

### Setup and data

| Script | When to run |
|---|---|
| `bootstrap.py` | default local setup, doctor (`--check`), and launch |
| `setup.ps1` / `setup.sh` | first clone: venv + demo extras + launch |
| `run_demo.ps1` / `run_demo.sh` | later Chainlit launches against `.venv` |
| `download_catalog.py` | missing `data/catalog.jsonl` |
| `extract_catalog_slots.py` | missing or stale slot sidecar |
| `load_nlu_env.ps1` / `load_nlu_env.sh` | put `nlu.env` into the current shell |

Committed alias JSON and the three-level category tree are runtime assets.
Rebuild them only when upstream sources or the frozen catalog change:

```bash
python scripts/build_aliases_color.py      # needs requirements-preprocess.txt
python scripts/build_aliases_material.py   # network; stdlib urllib
python scripts/build_category_tree.py      # local catalog
python scripts/extract_catalog_slots.py
```

Details: [`catalog_preprocess/README.md`](catalog_preprocess/README.md).

### Agent and NLU

| Script | Purpose |
|---|---|
| `nlu_console.py` | interactive one-turn production pipeline |
| `nlu_probe.py` | fixture grounding; `--live` calls Ollama |

### Evaluation

| Script | Purpose |
|---|---|
| `demo_session.py` | one readable public-set session trace |
| `demo_user_agent_modes.py` | Scenario Buyer wording modes 1–4 |
| `check_parity.py` | Agent catalog helpers vs official evaluator helpers |

Official harness (not under `scripts/`):

```bash
python -m evaluator.local_evaluator --catalog data/catalog.jsonl --dataset data/public_set.jsonl --output results.json
python -m unittest discover -s tests -v
```

### Optional UI assets

| Script | Purpose |
|---|---|
| `build_catalog_images.py` | `data/catalog_images.jsonl` for product photos (large metadata download) |
| `rebuild_demo_catalog.py` | `data/catalog.demo.jsonl` subset |
| `export_catalog_slots_csv.py` | inspect sidecar tables |
| `survey_catalog_fields.py` | read-only catalog field survey |

## bootstrap.py flags

```text
--extras demo|reranker|preprocess|all|dev   repeatable or comma-separated
--check                                     print readiness, do not install
--skip-pip / --skip-catalog / --skip-sidecar / --skip-ollama / --skip-index
--force-catalog / --force-sidecar
--warm-index                                also implied by --run demo|eval
--run none|demo|eval|tests|console
--port 8006                                 Chainlit port (default; 8005 may be a cached old shell)
```

`--run demo` adds the `demo` extra when it is missing. `--run tests` does the
same because several demo tests import Chainlit.

## Typical workflows

Live demo (full catalog + Ollama):

```bash
python scripts/bootstrap.py --extras demo --run demo
```

Offline regex Agent, no Ollama:

```bash
python scripts/bootstrap.py --skip-ollama
# then, in that shell:
#   Windows:  $env:AGENT_UNDERSTAND_MODE="regex"
#   Unix:     export AGENT_UNDERSTAND_MODE=regex
python -m evaluator.local_evaluator --catalog data/catalog.jsonl --dataset data/public_set.jsonl --output results.json
```

Optional reranker (large):

```bash
python scripts/bootstrap.py --extras demo,reranker --skip-index
# first download of Qwen weights: set AGENT_RERANKER_LOCAL_FILES_ONLY=0 once
```

Inspect NLU without Chainlit:

```bash
python scripts/nlu_console.py
```
