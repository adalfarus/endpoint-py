from __future__ import annotations

from typing import Literal, Optional

import pytest

from ..native_parser import Argument, NArgsMode, NArgsSpec
from ..parser_collection import (
    ArgparseParser,
    ArgumentParsingError,
    FastParser,
    LightParser,
    StrictDFAParser,
    TinyParser,
    TokenStreamParser,
)
from ..functional import BrokenType, NoDefault


def _arg(name: str, type_: type, *, default=NoDefault(), required: bool = False) -> Argument:
    nargs = NArgsMode.MIN_MAX(1, 1, NArgsSpec.NUMBER(1))
    return Argument(
        name=name,
        alternative_names=[],
        letter=name[0],
        type=type_,
        broken_type=BrokenType(base_type=type_, arguments=()),
        default=default,
        choices=[],
        required=required,
        positional_only=False,
        kwarg_only=False,
        help="",
        metavar=name,
        nargs=nargs,
        checking_func=None,
    )


def test_light_parser_parses_long_and_short_flags() -> None:
    p = LightParser({})
    args = [
        _arg("verbose", bool, default=False),
        _arg("count", int, required=True),
    ]

    pos, kw = p.parse_args(["--verbose", "--count", "3"], args, endpoint_path="ep", endpoint_help_func=lambda: "")
    assert pos == []
    assert kw["verbose"] is True
    assert kw["count"] == 3

    # short combined bools: -v
    pos2, kw2 = p.parse_args(["-v", "--count=4"], args, endpoint_path="ep", endpoint_help_func=lambda: "")
    assert pos2 == []
    assert kw2["verbose"] is True
    assert kw2["count"] == 4


def test_token_stream_parser_repeatable_collections() -> None:
    p = TokenStreamParser({"repeatable_collections": True})
    arg_tags = _arg("tags", list[str])
    args = [arg_tags]

    _, kw = p.parse_args(
        ["--tags=a,b", "--tags=c"], args, endpoint_path="ep", endpoint_help_func=lambda: ""
    )
    assert kw["tags"] == ["a", "b", "c"]


def test_strict_dfa_parser_inline_assignment_and_bool() -> None:
    p = StrictDFAParser({})
    args = [
        _arg("flag", bool, default=False),
        _arg("value", int, required=True),
    ]

    # bool presence
    _, kw = p.parse_args(["--flag", "--value=3"], args, endpoint_path="ep", endpoint_help_func=lambda: "")
    assert kw["flag"] is True
    assert kw["value"] == 3


def test_fast_parser_basic() -> None:
    p = FastParser({"FAST_ALLOW_POSITIONALS": True})
    args = [
        _arg("value", int, required=True),
        _arg("flag", bool, default=False),
    ]

    _, kw = p.parse_args(
        ["10", "--flag"], args, endpoint_path="ep", endpoint_help_func=lambda: ""
    )
    assert kw["value"] == 10
    assert kw["flag"] is True


def test_tiny_parser_defaults_and_required() -> None:
    p = TinyParser({})
    args = [
        _arg("value", int, required=True),
        _arg("opt", int, default=5),
    ]

    _, kw = p.parse_args(["10"], args, endpoint_path="ep", endpoint_help_func=lambda: "")
    assert kw["value"] == 10
    assert kw["opt"] == 5


def test_argument_parsing_error_str_and_parser_flag_introspection() -> None:
    err = ArgumentParsingError("boom", idx=2, endpoint_path="ep.path")
    assert "boom" in str(err)
    assert "(idx=2)" in str(err)
    assert "[ep.path]" in str(err)

    assert "smart_typing" in LightParser({}).list_known_flags()
    assert "repeatable_collections" in TokenStreamParser({}).list_known_flags()
    assert "DFA_ASSIGN_TOKENS" in StrictDFAParser({}).list_known_flags()
    assert "FAST_ASSIGN_CHAR" in FastParser({}).list_known_flags()
    assert TinyParser({}).list_known_flags() == {}


def test_explain_flag_methods_and_explain_flags_methods() -> None:
    LightParser({}).explain_flag("smart_typing")
    TokenStreamParser({}).explain_flag("repeatable_collections")
    StrictDFAParser({}).explain_flag("DFA_ASSIGN_TOKENS")
    FastParser({}).explain_flag("FAST_ASSIGN_CHAR")
    with pytest.raises(ValueError):
        TinyParser({}).explain_flag("x")


def test_type1_coerce_from_type_literal_union_and_tuple_arity() -> None:
    p = LightParser({})
    mode = _arg("mode", str)
    mode.type = Literal["fast", "slow"]  # type: ignore[assignment]
    assert p._coerce_from_type("fast", mode) == "fast"
    # Current implementation falls back to `type(c)(value)` and accepts arbitrary strings.
    assert p._coerce_from_type("bad", mode) == "bad"

    maybe = _arg("maybe", str)
    maybe.type = Optional[int]  # type: ignore[assignment]
    assert p._coerce_from_type("3", maybe) == 3
    assert p._coerce_from_type("none", maybe) is None

    pair = _arg("pair", str)
    pair.type = tuple[int, str]  # type: ignore[assignment]
    assert p._coerce_from_type("1,a", pair) == (1, "a")
    with pytest.raises(ArgumentParsingError):
        p._coerce_from_type("1", pair)


def test_token_stream_parser_end_of_options_and_missing_value_error() -> None:
    p = TokenStreamParser({"interleaved_positionals": False})
    args = [_arg("value", int, required=True)]

    _, kw = p.parse_args(["--", "7"], args, endpoint_path="ep", endpoint_help_func=lambda: "")
    assert kw["value"] == 7

    with pytest.raises(ArgumentParsingError):
        p.parse_args(["--value"], args, endpoint_path="ep", endpoint_help_func=lambda: "")


def test_argparse_parser_filters_disabled_flags_and_rejects_extra() -> None:
    p = ArgparseParser({"allow_abbrev": False, "--value": False})
    args = [_arg("value", int, required=True)]

    with pytest.raises(ArgumentParsingError):
        p.parse_args(["junk"], args, endpoint_path="ep", endpoint_help_func=lambda: "")


def test_strict_dfa_parser_errors_and_short_inline_assignment() -> None:
    p = StrictDFAParser({})
    args = [
        _arg("flag", bool, default=False),
        _arg("value", int, required=True),
    ]

    _, kw = p.parse_args(["-v=3", "--flag"], args, endpoint_path="ep", endpoint_help_func=lambda: "")
    assert kw["value"] == 3
    assert kw["flag"] is True

    with pytest.raises(ArgumentParsingError):
        p.parse_args(["10", "--flag"], args, endpoint_path="ep", endpoint_help_func=lambda: "")


def test_fast_and_tiny_error_paths() -> None:
    with pytest.raises(ValueError):
        FastParser({"FAST_ASSIGN_CHAR": "::"})

    fp = FastParser({"FAST_ALLOW_POSITIONALS": False})
    with pytest.raises(ArgumentParsingError):
        fp.parse_args(["10"], [_arg("value", int, required=True)], endpoint_path="ep", endpoint_help_func=lambda: "")

    tp = TinyParser({})
    _, kw = tp.parse_args([], [_arg("value", int, required=True)], endpoint_path="ep", endpoint_help_func=lambda: "")
    assert "value" in kw
