# Results

All results here are smoke or pre-hardening reads. **No full
model-vs-environment eval has been completed against the current code.**

## Baseline (Before v1 Hardening)

Source: an earlier scratch implementation, prior to the
dead-end/progress/typed-message hardening carried into this repo.

| Model | Tier | Examples | Rollouts | Reward Avg | Reward Std | pass@1 | pass@2 | pass^2 | Notes |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| `gpt-5-nano` | easy | 3 | 2 each | 0.405 | 0.774 | 0.167 | 0.333 | 0.000 | 1/6 solved; one solve scored 2.13 |
| `gpt-5-nano` | easy | 1 | 2 each | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | Run that surfaced the dead-end false-negative blocker |

The second run mattered more than the first: the transcript showed the model
bricked the puzzle, correctly identified that no legal moves remained, and then
the environment forced 33 extra turns. That failure drove the v1 blocker fixes.

## Current Repo

### Live Eval: `easy` Tier, Post-Hardening

Command:

```powershell
uv run vf-eval magic_sort -a '{\"tier\":\"easy\",\"num_train_examples\":5,\"num_eval_examples\":5}' --provider openai -m gpt-5-nano -n 3 -r 2 --disable-tui --disable-env-server --save-results
```

3 puzzles x 2 rollouts. Saved to `outputs/evals/magic_sort--gpt-5-nano/e5b71f34`.

| Metric | Value |
|---|---|
| solve rate | 6/6 (100%) |
| reward mean | 1.828 |
| reward std | 0.139 |
| par | 12-13 |
| moves taken | 16-29 |
| mean turns | 21.2 |
| illegal-move rate | 0.00-0.08 |
| dead ends | 0 |
| no-progress stops | 0 |
| total output tokens | 649,793 |

**Findings:**

1. **`easy` is saturated for this model.** The tier is 4 colors with 2 empty
   bottles. The earlier 1-empty configuration scored 1/6 for the same model.
   **One empty bottle moved the solve rate from 17% to 100%** — the
   `colors / (colors + empties)` ratio is a far sharper difficulty dial than
   expected, and it is the knob to reach for first.
2. **A saturated tier teaches the wrong skill.** Reward std is non-zero
   (0.139), so a trainer would still see gradient — but every rollout solved,
   so the only variation is efficiency. Training here would teach shorter
   solutions, not solving. Use a tighter configuration for training this model
   class.
3. **The dead-end path did not execute.** Zero dead ends occurred, because the
   second empty bottle removes the condition that produced them. Dead-end
   termination remains covered only by unit tests and the exploit probe, not by
   live play.
4. **Cost is driven by reasoning, not wasted turns.** 650k output tokens across
   6 rollouts, essentially unchanged from the pre-hardening run, despite the
   dead-end fix. The 21 legitimate turns each carry 4-7k reasoning tokens.
   Turn count and model verbosity are the cost levers; loop-burn was not the
   main expense.
5. **Saturation is model-relative.** 100% here says nothing about a 1B
   open-weights model on the same tier. Band checks must be re-run per model.

### Deterministic Exploit Pass

Command: `uv run python -m magic_sort_env.exploits`.

| Probe | Before | After | Finding |
|---|---|---|---|
| dead-end false negative | 39 turns, reward 0.000 | 5 moves, reward 0.253 | terminal dead-end detection cuts loop burn and gives progress credit |
| failure-gradient | 0.000 vs 0.000 | 0.281 vs 0.366 | progress consolation creates spread among failures without reaching solve payout |
| fog-farming | hypothetical reveal reward 0.883 (5 reveals) | current reward 0.383 (5 reveals logged only) | reveals are metrics, not rewards; omniscient par prices exploratory pours |
| stuck no-op loop | would run to cap 39 turns | stopped=True, moves=3, reward=0.239 | repeat-stop catches identical stuck-bottle attempts |

### Framework-Free Policy Smoke

Command: `uv run python -m magic_sort_env.core --tier <tier> --examples N`.

| Tier | Policy | Seeds | Reward Range | Notes |
|---|---|---:|---|---|
| `trivial` | optimal | 0-2 | 2.20 | exact par solve every time |
| `trivial` | random | 0-2 | 1.74-1.93 | random solves, inefficient |
| `easy` | optimal | 0-2 | 2.20 | exact par solve every time |
| `easy` | random | 0-2 | 1.57-1.68 | random solves, inefficient |
| `medium` | optimal | 0-1 | 2.20 | includes a stuck-bottle sample at seed 0 |
| `medium` | random | 0-1 | 1.71-1.79 | random solves, inefficient |

### Live Adapter Smoke

Command:

```powershell
uv run vf-eval magic_sort -a '{\"tier\":\"trivial\",\"num_train_examples\":1,\"num_eval_examples\":1,\"cap_multiple\":1}' --provider openai -m gpt-5-nano -n 1 -r 1 --max-tokens 64 --disable-tui --disable-env-server --save-results
```

Saved to `outputs/evals/magic_sort--gpt-5-nano/9d83c631`.

| Model | Tier | Examples | Rollouts | Reward | pass@1 | Turns | Progress | Stop | Notes |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| `gpt-5-nano` | `trivial` | 1 | 1 | 0.338 | 0.000 | 4 | 0.750 | no-progress stop | Tiny token-capped adapter smoke; validates wrapper/metrics/stop path, not competence |

The current repo's live smoke completed in 7 seconds and did **not** emit the
raw-dict message warning from the scratch adapter.

Suggested fuller pass:

```powershell
uv run vf-eval magic_sort -a '{\"tier\":\"trivial\",\"num_train_examples\":3,\"num_eval_examples\":3}' --provider openai -m gpt-5-nano -n 1 -r 2 --disable-tui --disable-env-server --save-results
uv run vf-eval magic_sort -a '{\"tier\":\"easy\",\"num_train_examples\":3,\"num_eval_examples\":3}' --provider openai -m gpt-5-nano -n 1 -r 2 --disable-tui --disable-env-server --save-results
```

Report reward average, spread, pass@k, pass^k, turn count, token count, and
wall-clock. Cost is a design variable for multi-turn reasoning environments.
