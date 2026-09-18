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

### Small-Model Band Tests (Ollama, local)

The question these answer: which model size can actually play this environment,
and on which tier? Training needs a model that solves *some* rollouts — with no
solves there is no reward spread and nothing to learn from.

Served via Ollama (quantized weights, so these slightly understate the bf16
versions a training platform would use).

**First-move legality probes** — can the model emit a *legal* opening pour?

| Model | Tier | Legal first moves | Failure mode |
|---|---|---:|---|
| `llama3.2:1b` | trivial | 0/3 | no parseable move (narrates prose instead of `pour O D`) |
| `llama3.2:3b` | trivial | 0/3 | well-formed but illegal moves (misreads board legality) |
| `qwen2.5:7b-instruct` | trivial | 4/4 | — |
| `qwen2.5:7b-instruct` | easy | 4/4 | — |

`qwen3:1.7b` is excluded: as a thinking model it consumed 1,200 tokens of
reasoning and emitted **zero** content, failing on never-stopping-reasoning
rather than on the task. Thinking models need a token budget or thinking
disabled before they can be assessed here.

**Full rollouts, `qwen2.5:7b-instruct` on `trivial`** (4 puzzles x 2 rollouts,
`--max-tokens 400`):

| Metric | Value |
|---|---|
| solve rate | 0/8 |
| outcome reward | 0.258 (consolation only) |
| progress | 0.519 |
| mean turns | 20.9 |
| no-progress stops | 6/8 |
| output tokens per rollout | ~122 |

**Full rollouts, `qwen2.5:7b-instruct` on `micro`, before illegal-feedback
fix** (4 puzzles x 2 rollouts, `--max-tokens 400`). `micro` (2 colors, 3
empties, depth 4, par 3-7) was added after the trivial run above; a seeded
random policy solves 23/30 seeds on it, so the tier itself is finishable by a
weak policy.

| Metric | Value |
|---|---|
| solve rate | 0/8 (max reward 0.56, below the >= 1.0 solve floor) |
| outcome reward | 0.376 +/- 0.114 (consolation only) |
| progress | 0.669 |
| illegal-move rate | 0.383 |
| mean turns | 12.8 |
| no-progress stops | 2/8 |
| output tokens per rollout | ~77 |

**Full rollouts, `qwen2.5:7b-instruct` on `micro`, after illegal-feedback fix**
(4 puzzles x 2 rollouts, `--max-tokens 400`). Illegal moves now name the
failure reason, the first illegal move is free, and consecutive identical
illegal moves trigger a legal-move list.

| Metric | Value |
|---|---|
| solve rate | 4/8 |
| outcome reward | 0.830 +/- 0.593 |
| progress | 0.787 |
| illegal-move rate | 0.360 |
| mean turns | 13.4 |
| no-progress stops | 3/8 |
| legal hints shown | 0 |
| output tokens per rollout | ~81 |

**Findings:**

1. **Model size sets a hard floor on playability.** 1B cannot follow the output
   protocol; 3B follows it but cannot read legality; 7B does both perfectly on
   first moves. That progression is a cleaner capability signal than any single
   solve rate.
2. **The 7B still solves nothing on `trivial`, but for a third reason: it
   loops.** Progress averages 0.52, so it genuinely sorts about half the board,
   then 6 of 8 rollouts end in the repeat-stop — after an illegal move the board
   is unchanged, so the model re-issues the same move until the loop guard fires.
   This is a distinct failure from "cannot plan."
3. **`micro` moved the failure mode but not the solve rate by itself.** Versus trivial:
   progress up (0.52 -> 0.67), repeat-stop deaths down (6/8 -> 2/8), turns down
   (20.9 -> 12.8) — and still 0/8 solves. The transcripts show why: the model
   no longer re-issues one identical move; it shotguns *different* illegal
   pours (38% of all moves) until the 3x-par cap burns out. The binding
   constraint is now legality feedback — the environment says only "illegal,
   wasted a turn" with no reason — which is exactly the loop-breaker decision.
4. **Illegal-reason feedback cleared the training gate.** The post-fix micro
   probe solved 4/8, which lands inside the 20-80% band with real reward spread
   (std 0.593). The legal-move list did not appear in this sample
   (`legal_hint_count=0`), so the lift came from naming the reason and giving one
   free correction, not from converting planning into lookup.
5. **Consequence for training: `qwen2.5:7b-instruct` + `micro` is the first
   trainable pair.** It is still a tiny local/quantized band read, not a training
   result. Hosted training should use the closest available bf16 model and keep
   the solve-rate gate as the preflight check.

### Hosted Preflights (Prime Inference, bf16, post illegal-feedback fix)

Purpose: re-run the 20-80% solve-rate gate on the exact bf16 models available
for hosted training, before spending training tokens. 4 puzzles x 2 rollouts,
`--max-tokens 400`, thinking disabled via
`extra_body.chat_template_kwargs.enable_thinking=false`.

**Thinking mode is disqualifying at this token budget.** With thinking left
on, `Qwen/Qwen3.5-4B` burned all 400 tokens in `reasoning_content` and
returned empty `content` on every rollout; the follow-up turn then failed
API-side (422: assistant message with no content). This reproduces the
`qwen3:1.7b` local finding on a hosted bf16 model and adds an API-level
failure mode on top.

