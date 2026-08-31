# Shopping Copilot

This chat runs `agent.orchestrator.Agent` and the same production
`TurnPipeline` used by the headless API:

- full `data/catalog.jsonl`
- default live NLU from `scripts/nlu.env` (first clone: `scripts/setup.ps1` or `python scripts/bootstrap.py --extras demo --run demo`);
- at most three complete NLU attempts, then deterministic regex extraction;
- Understand stages `turn_delta`; Intent Router commits it and records its
  token usage;
- strict/lenient exact selection, hybrid base recall, and optional
  strict/relaxed/raw weighted RRF;
- optional Qwen head reranking with deterministic fixed/adaptive belief
  fallback; and
- production two-observation Dynamic Slate planning with seeded 20% attribute
  exploration and an unchanged planned slate.

While a turn runs, the circuit card follows the production progress-node IDs
for Understand, Router, Retrieve, and Decide. Conditional nodes are marked
completed, skipped, or failed according to the branch actually taken. The
sidebar keeps the node inputs/outputs and final trace. The response `usage`
fields reflect Router prompt/completion tokens; Understand tokens are not
currently reported.

A no-information turn can page unshown products from `last_ranked` when
`turn_delta` is absent, `disclosure_empty` is not false, and a reusable product
remains. That branch skips Router, Retrieve, and Dynamic Slate planning but
still persists and renders the page.

Try a shopper sentence such as: *I'd prefer something green and easy to wear.*
