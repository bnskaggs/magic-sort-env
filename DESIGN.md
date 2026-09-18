# Design Notes

This document is the important part of the repo. Code is cheap; reward design is
where the skill lives.

## Artifact Status

Magic Sort Env is **engine-tested, eval-run, trainer-verified (one LoRA
run)**.

It exposes the same `load_environment()` interface used by Prime Intellect's
`verifiers` environments and has train/eval splits, generated tasks, reward
shaping, and difficulty knobs. The engine and reward are covered by tests and a
deterministic exploit pass. Live evals, local band probes, and one hosted LoRA
GRPO run (`Qwen3.5-9B` on `trivial`, 2026-09-18) have run; the training curve
rose on both the train batches and a frozen eval split with zero legal-move
hints shown, which is the design's core claim surviving contact with a real
trainer. Scope stays narrow: one run, one model, one tier. The README does not
claim otherwise.

## Design Choices

### Compact State

The model sees bottle stacks as JSON of letters rather than color names. This
saves context and avoids teaching a model to manipulate irrelevant nouns.

### Server-Authoritative Scoring

The reward does not trust the live transcript. It replays the model's parsed
commands from the true starting board, then scores the replay. This mirrors the
anti-cheat pattern from the original outwit.games implementation.

### Exact Par

The generator rejects puzzles until a BFS solver proves a solution and returns a
shortest path. That path length is `par`.

Hidden-layer puzzles use **omniscient par**: the solver sees through the fog.
This is intentionally stricter than the model's information state. The gap
between actual moves and omniscient par is a metric for planning under
uncertainty, not a bug.

### Partial-Information V2

V2 adds two mechanics from the original Magic Sort design:

- **Stuck bottles:** fixed obstacles that cannot be used as a source.
- **Hidden layers:** bottom-contiguous `?` cells that reveal when layers above
  them are poured off.

Fog changes information, not state. The true board is fixed and solver-verified
before cells are hidden.

## Exploit Catalogue

### 1. Cumulative Intermediate Rewards

Risk: rewarding each move, reveal, or safe fuel-equivalent state creates a farm.
The model can optimize the intermediate counter instead of solving.

Defense: no per-move progress reward. Progress is scored only from the terminal
replayed board and capped below the solve payout.

### 2. Efficiency Farm

Risk: if efficiency paid on failed rollouts, the model could take one strong
move, stop early, and preserve a high par/move ratio.

Defense: efficiency pays only after solve.

### 3. Consolation Camping

Risk: if consolation can approach the solve payout, the model can cluster a few
colors and stop.

Defense: consolation is `0.45 * progress`; solve alone pays `1.0`, before
efficiency or format. A failed rollout cannot beat a solved one.

### 4. Dead-End False Negative

Observed in an early local run: the model bricked the puzzle by
burning its only empty bottle, correctly said no legal moves remained, and the
environment kept asking for moves until the cap. It scored zero and burned about
15 minutes.

Defense: when `legal_pours()` is empty, the episode terminates immediately. If
the model correctly calls the dead end, it gets a tiny non-solve credit. This is
the mirror image of reward hacking: the verifier failing to recognize legitimate
play.

Measured probe: the old path would run to 39 turns and score 0.000; the hardened
path stops after 4 moves and scores 0.253 from progress plus dead-end credit.

### 5. No Gradient Among Failures

Risk: completed-bottle-only consolation makes most failed rollouts score exactly
zero, indistinguishable from nonsense output. GRPO then has no useful spread
among failures.

Defense: terminal progress is the average longest same-color run per bottle,
normalized. That rewards actual sorting progress while staying capped.

Measured probe: two failed boards that both scored 0.000 under completed-bottle
consolation now score 0.281 and 0.366, creating gradient among failures.

### 6. Protocol Drift Masquerading As Bad Planning

Observed in the first smoke eval: the only solving rollout was also the only
cleanly formatted rollout. Planning and output-protocol adherence were
confounded.

Defense: `strict_format=True` gives one non-consuming format warning before
unparseable output wastes a turn. Format is also reported separately as a metric.

### 7. Illegal-Move Looping

Observed in local band probes: a quantized 7B model could produce legal opening
moves and sort about half the board, then fail by issuing illegal pours. On
`trivial`, it often repeated the same illegal move until the repeat-stop fired.
On `micro`, it mostly tried different illegal moves and burned the cap.

Defense: illegal moves now name the specific reason (destination full, color
mismatch, source empty, source stuck, or bad index). The first illegal move is
free, mirroring the one free format warning, because it is a correction point
rather than evidence of bad planning. Later illegal moves waste turns.
Consecutive repeats of the same illegal move show the current legal-move list.
That escalation is measured as `legal_hint_count`, because showing legal moves
can turn planning into lookup.

Measured probe: `qwen2.5:7b-instruct` on `micro` moved from 0/8 solves before
feedback to 4/8 solves after feedback, with reward std 0.593. `legal_hint_count`
was 0 in that sample, so the lift came from reason feedback and the free
correction, not from legal-move lookup.

### 8. Stuck-Bottle No-Op Loops

Risk: repeatedly trying to pour from a stuck bottle can burn turns without
meaningful state change.

Defense: illegal moves waste turns, no reward is attached to attempts, and the
repeat-stop catches identical no-progress loops.

Measured probe: repeated pours from a stuck bottle would run to a 39-turn cap;
the hardened path stops after 2 consumed moves with `no_progress_stop=True`.

### 9. Fog Farming

Risk: on hidden-layer tiers, a model may make cheap exploratory pours purely to
trigger reveals rather than progress toward solve.

Defense: reveals are metrics, not rewards. Omniscient par makes reveal-heavy
solutions pay an efficiency cost.

Measured probe: a hypothetical `+0.1 per reveal` reward would have paid 0.483
for a reveal-farming line with 1 genuine reveal; the current reward pays 0.383
and logs the reveal as a metric only.

**Metric bug found and fixed (2026-09-17).** The first `reveal_count`
implementation compared the rendered board before and after each pour, so it
counted *every successful pour* as a reveal — it reported 3.25 reveals per
rollout on `trivial`, a tier with no hidden cells at all. Reveals are now
counted as decreases in the hidden-cell count (`core.hidden_cell_count`), with
a regression test. Any earlier reveal figures in this repo's history are wrong.

### 10. Rates Reward Small Denominators

General lesson: bare rates make "do one thing perfectly
and stop" look good.

Defense: Magic Sort has no quality-rate reward. Efficiency is conditional on
solve; progress is normalized over every bottle.

### 11. Easy-Only Exploit Testing

General lesson: a reward spec can be safe in an easy world and
farmed in a hard one.

Defense: smoke scripts and results should report at least trivial/easy/medium,
and exploit passes should run on the hardest tier the model can still interact
with.

## Open Design Knobs

- Re-run the 20-80% solve-rate gate for the exact hosted-training model, not
  just local quantized `qwen2.5:7b-instruct`.
- Decide whether hidden layers belong on `medium` by default or only in `hard`.
- Decide whether "no legal moves" should remain a tiny credit or a pure
  terminal annotation.
- Decide whether the eventual Bazaar capstone should use omniscient reference
  value the way this env uses omniscient par.
