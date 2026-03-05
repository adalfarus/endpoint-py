"""TBA"""

from __future__ import annotations

from typing import Any

import pytest

from ..endpoints import ArgparseEndpoint, EndpointError, EndpointProtocol, NativeEndpoint


def test_endpoint_protocol_is_abstract() -> None:
    """EndpointProtocol must not be instantiable directly."""
    with pytest.raises(TypeError):
        EndpointProtocol()  # type: ignore[abstract]


def test_endpoint_error_message_roundtrip() -> None:
    err = EndpointError("boom")
    assert str(err) == "boom"


def test_native_endpoint_call_without_function_is_noop() -> None:
    ep = NativeEndpoint(name="test")
    # Should not raise even though no function is configured
    ep.call(args=[1], kwargs={"x": 2})


def test_native_endpoint_call_invokes_function() -> None:
    called: dict[str, Any] = {}

    def fn(a: int, b: int) -> None:
        called["args"] = (a, b)

    ep = NativeEndpoint(name="add", function=fn)
    ep.call(args=[1, 2], kwargs={})

    assert called["args"] == (1, 2)


def test_native_endpoint_call_uses_calling_func_wrapper() -> None:
    seen: dict[str, Any] = {}

    def fn(x: int) -> None:
        seen["fn_called_with"] = x

    def wrapper(endpoint: EndpointProtocol, func, *args, **kwargs):  # type: ignore[no-untyped-def]
        # record and then call
        seen["endpoint"] = endpoint
        seen["func"] = func
        seen["args"] = args
        seen["kwargs"] = kwargs
        func(*args, **kwargs)

    ep = NativeEndpoint(name="wrapped", function=fn, calling_func=wrapper)
    ep.call(args=[10], kwargs={})

    assert seen["fn_called_with"] == 10
    assert seen["args"] == (10,)
    assert seen["kwargs"] == {}


def test_native_endpoint_add_argument_and_copy_arguments() -> None:
    ep = NativeEndpoint(name="ep")
    ep.add_argument(
        name="count",
        types=[int],
        default=0,
        choices=[0, 1, 2],
        required=False,
        positional_only=True,
        help_="number of items",
        # metavar="COUNT",
    )

    args = ep.copy_arguments()
    assert len(args) == 1
    a = args[0]
    assert a.name == "count"
    assert a.type is int
    assert a.default == 0
    assert a.choices == [0, 1, 2]
    assert a.positional_only is True
    assert a.kwarg_only is False
    #assert a.metavar == "COUNT"


def test_native_endpoint_add_argument_reorders_when_requested() -> None:
    ep = NativeEndpoint(name="ep")
    ep.add_argument(name="optional", types=[int], default=0, required=False)
    ep.add_argument(name="required", types=[int], required=True, automatically_reorder_arguments=True)

    ordered = ep.copy_arguments()
    # required argument should come before optional when reordering is enabled
    assert [a.name for a in ordered] == ["required", "optional"]


def test_native_endpoint_add_argument_rejects_conflicting_positional_flags() -> None:
    ep = NativeEndpoint(name="ep")
    with pytest.raises(ValueError):
        ep.add_argument(
            name="bad",
            types=[int],
            positional_only=True,
            kwarg_only=True,
        )


def test_native_endpoint_add_argument_rejects_positional_with_flag_names() -> None:
    ep = NativeEndpoint(name="ep")
    with pytest.raises(ValueError):
        ep.add_argument(
            name="bad",
            types=[int],
            positional_only=True,
            letter="b",
        )


def test_native_endpoint_change_argument_updates_fields() -> None:
    ep = NativeEndpoint(name="ep")
    ep.add_argument(name="value", types=[int], default=1, required=False)

    ep.change_argument("value", default=2, required=True)

    [arg] = ep.copy_arguments()
    assert arg.default == 2
    assert arg.required is True


def test_native_endpoint_change_argument_unknown_raises() -> None:
    ep = NativeEndpoint(name="ep")
    with pytest.raises(ValueError):
        ep.change_argument("missing")


def test_native_endpoint_guess_letters_and_shortforms_assigns_options() -> None:
    ep = NativeEndpoint(name="ep")
    ep.add_argument(name="verbose", types=[bool], default=False)
    ep.add_argument(name="output_file", types=[str], default="")

    ep.guess_letters_and_shortforms()

    args = ep.copy_arguments()
    names = {a.name: a for a in args}
    assert names["verbose"].letter is not None
    # output_file gets metavar with '-' and at least one alternative name
    assert names["output_file"].alternative_names


def test_native_endpoint_generate_help_includes_usage_and_options() -> None:
    ep = NativeEndpoint(name="prog", help_str="example endpoint")
    ep.add_argument(name="count", types=[int], default=1, help_="how many", metavar="COUNT")

    help_text = ep.generate_help(prog="prog")
    assert "usage: prog" in help_text
    assert "COUNT" in help_text
    assert "how many" in help_text
    assert "example endpoint" in help_text


def test_native_endpoint_to_argparse_and_to_argparse_endpoint_roundtrip() -> None:
    ep = NativeEndpoint(name="prog")
    ep.add_argument(name="flag", types=[bool], default=False, help_="toggle flag")
    ep.add_argument(name="count", types=[int], default=1, help_="count")

    parser = ep.to_argparse()
    ns = parser.parse_args(["--flag", "--count", "3"])
    assert ns.flag is True
    assert ns.count == 3

    aep = ep.to_argparse_endpoint()
    parsed_pos, parsed_kw = aep.parse(["prog", "--flag", "--count", "4"], skip_first_arg=True)
    assert parsed_pos == []
    assert parsed_kw["flag"] is True
    assert parsed_kw["count"] == 4


def test_argparse_endpoint_help_and_call() -> None:
    called: dict[str, Any] = {}

    def fn(*, value: int) -> None:
        called["value"] = value

    ep = ArgparseEndpoint(prog="prog", description="desc")
    ep.set_help_str("extra help")
    ep.set_calling_func(fn)
    ep.add_argument("--value", type=int, required=True)

    # automatic help args should return help mapping instead of calling func
    _, help_map = ep.parse(["prog", "--help"], skip_first_arg=True)
    assert "help" in help_map
    assert "desc" in help_map["help"]

    # normal parse should call fn and return parsed mapping
    _, parsed = ep.parse(["prog", "--value", "5"], skip_first_arg=True, automatic_help_args=())
    assert parsed["value"] == 5
    assert called["value"] == 5
