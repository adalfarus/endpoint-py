"""Functional"""
import sys

from dataclasses import dataclass, field, asdict

# Standard typing imports for aps
import typing_extensions as _te
import collections.abc as _a
import typing as _ty

if _ty.TYPE_CHECKING:
    import _typeshed as _tsh
import types as _ts

__all__ = ["NoDefault", "pretty_type", "BrokenType", "break_type", "guess_type", "ArgumentAnalysis", "Analysis",
           "analyze_function", "get_analysis"]


class NoDefault:
    def __repr__(self) -> str:
        return "<NoDefault Object>"


def pretty_type(tp) -> str:
    if isinstance(tp, type):  # Builtins + normal classes
        return tp.__name__

    # typing constructs (list[int], dict[str, bool], Union, ...)
    origin = _ty.get_origin(tp)
    args = _ty.get_args(tp)

    if origin:
        name = getattr(origin, "__name__", str(origin))
        if args:
            return f"{name}[{', '.join(pretty_type(a) for a in args)}]"
        return name
    if hasattr(tp, "__args__") and hasattr(tp, "__origin__"):  # Literal values
        return str(tp)
    return str(tp)  # Fallback


@dataclass(frozen=True)
class BrokenType:
    base_type: _ty.Any
    arguments: tuple[_ty.Self, ...]

    def __str__(self) -> str:
        arg_str: str = ", ".join(str(x) if isinstance(x, BrokenType) else pretty_type(x) for x in self.arguments)
        return f"BrokenType(base_type={pretty_type(self.base_type)}, arguments=({arg_str}))"

    def __repr__(self) -> str:
        return str(self)


def break_type(type_annotation: _ty.Any) -> BrokenType | tuple[BrokenType]:  # _ty.Any | BrokenType | tuple[_ty.Any | BrokenType, ...]:
    """
    Recursively break a typing annotation into BrokenType nodes.

    Leaves are returned as-is (e.g. int, str, bool, NoneType, etc).
    Containers/generics become BrokenType(origin, tuple(broken_args)).
    Unions become BrokenType(typing.Union, tuple(broken_members)).
    Literals become BrokenType(typing.Literal, tuple(literal_values)).
    """
    if isinstance(type_annotation, _ty.ForwardRef):  # Resolve forward refs if any (best-effort; if unresolved, keep as-is)
        return BrokenType(type_annotation.__forward_arg__, tuple())

    origin = _ty.get_origin(type_annotation)
    args = _ty.get_args(type_annotation)

    if origin is None:  # Not a parametrized typing construct -> leaf
        return BrokenType(type_annotation, tuple())
    if origin is _ty.Literal:  # Literal[...] -> keep the literal values as arguments (not further broken)
        return BrokenType(_ty.Literal, tuple(args))
    if origin is _ty.Union or origin is _ts.UnionType:  # Union or X | Y
        return BrokenType(_ty.Union, tuple(break_type(a) for a in args))  # normalize base_type to typing.Unionś
    return BrokenType(origin, tuple(break_type(a) for a in args))  # Everything else (list[T], dict[K, V], tuple[...], set[T], typing.List[T], etc.)


B = _ty.TypeVar("B")
def guess_type(value: B) -> type[B]:
    return type(value)


@dataclass(slots=True)
class ArgumentAnalysis:
    name: str
    default: _ty.Any | NoDefault
    choices: _a.Sequence[_ty.Any] = field(default_factory=tuple)        # Literal choices
    type: _ty.Any = None                                             # raw annotation (from __annotations__)
    type_choices: _a.Sequence[_ty.Any] = field(default_factory=tuple)    # Union choices
    doc_help: str = ""
    pos_only: bool = False
    kwarg_only: bool = False
    is_arg: bool = False
    is_kwarg: bool = False


@dataclass(slots=True)
class Analysis:
    name: str
    doc: str = ""
    help_: str = ""
    arguments: list[ArgumentAnalysis] = field(default_factory=list)

    has_args: bool = False       # corresponds to "has_*args"
    has_kwargs: bool = False     # corresponds to "has_**kwargs"

    return_type: _ty.Any = None
    return_choices: _a.Sequence[_ty.Any] = field(default_factory=tuple)
    return_doc_help: str = ""

    def to_dict(self) -> dict[str, _ty.Any]:
        """Backwards-compatible dict shape (including the original keys)."""
        return {
            "name": self.name,
            "doc": self.doc,
            "help": self.help_,
            "arguments": [asdict(a) for a in self.arguments],
            "has_*args": self.has_args,
            "has_**kwargs": self.has_kwargs,
            "return_type": self.return_type,
            "return_choices": list(self.return_choices),
            "return_doc_help": self.return_doc_help,
        }

    @classmethod
    def from_dict(cls, data: dict[str, _ty.Any]) -> "Analysis":
        """Create an Analysis from the dict returned by your current analyze_function()."""
        return cls(
            name=data.get("name", ""),
            doc=data.get("doc", "") or "",
            help_=data.get("help", "") or "",
            arguments=[ArgumentAnalysis(**a) for a in (data.get("arguments") or [])],
            has_args=bool(data.get("has_*args", False)),
            has_kwargs=bool(data.get("has_**kwargs", False)),
            return_type=data.get("return_type"),
            return_choices=tuple(data.get("return_choices") or ()),
            return_doc_help=data.get("return_doc_help", "") or "",
        )


