# agent — shopping copilot implementation

The evaluator imports only `starter.agent.Agent`. Real logic lives in this package, in three layers plus the intention router. Every `.py` file starts with Purpose / Input / Output / Role. Every layer and subpackage has its own README.

```text
agent/
  orchestrator.py     Agent.reset / respond
  pipeline.py         one turn: understand → intention router → retrieve → decide
  domain.py           evaluator protocol mirror
  stages.py           swappable stage Protocols

  understand/         message → turn_delta              see README.md
    mode.py           nlu (default) vs regex
    state/            session memory, miss, fail-safe, conversion gate
    attributes/       constraints, semicolon restore
    observation/      extract into turn_delta (hybrid: nlu then regex)

  intent_router/      override vs accumulate, hard exact pool, intention

  retrieve/           router pool → SearchHit                see README.md
    catalog/          SQLite index and CatalogRetriever
    candidates/       score exact set, else BM25

  decide/             SearchHit → official response     see README.md
    ranking/          temperature-0.12 posterior
    clarification/    question × slate
    response/         writeback + respond dict
```

`pipeline` calls `StateDetector.apply` then `IntentRouter.apply` then `CandidateOrganizer.apply`. Observation classify runs inside the first call.

Understand defaults to local NLU. Mode, Ollama startup, retries, and regex fallback: [`docs/architecture/understand_nlu.md`](../docs/architecture/understand_nlu.md). Kit tests pin `understand_mode="regex"` and mock the router LLM. Intention routing has no regex fallback.
