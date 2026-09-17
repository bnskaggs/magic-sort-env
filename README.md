# Magic Sort Env

A Magic Sort / water-sort reinforcement-learning environment for LLM agents.

Take a shipped game mechanic, turn it into a reusable RL environment, and
document the reward design well enough that another environment builder can
audit it.

Status: **eval-proven, trainer-unverified**. The environment runs under
`vf-eval` and has tests for its mechanics, generator, reward decomposition, and
known exploit fixes. It has not yet been consumed by a full `prime-rl` training
job.

## Why This Exists

Most public environments test single-turn instruction following or short tool
loops. Magic Sort is different: it asks a model to plan through a multi-turn,
hard-constraint state space. In an early smoke eval, `gpt-5-nano` saturated
instruction-following and Wordle-style environments, then solved only 1 of 6
easy Magic Sort rollouts. That makes this a useful training target rather than
just another solved benchmark.

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

## Tiers

| Tier | Colors | Empty Bottles | Layered Mechanics |
|---|---:|---:|---|
| `trivial` | 3 | 2 | none |
| `easy` | 4 | 2 | none |
| `medium` | 6 | 2 | 0-1 stuck and/or hidden bottle |
| `hard` | 8 | 2 | 1-2 stuck bottles and 1-2 hidden bottles |

The second empty bottle on `easy` is deliberate. A one-empty easy tier caused
dead ends and expensive failed rollouts in early evals.

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

- Eval-proven, trainer-unverified.
- The current `vf-eval` run path uses `--disable-env-server` on Windows.
- No claims are made about skill transfer from Magic Sort to other domains.
- Hidden-layer `par` is omniscient and documented as such.

## What Would Pay For The Next Version?

An environment vendor or lab looking for hard, multi-turn, partially observable
planning tasks with an explicit exploit catalogue. The next version worth money
is not more water-sort polish; it is the same design discipline applied to
economic environments where agents manage scarce resources, credit, and
adversaries.
