"""Framework-free Magic Sort engine.

The environment wrapper is intentionally thin. This module owns the game rules,
generator, solver, reward decomposition, and deterministic policy smoke tests.

State convention:
- A bottle is a list of one-character color IDs.
- Index 0 is the bottom; the last element is the top.
- Empty bottles are [].
- Every bottle has fixed capacity ``depth``.
"""

from __future__ import annotations

import argparse
import itertools
import json
import random
from collections import deque
from dataclasses import dataclass
from typing import Iterable

LETTERS = "ABCDEFGHIJKLMNOP"


@dataclass(frozen=True)
class Puzzle:
    """A generated task.

    ``par`` is omniscient for hidden-layer puzzles: the solver sees the true
    board. That is deliberate. The gap between actual moves and omniscient par is
    the uncertainty-handling signal.
    """

    true_board: tuple[tuple[str, ...], ...]
    visible_board: tuple[tuple[str, ...], ...]
    hidden_mask: tuple[tuple[bool, ...], ...]
    stuck: tuple[int, ...]
    depth: int
    par: int
    tier: str
    seed: int


@dataclass(frozen=True)
class ReplayResult:
    final_board: tuple[tuple[str, ...], ...]
    visible_board: tuple[tuple[str, ...], ...]
    solved: bool
    dead_end: bool
    moves: int
    parsed_turns: int
    assistant_turns: int
    illegal_moves: int
    repeated_messages: int
    no_progress_stopped: bool
    dead_end_called: bool
    reveals: int
    moves_after_first_reveal: int
    illegal_after_reveal: int
    progress: float
    reward: float
    components: dict[str, float]


def freeze(board: Iterable[Iterable[str]]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(bottle) for bottle in board)


def thaw(board: Iterable[Iterable[str]]) -> list[list[str]]:
    return [list(bottle) for bottle in board]


def top_run(bottle: list[str] | tuple[str, ...]) -> int:
    if not bottle:
        return 0
    color = bottle[-1]
    count = 0
    for cell in reversed(bottle):
        if cell != color:
            break
        count += 1
    return count


def is_solved_bottle(bottle: list[str] | tuple[str, ...], depth: int) -> bool:
    return len(bottle) == 0 or (len(bottle) == depth and len(set(bottle)) == 1)


def is_solved(board: Iterable[Iterable[str]], depth: int) -> bool:
    return all(is_solved_bottle(tuple(bottle), depth) for bottle in board)


def legal(
    board: Iterable[Iterable[str]],
    origin: int,
    destination: int,
    depth: int,
    stuck: Iterable[int] = (),
) -> bool:
    state = thaw(board)
    stuck_set = set(stuck)
    if origin == destination:
        return False
    if origin < 0 or destination < 0:
        return False
    if origin >= len(state) or destination >= len(state):
        return False
    if origin in stuck_set:
        return False
    src = state[origin]
    dst = state[destination]
    if not src or len(dst) >= depth:
        return False
    return len(dst) == 0 or dst[-1] == src[-1]


def apply_pour(
    board: Iterable[Iterable[str]],
    origin: int,
    destination: int,
    depth: int,
) -> tuple[tuple[tuple[str, ...], ...], int]:
    state = thaw(board)
    src = state[origin]
    dst = state[destination]
    run = top_run(src)
    room = depth - len(dst)
    moved = min(run, room)
    for _ in range(moved):
        dst.append(src.pop())
    return freeze(state), moved


def legal_pours(
    board: Iterable[Iterable[str]], depth: int, stuck: Iterable[int] = ()
) -> list[tuple[int, int]]:
    return [
        (origin, destination)
        for origin in range(len(tuple(board)))
        for destination in range(len(tuple(board)))
        if legal(board, origin, destination, depth, stuck)
    ]


def solved_state(n_colors: int, n_empty: int, depth: int) -> tuple[tuple[str, ...], ...]:
    return freeze([[LETTERS[i]] * depth for i in range(n_colors)] + [[] for _ in range(n_empty)])


