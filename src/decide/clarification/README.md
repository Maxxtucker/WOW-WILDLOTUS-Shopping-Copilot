# decide/clarification — question selection and slate

## Purpose

Pipeline stage 7 jointly searches “which `ask_attribute` to ask” and “how many products to show.” Production uses `DynamicSlatePlanner` with two answer observations. `ScoreAwarePlanner` remains only as a compatibility object whose `max_planning_candidates` setting is read by `Clarifier`; its one-step plan is not executed.

The structured `ask_attribute` is the machine-readable question. `message` is customer-facing wording generated later by the response stage.

## Files

| File | Role |
|---|---|
| `types.py` | `Plan`, sentinel `NO_ADDITIONAL`. |
| `utility.py` | Session-weighted HitRate/MRR utility; defaults to `0.50 + 0.30/rank + 0.02*(11-turn)`. |
| `questions.py` | Still-informative attributes; `explain_question` templates. |
| `replies.py` | Cache `predict_reply` for planner counterfactuals. |
| `dynamic_adapter.py` | Production catalog-signature, no-information, and tail transition model. |
| `dynamic_slate.py` | Production two-observation Dynamic Slate search. |
| `slate.py` | Compatibility gate; currently returns the planned slate unchanged. |
| `stage.py` | Production entry, trace decomposition, deterministic exploration, fallback, and gate call. |
| `planner.py`, `distinguish.py` | Legacy one-step planner retained for compatibility and isolated callers. |

## Collaboration

```text
Clarifier.apply
    make_answer_signature(retriever, disclosed)
    eligible_questions                   # pre-viability, informative, unasked
    CatalogSignatureTransitionModel
        viability filter + head/tail state
    DynamicSlatePlanner.plan
        viable questions × k∈[0, top_k]
        immediate TechnicalScore components + two-observation future value
    deterministic epsilon policy         # 80% exploit, 20% uniform pre-viability explore
    pre-final fallback question if needed
    apply_sequential_gate                 # current no-op
```

The production planner asks the retriever how a candidate could answer through a cached callback. It does not execute SQL directly and does not mutate the live session while expanding branches.

## Core variables

- `Plan`: `recommendations`, `ask_attribute`, `expected_value`, `reason`
- `NO_ADDITIONAL`: no more information is available for that attribute
- outer eligibility cap: `max_planning_candidates = 500`
- Dynamic Slate planning head: at most 80 candidates, with at least 0.20 tail mass
- `lookahead_steps = 2`
- `ATTRIBUTE_EXPLORATION_RATE = 0.20`

## Core code

- Entry: `Clarifier.apply` in `stage.py`
- Production search: `DynamicSlatePlanner.plan` in `dynamic_slate.py`
- Production transitions: `CatalogSignatureTransitionModel` in `dynamic_adapter.py`
- Compatibility planner: `ScoreAwarePlanner.plan` in `planner.py`
- No-op gate: `apply_sequential_gate` in `slate.py`

## Dynamic Slating

Dynamic Slating selects the current structured question and recommendation count together:

```math
u_t=(a_t,k_t), \qquad k_t\in\{0,1,\ldots,10\}.
```

Its input is a ranked candidate belief from the ranking stage, together with the current turn, eligible questions, conversion-gate probability, and optional probability mass outside the planning head.

For candidate `d_i`:

```math
p_i=P(X=d_i\mid S_t),
```

with:

```math
\sum_{i=1}^{N}p_i+p_{\mathrm{tail}}=1.
```

If the target first appears at turn `t` and rank `r`, its score contribution is:

```math
U(t,r)=w_H+\frac{w_M}{r}+w_E\frac{11-t}{10},
\qquad (w_H,w_M,w_E)=(0.50,0.30,0.20)\text{ by default}.
```

The current expected hit value of showing the first `k_t` products is:

```math
I_t(S_t,k_t)
=g_t\sum_{r=1}^{k_t}p_rU(t,r),
```

where `g_t` is the probability that the current intent is eligible to convert.

For a normalized answer `y`, the no-hit answer branch has joint probability:

