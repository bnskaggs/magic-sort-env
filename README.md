# Magic Sort Env

A Magic Sort / water-sort reinforcement-learning environment for LLM agents.

Take a shipped game mechanic, turn it into a reusable RL environment, and
document the reward design well enough that another environment builder can
audit it.

Status: **engine-tested, eval-run, trainer-unverified.**

- Mechanics, generator, exact par, and reward decomposition are covered by
  tests (`uv run pytest`).
- The reward-design defenses are checked by a deterministic exploit pass
  (`uv run python -m magic_sort_env.exploits`).
- A full model-vs-environment eval has been run on the `easy` tier
  (`gpt-5-nano`, 6 rollouts, 100% solve, reward 1.828 +/- 0.139) — see
  [results/results.md](results/results.md). The environment runs end to end and
  the reward decomposes as designed. **That eval also showed `easy` is
  saturated for this model**, so it is a usable eval for weaker models but the
  wrong tier for training this class.
- A local Ollama band probe found the first trainable pair:
  `qwen2.5:7b-instruct` on `micro` solved 4/8 after illegal-move feedback was
  added. This is a band read, not a training result.
- No training run has been performed. The `dataset` (train) split, shaped
  rewards as gradient, and group variance as advantage have never executed.

## Why This Exists

Most public environments test single-turn instruction following or short tool
loops. Magic Sort is different: it asks a model to plan through a multi-turn,
hard-constraint state space, and its difficulty is unusually sharp: for
`gpt-5-nano`, the `easy` tier with **one** empty bottle scored 1/6, and with
**two** empty bottles scored 6/6. One bottle spans the entire range from
near-impossible to saturated, which makes the tier knobs a precise instrument
for putting a given model inside the useful 20-80% band.

## Environment Protocol

State is shown as compact JSON:

```json
{"0":["C","C","D","B"],"1":["D","B","D","A"],"2":["B","C","A","B"],"3":["A","D","C","A"],"4":[]}
```

Rules:

- Each bottle is a stack. Index `0` is the bottom; the last element is the top.
- A move is `pour O D`.
- A pour moves the top contiguous block of one color from bottle `O` to bottle
  `D`.
- A pour is legal when `D` is empty or its top color matches `O`'s top color,
  and `D` has room.
- Stuck bottles cannot be poured from.
- Hidden cells are shown as `?`; they reveal when layers above them are poured
  off.
- Solved means every bottle is empty or full of one color.
- Illegal moves name the reason. The first illegal move is free; later illegal
  moves waste a turn. Repeating the same illegal move consecutively also shows
  the current legal-move list.

## Tiers

| Tier | Colors | Empty Bottles | Layered Mechanics |
|---|---:|---:|---|
| `micro` | 2 | 3 | none |
| `trivial` | 3 | 2 | none |
| `easy` | 4 | 2 | none |
| `medium` | 6 | 2 | 0-1 stuck and/or hidden bottle |
| `hard` | 8 | 2 | 1-2 stuck bottles and 1-2 hidden bottles |

**Difficulty is extremely sensitive to the empty-bottle count.** For
`gpt-5-nano`, `easy` with 1 empty solved 1/6 and with 2 empties solved 6/6.
Rather than editing tiers, override the dial directly:

```powershell
uv run vf-eval magic_sort -a '{\"tier\":\"easy\",\"n_empty\":1}' --provider openai -m gpt-5-nano -n 3 -r 2 --disable-tui --disable-env-server
```

`n_colors`, `n_empty`, and `depth` all override the selected tier, so a single
tier can be walked across the 20-80% band for whatever model you are targeting.

## Reward

The reward is a weighted sum, but scoring is server-authoritative: the rubric
replays the model's parsed `pour O D` moves from the initial true board.

Solved rollouts:

- `+1.0` for solving.
- `+1.0 * min(1, par / moves)` for efficiency.
- `+0.2` for clean command formatting.

Failed rollouts:

- No solve or efficiency credit.
- `+0.45 * progress`, where progress is the average longest same-color run per
  bottle, normalized.
- `+0.05` when a genuine dead end is correctly called.
- `+0.2` for clean command formatting.

Why this shape:

- Efficiency pays only on solve, so it cannot become a consolation farm.
- Progress credit is capped below the solve payout, so failed rollouts can have
  gradient without beating success.
- Format is low weight. It teaches the action grammar early and then should stop
  mattering once all rollouts format correctly.
- Dead ends terminate immediately. The first version burned 33 extra model turns
  after a puzzle was already bricked.

For hidden-layer puzzles, `par` is omniscient: the solver sees the true board.
That is intentional. The gap between omniscient par and actual moves is the
uncertainty-handling signal.

## Usage

Install locally:

```powershell
cd magic-sort-env
uv sync --extra dev
```

Run tests:

```powershell
uv run pytest
```

Run a cheap smoke eval:

```powershell
uv run vf-eval magic_sort -a '{\"tier\":\"trivial\",\"num_train_examples\":3,\"num_eval_examples\":3}' --provider openai -m gpt-5-nano -n 1 -r 2 --disable-tui --disable-env-server --save-results
```

PowerShell requires the escaped JSON quotes shown above.

Run the framework-free smoke script:

```powershell
uv run python -m magic_sort_env.core --tier easy --examples 3
```

## Results

See `results/results.md`. All results are small-sample smoke reads unless stated
otherwise. The repo intentionally reports wall-clock and token cost beside
reward and pass rates.

## Honest Limits

- Engine-tested and eval-run, but **no training run has happened**. The first
  local trainable band is `qwen2.5:7b-instruct` on `micro` after illegal-move
  feedback (4/8 solves, reward std 0.593). See [results/results.md](results/results.md).
- `results/` numbers are small-sample. Ollama-served models are quantized.
- Hidden layers and stuck bottles are unit-tested but have not been observed in
  a live model rollout.
- A `reveal_count` bug (counted every pour as a reveal) was found and fixed on
  2026-09-17; earlier reveal figures in the git history are wrong.
- The current `vf-eval` path uses `--disable-env-server` on Windows. Saving
  results fails for model names containing a colon on Windows (path syntax).
- No claims are made about skill transfer from Magic Sort to other domains.
- Hidden-layer `par` is omniscient and documented as such.

## What Would Pay For The Next Version?

An environment vendor or lab looking for hard, multi-turn, partially observable
planning tasks with an explicit exploit catalogue. The next version worth money
is not more water-sort polish; it is the same design discipline applied to
economic environments where agents manage scarce resources, credit, and
adversaries.
