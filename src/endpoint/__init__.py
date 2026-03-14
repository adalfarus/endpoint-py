"""TBA"""

# Internal import
from . import endpoints, functional, interface, native_parser, parser_collection, str_guess, structure
from .endpoints import NativeEndpoint, ArgparseEndpoint
from .interface import Interface
from .native_parser import NativeParser

# Standard typing imports for aps
import typing_extensions as _te
import collections.abc as _a
import typing as _ty

if _ty.TYPE_CHECKING:
    import _typeshed as _tsh
import types as _ts

__version__ = "2.1.1.3"
__all__ = ["NativeEndpoint", "ArgparseEndpoint", "Interface", "NativeParser", "__version__"]