def random_fill(
    n_colors: int, n_empty: int, depth: int, rng: random.Random
) -> tuple[tuple[str, ...], ...]:
    blocks: list[str] = []
    for i in range(n_colors):
        blocks.extend([LETTERS[i]] * depth)
    rng.shuffle(blocks)
    filled = [
        blocks[i * depth : (i + 1) * depth] for i in range(n_colors)
    ]
    return freeze(filled + [[] for _ in range(n_empty)])


def random_fill_with_stuck(
    n_colors: int,
    n_empty: int,
    depth: int,
    stuck_count: int,
    rng: random.Random,
) -> tuple[tuple[tuple[str, ...], ...], tuple[int, ...]]:
    """Build a board with reliable stuck obstacles.

    A stuck bottle cannot be poured from, so a random mixed stuck bottle is
    usually unsolvable. The playable stuck shape is a non-full same-color stack
    that can receive more of that color later.
    """

    total_bottles = n_colors + n_empty
    stuck = tuple(range(stuck_count))
    state: list[list[str]] = [[] for _ in range(total_bottles)]
    blocks: list[str] = []
    for color_idx in range(n_colors):
        color = LETTERS[color_idx]
        if color_idx < stuck_count:
            height = rng.randint(1, depth - 1)
            state[color_idx] = [color] * height
            blocks.extend([color] * (depth - height))
        else:
            blocks.extend([color] * depth)
    rng.shuffle(blocks)
    targets = [i for i in range(total_bottles) if i not in stuck]
    while blocks:
        open_targets = [i for i in targets if len(state[i]) < depth]
        if not open_targets:
            raise RuntimeError("not enough capacity while building stuck board")
        target = rng.choice(open_targets)
        state[target].append(blocks.pop())
    return freeze(state), stuck


def canon(board: Iterable[Iterable[str]]) -> tuple[tuple[str, ...], ...]:
    return tuple(sorted(tuple(bottle) for bottle in board))


def solve_path(
    board: Iterable[Iterable[str]],
    depth: int,
    stuck: Iterable[int] = (),
    node_cap: int = 300_000,
) -> tuple[list[tuple[int, int]] | None, bool]:
    start_board = freeze(board)
    if is_solved(start_board, depth):
        return [], True
    seen = {canon(start_board)}
    queue = deque([(start_board, [])])
    nodes = 0
    while queue:
        current, path = queue.popleft()
        for move in legal_pours(current, depth, stuck):
            nxt, _ = apply_pour(current, move[0], move[1], depth)
            key = canon(nxt)
            if key in seen:
                continue
            new_path = path + [move]
            if is_solved(nxt, depth):
                return new_path, True
            seen.add(key)
            queue.append((nxt, new_path))
            nodes += 1
            if nodes > node_cap:
                return greedy_path(start_board, depth, stuck), False
    return None, True


def solve_par(
    board: Iterable[Iterable[str]],
    depth: int,
    stuck: Iterable[int] = (),
    node_cap: int = 300_000,
) -> tuple[int | None, bool]:
    path, exact = solve_path(board, depth, stuck, node_cap)
    return (None if path is None else len(path)), exact


def greedy_path(
    board: Iterable[Iterable[str]],
    depth: int,
    stuck: Iterable[int] = (),
    limit: int = 200,
) -> list[tuple[int, int]] | None:
    current = freeze(board)
    path: list[tuple[int, int]] = []
    for _ in range(limit):
        if is_solved(current, depth):
            return path
        best_move: tuple[int, int] | None = None
        best_score = -1
        for move in legal_pours(current, depth, stuck):
            nxt, moved = apply_pour(current, move[0], move[1], depth)
            score = moved + (10 if is_solved_bottle(nxt[move[1]], depth) else 0)
            if score > best_score:
                best_move = move
                best_score = score
        if best_move is None:
            return None
        current, _ = apply_pour(current, best_move[0], best_move[1], depth)
        path.append(best_move)
    return None


