from __future__ import annotations

import pytest

from ..native_parser import Argument, NArgsMode, NArgsSpec
from ..parser_collection import (
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

    pos, kw = p.parse_args(["--verbose", "--count", "3"], args, endpoint_path="ep")
    assert pos == []
    assert kw["verbose"] is True
    assert kw["count"] == 3

    # short combined bools: -v
    pos2, kw2 = p.parse_args(["-v", "--count=4"], args, endpoint_path="ep")
    assert pos2 == []
    assert kw2["verbose"] is True
    assert kw2["count"] == 4


def test_token_stream_parser_repeatable_collections() -> None:
    p = TokenStreamParser({"repeatable_collections": True})
    arg_tags = _arg("tags", list[str])
    args = [arg_tags]

    _, kw = p.parse_args(
        ["--tags=a,b", "--tags=c"], args, endpoint_path="ep"
    )
    assert kw["tags"] == ["a", "b", "c"]


def test_strict_dfa_parser_inline_assignment_and_bool() -> None:
    p = StrictDFAParser({})
    args = [
        _arg("flag", bool, default=False),
        _arg("value", int, required=True),
    ]

    # bool presence
    _, kw = p.parse_args(["--flag", "--value=3"], args, endpoint_path="ep")
    assert kw["flag"] is True
    assert kw["value"] == 3


def test_fast_parser_basic() -> None:
    p = FastParser({"FAST_ALLOW_POSITIONALS": True})
    args = [
        _arg("value", int, required=True),
        _arg("flag", bool, default=False),
    ]

    _, kw = p.parse_args(
        ["10", "--flag"], args, endpoint_path="ep"
    )
    assert kw["value"] == 10
    assert kw["flag"] is True


def test_tiny_parser_defaults_and_required() -> None:
    p = TinyParser({})
    args = [
        _arg("value", int, required=True),
        _arg("opt", int, default=5),
    ]

    _, kw = p.parse_args(["10"], args, endpoint_path="ep")
    assert kw["value"] == 10
    assert kw["opt"] == 5

