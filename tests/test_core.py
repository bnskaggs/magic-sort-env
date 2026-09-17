import random

from magic_sort_env import core


def test_pour_moves_top_contiguous_run():
    board = (("A", "B", "B"), (), ())

    assert core.legal(board, 0, 1, depth=4)
    nxt, moved = core.apply_pour(board, 0, 1, depth=4)

    assert moved == 2
    assert nxt == (("A",), ("B", "B"), ())


def test_pour_legality_checks_capacity_match_empty_and_stuck():
    board = (("A", "B"), ("C",), ("B", "B", "B", "B"), ())

    assert not core.legal(board, 0, 1, depth=4)
    assert not core.legal(board, 0, 2, depth=4)
    assert core.legal(board, 0, 3, depth=4)
    assert not core.legal(board, 0, 3, depth=4, stuck=(0,))


def test_illegal_reason_names_legality_failure():
    board = (("A", "B"), ("C",), ("B", "B", "B", "B"), ())

    assert core.illegal_reason(board, 0, 0, depth=4) == "origin and destination are the same bottle"
    assert core.illegal_reason(board, -1, 0, depth=4) == "bottle index is negative"
    assert core.illegal_reason(board, 9, 0, depth=4) == "source bottle 9 does not exist"
    assert core.illegal_reason(board, 0, 9, depth=4) == "destination bottle 9 does not exist"
    assert core.illegal_reason(board, 0, 3, depth=4, stuck=(0,)) == "source bottle 0 is stuck"
    assert core.illegal_reason(((), ("A",)), 0, 1, depth=4) == "source bottle 0 is empty"
    assert core.illegal_reason(board, 0, 2, depth=4) == "destination bottle 2 is full"
    assert core.illegal_reason(board, 0, 1, depth=4) == "destination top C does not match source top B"
    assert core.illegal_reason(board, 0, 3, depth=4) is None


def test_generator_returns_solvable_exact_par_and_is_seeded():
    p1 = core.generate(tier="easy", seed=7)
    p2 = core.generate(tier="easy", seed=7)

    assert p1.true_board == p2.true_board
    path, exact = core.solve_path(p1.true_board, p1.depth, p1.stuck)
    assert exact
    assert path is not None
    assert len(path) == p1.par
    assert p1.par > 0


def test_train_and_eval_seed_ranges_are_disjoint_by_construction():
    train = {core.generate(tier="trivial", seed=i).true_board for i in range(5)}
    evald = {core.generate(tier="trivial", seed=1_000_000 + i).true_board for i in range(5)}

    assert train.isdisjoint(evald)


def test_reward_decomposition_and_consolation_below_solve():
    puzzle = core.generate(tier="easy", seed=1)
    solved = core.rollout_policy(puzzle, "optimal")
    failed_board = puzzle.true_board

    solved_components = core.reward_components(
        solved.final_board,
        puzzle.depth,
        puzzle.par,
        solved=True,
        moves=puzzle.par,
        format_ok=True,
    )
    failed_components = core.reward_components(
        failed_board,
        puzzle.depth,
        puzzle.par,
        solved=False,
        moves=0,
        format_ok=True,
    )

    assert solved_components == {
        "solve": 1.0,
        "efficiency": 1.0,
        "consolation": 0.0,
        "dead_end": 0.0,
        "format": 0.2,
    }
    assert failed_components["consolation"] < 1.0
    assert core.reward(failed_board, puzzle.depth, puzzle.par, False, 0, True) < 1.0


def test_progress_credit_spreads_failed_positions():
    disordered = (("A", "B", "C", "D"), ("A", "B", "C", "D"), (), ())
    clustered = (("A", "A", "A", "D"), ("B", "B", "C", "D"), (), ())

    assert core.progress_score(clustered, depth=4) > core.progress_score(disordered, depth=4)


def test_hidden_layers_are_bottom_contiguous_and_visible_top_is_never_hidden():
    rng = random.Random(4)
    board = (("A", "B", "C", "D"), ("A", "A", "B", "C"), (), ())
    mask = core.make_hidden_mask(board, count=1, rng=rng)

    assert mask is not None
    for bottle, row in zip(board, mask):
        if row:
            assert row[-1] is False
            # Once a visible layer appears, every layer above it is visible.
            seen_visible = False
            for hidden in row:
                if not hidden:
                    seen_visible = True
                if seen_visible:
                    assert not hidden


def test_stuck_generation_never_uses_stuck_as_solution_source():
    puzzle = next(
        p
        for p in (
            core.generate(
                tier="medium",
                seed=i,
                use_stuck=True,
                use_hidden=False,
                stuck_count=1,
            )
            for i in range(50)
        )
        if p.stuck
    )
    path, exact = core.solve_path(puzzle.true_board, puzzle.depth, puzzle.stuck)

    assert exact
    assert path is not None
    assert puzzle.stuck
    assert not any(origin in puzzle.stuck for origin, _ in path)

def test_reveal_counting_ignores_ordinary_board_changes():
    """A pour changes the board; that is not a reveal.

    The first implementation compared rendered boards before and after a pour,
    so it counted every successful pour as a reveal - including on tiers with no
    hidden cells at all.
    """
    board = (("A", "B", "B"), (), ())
    no_fog = ((False, False, False), (), ())

    before = core.hidden_cell_count(no_fog)
    _, moved = core.apply_pour(board, 0, 1, depth=4)
    after_mask = core.reveal_after_pour(no_fog, 0, 1, moved)

    assert before == 0
    assert core.hidden_cell_count(after_mask) == 0

    fogged = ((True, True, False), (), ())
    _, moved2 = core.apply_pour((("A", "B", "B"), (), ()), 0, 1, depth=4)
    revealed_mask = core.reveal_after_pour(fogged, 0, 1, moved2)
    assert core.hidden_cell_count(revealed_mask) < core.hidden_cell_count(fogged)


def test_micro_tier_is_playable_by_a_random_policy():
    """micro exists so small models can finish puzzles.

    The trainability signal is that even a random policy solves most seeds:
    if random can't finish, a looping 3B-7B model certainly can't, and zero
    solves means zero reward variance and zero gradient.
    """
    solved = 0
    for seed in range(20):
        puzzle = core.generate(tier="micro", seed=seed)
        assert not puzzle.stuck
        assert core.hidden_cell_count(puzzle.hidden_mask) == 0
        assert 2 <= puzzle.par <= 8
        if core.rollout_policy(puzzle, "random").solved:
            solved += 1
    assert solved >= 12


def test_known_dead_end_position_has_no_legal_pours():
    board = (
        ("C", "C"),
        ("D", "B", "D", "D"),
        ("B", "C", "A", "A"),
        ("A", "D", "C", "A"),
        ("B", "B"),
    )

    assert core.legal_pours(board, depth=4) == []
