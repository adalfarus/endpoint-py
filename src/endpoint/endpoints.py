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
from .native_parser import NativeParser, ArgumentParsingError, Argument, Parser, NArgsMode, NArgsSpec
from .parser_collection import LightParser, FastParser, TokenStreamParser, ArgparseParser, StrictDFAParser, TinyParser

# Standard typing imports for aps
import typing_extensions as _te
import collections.abc as _a
import typing as _ty

if _ty.TYPE_CHECKING:
    import _typeshed as _tsh
import types as _ts

__all__ = ["EndpointError", "EndpointProtocol", "NativeEndpoint", "ArgparseEndpoint"]


class EndpointError(Exception):
    """TBA"""

    def __init__(self, message: str) -> None:
        super().__init__(message)


#@_ty.runtime_checkable (_ty.Protocol)
class EndpointProtocol(metaclass=abc.ABCMeta):
    @abc.abstractmethod
    def call(self, args: list[_ty.Any], kwargs: dict[str, _ty.Any]) -> None: ...
    @abc.abstractmethod
    def set_calling_func(self, func: _a.Callable) -> None: ...
    @abc.abstractmethod
    def add_argument(self, *args, **kwargs) -> None: ...
    @abc.abstractmethod
    def generate_help(self, prog: str = "endpoint", automatic_help_args: tuple[str, ...] = ("-?", "-h", "--?", "--help")
                      ) -> str: ...
    @abc.abstractmethod
    def get_help_str(self) -> str: ...
    @abc.abstractmethod
    def set_help_str(self, help_str: str) -> None: ...
    @abc.abstractmethod
    def parse(self, arguments: list[str] | None = None, *, skip_first_arg: bool = True,
              automatic_help_args: tuple[str, ...] = ("-?", "-h", "--?", "--help")
              ) -> tuple[list[_ty.Any], dict[str, _ty.Any]]: ...
    @abc.abstractmethod
    def __repr__(self) -> str: ...


NARGS_TYPE = (NArgsMode
              | NArgsMode.ONE_OR_MORE
              | NArgsMode.ZERO_OR_MORE
              | type[NArgsMode.ONE_OR_MORE]
              | type[NArgsMode.ZERO_OR_MORE]
              | NArgsMode.NUMBER
              | NArgsMode.MIN_MAX)