class AnalyzableFunction(_ty.Protocol):
    __name__: str
    __doc__: str | None
    __annotations__: _ty.Mapping[str, _ty.Any]
    __defaults__: tuple[_ty.Any, ...] | None
    __kwdefaults__: dict[str, _ty.Any] | None
    __code__: _ts.CodeType
    def __call__(self, *args: _ty.Any, **kwargs: _ty.Any) -> _ty.Any: ...


def old_analyze_function(function: _a.Callable, /, break_types: bool = True, guess_types: bool = True) -> dict[str, list[_ty.Any] | str | None]:
    """
    Analyzes a given function's signature and docstring, returning a structured summary of its
    arguments, including default values, types, keyword-only flags, documentation hints, and
    choices for `Literal`-type arguments. Also extracts information on `*args`, `**kwargs`,
    and the return type.

    Args:
        function (types.FunctionType): The function to analyze.
        break_types (bool): If composite types like list[str] should be broken down.
        guess_types (bool): Try to guess the type if only a value is provided.

    Returns:
        dict: A dictionary containing the following keys:
            - "name" (str): The name of the function.
            - "doc" (str): The function's docstring.
            - "arguments" (List[Dict[str, Union[str, None]]]): Details of each argument:
                - "name" (str): The argument's name.
                - "default" (Any or None): The default value, if provided.
                - "choices" (List[Any] or []): Options for `Literal` type hints, if applicable.
                - "type" (Any or None): The argument's type hint.
                - "doc_help" (str): The extracted docstring help for the argument.
                - "kwarg_only" (bool): True if the argument is keyword-only.
            - "has_*args" (bool): True if the function accepts variable positional arguments.
            - "has_**kwargs" (bool): True if the function accepts variable keyword arguments.
            - "return_type" (Any or None): The function's return type hint.
            - "return_choices" (List[Any] or []): Options for `Literal` type hints for the return type, if applicable.
            - "return_doc_help" (str): The extracted docstring help for the return type.
    """
    if hasattr(function, "__func__"):
        function = function.__func__
    elif not isinstance(function, _ts.FunctionType):
        raise ValueError(f"Only a real function can be analyzed, not '{function}'")

    name = function.__name__
    arg_count = (
        function.__code__.co_posonlyargcount
        + (function.__code__.co_argcount - function.__code__.co_posonlyargcount)
        + function.__code__.co_kwonlyargcount
    )
    argument_names: list[str | Special] = list(function.__code__.co_varnames[:arg_count] or ())
    has_args = (function.__code__.co_flags & 0b0100) == 4
    has_kwargs = (function.__code__.co_flags & 0b1000) == 8
    defaults: list[NoDefault | None | _ty.Any] = [NoDefault() for _ in range(len(argument_names))]
    defaults.extend(list(function.__defaults__ or ()))
    if function.__kwdefaults__ is not None:
        defaults.extend(list(function.__kwdefaults__.values()))
    defaults = defaults[len(defaults) - len(argument_names) :]
    types = function.__annotations__ or {}
    docstring = function.__doc__ or ""
    type_hints = _ty.get_type_hints(function)

    only_pos_argcount = function.__code__.co_posonlyargcount  # Before which we have only positionals
    pos_argcount = function.__code__.co_argcount  # After which i we have kwarg only
    if has_args:
        argument_names.insert(pos_argcount, Special("args"))
        defaults.insert(pos_argcount, NoDefault())
        pos_argcount += 1
    if has_kwargs:
        argument_names.append(Special("kwargs"))
        defaults.append(NoDefault())
    argument_names.append("return")
    defaults.append(NoDefault())

    result = {
        "name": name,
        "doc": docstring,
        "help": "",
        "arguments": [],
        "has_*args": has_args,
        "has_**kwargs": has_kwargs,
        "return_type": break_type(function.__annotations__.get("return")) if break_types else function.__annotations__.get("return"),
        "return_choices": [],
        "return_doc_help": "",
    }
    func_help_ = docstring
    for i, (argument, default) in enumerate(zip(argument_names, defaults)):
        if isinstance(argument, Special):
            argument_name = argument.heart
        else:
            argument_name = argument
        argument_start = func_help_.find(argument_name)
        help_str, choices, type_choices = "", tuple(), tuple()
        if argument_start != -1:
            help_start = argument_start + len(
                argument_name
            )  # Where argument_name ends in docstring (func_help_)
            newline_offset = func_help_[argument_start:].find("\n")
            if newline_offset == -1:
                newline_offset = len(func_help_) - argument_start
            next_line = argument_start + newline_offset
            help_str = func_help_[help_start:next_line].strip(": \n\t")
            func_help_ = func_help_[:help_start-len(argument_name)] + func_help_[next_line:]
        if argument_name == "return":
            type_hint = result["return_type"]
            if getattr(type_hint, "__origin__", None) is _ty.Literal:
                choices = type_hint.__args__
            result["return_choices"] = choices
            result["return_doc_help"] = help_str
            continue
        type_hint = type_hints.get(argument_name)
        if getattr(type_hint, "__origin__", None) is _ty.Literal:
            choices = type_hint.__args__
        elif getattr(type_hint, "__origin__", None) is _ty.Union or type(type_hint) is _ts.UnionType:
            type_choices = type_hint.__args__

        if isinstance(argument, Special):
            if argument.heart == "args":
                type_ = tuple[_ty.Any]
            elif argument.heart == "kwargs":
                type_ = dict[str, _ty.Any]
            else:
                raise RuntimeError("Something went wrong")
        else:
            type_ = types.get(argument_name)
            if guess_types and type_ is None:
                type_ = guess_type(default) if default else None

        result["arguments"].append(
            {
                "name": argument_name,
                "default": default,
                "choices": choices,
                "type": break_type(type_) if break_types else type_,
                "type_choices": type_choices,
                "doc_help": help_str,
                "pos_only": i < only_pos_argcount,
                "kwarg_only": i >= pos_argcount,
            }
        )
    result["help"] = func_help_.strip()
    return result


