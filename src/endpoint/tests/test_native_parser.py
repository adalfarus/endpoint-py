from __future__ import annotations

import pytest

from ..native_parser import (
    Argument,
    ArgumentParsingError,
    NativeBoolParserFragment,
    NativeBytesParserFragment,
    NativeComplexParserFragment,
    NativeDictParserFragment,
    NativeFloatingPointNumberParserFragment as NativeFloatParserFragment,
    NativeIntegerParserFragment,
    NativeIterableParserFragment,
    NativeListParserFragment,
    NativeParser,
    NativeSetParserFragment,
    NativeStringParserFragment,
    NativeTupleParserFragment,
    NArgsMode,
    NArgsSpec,
    TokenStream,
)
from ..functional import BrokenType, NoDefault


def _arg_for(
    name: str,
    type_: type,
    *,
    default=NoDefault(),
    required: bool = False,
    positional_only: bool = False,
    kwarg_only: bool = False,
) -> Argument:
    broken = BrokenType(base_type=type_, arguments=())
    nargs = NArgsMode.MIN_MAX(1, 1, NArgsSpec.NUMBER(1))
    return Argument(
        name=name,
        alternative_names=[],
        letter=None,
        type=type_,
        broken_type=broken,
        default=default,
        choices=[],
        required=required,
        positional_only=positional_only,
        kwarg_only=kwarg_only,
        help="",
        metavar=name,
        nargs=nargs,
        checking_func=None,
    )


def test_token_stream_basic_operations() -> None:
    ts = TokenStream("abc")
    assert ts.consume() == "a"
    assert ts.get_index() == 1
    ts.reverse()
    assert ts.get_index() == 0
    copy = ts.copy()
    assert copy.get_index() == ts.get_index()


def test_native_string_parser_fragment_parses_simple_and_quoted() -> None:
    frag = NativeStringParserFragment()
    assert frag.parse(["hello"], False) == "hello"
    assert frag.parse(["'world'"], False) == "world"


def test_native_integer_parser_fragment_parses_and_errors() -> None:
    frag = NativeIntegerParserFragment()
    assert frag.parse(["10"], False) == 10
    err = frag.parse(["10", "11"], False)
    assert isinstance(err, ArgumentParsingError)


def test_native_float_parser_fragment_parses_and_errors() -> None:
    frag = NativeFloatParserFragment()
    assert frag.parse(["1.5"], False) == 1.5
    err = frag.parse(["1.5", "x"], False)
    assert isinstance(err, ArgumentParsingError)


def test_native_iterable_parser_fragment_parses_csv_list() -> None:
    frag = NativeIterableParserFragment()
    out = frag.parse(["a,b,c"], False)
    assert out == ["a", "b", "c"]


def test_native_dict_parser_fragment_parses_simple_mapping() -> None:
    frag = NativeDictParserFragment()
    out = frag.parse(["a:b,b:c"], False)
    assert out == {"a": "b", "b": "c"}


def test_native_set_parser_fragment_parses_set_like_input() -> None:
    frag = NativeSetParserFragment()
    out = frag.parse(["a,b"], False)
    assert out == {"a", "b"}


def test_native_tuple_parser_fragment_parses_tuple_like_input() -> None:
    frag = NativeTupleParserFragment()
    out = frag.parse(["a,b"], False)
    assert out == ("a", "b")


def test_native_complex_parser_fragment_parses_complex() -> None:
    frag = NativeComplexParserFragment()
    assert frag.parse(["1+2j"], False) == complex("1+2j")


def test_native_bytes_parser_fragment_parses_bytes() -> None:
    frag = NativeBytesParserFragment()
    out = frag.parse(["hello"], False)
    assert isinstance(out, bytes)
    assert out == b"hello"


def test_native_bool_parser_fragment_toggle_and_simple() -> None:
    frag_default = NativeBoolParserFragment(toggle_value=False)
    assert frag_default.parse([], False) is True
    frag_toggle = NativeBoolParserFragment(toggle_value=True)
    assert frag_toggle.parse(["x"], False) is True


def test_native_parser_basic_end_to_end_positional_and_kwarg() -> None:
    parser = NativeParser({})
    args = [
        _arg_for("a", int, required=True, positional_only=True),
        _arg_for("b", int, required=True),
    ]

    pos, kw = parser.parse_args(["1", "--b", "2"], args, endpoint_path="ep")
    # a is positional-only, b is kwarg
    assert "a" in kw and "b" in kw
    assert kw["a"] == 1
    assert kw["b"] == 2

