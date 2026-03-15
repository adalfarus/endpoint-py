import abc
import argparse
import warnings
from functools import reduce
from operator import or_
import sys
from argparse import ArgumentParser
import shutil

# Internal imports
from .str_guess import guess_letters, guess_prefix_shortforms, guess_shortforms
from .functional import break_type, Analysis, get_analysis, NoDefault
from .native_parser import (NativeParser, ArgumentParsingError, Argument, Parser, NArgsMode, NArgsSpec,
                            NArgsModeNumber, NArgsOneOrMore, NArgsZeroOrMore, NArgsMinMax)

# Standard typing imports for aps
import typing_extensions as _te
import collections.abc as _a
import typing as _ty

if _ty.TYPE_CHECKING:
    import _typeshed as _tsh
import types as _ts

__all__ = ["EndpointError", "EndpointProtocol", "NativeEndpoint", "ArgparseEndpoint", "CallingFunc"]


class EndpointError(Exception):
    """Base error raised for endpoint configuration and runtime issues."""

    def __init__(self, message: str) -> None:
        """Initialize the endpoint error.

        :param message: Human-readable error message.
        """
        super().__init__(message)


P = _ty.ParamSpec("P")
R = _ty.TypeVar("R")
class CallingFunc(_ty.Protocol[P, R]):
    """Protocol for custom endpoint invocation wrappers."""

    def __call__(self, endpoint: "EndpointProtocol", fn: _a.Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
        """Execute ``fn`` for an endpoint with full call context.

        :param endpoint: Endpoint that owns the function.
        :param fn: Target callable to execute.
        :param args: Positional call arguments.
        :param kwargs: Keyword call arguments.
        :returns: Wrapped call result.
        """
        ...
class EndpointProtocol(metaclass=abc.ABCMeta):
    """Abstract interface implemented by endpoint parser backends."""

    @abc.abstractmethod
    def call(self, args: list[_ty.Any], kwargs: dict[str, _ty.Any]) -> None:
        """Call the underlying endpoint function.

        :param args: Positional arguments for the endpoint function.
        :param kwargs: Keyword arguments for the endpoint function.
        """
        ...
    @abc.abstractmethod
    def set_calling_func(self, func: CallingFunc) -> None:
        """Set a custom invocation wrapper.

        :param func: Wrapper callable that controls endpoint invocation.
        """
        ...
    @abc.abstractmethod
    def add_argument(self, *args, **kwargs) -> None:
        """Register one argument definition on the endpoint."""
        ...
    @abc.abstractmethod
    def generate_help(self, prog: str = "endpoint", automatic_help_args: tuple[str, ...] = ("-?", "-h", "--?", "--help")
                      ) -> str:
        """Build endpoint help text.

        :param prog: Program name shown in usage output.
        :param automatic_help_args: Tokens recognized as help flags.
        :returns: Formatted help text.
        """
        ...
    @abc.abstractmethod
    def get_help_str(self) -> str:
        """Return the endpoint-level descriptive help text."""
        ...
    @abc.abstractmethod
    def set_help_str(self, help_str: str) -> None:
        """Set the endpoint-level descriptive help text.

        :param help_str: Plain text used as endpoint description.
        """
        ...
    @abc.abstractmethod
    def parse(self, arguments: list[str] | None = None, *, skip_first_arg: bool = True,
              automatic_help_args: tuple[str, ...] = ("-?", "-h", "--?", "--help")
              ) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
        """Parse CLI tokens into positional and keyword endpoint arguments.

        :param arguments: Explicit argument vector; defaults to ``sys.argv``.
        :param skip_first_arg: Skip argv program name before parsing.
        :param automatic_help_args: Tokens recognized as help flags.
        :returns: Tuple of parsed positional and keyword arguments.
        """
        ...
    @abc.abstractmethod
    def __repr__(self) -> str:
        """Return a concise debug representation."""
        ...


NARGS_TYPE = (NArgsMode
              | NArgsOneOrMore
              | NArgsZeroOrMore
              | type[NArgsOneOrMore]
              | type[NArgsZeroOrMore]
              | NArgsModeNumber
              | NArgsMinMax)
D = _ty.TypeVar("D")
class ArgumentChanges(_ty.TypedDict, total=False):
    """Valid field updates accepted by :meth:`NativeEndpoint.change_argument`."""

    alternative_names: list[str]
    letter: str | None
    types: list[type]
    default: object | None
    choices: list[object]
    required: bool
    positional_only: bool
    kwarg_only: bool
    help_: str
    metavar: str | None
    nargs: NARGS_TYPE
    checking_func: _a.Callable[[Argument, _ty.Any], _ty.Any | ArgumentParsingError] | None
# TODO: Decorator or similar that changed endpoint argument recognition like @change_args(type_="type")
class NativeEndpoint(EndpointProtocol):  # TODO: As '-argument' is now valid we need to stop using only -- in conversion and help
    """Represents the endpoint of a trace from an argument structure object.

    The `EndPoint` class serves as a container for functions associated with
    a particular argument path, providing a way to call the function with
    predefined arguments and keyword arguments.

    :ivar _arguments: Registered endpoint argument definitions.
    :ivar _function: Function executed when the endpoint is called.
    """
    DEFAULT_PARSER: type[Parser] = NativeParser

    def __init__(self, name: str, help_str: str = "", function: _a.Callable | None = None, *,
                 calling_func: CallingFunc | None = None, parser: Parser | None = None) -> None:
        """Create a native endpoint.

        :param name: Endpoint/program display name.
        :param help_str: Endpoint description used in help text.
        :param function: Callable executed when parse succeeds.
        :param calling_func: Optional invocation wrapper around ``function``.
        :param parser: Custom parser instance; defaults to :attr:`DEFAULT_PARSER`.
        """
        self._arguments: list[Argument] = list()
        self._function: _a.Callable | None = function
        self._name: str = name
        self._help_str: str = help_str
        self._calling_func: CallingFunc | None = calling_func
        self._parser: Parser = parser or self.DEFAULT_PARSER({})

    def call(self, args: list[_ty.Any], kwargs: dict[str, _ty.Any]) -> None:
        """Execute the endpoint function with parsed arguments.

        :param args: Positional call arguments.
        :param kwargs: Keyword call arguments.
        """
        if self._function is None:
            return
        if self._calling_func is not None:
            self._calling_func(self, self._function, *args, **kwargs)
        else:
            self._function(*args, **kwargs)

    def set_calling_func(self, func: _a.Callable | None) -> None:
        """Set or clear the custom call wrapper.

        :param func: Wrapper callable or ``None`` to disable wrapping.
        """
        self._calling_func = func

    # TODO: Make more efficient?
    def _check_and_sort_arguments(self) -> list[Argument]:
        """Validate uniqueness and return required arguments first.

        :returns: Sorted argument list with required entries before optional ones.
        :raises ValueError: If any name, alias, or letter is duplicated.
        """
        names: set[str] = set()
        required: list[Argument] = list()
        others: list[Argument] = list()

        for argu in self._arguments:
            ns = [argu.metavar] + argu.alternative_names + ([argu.letter] if argu.letter is not None else [])
            for n in ns:
                if n in names:
                    raise ValueError(f"You can't have the argument name '{n}' more than once.")
                names.add(n)
            if argu.required:
                required.append(argu)
            else:
                others.append(argu)
        return required + others

    def add_argument(self, name: str, alternative_names: list[str] | None = None, letter: str | None = None,
                     types: list[type[D]] | None = None, default: D | NoDefault = NoDefault(), choices: list[D] | None = None,
                     required: bool = False, positional_only: bool = False, kwarg_only: bool = False, help_: str = "",
                     metavar: str | None = None, nargs: NARGS_TYPE = NArgsMode.ONE_OR_MORE,
                     checking_func: _a.Callable[[Argument, _ty.Any], _ty.Any | ArgumentParsingError] | None = None,
                     automatically_reorder_arguments: bool = False) -> None:
        """Register a new argument specification on the endpoint.

        :param name: Primary internal argument name.
        :param alternative_names: Optional long-form aliases.
        :param letter: Optional one-letter short flag.
        :param types: Allowed Python types for parsed values.
        :param default: Default value when not provided on the CLI.
        :param choices: Explicit allowed values.
        :param required: Whether parsing should fail when argument is missing.
        :param positional_only: Whether argument can only be provided positionally.
        :param kwarg_only: Whether argument can only be provided as a flag.
        :param help_: Human-readable help description.
        :param metavar: Display name in usage/help output.
        :param nargs: Cardinality specification for consumed values.
        :param checking_func: Optional post-parse validation function.
        :param automatically_reorder_arguments: Reorder required arguments first.
        :raises ValueError: On incompatible argument mode combinations.
        """
        if "-" in name:  # Name is namespace so we need to guarantee a valid name
            if positional_only:
                raise ValueError("Positional only arguments cannot have '-' in it's name.")
            if name.startswith("-"):  # To achieve compatibility with argparse
                kwarg_only = True
            name = name.lstrip("-")
            if metavar is None:
                metavar = name
            name = name.replace("-", "_")
        if alternative_names is None:
            alternative_names = list()
        if any([metavar] + alternative_names + ([letter] if letter else [])) and positional_only:
            raise ValueError("Positional only arguments cannot have an argument name (metavar, alternative_names, or letter)")
        elif not metavar and positional_only:
            metavar = ""
        if types is None:
            types = list()
        if choices is None:
            choices = list()
        if types == [bool]:
            if isinstance(default, NoDefault):
                default = False
            kwarg_only = True
        if positional_only and kwarg_only:
            raise ValueError("An Argument can only be only_positional or only_kwarg, not both.")
        if nargs == NArgsMode.ONE:
            nargs = NArgsMode.MIN_MAX(1, 1)
        elif nargs == NArgsMode.ZERO_OR_ONE:
            nargs = NArgsMode.MIN_MAX(0, 1)
        elif nargs == NArgsMode.ONE_OR_MORE:
            nargs = NArgsMode.MIN_MAX(1, None)
        elif isinstance(nargs, NArgsOneOrMore):
            nargs = NArgsMode.MIN_MAX(1, None, nargs.spec)
        elif nargs == NArgsMode.ZERO_OR_MORE:
            nargs = NArgsMode.MIN_MAX(0, None)
        elif isinstance(nargs, NArgsZeroOrMore):
            nargs = NArgsMode.MIN_MAX(0, None, nargs.spec)
        elif isinstance(nargs, NArgsModeNumber):
            nargs = NArgsMode.MIN_MAX(nargs.n, nargs.n)
        if nargs.spec == NArgsSpec.FEW:
            nargs.spec = NArgsSpec.NUMBER(nargs.min)
        elif nargs.spec == NArgsSpec.MANY:
            nargs.spec = NArgsSpec.NUMBER(nargs.max)
        type_ = reduce(or_, types or [str])
        self._arguments.append(
            Argument(
                name, alternative_names,
                letter, type_, break_type(type_),
                default, choices, required,
                positional_only, kwarg_only,
                help_, metavar or name.replace("_", "-"),  # If another metavar is wanted, parse it explicitly
                nargs, checking_func
            )
        )
        if automatically_reorder_arguments:
            self._arguments = self._check_and_sort_arguments()

    def change_argument(self, name: str, automatically_reorder_arguments: bool = False,
                        **kwargs: _te.Unpack[ArgumentChanges]) -> None:
        """Modify an existing argument definition.

        :param name: Name of the argument to update.
        :param automatically_reorder_arguments: Reorder required arguments first.
        :param kwargs: Argument fields to update.
        :raises ValueError: If no argument with ``name`` exists.
        """
        argument: Argument | None = None
        i: int = -1
        for i, arg in enumerate(self._arguments):
            if arg.name == name:
                argument = arg
                break
        if argument is None or i == -1:
            raise ValueError(f"There is no argument with the name '{name}'. Please create it first.")
        self._arguments.remove(argument)
        arguments: dict[str, _ty.Any] = {
            "name": argument.name,
            "alternative_names": argument.alternative_names,
            "letter": argument.letter,
            "types": [argument.type] if not argument.broken_type.base_type == _ty.Union else argument.broken_type.arguments,
            "default": argument.default,
            "choices": argument.choices,
            "required": argument.required,
            "positional_only": argument.positional_only,
            "kwarg_only": argument.kwarg_only,
            "help_": argument.help,
            "metavar": argument.metavar,
            "nargs": argument.nargs,
            "checking_func": argument.checking_func,
            **kwargs
        }
        self.add_argument(**arguments, automatically_reorder_arguments=False)
        new_argument: Argument = self._arguments.pop(-1)
        self._arguments.insert(i, new_argument)
        if automatically_reorder_arguments:
            self._arguments = self._check_and_sort_arguments()

    def copy_arguments(self) -> list[Argument]:
        """Return a shallow copy of registered argument definitions.

        :returns: Copy of internal argument list.
        """
        return self._arguments.copy()

    def guess_letters_and_shortforms(self, guess_letters_: bool = True, guess_prefix_shortforms_: bool = True,
                                     guess_shortforms_: bool = True) -> None:
        """Populate aliases and optional letters for registered arguments.

        :param guess_letters_: Enable single-letter guessing.
        :param guess_prefix_shortforms_: Enable compact prefix alias guessing.
        :param guess_shortforms_: Enable token-aware shortform guessing.
        """
        names: list[str] = [arg.metavar for arg in self._arguments if not arg.positional_only]
        all_short_alternative_names: dict[str, str] = dict()
        all_alternative_names: dict[str, str] =  dict()
        all_letters: dict[str, str] =  dict()

        if guess_prefix_shortforms_:
            all_short_alternative_names = guess_prefix_shortforms(names)
        if guess_shortforms_:
            all_alternative_names = guess_shortforms(names)
        if guess_letters_:
            all_letters = guess_letters(names)

        for arg in self._arguments:
            short_alternative_name: str = all_short_alternative_names.get(arg.metavar, arg.metavar)
            alternative_name: str = all_alternative_names.get(arg.metavar, arg.metavar)
            arg.alternative_names = list(filter(lambda x: x != "" and x != arg.metavar, [short_alternative_name, alternative_name]))

            arg_letter: str | None = all_letters.get(arg.metavar, None)
            if arg_letter is not None:
                arg.letter = arg_letter

    def generate_help(self, prog: str = "endpoint",
                      automatic_help_args: tuple[str, ...] = ("-?", "-h", "--?", "--help"),
                      automatic_help_type: _ty.Literal["native", "argparse"] = "native",
                      width: int | None = None) -> str:
        """Render argparse-like help text for this endpoint.

        :param prog: Program/command name shown in the usage line.
        :param automatic_help_args: Help tokens shown in usage output.
        :param automatic_help_type: If positional arguments should be under a different header than keyword arguments.
        :param width: Optional wrapping width; autodetected when ``None``.
        :returns: Formatted endpoint help text.
        """
        if width is None:  # Try to get terminal width
            width = shutil.get_terminal_size(fallback=(88, 24)).columns

        split_positionals: bool = automatic_help_type == "argparse"

        # Arg usage
        usage_fragments: list[str] = list()
        usage_fragments.append(" ".join(f"[{help_arg}]" for help_arg in automatic_help_args))
        usage_fragments.append(" ".join(a.usage_fragment() for a in self._arguments))
        usage = " ".join(usage_fragments)
        out = [f"usage: {prog} {usage}".rstrip()]

        if self._help_str:
            out.insert(1, f"explaination: {self._help_str}")

        if split_positionals:
            out.extend(["", "positional arguments:"])
            indent = "  "

            for a in self._arguments:
                if not a.kwarg_only:
                    out.append(f"{indent}{a.name}")

        out.extend(["", "options:"])

        left = [a.left_column(split_positionals=split_positionals) for a in self._arguments]
        left_w = min(max((len(s) for s in left), default=0), 40)

        indent = "  "
        gap = "  "

        for a, l in zip(self._arguments, left):
            right = a.right_column(split_positionals=split_positionals)  # Argparse does not have metadata information

            if not right:
                out.append(f"{indent}{l}")
                continue

            avail = max(10, width - (len(indent) + left_w + len(gap)))

            words = right.split()
            lines: list[str] = []
            cur: list[str] = []
            cur_len = 0

            for w in words:
                add = len(w) + (1 if cur else 0)
                if cur_len + add > avail:
                    lines.append(" ".join(cur))
                    cur = [w]
                    cur_len = len(w)
                else:
                    cur.append(w)
                    cur_len += add

            if cur:
                lines.append(" ".join(cur))

            out.append(f"{indent}{l.ljust(left_w)}{gap}{lines[0]}")
            for ln in lines[1:]:
                out.append(f"{indent}{' '.ljust(left_w)}{gap}{ln}")

        return "\n".join(out)

    def get_help_str(self) -> str:
        """Return endpoint-level description text.

        :returns: Description used in help rendering.
        """
        return self._help_str

    def set_help_str(self, help_str: str) -> None:
        """Set endpoint-level description text.

        :param help_str: Description used in help rendering.
        """
        self._help_str = help_str

    def parse(self, arguments: list[str] | None = None, *, skip_first_arg: bool = True,
              automatic_help_args: tuple[str, ...] = ("-?", "-h", "--?", "--help"),
              automatic_help_type: _ty.Literal["native", "argparse"] = "native",
              ) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
        """Parse arguments, call endpoint function, and return parsed values.

        :param arguments: Explicit argv list; defaults to ``sys.argv``.
        :param skip_first_arg: Skip program path in argv.
        :param automatic_help_args: Tokens that trigger help output.
        :param automatic_help_type: If positional arguments should be under a different header than keyword arguments.
        :returns: Tuple of parsed positional and keyword arguments.
        """
        if arguments is None:
            arguments = sys.argv
        if skip_first_arg:
            arguments = arguments[1:]

        for arg in arguments:
            if arg in automatic_help_args:
                print(self.generate_help(prog=self._name, automatic_help_args=automatic_help_args,
                                         automatic_help_type=automatic_help_type))
                sys.exit(0)
                return list(), dict()

        if not self._parser.IS_FULLY_FEATURED:
            warnings.warn(f"The chosen parser '{self._parser}' is not fully features. This means features like: "
                          f"\n- Positionals\n- Keywords\n- Choices\n- Pos-only\n- Keyword-only\n- Pos or Keyword\n- "
                          f"Complex types\n- ...", stacklevel=2)
        try:
            parsed_pos, parsed_kwarg = self._parser.parse_args(arguments, self.copy_arguments(), self._name, self.generate_help)
        except ValueError as e:
            print(f"{e}")
            sys.exit(0)
        self.call(args=parsed_pos, kwargs=parsed_kwarg)

        return parsed_pos, parsed_kwarg

    @staticmethod
    def _add_arg_to_argparse_like(argument: Argument, parser: _ty.Any) -> None:
        """Mirror one native argument onto an argparse-like parser.

        :param argument: Native argument definition.
        :param parser: Target parser object supporting ``add_argument``.
        """
        is_bool: bool = bool == argument.broken_type.base_type or (
                    argument.broken_type.base_type == _ty.Union and bool in argument.broken_type.arguments)
        names = list()
        if argument.letter:
            names.append(f"-{argument.letter}")
        names.extend([f"--{x}" for x in [argument.metavar, *argument.alternative_names]])

        if is_bool:
            parser.add_argument(*names, help=argument.help,
                                default=argument.default, action="store_true",
                                required=argument.required)
        elif argument.positional_only:
            parser.add_argument(argument.name, help=argument.help,  # Positional
                                default=argument.default, type=argument.type,
                                choices=argument.choices if argument.choices else None,
                                metavar=argument.metavar, nargs="?")
        elif argument.kwarg_only:
            parser.add_argument(*names, help=argument.help, dest=argument.name,  # Kwarg
                                default=argument.default, type=argument.type,
                                choices=argument.choices if argument.choices else None,
                                metavar=argument.metavar, required=argument.required)
        else:
            warnings.warn("ArgParse doesn't support arguments that can be both positional and kwarg out of the box. "
                          "Please remember to apply defaults for those yourself after parsing! Additionally in py3.11 "
                          "there is a bug where the argparse.SUPRESS keyword is fed into an argument converted leading "
                          "to a crash for positional values that have both argpase.SUPRESS and type=... . "
                          "So you need to omit type and convert it afterwards yourself."
                          "Alternatively you can use ArgparseEndpoint with .set_implicit_argument_default(...) "
                          "instead of raw argparse.", stacklevel=2)
            parser.add_argument(argument.name, help=argument.help,  # Positional
                                default=argparse.SUPPRESS, # type=argument.type,  # py3.11 argparse bug fix
                                choices=argument.choices if argument.choices else None,
                                metavar=argument.metavar, nargs="?" if not argument.required else 1)
            parser.add_argument(*names, help=argument.help, dest=argument.name,  # Kwarg
                                default=argparse.SUPPRESS, type=argument.type,
                                choices=argument.choices if argument.choices else None,
                                metavar=argument.metavar, required=argument.required)
            if isinstance(parser, ArgparseEndpoint):
                parser.set_implicit_argument_default(argument.name, argument.default)
                parser.set_implicit_argument_type(argument.name, argument.type)

    def to_argparse(self) -> ArgumentParser:
        """Build a standalone :class:`argparse.ArgumentParser`.

        :returns: Populated argparse parser mirroring this endpoint.
        """
        parser = ArgumentParser(prog=self._name, description=self._help_str)
        for argument in self._arguments:
            self._add_arg_to_argparse_like(argument, parser)
        return parser

    def to_argparse_endpoint(self) -> "ArgparseEndpoint":
        """Build an :class:`ArgparseEndpoint` from current argument definitions.

        :returns: Populated :class:`ArgparseEndpoint`.
        """
        aep = ArgparseEndpoint(prog=self._name, description=self._help_str)
        for argument in self._arguments:
            self._add_arg_to_argparse_like(argument, aep)
        return aep

    @classmethod
    def from_function(cls, function: _a.Callable, name: str, help_str: str = "", snakecase_replacement: str = "-",
                      function_argument_ignore_prefix: str = "_",
                      ignored_function_arguments: tuple[str, ...] = ("cls", "self"), *,
                      generate_shortforms_and_letters: bool = True, calling_func: CallingFunc | None = None,
                      parser: Parser | None = None) -> _te.Self:
        """Create an endpoint by analyzing a callable signature.

        :param function: Source callable used to generate arguments.
        :param name: Endpoint/program display name.
        :param help_str: Explicit help override; inferred when empty.
        :param snakecase_replacement: Replacement for underscores in metavars.
        :param function_argument_ignore_prefix: What function arguments with prefix should be ignored.
        :param ignored_function_arguments: What argument names should be ignored.
        :param generate_shortforms_and_letters: Whether to auto-generate aliases.
        :param calling_func: Optional custom invocation wrapper.
        :param parser: Optional parser backend implementation.
        :returns: Configured endpoint instance.
        """
        ep = cls(name=name, help_str=help_str, function=function, calling_func=calling_func, parser=parser)
        analysis: Analysis = get_analysis(function, break_types=False)

        for arg in analysis.arguments:
            if arg.name in ignored_function_arguments or arg.name.startswith(function_argument_ignore_prefix) or arg.is_kwarg:
                continue
            ep.add_argument(
                name=arg.name,
                #name=arg.name.replace("_", snakecase_replacement),
                types=list(arg.type_choices) or [arg.type],
                default=arg.default,
                choices=list(arg.choices),
                help_=arg.doc_help,
                required=isinstance(arg.default, NoDefault),
                positional_only=arg.pos_only, kwarg_only=arg.kwarg_only,
                nargs=NArgsMode.ONE_OR_MORE if not arg.is_arg else NArgsMode.ZERO_OR_MORE,
                metavar=arg.name.replace("_", snakecase_replacement) if not arg.pos_only else None
            )

        if generate_shortforms_and_letters:
            ep.guess_letters_and_shortforms()
        if not help_str:
            ep.set_help_str(analysis.help_.replace("\n", " "))
        return ep

    def __repr__(self) -> str:
        """Return debug representation including argument overview.

        :returns: Representation string.
        """
        args = [
            f"{arg.name}: {arg}"
            for arg in self._arguments
        ]
        return f"Endpoint(arguments={args})"


class ArgparseEndpoint(EndpointProtocol):
    """Adapter implementing :class:`EndpointProtocol` on top of argparse.

    The wrapper keeps a stable endpoint API while delegating parsing behavior
    to :class:`argparse.ArgumentParser`.
    """

    def __init__(self, *, prog: str = "endpoint", description: str | None = None, add_help: bool = False) -> None:
        """Create an argparse-backed endpoint.

        :param prog: Program name used by argparse help output.
        :param description: Optional argparse description text.
        :param add_help: Whether argparse should auto-add ``-h/--help``.
        """
        self._parser = ArgumentParser(prog=prog, description=description, add_help=add_help)
        self._func: _a.Callable | None = None
        self._help_str: str = ""
        self._argument_defaults: dict[str, _ty.Any] = dict()
        self._argument_types: dict[str, _ty.Any] = dict()

    def set_calling_func(self, func: _a.Callable) -> None:
        """Set the callback executed after parsing.

        :param func: Callable receiving parsed args and kwargs.
        """
        self._func = func

    def call(self, args: tuple[_ty.Any], kwargs: dict[str, _ty.Any]) -> None:
        """Execute the configured callback with parsed values.

        :param args: Positional values passed to callback.
        :param kwargs: Keyword values passed to callback.
        """
        if self._func is None:
            return
        self._func(*args, **kwargs)

    def add_argument(self, *args, **kwargs) -> None:
        """Delegate argument registration to underlying argparse parser."""
        self._parser.add_argument(*args, **kwargs)

    def set_implicit_argument_default(self, arg_name: str, default: _ty.Any) -> None:
        """Store fallback default for mixed positional/keyword argument cases.

        :param arg_name: Argument destination name.
        :param default: Value used when argparse suppresses the destination.
        """
        self._argument_defaults[arg_name] = default

    def set_implicit_argument_type(self, arg_name: str, default: _ty.Any) -> None:
        """Store type for mixed positional/keyword argument cases.

        :param arg_name: Argument destination name.
        :param default: Type used when argparse "cannot" convert the type due to a bug.
        """
        self._argument_types[arg_name] = default

    def clear_implicit_argument_defaults(self) -> None:
        """Remove all stored implicit defaults."""
        self._argument_defaults.clear()

    def generate_help(self, prog: str = "endpoint", automatic_help_args: tuple[str, ...] = ("-?", "-h", "--?", "--help")
                      ) -> str:
        """Generate help output for the wrapped argparse parser.

        :param prog: Program name override for formatter compatibility.
        :param automatic_help_args: Unused compatibility parameter.
        :returns: Generated help text.
        """
        formatter = self._parser.formatter_class(prog)  # Keep argparse formatting but allow overriding prog
        base = self._parser.format_help()
        if self._help_str:
            return f"{self._help_str.rstrip()}\n\n{base}"
        return base

    def get_help_str(self) -> str:
        """Return custom prepended help text.

        :returns: Endpoint help prefix.
        """
        return self._help_str

    def set_help_str(self, help_str: str) -> None:
        """Set custom prepended help text.

        :param help_str: Text prepended before argparse help output.
        """
        self._help_str = help_str

    def get_argparse(self) -> ArgumentParser:
        """Expose the underlying argparse parser instance.

        :returns: Wrapped :class:`ArgumentParser`.
        """
        return self._parser

    def set_argparse(self, parser: ArgumentParser) -> None:
        """Replace the wrapped argparse parser.

        :param parser: Parser instance to wrap.
        """
        self._parser = parser

    def parse(self, arguments: list[str] | None = None, *, skip_first_arg: bool = True,
              automatic_help_args: tuple[str, ...] = ("-?", "-h", "--?", "--help")
              ) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
        """Parse argv with argparse and invoke callback when configured.

        :param arguments: Explicit argv list; defaults to ``sys.argv``.
        :param skip_first_arg: Skip program path token.
        :param automatic_help_args: Tokens that trigger help-return shortcut.
        :returns: Tuple of positional values (always empty) and parsed kwargs.
        """
        argv = sys.argv if arguments is None else arguments
        if skip_first_arg and argv:
            argv = argv[1:]

        if automatic_help_args and any(a in argv for a in automatic_help_args):
            print(self.generate_help(prog=self._parser.prog))
            sys.exit(0)
            return list(), dict()

        ns = self._parser.parse_args(argv)

        for argument_name, argument_default in self._argument_defaults.items():
            if not hasattr(ns, argument_name) or getattr(ns, argument_name) == argparse.SUPPRESS:
                setattr(ns, argument_name, argument_default)
            elif type_ := self._argument_types.get(argument_name):
                setattr(ns, argument_name, type_(getattr(ns, argument_name)))

        parsed = vars(ns)

        self.call(tuple(), parsed)
        return list(), parsed

    def __repr__(self) -> str:
        """Return concise debug representation for the adapter.

        :returns: Representation string.
        """
        return f"Endpoint(prog={self._parser.prog!r}, has_func={self._func is not None}, args={len(self._parser._actions)})"