def progress_score(board: Iterable[Iterable[str]], depth: int) -> float:
    """Progress credit for failures.

    Counts the longest same-color run in each bottle. This creates reward spread
    among failed rollouts without letting consolation approach the solve payout.
    """

    state = freeze(board)
    if not state:
        return 0.0
    total = 0.0
    for bottle in state:
        if not bottle:
            total += 1.0
            continue
        best = 1
        for i, color in enumerate(bottle):
            run = 1
            for other in bottle[i + 1 :]:
                if other == color:
                    run += 1
                else:
                    break
            best = max(best, run)
        total += best / depth
    return total / len(state)


def reward_components(
    board: Iterable[Iterable[str]],
    depth: int,
    par: int,
    solved: bool,
    moves: int,
    format_ok: bool,
    dead_end_called: bool = False,
) -> dict[str, float]:
    if solved:
        solve = 1.0
        efficiency = min(1.0, par / max(moves, 1))
        consolation = 0.0
        dead_end = 0.0
    else:
        solve = 0.0
        efficiency = 0.0
        consolation = 0.45 * progress_score(board, depth)
        dead_end = 0.05 if dead_end_called else 0.0
    return {
        "solve": solve,
        "efficiency": efficiency,
        "consolation": consolation,
        "dead_end": dead_end,
        "format": 0.2 if format_ok else 0.0,
    }


def reward(
    board: Iterable[Iterable[str]],
    depth: int,
    par: int,
    solved: bool,
    moves: int,
    format_ok: bool,
    dead_end_called: bool = False,
) -> float:
    return sum(
        reward_components(board, depth, par, solved, moves, format_ok, dead_end_called).values()
    )


def choose_stuck(
    board: tuple[tuple[str, ...], ...],
    depth: int,
    count: int,
    rng: random.Random,
) -> tuple[int, ...] | None:
    candidates = [
        i
        for i, bottle in enumerate(board)
        if 0 < len(bottle) < depth
        and not is_solved_bottle(bottle, depth)
    ]
    if len(candidates) < count:
        return None
    rng.shuffle(candidates)
    return tuple(sorted(candidates[:count]))


def stuck_candidates(
    board: tuple[tuple[str, ...], ...],
    depth: int,
) -> list[int]:
    return [
        i
        for i, bottle in enumerate(board)
        if 0 < len(bottle) < depth and not is_solved_bottle(bottle, depth)
    ]


def make_hidden_mask(
    board: tuple[tuple[str, ...], ...],
    count: int,
    rng: random.Random,
    unavailable: Iterable[int] = (),
) -> tuple[tuple[bool, ...], ...] | None:
    unavailable_set = set(unavailable)
    candidates = []
    for i, bottle in enumerate(board):
        if i in unavailable_set or len(bottle) < 2:
            continue
        # Need a hidden boundary whose color differs from the visible color above.
        valid_boundaries = [
            boundary
            for boundary in range(1, len(bottle))
            if bottle[boundary - 1] != bottle[boundary]
        ]
        if valid_boundaries:
            candidates.append((i, valid_boundaries))
    if len(candidates) < count:
        return None
    rng.shuffle(candidates)
    hidden = [[False] * len(bottle) for bottle in board]
    for bottle_idx, boundaries in candidates[:count]:
        boundary = rng.choice(boundaries)
        for layer_idx in range(boundary):
            hidden[bottle_idx][layer_idx] = True
    return tuple(tuple(row) for row in hidden)


def visible_from(
    board: Iterable[Iterable[str]], hidden_mask: Iterable[Iterable[bool]]
) -> tuple[tuple[str, ...], ...]:
    visible = []
    for bottle, mask in zip(board, hidden_mask):
        visible.append(tuple("?" if is_hidden else color for color, is_hidden in zip(bottle, mask)))
    return tuple(visible)