```math
q_t(y\mid a_t,k_t)
=\sum_{i=1}^{N}
p_i\left[1-g_t\mathbf{1}(i\leq k_t)\right]\ell_i^t(y)
+p_{\mathrm{tail}}\ell_{\mathrm{tail}}^t(y),
```

where:

```math
\ell_i^t(y)=P(Y_{t+1}=y\mid X=d_i,a_t,S_t).
```

After the miss and answer, the integration builds a new planning state:

```math
S_{t+1}^{y,k_t}
=\mathrm{UpdateAndRetrieve}(S_t,a_t,k_t,y).
```

The finite-horizon recursion is:

```math
V_t^{(0)}(S_t)=\max_{a_t,k_t}I_t(S_t,k_t),
```

```math
Q_t^{(h)}(S_t,a_t,k_t)
=I_t(S_t,k_t)
+\sum_yq_t(y\mid a_t,k_t)
V_{t+1}^{(h-1)}\left(S_{t+1}^{y,k_t}\right),
```

```math
V_t^{(h)}(S_t)=\max_{a_t,k_t}Q_t^{(h)}(S_t,a_t,k_t).
```

The production policy uses two answer observations:

```math
(a_t^*,k_t^*)
=\underset{a_t,k_t}{\mathrm{arg\,max}}\;
Q_t^{(2)}(S_t,a_t,k_t).
```

In each branch it:

1. evaluates the current hit value;
2. predicts the first no-hit answer and next state;
3. chooses a new question and slate size at `t+1`;
4. predicts the second no-hit answer;
5. uses the best immediate slate at `t+2` as the terminal approximation.

`k_t=0` means asking a question without exposing a product. On turn 10, the default configuration returns the full valid slate because no later answer can be consumed.

`Clarifier` now runs `DynamicSlatePlanner` as its production policy. The
catalog-signature adapter in `dynamic_adapter.py` converts ranked candidates
into bounded no-hit/answer branches without mutating the live session. The
runtime uses two answer observations, permits `k=0`, compacts typed answers to
at most 12 branches, and compacts free-form `other` answers to at most 4
branches so literal catalog strings are not treated as perfectly parseable.
The adapter reserves a calibrated tail floor, adds catalog-coverage and parser-
uncertainty mass to `NO_ADDITIONAL`, and assigns successful tail answers a
bounded re-retrieval value. Questions below 10% effective coverage (`catalog
coverage × parser reliability`) are removed from the action set, so a tiny
modeled advantage cannot waste a turn on a very sparse attribute. A
no-preference answer to one attribute returns to retrieval and Dynamic Slate
instead of paging the previous ranking forever. If retrieval produces an empty
head, the tail model can still choose a high-coverage recovery question with
`k=0` rather than repeatedly returning no question and no products.

The pre-viability eligibility pass removes previously asked attributes and
requires at least one informative answer signature. It does not remove an
attribute merely because that attribute already appears in
`state.typed_constraints`. Viability filtering is a later, separate step.

## Deterministic attribute exploration

After Dynamic Slate chooses its expected-TechnicalScore optimum, `Clarifier`
applies a deterministic epsilon-greedy question policy. It keeps the planner
attribute 80% of the time. With 20% probability, it uniformly selects from the
pre-viability attributes that are still unasked and have at least one
informative answer signature in the current ranked candidates.

This exploration path can select size, use case, or budget without changing
the viability threshold used by the 80% exploitation path. It does not explore
when the ranked candidates or exploration pool are empty, and it never explores
on turn 10. Product recommendations and slate size remain planner-controlled.
The seed combines `session_id`, `intent_version`, and `turn`, making decisions
reproducible and starting a new sequence after an accepted intent override.

On turn 10, Dynamic Slate forces the full allowed ranked prefix and
`ask_attribute=None`; epsilon exploration and fallback-question injection are
disabled. Before turn 10, a null selected question is replaced without
changing the planned recommendations.

`apply_sequential_gate()` is currently a compatibility no-op. It returns the
planned recommendations exactly; the `gate_rank1` progress node is skipped and
`keep_planned` is the active path.
