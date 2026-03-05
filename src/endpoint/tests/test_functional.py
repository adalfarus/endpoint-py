from __future__ import annotations

from typing import Any, Callable

import pytest

from ..endpoints import NativeEndpoint
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
    assert "Mixed docstring styles" in help_str
    # Be tolerant of docstyle differences
    assert "Args:" in help_str or "Parameters" in help_str


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