def reveal_after_pour(
    hidden_mask: tuple[tuple[bool, ...], ...],
    origin: int,
    destination: int,
    moved: int,
) -> tuple[tuple[bool, ...], ...]:
    """Update hidden mask after a pour.

    Moved layers become visible in the destination. Hidden layers are an
    information constraint on the starting board, not a property that travels
    with a color block forever.
    """

    masks = [list(row) for row in hidden_mask]
    for _ in range(moved):
        if masks[origin]:
            masks[origin].pop()
            masks[destination].append(False)
    return tuple(tuple(row) for row in masks)


TIERS = {
    "trivial": dict(n_colors=3, n_empty=2, depth=4, stuck_range=(0, 0), hidden_range=(0, 0)),
    "easy": dict(n_colors=4, n_empty=2, depth=4, stuck_range=(0, 0), hidden_range=(0, 0)),
    "medium": dict(n_colors=6, n_empty=2, depth=4, stuck_range=(0, 1), hidden_range=(0, 1)),
    "hard": dict(n_colors=8, n_empty=2, depth=4, stuck_range=(1, 2), hidden_range=(1, 2)),
}


def generate(
    tier: str = "easy",
    seed: int = 0,
    *,
    use_stuck: bool | None = None,
    use_hidden: bool | None = None,
    stuck_count: int | None = None,
    hidden_count: int | None = None,
    n_colors: int | None = None,
    n_empty: int | None = None,
    depth: int | None = None,
    node_cap: int = 300_000,
) -> Puzzle:
    cfg = dict(TIERS[tier])
    # Overrides matter because difficulty here is extremely sensitive: for
    # gpt-5-nano, easy with 1 empty solved 1/6 and with 2 empties solved 6/6.
    # The colors/empties ratio is the primary band control.
    if n_colors is not None:
        cfg["n_colors"] = n_colors
    if n_empty is not None:
        cfg["n_empty"] = n_empty
    if depth is not None:
        cfg["depth"] = depth
    rng = random.Random(seed)
    use_stuck = tier in {"medium", "hard"} if use_stuck is None else use_stuck
    use_hidden = tier in {"medium", "hard"} if use_hidden is None else use_hidden
    for _ in range(500):
        requested_stuck = 0
        if use_stuck:
            lo, hi = cfg["stuck_range"]
            requested_stuck = rng.randint(lo, hi) if stuck_count is None else stuck_count
        if requested_stuck:
            board, stuck = random_fill_with_stuck(
                cfg["n_colors"], cfg["n_empty"], cfg["depth"], requested_stuck, rng
            )
        else:
            board = random_fill(cfg["n_colors"], cfg["n_empty"], cfg["depth"], rng)
            stuck = ()
        if is_solved(board, cfg["depth"]):
            continue
        base_path, exact = solve_path(board, cfg["depth"], (), node_cap)
        if base_path is None or not exact:
            continue
        path = base_path
        if stuck:
            path, exact = solve_path(board, cfg["depth"], stuck, node_cap)
        if path is None or not exact or len(path) == 0:
            continue
        hidden_mask = tuple(tuple(False for _ in bottle) for bottle in board)
        if use_hidden:
            lo, hi = cfg["hidden_range"]
            count = rng.randint(lo, hi) if hidden_count is None else hidden_count
            if count:
                mask = make_hidden_mask(board, count, rng, unavailable=stuck)
                if mask is None:
                    continue
                hidden_mask = mask
        return Puzzle(
            true_board=board,
            visible_board=visible_from(board, hidden_mask),
            hidden_mask=hidden_mask,
            stuck=stuck,
            depth=cfg["depth"],
            par=len(path),
            tier=tier,
            seed=seed,
        )
    raise RuntimeError(f"failed to generate {tier} puzzle after 500 attempts")


def render(board: Iterable[Iterable[str]]) -> str:
    return json.dumps({str(i): list(bottle) for i, bottle in enumerate(board)}, separators=(",", ":"))


