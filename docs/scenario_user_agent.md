# Scenario evaluator

`evaluator.scenario_evaluator.ScenarioEvaluator` is a standalone Buyer module
for the four-mode design. It does not replace `starter.agent.Agent`. Official
`evaluator.local_evaluator.evaluate()` still uses the original template customer
(equivalent to Scenario Mode 1). The demo Eval dock can run this Buyer on
selected `public_set` sessions.

The compatibility calls are:

```python
buyer = ScenarioEvaluator(mode=2)
message = buyer.initial_message(sample, category, disclosed)
message, boundary_used = buyer.customer_reply(
    sample, ask_attribute, disclosed, boundary_used
)
```

The original module-level `initial_message(...)` and `customer_reply(...)`
helpers remain available as deterministic Mode 1 helpers. A session-oriented
form is also supported when needed: call `reset(session_id, sample, category)`
and then use the session ID in the two methods.

## Modes

- **Mode 1 — Template Buyer:** the original `initial_message` and
  `customer_reply` output is returned directly. No network request is made.
- **Mode 2 — Protected-keyword paraphrase:** the deterministic output and a
  `protected_keywords` list are sent to the LLM. Only the language around those
  words may change; every protected keyword must remain exactly present. A
  validator rejects missing, extra, negated, or unchanged output and uses a
  deterministic paraphrase fallback when needed.
- **Mode 3 — Meaning-preserving rewrite:** the LLM receives structured semantic
  targets and synonym/description hints. It may rewrite the full sentence and
  replace a canonical keyword with a meaning-equivalent expression. A local
  validator checks category/constraint evidence, rejects negation and extra
  constraints, and falls back to a deterministic synonym expression.
- **Mode 4 — Poor-English rewrite:** the LLM receives the same structured
  targets as Mode 3, but must simulate imperfect English through grammar or
  spelling mistakes, unnatural word order, or a long description instead of a
  direct keyword. The validator first applies the Mode 3 semantic checks, then
  requires a poor-English or circumlocution signal. It never permits a change
  of intent; invalid output falls back to a deterministic poor-English message.

The LLM only generates user messages. It cannot modify the shopping agent's
recommendations or `ask_attribute` response field.

## LLM mode

Modes 2-4 need a chat model. The Eval dock **LLM mode** control (and the
`llm_mode=` constructor argument) selects the backend:

- **remote** (default): OpenAI-compatible HTTP, using `CONVERGE_LLM_BASE_URL`
  and `CONVERGE_LLM_MODEL`. Both must be set. A matching API key is still
  required. `CONVERGE_LLM_BACKEND=remote` is the env default.
- **local**: the same Ollama pin as NLU (`AGENT_NLU_MODEL`, default
  `qwen3.5:4b` at `AGENT_NLU_HOST`).

If LLM mode is remote but either `CONVERGE_LLM_BASE_URL` or
`CONVERGE_LLM_MODEL` is missing, the Buyer uses local `qwen3.5:4b` instead.
If the chosen client is missing, the request fails, or the rewrite fails
validation, that turn uses the deterministic Mode 2-4 fallback. Mode 1 never
calls a model.

Official `local_evaluator.evaluate()` is unchanged and stays on Mode 1
templates.

## API key configuration

The Buyer automatically reads `.env` from the repository root. Fill in the
provided `.env` file (it is ignored by Git), or copy `.env.example` to `.env`:

```dotenv
DEEPSEEK_API_KEY=your-deepseek-api-key
CONVERGE_LLM_PROVIDER=deepseek
CONVERGE_LLM_BASE_URL=https://api.deepseek.com/v1
CONVERGE_LLM_MODEL=deepseek-chat
CONVERGE_LLM_BACKEND=remote
CONVERGE_USER_MODE=1
```

Use `CONVERGE_USER_MODE=2`, `3`, or `4` when constructing the standalone module
without an explicit `mode=` argument. An explicit constructor argument wins.

Real process environment variables take precedence over values from `.env`.

PowerShell examples:

```powershell
# Select a scenario mode.
$env:CONVERGE_USER_MODE = "2"

# Qwen through DashScope's OpenAI-compatible endpoint.
$env:DASHSCOPE_API_KEY = "your-dashscope-key"
$env:CONVERGE_LLM_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
$env:CONVERGE_LLM_MODEL = "qwen-plus"

# Or use the generic names:
# $env:CONVERGE_LLM_API_KEY = "your-key"
# $env:CONVERGE_LLM_PROVIDER = "qwen"
```

For DeepSeek (the `dp` alias is also accepted):

```powershell
$env:CONVERGE_USER_MODE = "4"
$env:DEEPSEEK_API_KEY = "your-deepseek-key"
$env:CONVERGE_LLM_PROVIDER = "deepseek"
$env:CONVERGE_LLM_MODEL = "deepseek-chat"
```

For OpenAI-compatible services:

```powershell
$env:CONVERGE_USER_MODE = "3"
$env:OPENAI_API_KEY = "your-key"
$env:CONVERGE_LLM_PROVIDER = "openai"
$env:CONVERGE_LLM_BASE_URL = "https://api.openai.com/v1"
$env:CONVERGE_LLM_MODEL = "gpt-4o-mini"
```

Recognized key variables are `CONVERGE_LLM_API_KEY`, `DASHSCOPE_API_KEY`,
`DS_API_KEY`, `QWEN_API_KEY`, `DEEPSEEK_API_KEY`, `DP_API_KEY`, and
`OPENAI_API_KEY`. The default endpoint is DashScope when a DashScope/Qwen key
is present, DeepSeek when a DeepSeek key is present, otherwise OpenAI.

Run only the module tests with:

```powershell
python -m unittest tests.test_scenario_evaluator -v
```

Show multiple random initial-message examples in the terminal with:

```powershell
python scripts/demo_user_agent_modes.py --samples 3 --seed 42
```

If the key is absent, the request fails, or the model returns invalid or
semantically unsafe JSON, the Buyer uses a deterministic mode-specific fallback
for that turn. Mode 1 always remains the exact original template.
