# Design Notes

This document is the important part of the repo. Code is cheap; reward design is
where the skill lives.

## Artifact Status

Magic Sort Env is **engine-tested, eval-incomplete, trainer-unverified**.

It exposes the same `load_environment()` interface used by Prime Intellect's
`verifiers` environments and has train/eval splits, generated tasks, reward
shaping, and difficulty knobs. The engine and reward are covered by tests and a
deterministic exploit pass. What has *not* happened: a full eval of a model
playing the current code, and any training run at all. The README does not
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
path stops after 5 moves and scores 0.253 from progress plus dead-end credit.

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

### 7. Stuck-Bottle No-Op Loops

Risk: repeatedly trying to pour from a stuck bottle can burn turns without
meaningful state change.

Defense: illegal moves waste turns, no reward is attached to attempts, and the
repeat-stop catches identical no-progress loops.

Measured probe: repeated pours from a stuck bottle would run to a 39-turn cap;
the hardened path stops after 3 consumed moves with `no_progress_stop=True`.

### 8. Fog Farming

Risk: on hidden-layer tiers, a model may make cheap exploratory pours purely to
trigger reveals rather than progress toward solve.

Defense: reveals are metrics, not rewards. Omniscient par makes reveal-heavy
solutions pay an efficiency cost.

Measured probe: a hypothetical `+0.1 per reveal` reward would have paid 0.883
for a reveal-farming line with 5 reveals; the current reward pays 0.383 and logs
the 5 reveals as metrics only.

### 9. Rates Reward Small Denominators

General lesson: bare rates make "do one thing perfectly
and stop" look good.

Defense: Magic Sort has no quality-rate reward. Efficiency is conditional on
solve; progress is normalized over every bottle.

### 10. Easy-Only Exploit Testing

General lesson: a reward spec can be safe in an easy world and
farmed in a hard one.

Defense: smoke scripts and results should report at least trivial/easy/medium,
and exploit passes should run on the hardest tier the model can still interact
with.

## Open Design Knobs

- Tune `easy` into the 20-80% solve band for the target model.
- Decide whether hidden layers belong on `medium` by default or only in `hard`.
- Decide whether "no legal moves" should remain a tiny credit or a pure
  terminal annotation.
- Decide whether the eventual Bazaar capstone should use omniscient reference
  value the way this env uses omniscient par.