def parse_rendered(rendered: str) -> tuple[tuple[str, ...], ...]:
    obj = json.loads(rendered)
    return tuple(tuple(obj[str(i)]) for i in range(len(obj)))


def optimal_policy(board: Iterable[Iterable[str]], depth: int, stuck: Iterable[int] = ()) -> tuple[int, int] | None:
    path, _ = solve_path(board, depth, stuck)
    return None if not path else path[0]


def random_policy(
    board: Iterable[Iterable[str]],
    depth: int,
    rng: random.Random,
    stuck: Iterable[int] = (),
) -> tuple[int, int] | None:
    moves = legal_pours(board, depth, stuck)
    return rng.choice(moves) if moves else None


def rollout_policy(puzzle: Puzzle, policy_name: str, cap_multiple: int = 3) -> ReplayResult:
    board = puzzle.true_board
    mask = puzzle.hidden_mask
    moves = 0
    rng = random.Random(10_000 + puzzle.seed)
    cap = cap_multiple * puzzle.par
    reveals = 0
    first_reveal_move: int | None = None
    illegal_after_reveal = 0
    while moves < cap and not is_solved(board, puzzle.depth) and legal_pours(board, puzzle.depth, puzzle.stuck):
        if policy_name == "optimal":
            move = optimal_policy(board, puzzle.depth, puzzle.stuck)
        elif policy_name == "random":
            move = random_policy(board, puzzle.depth, rng, puzzle.stuck)
        else:
            raise ValueError(f"unknown policy {policy_name}")
        if move is None:
            break
        if not legal(board, move[0], move[1], puzzle.depth, puzzle.stuck):
            if first_reveal_move is not None:
                illegal_after_reveal += 1
            moves += 1
            continue
        new_board, moved = apply_pour(board, move[0], move[1], puzzle.depth)
        old_visible = visible_from(board, mask)
        mask = reveal_after_pour(mask, move[0], move[1], moved)
        new_visible = visible_from(new_board, mask)
        if new_visible != old_visible:
            reveals += 1
            if first_reveal_move is None:
                first_reveal_move = moves + 1
        board = new_board
        moves += 1
    solved = is_solved(board, puzzle.depth)
    dead_end = not solved and not legal_pours(board, puzzle.depth, puzzle.stuck)
    components = reward_components(
        board,
        puzzle.depth,
        puzzle.par,
        solved,
        moves,
        format_ok=True,
        dead_end_called=dead_end,
    )
    return ReplayResult(
        final_board=board,
        visible_board=visible_from(board, mask),
        solved=solved,
        dead_end=dead_end,
        moves=moves,
        parsed_turns=moves,
        assistant_turns=moves,
        illegal_moves=0,
        repeated_messages=0,
        no_progress_stopped=False,
        dead_end_called=dead_end,
        reveals=reveals,
        moves_after_first_reveal=0 if first_reveal_move is None else max(0, moves - first_reveal_move),
        illegal_after_reveal=illegal_after_reveal,
        progress=progress_score(board, puzzle.depth),
        reward=sum(components.values()),
        components=components,
    )


def demo(tier: str, examples: int) -> None:
    print(f"{'tier':8} {'seed':>5} {'par':>4} {'stuck':>8} {'policy':10} {'solved':>7} {'dead':>5} {'moves':>6} {'reward':>7}")
    for seed in range(examples):
        puzzle = generate(tier=tier, seed=seed)
        for policy in ("optimal", "random"):
            result = rollout_policy(puzzle, policy)
            print(
                f"{tier:8} {seed:5} {puzzle.par:4} {str(puzzle.stuck):>8} "
                f"{policy:10} {str(result.solved):>7} {str(result.dead_end):>5} "
                f"{result.moves:6} {result.reward:7.2f}"
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tier", default="easy", choices=sorted(TIERS))
    parser.add_argument("--examples", default=3, type=int)
    args = parser.parse_args()
    demo(args.tier, args.examples)
