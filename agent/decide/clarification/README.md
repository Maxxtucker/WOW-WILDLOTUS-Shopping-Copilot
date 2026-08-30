# decide/clarification — question selection and slate

## Purpose

Pipeline stage 7. Joint search over “which `ask_attribute` to ask” and “how many products to show”. The existing runtime objective is one-step expected TechnicalScore, followed by sequential slate risk gating that usually keeps rank 1.

The simulator reads only structured `ask_attribute`. It does not infer the question from `message`.

## Files

| File | Role |
|---|---|
| `types.py` | `Plan`, sentinel `NO_ADDITIONAL`. |
| `utility.py` | `hit_utility(turn, rank) = 0.50 + 0.30/rank + 0.02*(11-turn)`. |
| `questions.py` | Still-informative attributes; `explain_question` templates. |
| `replies.py` | Cache `predict_reply` for planner counterfactuals. |
| `distinguish.py` | Partition by predicted reply; estimate next-turn Top-10 utility. |
| `planner.py` | `ScoreAwarePlanner.plan`: one-step search over question × slate prefix. |
| `dynamic_slate.py` | Proposed two-observation Dynamic Slating policy. |
| `slate.py` | Sequential gate after planning. |
| `stage.py` | `Clarifier`: stage entry for plan + gate. |

## Collaboration

```text
Clarifier.apply
    make_answer_signature(retriever, disclosed)
    ScoreAwarePlanner.plan(state, ranked, top_k, answer_signature)
        eligible_questions × k∈[0, top_k]
            immediate-hit utility + future_value(partitions)
    apply_sequential_gate → usually rank-1; turn 10 or empty disclosure is full slate and no question
```

The existing planner asks the catalog how an ASIN would answer through a callback. It does not touch SQLite directly.

## Core variables

- `Plan`: `recommendations`, `ask_attribute`, `expected_value`, `reason`
- `NO_ADDITIONAL`: no more information is available for that attribute
- `max_planning_candidates = 500`

## Core code

- Entry: `Clarifier.apply` in `stage.py`
- Existing search: `ScoreAwarePlanner.plan` in `planner.py`
- Proposed search: `DynamicSlatePlanner.plan` in `dynamic_slate.py`
- Distinguishability: `future_value` in `distinguish.py`
- Gate: `apply_sequential_gate` in `slate.py`

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
U(t,r)=0.50+\frac{0.30}{r}+0.02(11-t).
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

The proposed policy uses two answer observations:

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
