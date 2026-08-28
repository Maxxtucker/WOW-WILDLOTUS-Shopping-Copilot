# Agent build instructions

This file is the standing brief for any agent that continues building this repository.

The contest kit layout must stay intact. Implementation work belongs in `agent/` (and thin wrappers such as `starter/agent.py`), not in a rewrite of the original tree.

## 1. Treat every user as a natural-language user

Do **not** reverse-engineer the evaluator's test-generation logic and then bake that generator into the agent.

The official evaluator is a **scoring harness**. Simulated customer text, intent-card construction, scenario templates, reply policies, and `public_set.jsonl` labels exist so organizers can score sessions. They are **not** a specification of how a real shopper speaks, and they must not become the agent's understanding or retrieval model.

**Forbidden**

- Copying or mirroring `evaluator/local_evaluator.py` helpers such as `intent_card`, `behavior_for`, `customer_reply`, constraint classifiers, or their regexes into agent code
- Precomputing per-product “evaluator fingerprints” (hard/soft constraints, reply signatures, scenario templates) and using those as the primary match key
- Special-casing public-set `session_id` values, labeled targets, or known simulator phrasing
- Building NLU, state, or retrieval that only works if the next message is produced by this evaluator

**Required**

- Treat `user_message` as unconstrained natural language from a shopper
- Extract intent and attributes from language, dialog state, and the allowed `user_profile`
- Design retrieval and clarification so they still work if the organizer paraphrases, reorders, or regenerates customer text
- Use `data/public_set.jsonl` and the local evaluator only to **measure** the agent, never to **define** its logic

Hits remain exact `parent_asin` matches. That scoring rule does not license cloning the simulator.

## 2. English only in docs and code comments

All documentation, README files, architecture notes, docstrings, and in-code comments must be written in **English**.

Do not add Chinese (or other non-English) comments, module headers, or docs. User-facing `message` strings may be English shopping copy; they are not a place for bilingual implementation notes.

## 3. Always work from the official problem and contest docs

Before changing agent behavior, re-read and stay consistent with:

1. [`docs/problem_requirements/problem_statement.md`](docs/problem_requirements/problem_statement.md) — problem, dual-track routing, dialog state, dynamic context, metrics
2. [`docs/competition_specification.md`](docs/competition_specification.md) — catalog fields, session protocol, Agent interface, scoring formula
3. [`docs/submission_rules.md`](docs/submission_rules.md) — submission shape, disallowed contents, output rules, reproducibility

If implementation convenience conflicts with those documents, the documents win. Do not invent protocol fields, catalog mutations, or evaluator changes.

Related kit files (interface only, not a license to clone simulator internals): `docs/agent_api_contract.json`, `docs/evaluation_config.json`.

## 4. Do not change the original repository skeleton

The frozen contest layout is defined in [`docs/architecture/original_repo_code_architecture.md`](docs/architecture/original_repo_code_architecture.md):

```text
.gitignore
DATA_ATTRIBUTION.md
README.md
data/public_set.jsonl
data/README.md
docs/          (kit specs and contracts)
evaluator/     (official local evaluator — do not modify)
starter/       (official Agent export surface)
tests/         (official evaluator tests — do not gut or replace)
```

**Keep**

- `evaluator/` and its public API unchanged
- `starter.agent.Agent` as the evaluator entry (`reset` / `respond` signatures and return shape)
- Official `data/`, kit `docs/` filenames, and `tests/test_evaluator.py` in place
- Catalog read-only; no mock ASINs or structural injections

**Allowed**

- Implement and refactor inside `agent/`
- Keep `starter/agent.py` as a thin re-export of `agent.Agent`
- Add tests, scripts, and extra docs **without** deleting or relocating the kit paths above

Do not restyle the contest kit into a new top-level layout, and do not move scoring or session simulation into the agent package.