| Model | Tier | Solves | Reward | Illegal rate | Legal hints |
|---|---|---:|---|---:|---:|
| `Qwen/Qwen3.5-4B` | `micro` | 1/8 | 0.556 +/- 0.550 | 0.537 | 1 |
| `Qwen/Qwen3.5-9B` | `micro` | 6/8 | 1.329 +/- 0.571 | 0.402 | 2 |
| `Qwen/Qwen3.5-9B` | `trivial` | 4/8 | 0.984 +/- 0.668 | 0.588 | 1 |
| `Qwen/Qwen3.5-4B` | `micro` + `n_empty=4` | 5/8 | 1.271 +/- 0.734 | 0.406 | 0 |

(`pass@k` lines from vf-eval overcount by including any rollout with reward
>= 0.5; solve counts above use the >= 1.0 solve floor.)

**Findings:**

1. **Two trainable pairs exist.** `Qwen3.5-9B` on `trivial` sits dead center
   (50%, shipped tier); `Qwen3.5-4B` on `micro`+4-empties is 62.5% with the
   highest reward spread at half the token price. The difficulty dial worked
   exactly as designed: one `n_empty` override moved the 4B from 12.5% to
   62.5%.
2. **The escalation hint stays rare** (0-2 of 8 rollouts across all pairs),
   so band positions come from reason feedback, not legal-move lookup.
3. **The 4B pair was launched first (2026-09-17) and blocked by a platform
   bug**, not by the environment: the hosted training image ships a legacy
   `connect-python` package its own `prime-sandboxes` guard rejects, and any
   env whose dependencies upgrade `verifiers` or `prime-sandboxes` breaks the
   harness. Three launches failed at $0 before the wheel was repackaged as a
   pure plugin (dependencies: `datasets` only — see `pyproject.toml`).
   Retry the 4B config when the platform image is fixed.

### First Training Run (2026-09-18)

Hosted LoRA GRPO on Prime Intellect: run `magic-sort-e--qwen3.5-9b--xbxz8z`,
`Qwen/Qwen3.5-9B` on the shipped `trivial` tier, config
[configs/train-qwen35-9b-trivial.toml](../configs/train-qwen35-9b-trivial.toml)
(60 steps x 64 rollouts, GRPO groups of 8, `max_tokens` 400, thinking
disabled). Total cost **$17.48** (120M tokens: 10.96M training, 108M
inference). Env version `0.1.3`.

**Train reward, per-batch mean (selected steps):**

| Step | Mean | p10 | p90 |
|---:|---|---|---|
| 0 | 0.598 | 0.225 | 1.665 |
| 10 | 0.826 | 0.203 | 1.710 |
| 20 | 1.521 | 0.239 | 1.991 |
| 30 | 1.670 | 1.555 | 1.927 |
| 40 | 1.784 | 1.663 | 1.927 |
| 47 | 1.843 | 1.659 | 2.000 |
| 59 | 1.800 | 1.669 | 2.000 |

**Frozen eval split (20 puzzles x 2 rollouts, temperature 0), every 15
steps:**

| Step | Reward | Illegal-move rate | Mean turns |
|---:|---|---|---|
| 0 (base model) | 1.013 | 0.592 | 18.95 |
| 15 | 1.181 | 0.545 | 17.98 |
| 30 | 1.620 | 0.440 | 16.38 |
| 45 | 1.661 | 0.442 | 16.15 |
| 60 | 1.456 | 0.409 | 15.08 |

**Findings:**

1. **The reward curve rises.** Train batch mean 0.60 -> ~1.80 plateau from
   step ~33; batch p10 went 0.23 -> 1.67, meaning by the plateau virtually
   every rollout in every batch solves. The reward ceiling (solve +
   efficiency at par + format) is 2.2.
2. **The frozen split confirms learning, not reward farming.** Held-out
   reward rose 1.013 -> 1.661 at step 45; illegal-move rate fell
   monotonically (0.59 -> 0.41) and solutions got shorter (19 -> 15 turns).
   `legal_hint_count` was 0 for the entire run — the escalation hint never
   fired, so none of the gain came from legal-move lookup.
3. **Late-run drift is visible and honest.** The step-60 eval dipped to
   1.456 while train reward held ~1.8. The step-45 checkpoint
   (`t3xlw91ycjc1abzxce1pwt34`) is the artifact worth keeping.
4. **Platform integration was the hard part.** Three $0 failed launches
   traced to the hosted image's dependency stack; the durable rule is that
   an environment wheel must be a pure plugin over the runtime's own
   packages (see the annotated `dependencies` block in `pyproject.toml`).

### Deterministic Exploit Pass

Command: `uv run python -m magic_sort_env.exploits`.

| Probe | Before | After | Finding |
|---|---|---|---|
| dead-end false negative | 39 turns, reward 0.000 | 4 moves, reward 0.253 | terminal dead-end detection cuts loop burn and gives progress credit |
| failure-gradient | 0.000 vs 0.000 | 0.281 vs 0.366 | progress consolation creates spread among failures without reaching solve payout |
| fog-farming | hypothetical reveal reward 0.483 (1 reveal) | current reward 0.383 (1 reveal logged only) | reveals are metrics, not rewards; omniscient par prices exploratory pours |
| stuck no-op loop | would run to cap 39 turns | stopped=True, moves=2, reward=0.239 | repeat-stop catches identical stuck-bottle attempts |

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
