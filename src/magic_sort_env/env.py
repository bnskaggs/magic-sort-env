"""Verifiers adapter for Magic Sort.

This file is intentionally boring: the game lives in ``core.py``. The adapter
builds datasets, runs the multi-turn protocol, and wires metrics/rewards into
the legacy ``vf-eval`` interface.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

import verifiers.legacy as vf
from datasets import Dataset

from . import core

POUR_RE = re.compile(r"\bpour\s+(\d+)\s+(\d+)\b", re.IGNORECASE)
NO_LEGAL_RE = re.compile(r"\b(no legal|stuck|dead[- ]?end|no moves)\b", re.IGNORECASE)

RULES = (
    "You are playing Magic Sort (water sort). Bottles hold stacks of colored "
    "letters; index 0 is the BOTTOM, the last element is the TOP. A pour moves "
    "the top contiguous block of one color from bottle O to bottle D. It is "
    "legal only if D is empty or D's top letter equals O's top letter, and D "
    "has room (capacity {depth}). Stuck bottles cannot be poured from. Cells "
    "shown as ? are hidden; they reveal when layers above them are poured off. "
    "Solve = every bottle is empty or a single color filled to capacity.\n"
    "Reply each turn with exactly one move: `pour O D` (example: `pour 3 1`). "
    "If there are no legal moves, say `no legal moves`."
)


def last_pour(text: str) -> tuple[int, int] | None:
    match = None
    for match in POUR_RE.finditer(text):
        pass
    return None if match is None else (int(match.group(1)), int(match.group(2)))


def dead_end_call(text: str) -> bool:
    return bool(NO_LEGAL_RE.search(text))


def assistant_texts(completion: list[dict[str, Any]]) -> list[str]:
    return [
        str(message.get("content") or "")
        for message in completion
        if message.get("role") == "assistant"
    ]


def replay(info: dict[str, Any], completion: list[dict[str, Any]]) -> core.ReplayResult:
    """Replay a model transcript from the authoritative starting board."""

    puzzle = core.Puzzle(
        true_board=tuple(tuple(b) for b in info["true_board"]),
        visible_board=tuple(tuple(b) for b in info["visible_board"]),
        hidden_mask=tuple(tuple(b) for b in info["hidden_mask"]),
        stuck=tuple(info["stuck"]),
        depth=int(info["depth"]),
        par=int(info["par"]),
        tier=str(info["tier"]),
        seed=int(info["seed"]),
    )
    board = puzzle.true_board
    mask = puzzle.hidden_mask
    assistant = assistant_texts(completion)
    assistant_turns = len(assistant)
    parsed_turns = 0
    illegal_moves = 0
    repeated_messages = 0
    no_progress_stopped = False
    dead_end_called = False
    reveals = 0
    first_reveal_move: int | None = None
    illegal_after_reveal = 0
    seen_messages: Counter[str] = Counter()
    cap = int(info.get("cap", puzzle.par * 3))
    moves = 0
    parse_warnings = 0

    for text in assistant:
        normalized = " ".join(text.lower().split())
        seen_messages[normalized] += 1
        if seen_messages[normalized] >= int(info.get("repeat_stop", 4)):
            repeated_messages += 1
            no_progress_stopped = True
            break

        legal_now = core.legal_pours(board, puzzle.depth, puzzle.stuck)
        if not legal_now:
            dead_end_called = dead_end_call(text)
            break

        move = last_pour(text)
        if move is None:
            if dead_end_call(text):
                dead_end_called = False
            if parse_warnings == 0:
                parse_warnings += 1
            else:
                moves += 1
            if moves >= cap:
                break
            continue
        parsed_turns += 1
        moves += 1
        if not core.legal(board, move[0], move[1], puzzle.depth, puzzle.stuck):
            illegal_moves += 1
            if first_reveal_move is not None:
                illegal_after_reveal += 1
            if moves >= cap:
                break
            continue

        old_visible = core.visible_from(board, mask)
        board, moved = core.apply_pour(board, move[0], move[1], puzzle.depth)
        mask = core.reveal_after_pour(mask, move[0], move[1], moved)
        new_visible = core.visible_from(board, mask)
        if new_visible != old_visible:
            reveals += 1
            if first_reveal_move is None:
                first_reveal_move = moves
        if core.is_solved(board, puzzle.depth) or moves >= cap:
            break

    solved = core.is_solved(board, puzzle.depth)
    dead_end = not solved and not core.legal_pours(board, puzzle.depth, puzzle.stuck)
    format_ok = parsed_turns == assistant_turns if assistant_turns else False
    components = core.reward_components(
        board,
        puzzle.depth,
        puzzle.par,
        solved,
        moves,
        format_ok,
        dead_end_called=dead_end and dead_end_called,
    )
    return core.ReplayResult(
        final_board=board,
        visible_board=core.visible_from(board, mask),
        solved=solved,
        dead_end=dead_end,
        moves=moves,
        parsed_turns=parsed_turns,
        assistant_turns=assistant_turns,
        illegal_moves=illegal_moves,
        repeated_messages=repeated_messages,
        no_progress_stopped=no_progress_stopped,
        dead_end_called=dead_end_called,
        reveals=reveals,
        moves_after_first_reveal=0 if first_reveal_move is None else max(0, moves - first_reveal_move),
        illegal_after_reveal=illegal_after_reveal,
        progress=core.progress_score(board, puzzle.depth),
        reward=sum(components.values()),
        components=components,
    )


def outcome_reward(completion, info, **kwargs) -> float:
    return replay(info, completion).reward


def format_reward(completion, info, **kwargs) -> float:
    return replay(info, completion).components["format"] / 0.2


def progress_metric(completion, info, **kwargs) -> float:
    return replay(info, completion).progress


def illegal_move_rate(completion, info, **kwargs) -> float:
    result = replay(info, completion)
    return result.illegal_moves / max(result.moves, 1)


def dead_end_metric(completion, info, **kwargs) -> float:
    return 1.0 if replay(info, completion).dead_end else 0.0


def dead_end_called_metric(completion, info, **kwargs) -> float:
    result = replay(info, completion)
    return 1.0 if result.dead_end and result.dead_end_called else 0.0


def reveal_count(completion, info, **kwargs) -> float:
    return float(replay(info, completion).reveals)


def moves_after_first_reveal(completion, info, **kwargs) -> float:
    return float(replay(info, completion).moves_after_first_reveal)


def illegal_after_reveal_rate(completion, info, **kwargs) -> float:
    result = replay(info, completion)
    denom = max(result.moves_after_first_reveal, 1)
    return result.illegal_after_reveal / denom


def no_progress_stop_metric(completion, info, **kwargs) -> float:
    return 1.0 if replay(info, completion).no_progress_stopped else 0.0


class MagicSortEnv(vf.MultiTurnEnv):
    def __init__(
        self,
        cap_multiple: int = 3,
        strict_format: bool = True,
        repeat_stop: int = 4,
        **kwargs,
    ):
        super().__init__(max_turns=200, **kwargs)
        self.cap_multiple = cap_multiple
        self.strict_format = strict_format
        self.repeat_stop = repeat_stop

    async def setup_state(self, state):
        info = state["info"]
        state["true_board"] = [list(bottle) for bottle in info["true_board"]]
        state["hidden_mask"] = [list(row) for row in info["hidden_mask"]]
        state["visible_board"] = core.visible_from(state["true_board"], state["hidden_mask"])
        state["moves"] = 0
        state["parse_warnings"] = 0
        state["last_messages"] = []
        state["cap"] = int(self.cap_multiple * info["par"])
        info["cap"] = state["cap"]
        info["repeat_stop"] = self.repeat_stop
        return state

    def _message(self, content: str):
        return [vf.UserMessage(content=content)]

    async def env_response(self, messages, state, **kwargs):
        text = str(messages[-1].get("content") or "") if messages else ""
        depth = int(state["info"]["depth"])
        stuck = tuple(state["info"]["stuck"])

        normalized = " ".join(text.lower().split())
        state["last_messages"].append(normalized)
        if len(state["last_messages"]) >= self.repeat_stop and len(set(state["last_messages"][-self.repeat_stop:])) == 1:
            state["final_env_response"] = self._message(
                f"stopped: repeated same response {self.repeat_stop} times\n"
                f"{core.render(state['visible_board'])}"
            )
            return state["final_env_response"]

        legal_now = core.legal_pours(state["true_board"], depth, stuck)
        if not legal_now:
            if dead_end_call(text):
                reply = "dead end confirmed: no legal moves remain"
            else:
                reply = "dead end: no legal moves remain"
            state["final_env_response"] = self._message(
                f"{reply}\n{core.render(state['visible_board'])}"
            )
            return state["final_env_response"]

        move = last_pour(text)
        if move is None:
            if self.strict_format and state["parse_warnings"] == 0:
                state["parse_warnings"] += 1
                return self._message(
                    "format warning: reply with exactly one command like `pour 3 1`. "
                    "No turn consumed.\n"
                    f"{core.render(state['visible_board'])}"
                )
            state["moves"] += 1
            reply = "No valid `pour O D` command found. Wasted a turn."
        else:
            origin, destination = move
            state["moves"] += 1
            if core.legal(state["true_board"], origin, destination, depth, stuck):
                old_visible = state["visible_board"]
                state["true_board"], moved = core.apply_pour(
                    state["true_board"], origin, destination, depth
                )
                state["hidden_mask"] = core.reveal_after_pour(
                    tuple(tuple(row) for row in state["hidden_mask"]),
                    origin,
                    destination,
                    moved,
                )
                state["visible_board"] = core.visible_from(
                    state["true_board"], state["hidden_mask"]
                )
                reveal_note = " reveal" if state["visible_board"] != old_visible else ""
                reply = f"ok{reveal_note}"
            else:
                reply = f"illegal: pour {origin} {destination} not allowed. Wasted a turn."

        board_text = core.render(state["visible_board"])
        if core.is_solved(state["true_board"], depth):
            state["final_env_response"] = self._message(f"solved\n{reply}\n{board_text}")
            return state["final_env_response"]
        if not core.legal_pours(state["true_board"], depth, stuck):
            state["final_env_response"] = self._message(f"dead end: no legal moves remain\n{reply}\n{board_text}")
            return state["final_env_response"]
        if state["moves"] >= state["cap"]:
            state["final_env_response"] = self._message(
                f"move cap ({state['cap']}) reached\n{reply}\n{board_text}"
            )
            return state["final_env_response"]
        return self._message(f"{reply}\n{board_text}")


def puzzle_row(puzzle: core.Puzzle) -> dict[str, Any]:
    visible = core.render(puzzle.visible_board)
    stuck_text = "none" if not puzzle.stuck else ", ".join(str(i) for i in puzzle.stuck)
    return {
        "prompt": [
            vf.SystemMessage(content=RULES.format(depth=puzzle.depth)).model_dump(),
            vf.UserMessage(
                content=(
                    f"Puzzle ({len(puzzle.true_board)} bottles, tier={puzzle.tier}, "
                    f"par={puzzle.par}, stuck={stuck_text}). Solve it.\n{visible}"
                )
            ).model_dump(),
        ],
        "answer": "",
        "info": {
            "true_board": [list(bottle) for bottle in puzzle.true_board],
            "visible_board": [list(bottle) for bottle in puzzle.visible_board],
            "hidden_mask": [list(row) for row in puzzle.hidden_mask],
            "stuck": list(puzzle.stuck),
            "depth": puzzle.depth,
            "par": puzzle.par,
            "tier": puzzle.tier,
            "seed": puzzle.seed,
        },
    }


def build_dataset(
    n: int,
    seed0: int,
    tier: str,
    use_stuck: bool | None,
    use_hidden: bool | None,
) -> Dataset:
    rows = []
    seed = seed0
    while len(rows) < n:
        rows.append(
            puzzle_row(
                core.generate(
                    tier=tier,
                    seed=seed,
                    use_stuck=use_stuck,
                    use_hidden=use_hidden,
                )
            )
        )
        seed += 1
    return Dataset.from_list(rows)


def load_environment(
    num_train_examples: int = 200,
    num_eval_examples: int = 40,
    tier: str = "easy",
    cap_multiple: int = 3,
    strict_format: bool = True,
    repeat_stop: int = 4,
    use_stuck: bool | None = None,
    use_hidden: bool | None = None,
    **kwargs,
) -> vf.Environment:
    train = build_dataset(num_train_examples, 0, tier, use_stuck, use_hidden)
    evald = build_dataset(num_eval_examples, 1_000_000, tier, use_stuck, use_hidden)

    rubric = vf.Rubric()
    rubric.add_reward_func(outcome_reward, weight=1.0)
    rubric.add_reward_func(format_reward, weight=0.0)
    rubric.add_metric(progress_metric)
    rubric.add_metric(illegal_move_rate)
    rubric.add_metric(dead_end_metric)
    rubric.add_metric(dead_end_called_metric)
    rubric.add_metric(reveal_count)
    rubric.add_metric(moves_after_first_reveal)
    rubric.add_metric(illegal_after_reveal_rate)
    rubric.add_metric(no_progress_stop_metric)

    return MagicSortEnv(
        dataset=train,
        eval_dataset=evald,
        rubric=rubric,
        cap_multiple=cap_multiple,
        strict_format=strict_format,
        repeat_stop=repeat_stop,
        message_type="chat",
    )
