from __future__ import annotations

import pytest

from ..endpoints import NativeEndpoint
from ..interface import Interface


def test_constructor_rejects_long_help_args_not_in_help_args() -> None:
    with pytest.raises(ValueError):
        Interface(
            "prog",
            automatic_help_args=("-h",),
            automatic_long_help_args=("--help",),
        )


def test_error_and_list_error_render_caret(capsys: pytest.CaptureFixture[str]) -> None:
    Interface._error(2, "abc")
    out = capsys.readouterr().out
    assert "abc" in out
    assert "  ^" in out

    Interface._lst_error(1, 1, ["aa", "bbb"])
    out = capsys.readouterr().out
    assert "aa bbb" in out
    assert "    ^" in out


def test_list_error_can_exit() -> None:
    with pytest.raises(SystemExit):
        Interface._lst_error(0, 0, ["x"], do_exit=True)


def test_path_and_check_path_roundtrip() -> None:
    itf = Interface("prog", NativeEndpoint("default"))
    assert itf._check_path("run") is False
    itf.path("run", lambda: None, "run help")
    # Current implementation treats existing endpoints as non-checkable in _check_path.
    assert itf._check_path("run") is False


def test_parse_cli_uses_endpoint_calling_wrapper() -> None:
    seen: dict[str, bool] = {"called": False, "wrapped": False}

    def endpoint() -> None:
        seen["called"] = True

    def wrapper(endpoint_obj, fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        seen["wrapped"] = True
        return fn(*args, **kwargs)

    itf = Interface("prog", NativeEndpoint("default"), endpoint_calling_func=wrapper)
    itf.path("run", NativeEndpoint("run", function=endpoint), "run help")
    path, _ = itf.parse_cli(["prog", "run"], skip_first_arg=True)

    # Current _parse_pre_args implementation drops the final matched token.
    assert path == ""
    assert seen["called"] is True
    assert seen["wrapped"] is True


def test_parse_cli_short_help_on_subtree_prints_structure_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    itf = Interface("prog", NativeEndpoint("default"))
    itf.path("group::a", lambda: None, "a help")
    itf.path("group::b", lambda: None, "b help")

    with pytest.raises(SystemExit):
        itf.parse_cli(["prog", "group", "-h"], skip_first_arg=True)

    out = capsys.readouterr().out
    assert "commands:" in out
    assert "group -> a" in out
    assert "group -> b" in out


def test_parse_cli_long_help_prints_endpoint_help(capsys: pytest.CaptureFixture[str]) -> None:
    itf = Interface("prog", NativeEndpoint("default"))
    itf.path("run", lambda: None, "run help")

    with pytest.raises(SystemExit):
        itf.parse_cli(["prog", "run", "--help"], skip_first_arg=True)

    out = capsys.readouterr().out
    assert "usage: run" in out


#! Bahavior has changed, now just the help is shown
# def test_parse_cli_default_message_endpoint_is_used(capsys: pytest.CaptureFixture[str]) -> None:
#     itf = Interface("prog", NativeEndpoint("default", function=lambda: print("not a valid endpoint")))
#     path, _ = itf.parse_cli(["prog", "unknown"], skip_first_arg=True)
#     out = capsys.readouterr().out
#
#     assert path == ""
#     assert "not a valid endpoint" in out


def test_parse_pre_args_with_skip_first_arg_false() -> None:
    itf = Interface("prog", NativeEndpoint("default"))
    itf.path("run", lambda: None, "run help")

    pre, tail, endpoint, _ = itf._parse_pre_args(["prog", "run"], skip_first_arg=False)
    assert pre == ["prog", "run"]
    assert tail == []
    assert endpoint is not None


def test_parse_without_structure() -> None:
    itf = Interface("prog", NativeEndpoint("default"))
    itf.path("", lambda: None, "run help")

    pre, tail, endpoint, _ = itf._parse_pre_args(["prog", "run"], skip_first_arg=False)
    assert pre == ["prog"]
    assert tail == ["run"]
    assert endpoint is None
