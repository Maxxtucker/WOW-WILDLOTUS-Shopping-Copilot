# Scenario Buyer agent

`evaluator.user_agent.ScenarioUserAgent` is the local-test Buyer shown in the
four-mode design. It does not replace `starter.agent.Agent`: the starter agent
is still the product-search agent. The local evaluator uses Mode 1 by default,
so existing deterministic evaluation remains unchanged.

The compatibility calls are:

```python
buyer = ScenarioUserAgent(mode=2)
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

- **Mode 1 — Template Buyer:** exact original `initial_message` and
  `customer_reply` behavior; no network or API key.
- **Mode 2 — Paraphrase Buyer:** the LLM rewrites wording only. Exact category
  and answer values are required; unsafe output falls back to the template.
- **Mode 3 — Policy-Variant Buyer:** the LLM may reorder wording, hesitate, or
  answer only part of a multi-value preference.
- **Mode 4 — Difficult/Misleading Buyer:** the LLM may produce missing, vague,
  mildly misleading, no-preference, or conflicting replies.

The LLM only generates user messages. It cannot modify the shopping agent's
recommendations or `ask_attribute` response field.

## API key configuration

The agent automatically reads `.env` from the repository root. Fill in the
provided `.env` file (it is ignored by Git), or copy `.env.example` to `.env`:

```dotenv
DEEPSEEK_API_KEY=your-deepseek-api-key
CONVERGE_LLM_PROVIDER=deepseek
CONVERGE_LLM_MODEL=deepseek-chat
CONVERGE_USER_MODE=1
```

Use `CONVERGE_USER_MODE=2`, `3`, or `4` when you want the corresponding
scenario mode; the command-line `--user-mode` option can also override it.

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
is present, DeepSeek when a DeepSeek key is present, otherwise OpenAI. You can
run the evaluator with `python -m evaluator.local_evaluator --user-mode 2`.

If the key is absent, the request fails, or the model returns invalid JSON,
the Buyer safely uses the original deterministic message for that turn.
