from __future__ import annotations

import pytest

from ..native_parser import (
    Argument,
    ArgumentParsingError,
    NativeIterableParserFragment,
    NativeParserFragment,
    NativeUnionParserFragment,
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
    ParsingErrorSeverity,
    TokenStream,
    ValueParsingError,
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

    pos, kw = parser.parse_args(["1", "--b", "2"], args, endpoint_path="ep", endpoint_help_func=lambda: "")
    # a is positional-only, b is kwarg
    assert "a" in kw and "b" in kw
    assert kw["a"] == 1
    assert kw["b"] == 2


def test_native_parser_deterministic_mode_simple() -> None:
    """When ALLOW_NON_DETERMINISTIC_BEHAVIOUR is False, use the deterministic branch."""
    parser = NativeParser({"ALLOW_NON_DETERMINISTIC_BEHAVIOUR": False})
    args = [_arg_for("x", int, required=True)]

    pos, kw = parser.parse_args(["1"], args, endpoint_path="ep", endpoint_help_func=lambda: "")
    assert pos == []
    assert kw["x"] == 1


def test_native_parser_deterministic_mode_too_many_positional_raises() -> None:
    parser = NativeParser({"ALLOW_NON_DETERMINISTIC_BEHAVIOUR": False})
    args = [_arg_for("x", int, required=True)]

    with pytest.raises(ValueError) as excinfo:
        parser.parse_args(["1", "2"], args, endpoint_path="ep", endpoint_help_func=lambda: "")

    # Aggregated error message should mention too many positional arguments
    assert "too many positional arguments" in str(excinfo.value)


def test_native_parser_str_parse_python_types_flag_controls_quoting() -> None:
    arg = _arg_for("s", str, required=True)

    parser_default = NativeParser({})
    _, kw_default = parser_default.parse_args(["'hi'"], [arg], endpoint_path="ep", endpoint_help_func=lambda: "")
    # With default STR_PARSE_PYTHON_TYPES=True, outer quotes are stripped
    assert kw_default["s"] == "hi"

    parser_no_py = NativeParser({"STR_PARSE_PYTHON_TYPES": False})
    _, kw_no_py = parser_no_py.parse_args(["'hi'"], [arg], endpoint_path="ep", endpoint_help_func=lambda: "")
    # When disabled, quotes are preserved
    assert kw_no_py["s"] == "'hi'"


def test_native_parser_bool_toggle_value_flag() -> None:
    """BOOL_TOGGLE_VALUE makes repeated bool flags toggle the value."""
    parser = NativeParser({"BOOL_TOGGLE_VALUE": True})
    args = [_arg_for("flag", bool, default=False)]

    args[0].nargs = NArgsMode.MIN_MAX(1, None, NArgsSpec.NUMBER(1))

    # Two occurrences => toggled back to False
    _, kw = parser.parse_args(["--flag", "--flag"], args, endpoint_path="ep", endpoint_help_func=lambda: "")
    assert kw["flag"] is False


def test_native_parser_allows_unknown_kwargs_when_flag_disabled() -> None:
    parser = NativeParser({"ERROR_IF_TOO_MANY_KWARGS": False})
    args = [_arg_for("known", int, required=False)]

    pos, kw = parser.parse_args(["--unknown=5"], args, endpoint_path="ep", endpoint_help_func=lambda: "")
    assert pos == []
    # Unknown kwarg should be preserved when ERROR_IF_TOO_MANY_KWARGS is False
    assert kw["unknown"] == ["5"]


def test_nargs_min_max_helpers_and_validation() -> None:
    with pytest.raises(ValueError):
        NArgsMode.MIN_MAX(-1, 1)

    mm = NArgsMode.MIN_MAX(1, None)
    assert mm.is_lower_max(999) is True
    assert mm.is_higher_min(2) is True


def test_argument_rendering_helpers_cover_readable_methods() -> None:
    arg = _arg_for("value", int, default=3, required=True, positional_only=False)
    arg.alternative_names = ["val"]
    arg.letter = "v"
    arg.help = "value help"
    arg.choices = [1, 2, 3]

    assert "-v" in arg.option_names()
    assert "--value" in arg.option_names()
    assert "required" in arg.right_column(split_positionals=False)
    assert "required" in arg.right_column(split_positionals=True)
    assert "default: 3" in arg.right_column(split_positionals=False)
    assert "default: 3" in arg.right_column(split_positionals=True)
    assert "Argument(value)" == arg.as_readable()
    assert isinstance(hash(arg), int)
    assert "value" in arg.usage_fragment()
    assert "--value" in arg.left_column(split_positionals=False)
    assert "--value" in arg.left_column(split_positionals=True)


def test_argument_and_value_parsing_error_helpers() -> None:
    stream = TokenStream("abc")
    stream.consume()

    err = ArgumentParsingError("boom", ParsingErrorSeverity.REACHED_INVALID_STATE, stream)
    with pytest.raises(ArgumentParsingError):
        err.raise_()
    assert ">" in err.show()
    assert "boom" in str(err)

    verr = ValueParsingError("vboom", None)
    assert "vboom" in str(verr)
    assert "vboom" in repr(verr)


def test_token_stream_additional_helpers() -> None:
    ts = TokenStream("abcd")
    ts.set_index(2)
    assert ts.consume_remaining() == "cd"
    ts.restart()
    assert ts.get_index() == 0
    assert "TokenStream" in str(ts)


def test_native_parser_fragment_base_iter_set_errors() -> None:
    frag = NativeParserFragment()
    with pytest.raises(ValueError):
        list(frag.iter("x", BrokenType(base_type=str, arguments=())))
    with pytest.raises(ValueError):
        frag.set("x", [(0, "y")])


def test_native_union_and_iterable_fragment_edge_paths() -> None:
    ufrag = NativeUnionParserFragment()
    assert ufrag.parse(["a"], False) == ["a"]
    rows = list(ufrag.iter("raw", BrokenType(base_type=None, arguments=())))
    assert rows[0][1] == "raw"

    ifrag = NativeIterableParserFragment(parse_python_types=False, error_if_unsure=True)
    err = ifrag.parse(["single"], False)
    assert isinstance(err, ArgumentParsingError)


def test_native_parser_list_known_flags_and_explain_flags() -> None:
    parser = NativeParser({})
    flags = parser.list_known_flags()
    assert "ERROR_IF_TOO_MANY_KWARGS" in flags
    assert "STR_DELIMITERS" in flags
    parser.explain_flag("STR_DELIMITERS")
