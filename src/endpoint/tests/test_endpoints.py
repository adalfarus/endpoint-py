"""TBA"""

from ..endpoints import EndpointProtocol, NativeEndpoint, ArgparseEndpoint, EndpointError
import pytest

# Standard typing imports for aps
import typing_extensions as _te
import collections.abc as _a
import typing as _ty

if _ty.TYPE_CHECKING:
    import _typeshed as _tsh
import types as _ts


def test_endpoint_protocol() -> None:
    try:
        EndpointProtocol()
    except Exception:
        ...
    else:
        raise RuntimeError("Abstract base class EndpointProtocol was initialized successfully.")


def test_native_endpoint_from_function() -> None:
    ...
