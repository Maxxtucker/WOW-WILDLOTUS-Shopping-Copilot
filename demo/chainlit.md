# Shopping Copilot

This chat runs the same production agent as `scripts/nlu_console.py`:

- full `data/catalog.jsonl`
- live NLU (load `scripts/nlu.env` before starting)
- one turn is understand → intention router → retrieve → ranking → decide

While a turn runs, the circuit card shows which node is live. The sidebar keeps an expandable understand result (rewrite, category walk, slots). The agent reply and product shelf appear when the turn finishes.

Try a shopper sentence such as: *I'd prefer something green and easy to wear.*