D = _ty.TypeVar("D")
class ArgumentChanges(_ty.TypedDict, total=False):
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
P = _ty.ParamSpec("P")
R = _ty.TypeVar("R")
class CallingFunc(_ty.Protocol[P, R]):
    def __call__(self, endpoint: EndpointProtocol, fn: _a.Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R: ...
class NativeEndpoint(EndpointProtocol):
    """Represents the endpoint of a trace from an argument structure object.

    The `EndPoint` class serves as a container for functions associated with
    a particular argument path, providing a way to call the function with
    predefined arguments and keyword arguments.

    Attributes:
        _arguments (list): A list of arguments known to the endpoint.
        _function (_ts.FunctionType): The actual function associated with this endpoint,
            which will be called when the endpoint is invoked.
    """
    DEFAULT_PARSER: type[Parser] = NativeParser

    def __init__(self, name: str, help_str: str = "", function: _a.Callable | None = None, *,
                 calling_func: CallingFunc | None = None, parser: Parser | None = None) -> None:
        self._arguments: list[Argument] = list()
        self._function: _a.Callable | None = function
        self._name: str = name
        self._help_str: str = help_str
        self._calling_func: CallingFunc | None = calling_func
        self._parser: Parser = parser or self.DEFAULT_PARSER({})

    def call(self, args: list[_ty.Any], kwargs: dict[str, _ty.Any]) -> None:
        """Executes the internal function using the specified arguments.

        This method forwards all positional and keyword arguments to the stored
        function, allowing flexible invocation from various contexts.

        Args:
            *args: Positional arguments to pass to the function.
            **kwargs: Keyword arguments to pass to the function.
        """
        if self._function is None:
            return
        if self._calling_func is not None:
            self._calling_func(self, self._function, *args, **kwargs)
        else:
            self._function(*args, **kwargs)

    def set_calling_func(self, func: _a.Callable | None) -> None:
        self._calling_func = func

    # TODO: Make more efficient?
    def _check_and_sort_arguments(self) -> list[Argument]:
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
        """
        Adds a new argument definition to the endpoint.

        This method registers a new argument including its type information,
        default value, validation rules, and display metadata.

        Args:
            name (str): The primary name of the argument.
            alternative_names (list[str] | None):
                Optional alternative long-form names (e.g., aliases).
                If None, an empty list is used.
            letter (str | None):
                Optional single-letter short flag.
                May only be set for boolean arguments (i.e., when `bool` is
                included in `types`). Raises ValueError otherwise.
            types (list[type[D]] | None):
                A list of allowed Python types for this argument.
                These are also processed into structured type metadata using
                `break_type()` for internal use.
            default (D | None): The default value if the argument is not provided.
            choices (list[D] | None): Optional list of valid values for the argument. If provided, input must match one of these values.
            required (bool): Whether this argument must be successful in order for the parsing to continue (see help for nargs).
            positional_only:
            kwarg_only:
            help_ (str): Help text describing the argument.
            metavar (str | None): Display name used in help output. Defaults to `name` if not provided.
            nargs: How many command line arguments the argument can/needs to capture to be considered successful.
            checking_func: Checks parsed argument and returns it (this checks if x in choices if not set). If something is wrong it returns an ArgumentParsingError.
            automatically_reorder_arguments: Reorders arguments based on required. That way required arguments will get positionals first.
        Raises: ValueError: If `letter` is set but `bool` is not included in `types`.
        Notes:
            - All type hints are processed through `break_type()` and stored
              as `broken_types` for structured type handling.
            - After insertion, `_check_arguments()` is called to ensure
              consistency across the endpoint.
        """
        if "-" in name:  # Name is namespace so we need to guarantee a valid name
            if positional_only:
                raise ValueError("Positional only arguments cannot have '-' in it's name.")
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
        elif isinstance(nargs, NArgsMode.ONE_OR_MORE):
            nargs = NArgsMode.MIN_MAX(1, None, nargs.spec)
        elif nargs == NArgsMode.ZERO_OR_MORE:
            nargs = NArgsMode.MIN_MAX(0, None)
        elif isinstance(nargs, NArgsMode.ZERO_OR_MORE):
            nargs = NArgsMode.MIN_MAX(0, None, nargs.spec)
        elif isinstance(nargs, NArgsMode.NUMBER):
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
        """
        Modifies an existing argument definition.

        This method replaces an existing `Argument` instance with an updated
        version using dataclass replacement semantics.

        Args:
            name (str):
                The name of the argument to modify.
            automatically_reorder_arguments: Reorders arguments based on required. That way required arguments will get positionals first.

            **kwargs:
                Fields to update on the argument. Any valid `Argument`
                field may be provided except `broken_types`, which is
                automatically recalculated when `types` is updated.

        Raises:
            ValueError:
                If no argument with the specified `name` exists.

        Notes:
            - If `types` is provided in `kwargs`, `broken_types` will be
              automatically regenerated using `break_type()`.
            - Direct modification of `broken_types` is not allowed.
            - The updated argument replaces the existing one in-place.
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
        return self._arguments.copy()

    def guess_letters_and_shortforms(self, guess_letters_: bool = True, guess_prefix_shortforms_: bool = True,
                                     guess_shortforms_: bool = True) -> None:
        """
        Automatically generates short and alternative names for all arguments.

        This method derives:

            - A short prefix-based alternative name for every argument
            - A secondary shortform alternative name
            - A single-letter flag for boolean arguments (when applicable)

        It uses:

            - `guess_prefix_shortforms()` for compact prefix-style names
            - `guess_shortforms()` for more descriptive short alternatives
            - `guess_letters()` to assign unique short letters to boolean arguments

        Notes:
            - Only arguments that include `bool` in their `types`
              are eligible for single-letter assignment.
            - Existing alternative names and letters are overwritten.
            - This method does not validate uniqueness conflicts beyond
              what the helper functions enforce.
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

    def generate_help(self, prog: str = "endpoint", automatic_help_args: tuple[str, ...] = ("-?", "-h", "--?", "--help"),
                      width: int | None = None) -> str:
        """
        Render an argparse-like help text for this endpoint.

        Args:
            prog: Program/command name shown in the usage line.
            automatic_help_args: Which arguments lead to help being displayed. This is passed so the help can display all help args.
            width: Target wrap width for help text.

        Returns:
            A formatted help string similar to argparse's help output.
        """
        if width is None:  # Try to get terminal width
            width = shutil.get_terminal_size(fallback=(88, 24)).columns

        # Arg usage
        usage_fragments: list[str] = list()
        usage_fragments.append(" ".join(f"[{help_arg}]" for help_arg in automatic_help_args))
        usage_fragments.append(" ".join(a.usage_fragment() for a in self._arguments))
        usage = " ".join(usage_fragments)
        out = [f"usage: {prog} {usage}".rstrip(), "", "options:"]

        if self._help_str:
            out.insert(1, f"explaination: {self._help_str}")

        left = [a.left_column() for a in self._arguments]
        left_w = min(max((len(s) for s in left), default=0), 40)

        indent = "  "
        gap = "  "

        for a, l in zip(self._arguments, left):
            right = a.right_column()

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
        return self._help_str

    def set_help_str(self, help_str: str) -> None:
        self._help_str = help_str

    def parse(self, arguments: list[str] | None = None, *, skip_first_arg: bool = True,
              automatic_help_args: tuple[str, ...] = ("-?", "-h", "--?", "--help")
              ) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
        """Parses CLI arguments and calls the endpoint.

        This method processes command-line input, navigates the argument structure,
        and calls the relevant endpoint function. If the path is unmatched, it calls
        the `default_endpoint`.

        Args:
            automatic_help_args:
            arguments (list, optional): Arguments to be parsed, if set to None sys.argv is used.
            skip_first_arg (bool): Defaults to true, this is to skip the path of the file that was called as that
                is often not what you want to get parsed. This parameter also influences if the base node is skipped.
        """
        if arguments is None:
            arguments = sys.argv
        if skip_first_arg:
            arguments = arguments[1:]

        for arg in arguments:
            if arg in automatic_help_args:
                print(self.generate_help(prog=self._name))
                sys.exit(0)
                return list(), dict()

        if not self._parser.IS_FULLY_FEATURED:
            warnings.warn(f"The chosen parser '{self._parser}' is not fully features. This means features like: "
                          f"\n- Positionals\n- Keywords\n- Choices\n- Pos-only\n- Keyword-only\n- Pos or Keyword\n- "
                          f"Complex types\n- ...", stacklevel=2)
        parsed_pos, parsed_kwarg = self._parser.parse_args(arguments, self.copy_arguments(), self._name)
        self.call(args=parsed_pos, kwargs=parsed_kwarg)

        return parsed_pos, parsed_kwarg

    @staticmethod
    def _add_arg_to_argparse_like(argument: Argument, parser: _ty.Any) -> None:
        is_bool: bool = bool == argument.broken_type.base_type or (
                    argument.broken_type.base_type == _ty.Union and bool in argument.broken_type.arguments)
        names = [f"--{x}" for x in [argument.metavar, *argument.alternative_names]]
        if argument.letter:
            names.append(f"-{argument.letter}")

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
                          "Please remember to apply defaults for those yourself after parsing! "
                          "Alternatively you can use ArgparseEndpoint with .set_implicit_argument_default(...) "
                          "instead of raw argparse.", stacklevel=2)
            parser.add_argument(argument.name, help=argument.help,  # Positional
                                default=argparse.SUPPRESS, type=argument.type,
                                choices=argument.choices if argument.choices else None,
                                metavar=argument.metavar, nargs="?")
            parser.add_argument(*names, help=argument.help, dest=argument.name,  # Kwarg
                                default=argparse.SUPPRESS, type=argument.type,
                                choices=argument.choices if argument.choices else None,
                                metavar=argument.metavar, required=argument.required)
            if isinstance(parser, ArgparseEndpoint):
                parser.set_implicit_argument_default(argument.name, argument.default)

    def to_argparse(self) -> ArgumentParser:
        parser = ArgumentParser(description=self._help_str)
        for argument in self._arguments:
            self._add_arg_to_argparse_like(argument, parser)
        return parser

    def to_argparse_endpoint(self) -> "ArgparseEndpoint":
        aep = ArgparseEndpoint(description=self._help_str)
        for argument in self._arguments:
            self._add_arg_to_argparse_like(argument, aep)
        return aep

    @classmethod
    def from_function(cls, function: _a.Callable, name: str, help_str: str = "", snakecase_replacement: str = "-", *,
                      generate_shortforms_and_letters: bool = True, calling_func: CallingFunc | None = None,
                      parser: Parser | None = None) -> _ty.Self:
        ep = cls(name=name, help_str=help_str, function=function, calling_func=calling_func, parser=parser)
        analysis: Analysis = get_analysis(function, break_types=False)

        for arg in analysis.arguments:
            if arg.name in {"cls", "self"} or arg.is_kwarg:
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
        args = [
            f"{arg.name}: {arg}"
            for arg in self._arguments
        ]
        return f"Endpoint(arguments={args})"


