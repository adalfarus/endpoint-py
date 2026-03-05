from __future__ import annotations

from typing import Any

from ..endpoints import NativeEndpoint
from ..native_parser import NativeParser


def _make_simple_endpoint() -> NativeEndpoint:
    def add(a: int, b: int) -> int:
        return a + b

    parser = NativeParser({})
    ep = NativeEndpoint.from_function(add, name="add", parser=parser)
    return ep


def test_integration_parse_and_call_add_endpoint() -> None:
    results: dict[str, Any] = {}

    def calling_func(endpoint, fn, *args, **kwargs):  # type: ignore[no-untyped-def]
        results["value"] = fn(*args, **kwargs)

    ep = _make_simple_endpoint()
    ep.set_calling_func(calling_func)

    # Simulate CLI-style call: program name + two integer args mapped by NativeParser
    pos, kw = ep.parse(["prog", "2", "3"], skip_first_arg=True, automatic_help_args=())

    assert results["value"] == 5
    assert pos == []
    assert "a" in kw and "b" in kw