def _get_from_func_help(func_help: str, argname: str) -> tuple[str, str]:
    argument_start = func_help.find(argname)
    help_str, choices, type_choices = "", tuple(), tuple()
    if argument_start != -1:
        help_start = argument_start + len(
            argname
        )  # Where argument_name ends in docstring (func_help_)
        newline_offset = func_help[argument_start:].find("\n")
        if newline_offset == -1:
            newline_offset = len(func_help) - argument_start
        next_line = argument_start + newline_offset
        help_str = func_help[help_start:next_line].strip(": \n\t")
        func_help = func_help[:help_start - len(argname)] + func_help[next_line:]
    return func_help, help_str


def analyze_function(function: _a.Callable, /, break_types: bool = True, guess_types: bool = True) -> dict[str, list[_ty.Any] | str | None]:
    """
    Analyzes a given function's signature and docstring, returning a structured summary of its
    arguments, including default values, types, keyword-only flags, documentation hints, and
    choices for `Literal`-type arguments. Also extracts information on `*args`, `**kwargs`,
    and the return type.

    Args:
        function (types.FunctionType): The function to analyze.
        break_types (bool): If composite types like list[str] should be broken down.
        guess_types (bool): Try to guess the type if only a value is provided.

    Returns:
        dict: A dictionary containing the following keys:
            - "name" (str): The name of the function.
            - "doc" (str): The function's docstring.
            - "arguments" (List[Dict[str, Union[str, None]]]): Details of each argument:
                - "name" (str): The argument's name.
                - "default" (Any or None): The default value, if provided.
                - "choices" (List[Any] or []): Options for `Literal` type hints, if applicable.
                - "type" (Any or None): The argument's type hint.
                - "doc_help" (str): The extracted docstring help for the argument.
                - "kwarg_only" (bool): True if the argument is keyword-only.
            - "has_*args" (bool): True if the function accepts variable positional arguments.
            - "has_**kwargs" (bool): True if the function accepts variable keyword arguments.
            - "return_type" (Any or None): The function's return type hint.
            - "return_choices" (List[Any] or []): Options for `Literal` type hints for the return type, if applicable.
            - "return_doc_help" (str): The extracted docstring help for the return type.
    """
    if hasattr(function, "__func__"):
        function = function.__func__
    elif not isinstance(function, _ts.FunctionType):
        raise ValueError(f"Only a real function can be analyzed, not '{function}'")

    name: str = function.__name__
    code: _ts.CodeType = function.__code__
    arg_count: int = code.co_argcount + code.co_kwonlyargcount
    has_args: bool = (code.co_flags & 0b0100) == 4
    has_kwargs: bool = (code.co_flags & 0b1000) == 8
    defaults: tuple[_ty.Any, ...] = function.__defaults__ or ()
    kwdefaults: dict[str, _ty.Any] = function.__kwdefaults__ or ()
    len_defaults: int = len(defaults) + len(kwdefaults)
    len_no_defaults: int = arg_count - len_defaults
    types = _ty.get_type_hints(function) or {}  # Cannot use __annotations__ here as they are just strings if types were deferred with 'from __future__ import annotations'
    docstring = function.__doc__ or ""
    type_hints = _ty.get_type_hints(function)

    posonly_n = code.co_posonlyargcount
    pos_or_kw_n = code.co_argcount
    kwonly_n = code.co_kwonlyargcount

    return_type = types.get("return")
    return_choices = []
    if getattr(return_type, "__origin__", None) is _ty.Literal:
        return_choices = return_type.__args__
    func_help: str
    return_help: str
    func_help, return_help = _get_from_func_help(docstring, "return")

    result = {
        "name": name,
        "doc": docstring,
        "help": "",
        "arguments": [],
        "has_*args": has_args,
        "has_**kwargs": has_kwargs,
        "return_type": break_type(return_type) if break_types else return_type,
        "return_choices": return_choices,
        "return_doc_help": return_help,
    }

    for i, argname in enumerate(code.co_varnames[:arg_count+has_args+has_kwargs]):
        func_help, help_str = _get_from_func_help(func_help, argname)
        choices: tuple[_ty.Any, ...] = tuple()
        type_choices: tuple[type[_ty.Any], ...] = tuple()
        is_posonly: bool = i < posonly_n
        # is_pos: bool = pos_or_kw_n > i >= posonly_n
        is_kwarg_only: bool = arg_count > i >= pos_or_kw_n

        default: _ty.Any | NoDefault
        if i < arg_count:
            type_hint = type_hints.get(argname)
            if getattr(type_hint, "__origin__", None) is _ty.Literal:
                type_choices = tuple(type(x) for x in type_hint.__args__)
                choices = type_hint.__args__
            elif getattr(type_hint, "__origin__", None) is _ty.Union or type(type_hint) is _ts.UnionType:
                type_choices = type_hint.__args__

            if i < len_no_defaults:
                default = NoDefault()
            elif i < pos_or_kw_n:
                default = defaults[i - len_no_defaults]
            else:
                default = kwdefaults[argname]
            type_ = types.get(argname)
            if guess_types and type_ is None:
                type_ = guess_type(default) if default else None
            result["arguments"].append({
                    "name": argname, "default": default, "choices": choices,
                    "type": break_type(type_) if break_types else type_, "type_choices": type_choices,
                    "doc_help": help_str, "pos_only": is_posonly, "kwarg_only": is_kwarg_only, "is_arg": False,
                    "is_kwarg": False})
        else:
            if has_args:
                type_ = tuple[_ty.Any]
                has_args = False
                result["arguments"].insert(code.co_argcount, {
                    "name": argname, "default": tuple(), "choices": choices,
                    "type": break_type(type_) if break_types else type_, "type_choices": type_choices,
                    "doc_help": help_str, "pos_only": True, "kwarg_only": False, "is_arg": True,
                    "is_kwarg": False})
            elif has_kwargs:
                type_ = dict[str, _ty.Any]
                has_kwargs = False
                result["arguments"].append({
                    "name": argname, "default": dict(), "choices": choices,
                    "type": break_type(type_) if break_types else type_, "type_choices": type_choices,
                    "doc_help": help_str, "pos_only": True, "kwarg_only": False, "is_arg": False,
                    "is_kwarg": True})
            else: raise RuntimeError("This cannot happen")
    result["help"] = func_help.strip()
    return result


def get_analysis(function: _a.Callable, /, break_types: bool = True) -> Analysis:
    """
    Analyzes a given function's signature and docstring, returning a structured summary of its
    arguments, including default values, types, keyword-only flags, documentation hints, and
    choices for `Literal`-type arguments. Also extracts information on `*args`, `**kwargs`,
    and the return type.

    Args:
        function (types.FunctionType): The function to analyze.
        break_types (bool): If composite types like list[str] should be broken down.

    Returns:
        Analysis
    """
    if (not isinstance(function, _ts.FunctionType)
            and hasattr(function, "__call__")
            and isinstance(function.__call__, _ts.FunctionType)):
        function = function.__call__
    return Analysis.from_dict(analyze_function(function, break_types=break_types))