class ArgparseEndpoint(EndpointProtocol):
    """
    A small wrapper around argparse that:
    - keeps a stable API surface for your EndpointProtocol
    - can modify (remove+readd) arguments
    - can auto-handle help flags before parsing
    - returns parsed args as dict[str, Any] and calls a configured function
    """

    def __init__(self, *, prog: str = "endpoint", description: str | None = None, add_help: bool = False) -> None:
        self._parser = ArgumentParser(prog=prog, description=description, add_help=add_help)
        self._func: _a.Callable | None = None
        self._help_str: str = ""
        self._argument_defaults: dict[str, _ty.Any] = dict()

    def set_calling_func(self, func: _a.Callable) -> None:
        self._func = func

    def call(self, args: tuple[_ty.Any], kwargs: dict[str, _ty.Any]) -> None:
        if self._func is None:
            return
        self._func(*args, **kwargs)

    def add_argument(self, *args, **kwargs) -> None:
        self._parser.add_argument(*args, **kwargs)

    def set_implicit_argument_default(self, arg_name: str, default: _ty.Any) -> None:
        self._argument_defaults[arg_name] = default

    def clear_implicit_argument_defaults(self) -> None:
        self._argument_defaults.clear()

    def generate_help(self, prog: str = "endpoint", automatic_help_args: tuple[str, ...] = ("-?", "-h", "--?", "--help")
                      ) -> str:
        formatter = self._parser.formatter_class(prog)  # Keep argparse formatting but allow overriding prog
        base = self._parser.format_help()
        if self._help_str:
            return f"{self._help_str.rstrip()}\n\n{base}"
        return base

    def get_help_str(self) -> str:
        return self._help_str

    def set_help_str(self, help_str: str) -> None:
        self._help_str = help_str

    def get_argparse(self) -> ArgumentParser:
        return self._parser

    def set_argparse(self, parser: ArgumentParser) -> None:
        self._parser = parser

    def parse(self, arguments: list[str] | None = None, *, skip_first_arg: bool = True,
              automatic_help_args: tuple[str, ...] = ("-?", "-h", "--?", "--help")
              ) -> tuple[list[_ty.Any], dict[str, _ty.Any]]:
        """
        Parse arguments and call the endpoint function (if set).

        Returns:
            dict[str, Any]: parsed args as a dict

        Notes:
            - If any token in `automatic_help_args` is present, this returns {"help": <help_str>}
              and does NOT call the endpoint func.
            - `replacement_parser` is accepted for API compatibility. Only "native" is supported here.
        """
        argv = sys.argv if arguments is None else arguments
        if skip_first_arg and argv:
            argv = argv[1:]

        if automatic_help_args and any(a in argv for a in automatic_help_args):
            return list(), {"help": self.generate_help(prog=self._parser.prog)}

        ns = self._parser.parse_args(argv)

        for argument_name, argument_default in self._argument_defaults:
            if not hasattr(ns, argument_name):
                setattr(ns, argument_name, argument_default)

        parsed = vars(ns)

        self.call(tuple(), parsed)
        return list(), parsed

    def __repr__(self) -> str:
        return f"Endpoint(prog={self._parser.prog!r}, has_func={self._func is not None}, args={len(self._parser._actions)})"
