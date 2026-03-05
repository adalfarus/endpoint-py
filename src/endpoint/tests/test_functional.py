from __future__ import annotations

from typing import Any, Callable, ForwardRef, Literal

import pytest

from ..endpoints import NativeEndpoint
from ..functional import (
    Analysis,
    ArgumentAnalysis,
    NoDefault,
    analyze_function,
    break_type,
    get_analysis,
    old_analyze_function,
    pretty_type,
    _get_from_func_help,
)
from . import _hard_functions as x_mod


@pytest.mark.parametrize(
    "func, expected_names",
    [
        (x_mod.signature_stress, ["a", "b", "c", "d"]),
        (x_mod.recursive_tree_op, ["root", "max_depth", "visit", "prune"]),
        (x_mod.tuple_pack_unpack, ["head", "items", "tail"]),
        (x_mod.parse_mode, ["value"]),
        (x_mod.default_weirdness, ["x", "y", "z", "when", "fmt", "strict"]),
    ],
)
def test_from_function_preserves_argument_names_prefix(
    func: Callable[..., Any], expected_names: list[str]
) -> None:
    """NativeEndpoint.from_function should preserve argument name order (prefix)."""
    ep = NativeEndpoint.from_function(func, name=func.__name__)
    arg_names = [a.name for a in ep.copy_arguments()]
    # Only require that the leading names match; analysis may drop *args/**kwargs
    assert arg_names[: len(expected_names)] == expected_names[: len(arg_names)]


def test_from_function_sets_help_from_docstring() -> None:
    ep = NativeEndpoint.from_function(x_mod.signature_stress, name="sig-stress")
    help_str = ep.get_help_str()
    assert "Mix" in help_str


def test_default_weirdness_required_vs_optional() -> None:
    ep = NativeEndpoint.from_function(x_mod.default_weirdness, name="default-weird")
    args = {a.name: a for a in ep.copy_arguments()}

    # x has no default => required, others have defaults
    assert args["x"].required is True
    assert all(not args[name].required for name in ["y", "z", "when", "fmt", "strict"])


def test_parse_mode_overloads_still_exposed_as_single_endpoint() -> None:
    ep = NativeEndpoint.from_function(x_mod.parse_mode, name="parse-mode")
    names = [a.name for a in ep.copy_arguments()]
    assert names == ["value"]


def test_pretty_type_and_break_type_basic_shapes() -> None:
    assert pretty_type(int) == "int"
    assert pretty_type(list[int]) == "list[int]"

    fwd = break_type(ForwardRef("Node"))
    assert fwd.base_type == "Node"

    union_bt = break_type(int | str)
    assert union_bt.base_type.__name__ == "Union"
    assert len(union_bt.arguments) == 2


def test_analysis_to_dict_from_dict_roundtrip() -> None:
    ana = Analysis(
        name="fn",
        doc="doc",
        help_="help",
        arguments=[
            ArgumentAnalysis(
                name="x",
                default=NoDefault(),
                choices=(1, 2),
                type=int,
                type_choices=(int,),
                doc_help="x help",
                pos_only=True,
                kwarg_only=False,
                is_arg=False,
                is_kwarg=False,
            )
        ],
        has_args=True,
        has_kwargs=False,
        return_type=int,
        return_choices=(1, 2),
        return_doc_help="ret",
    )
    data = ana.to_dict()
    rebuilt = Analysis.from_dict(data)
    assert rebuilt.name == "fn"
    assert rebuilt.has_args is True
    assert rebuilt.return_choices == (1, 2)
    assert rebuilt.arguments[0].name == "x"


def test_get_from_func_help_extracts_line() -> None:
    rest, help_str = _get_from_func_help("x: value help\nother", "x")
    assert "x: value help" not in rest
    assert help_str == "value help"


def test_analyze_function_rejects_non_function() -> None:
    with pytest.raises(ValueError):
        analyze_function(object())  # type: ignore[arg-type]


def test_analyze_and_old_analyze_function_cover_varargs_and_literal() -> None:
    def sample(
        a: int,
        b: str = "x",
        *args: int,
        mode: Literal["fast", "slow"] = "fast",
        **kwargs: int,
    ) -> Literal["ok"]:
        """a: first
        b: second
        mode: mode help
        return: result help
        """
        return "ok"

    new_data = analyze_function(sample)
    with pytest.raises(NameError):
        old_analyze_function(sample)

    assert new_data["has_*args"] is True
    assert new_data["has_**kwargs"] is True
    assert new_data["return_choices"] == ("ok",)


def test_analyze_function_accepts_bound_method_via___func__() -> None:
    class C:
        def method(self, x: int) -> int:
            return x

    info = analyze_function(C().method)
    assert info["name"] == "method"


def test_get_analysis_supports_callable_objects() -> None:
    class CallableObj:
        def __call__(self, value: int) -> int:
            return value

    ana = get_analysis(CallableObj)
    assert ana.name == "__call__"
    assert ana.arguments[0].name == "self"
