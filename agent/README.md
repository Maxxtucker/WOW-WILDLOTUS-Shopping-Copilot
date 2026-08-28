# agent — shopping copilot implementation

The evaluator imports only `starter.agent.Agent`. Real logic lives in this package, in three layers. Every `.py` file starts with Purpose / Input / Output / Role. Every layer and subpackage has its own README.

```text
agent/
  orchestrator.py     Agent.reset / respond
  pipeline.py         one turn: understand → retrieve → decide
  domain.py           evaluator protocol mirror
  stages.py           swappable stage Protocols

  understand/         message → SessionState          see README.md
    mode.py           nlu (default) vs regex
    state/            session memory, miss, fail-safe
    intention/        override conversion-gate writeback
    attributes/       constraints, semicolon restore
    observation/      extract then apply (hybrid: nlu then regex)

  retrieve/           SessionState → SearchHit        see README.md
    catalog/          SQLite index and CatalogRetriever
    filtering/        exact signature intersection
    candidates/       exact pool first, else BM25

  decide/             SearchHit → official response   see README.md
    ranking/          temperature-0.12 posterior
    clarification/    question × slate
    response/         writeback + respond dict
```

`pipeline` calls only `StateDetector.apply`. Observation classify runs inside that call.

Understand defaults to local NLU. Mode, Ollama startup, retries, and regex fallback: [`docs/architecture/understand_nlu.md`](../docs/architecture/understand_nlu.md). Kit tests pin `understand_mode="regex"`.
