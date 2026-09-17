import asyncio

import verifiers.legacy as vf
from datasets import Dataset

from magic_sort_env import core
from magic_sort_env.env import MagicSortEnv, replay


DEAD_END_INITIAL = [
    ["C", "C", "D", "B"],
    ["D", "B", "D", "A"],
    ["B", "C", "A", "B"],
    ["A", "D", "C", "A"],
    [],
]

DEAD_END_MOVES = [
    "pour 0 4",
    "pour 2 4",
    "pour 0 1",
    "pour 1 2",
    "pour 0 1",
    "no legal moves",
]


def _info():
    par, exact = core.solve_par(DEAD_END_INITIAL, depth=4)
    assert exact
    assert par is not None
    mask = [[False] * len(bottle) for bottle in DEAD_END_INITIAL]
    return {
        "true_board": DEAD_END_INITIAL,
        "visible_board": DEAD_END_INITIAL,
        "hidden_mask": mask,
        "stuck": [],
        "depth": 4,
        "par": par,
        "tier": "easy",
        "seed": 123,
        "cap": 3 * par,
        "repeat_stop": 4,
    }


def test_replay_recognizes_dead_end_call_and_scores_progress():
    completion = [
        {"role": "assistant", "content": text}
        for text in DEAD_END_MOVES
    ]

    result = replay(_info(), completion)

    assert result.dead_end
    assert result.dead_end_called
    assert result.reward > 0
    assert result.moves < _info()["cap"]


def test_replay_stops_repeated_no_progress_loop():
    completion = [{"role": "assistant", "content": "thinking..."} for _ in range(5)]

    result = replay(_info(), completion)

    assert result.no_progress_stopped
    assert result.repeated_messages == 1


def test_env_response_returns_typed_user_messages_on_dead_end():
    env = MagicSortEnv(dataset=Dataset.from_list([{"prompt": [], "answer": "", "info": _info()}]))
    state = {
        "info": _info(),
        "true_board": [
            ["C", "C"],
            ["D", "B", "D", "D"],
            ["B", "C", "A", "A"],
            ["A", "D", "C", "A"],
            ["B", "B"],
        ],
        "hidden_mask": [[False, False], [False] * 4, [False] * 4, [False] * 4, [False, False]],
        "visible_board": (
            ("C", "C"),
            ("D", "B", "D", "D"),
            ("B", "C", "A", "A"),
            ("A", "D", "C", "A"),
            ("B", "B"),
        ),
        "moves": 6,
        "cap": 39,
        "parse_warnings": 0,
        "last_messages": [],
    }

    messages = asyncio.run(
        env.env_response([vf.AssistantMessage(content="no legal moves")], state)
    )

    assert isinstance(messages[0], vf.UserMessage)
    assert "dead end confirmed" in messages[0].content
    assert state["final_env_response"] == messages
