from __future__ import annotations

from ..str_guess import guess_letters, guess_prefix_shortforms, guess_shortforms


def test_guess_prefix_shortforms_unique_and_min_len() -> None:
    args = ["output", "option", "optimize"]
    res = guess_prefix_shortforms(args, min_len=2)
    # Every key present, shortforms non-empty and unique
    assert set(res.keys()) == set(args)
    assert len(set(res.values())) == len(args)
    assert all(len(v) >= 2 for v in res.values() if v)


def test_guess_letters_assigns_unique_letters() -> None:
    args = ["verbose", "version", "value"]
    res = guess_letters(args)
    assert set(res.keys()) == set(args)
    # letters must be single-character or empty, and overall unique where non-empty
    letters = [v for v in res.values() if v]
    assert all(len(v) == 1 for v in letters)
    assert len(set(letters)) == len(letters)


def test_guess_shortforms_token_aware_and_collision_resolving() -> None:
    args = ["output-file", "output-format", "out"]
    res = guess_shortforms(args, soft_min=3, soft_max=4)

    # Should all be different and at least soft_min in length
    assert set(res.keys()) == set(args)
    assert len(set(res.values())) == len(args)
    assert all(len(v) >= 3 for v in res.values())

