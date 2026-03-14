import sys

# Internal import
from .endpoints import EndpointProtocol, NativeEndpoint, CallingFunc
from .native_parser import Parser
from .structure import _Node, rename_structure, Structure, add_command_to_structure, StructureError, structure_help

# Standard typing imports for aps
import typing_extensions as _te
import collections.abc as _a
import typing as _ty

if _ty.TYPE_CHECKING:
    import _typeshed as _tsh
import types as _ts

__all__ = ["Interface"]


class Interface:
    """Command router that maps CLI paths to endpoint parsers/callables.

    The interface keeps a command tree, resolves the best matching path prefix,
    and delegates remaining tokens to the selected endpoint parser.
    """

    def __init__(self, interface_name: str, default_endpoint_or_message: EndpointProtocol | _a.Callable | str | None = None,
                 endpoint_calling_func: CallingFunc | None = None,
                 automatic_help_args: tuple[str, ...] = ("-?", "-h", "--?", "--help"),
                 automatic_long_help_args: tuple[str, ...] = ("--?", "--help"), help_separator: str = " -> ",
                 structure: _Node | None = None, add_to_structure: bool = True, *, path_separator: str = "::",
                 function_argument_ignore_prefix: str = "___",
                 ignored_function_arguments: tuple[str, ...] = ("cls", "self"),
                 generate_shortforms_and_letters: bool = True,
                 native_endpoint_default_parser: Parser | None = None) -> None:
        """Initialize interface configuration and root structure.

        :param interface_name: Root command name.
        :param default_endpoint_or_message: Default endpoint/callable/message for unmatched paths.
        :param endpoint_calling_func: Optional wrapper invoked around endpoint calls.
        :param automatic_help_args: Tokens that trigger built-in help output.
        :param automatic_long_help_args: Subset of help tokens that always request endpoint help.
        :param help_separator: Separator used in rendered path/help output.
        :param structure: Optional pre-built structure tree to adopt.
        :param add_to_structure: Whether unknown path segments may be created on registration.
        :param path_separator: Token separator used while registering paths.
        :param function_argument_ignore_prefix: The prefix of arguments that should be ignored while using .from_func
        :param ignored_function_arguments: What argument names should be ignored while using .from_func
        :param generate_shortforms_and_letters: Whether function-derived endpoints auto-generate aliases.
        :param native_endpoint_default_parser: Parser preset for auto-wrapped callables.
        :return: None.
        :raises ValueError: If long-help tokens are not included in ``automatic_help_args``.
        """
        self._interface_name: str = interface_name
        # if default_endpoint_or_message is None:
        #     default_endpoint = AutoEndpoint(lambda: print("This is not a valid endpoint."), "")
        if isinstance(default_endpoint_or_message, str):
            default_endpoint = NativeEndpoint.from_function(lambda: print(default_endpoint_or_message), "",
                                                            function_argument_ignore_prefix=function_argument_ignore_prefix,
                                                            ignored_function_arguments=ignored_function_arguments,
                                                            generate_shortforms_and_letters=generate_shortforms_and_letters,
                                                            parser=native_endpoint_default_parser)
        elif default_endpoint_or_message is None:
            default_endpoint = default_endpoint_or_message
        elif not isinstance(default_endpoint_or_message, EndpointProtocol):
            default_endpoint = NativeEndpoint.from_function(default_endpoint_or_message, "",
                                                            function_argument_ignore_prefix=function_argument_ignore_prefix,
                                                            ignored_function_arguments=ignored_function_arguments,
                                                            generate_shortforms_and_letters=generate_shortforms_and_letters,
                                                            parser=native_endpoint_default_parser)
        else:
            default_endpoint = default_endpoint_or_message
        self._default_endpoint: EndpointProtocol | None = default_endpoint  # Print structure help if None
        if endpoint_calling_func is not None and self._default_endpoint is not None:
            self._default_endpoint.set_calling_func(endpoint_calling_func)
        self._endpoint_calling_func: CallingFunc | None = endpoint_calling_func
        self._automatic_help_args: tuple[str, ...] = automatic_help_args
        if not all(x in automatic_help_args for x in automatic_long_help_args):
            raise ValueError(f"Not all long help arg ({automatic_long_help_args}) are in the normal help args "
                             f"({automatic_help_args}).")
        self._automatic_long_help_args: tuple[str, ...] = automatic_long_help_args
        self._help_separator: str = help_separator
        self._structure: _Node
        if structure is not None:
            rename_structure(structure, interface_name)
            self._structure = structure
        else:
            self._structure = Structure(interface_name)
        self._add_to_structure: bool = add_to_structure
        self._path_separator: str = path_separator
        self._function_argument_ignore_prefix: str = function_argument_ignore_prefix
        self._ignored_function_arguments: tuple[str, ...] = ignored_function_arguments
        self._generate_shortforms_and_letters: bool = generate_shortforms_and_letters
        self._native_endpoint_default_parser: Parser = native_endpoint_default_parser

    @staticmethod
    def _error(i: int, command_string: str) -> None:
        """Print a caret marker at one character index in a command string.

        :param i: Error index within ``command_string``.
        :param command_string: Full command string.
        :return: None.
        """
        print(f"{command_string}\n{' ' * i + '^'}")

    @staticmethod
    def _lst_error(
        i: int, arg_i: int, command_lst: list[str], do_exit: bool = False
    ) -> None:
        """Print a caret marker for a tokenized command line.

        :param i: Index of the failing argument in ``command_lst``.
        :param arg_i: Character offset within the failing argument.
        :param command_lst: Tokenized command line.
        :param do_exit: Whether to terminate process with status ``1`` afterwards.
        :return: None.
        :raises SystemExit: If ``do_exit`` is ``True``.
        """
        length = sum(len(item) for item in command_lst[:i]) + i
        print(" ".join(command_lst) + "\n" + " " * (length + arg_i) + "^")
        if do_exit:
            sys.exit(1)

    def _check_path(self, path: str) -> bool:
        """Check whether a path exists in the current command tree.

        :param path: Path expression using the configured separator.
        :return: ``True`` if path lookup succeeds, otherwise ``False``.
        """
        try:
            add_command_to_structure(path, None, None, self._structure, create_path=False,
                                     separator=self._path_separator)
        except StructureError:
            return False
        return True

    def path(self, path: str, endpoint: EndpointProtocol | _a.Callable | None = None, help_: str | None = None, /, replace_endpoint: bool = True) -> None:
        """Register or update one command path endpoint.

        Non-endpoint callables are wrapped into :class:`NativeEndpoint` using
        this interface's parser-generation options.

        :param path: Command path to register.
        :param endpoint: Endpoint object or callable.
        :param help_: Optional path help text.
        :param replace_endpoint: Whether existing endpoint replacement is allowed.
        :return: None.
        :raises StructureError: If registration violates structure constraints.
        """
        if endpoint is not None:
            if not isinstance(endpoint, EndpointProtocol):
                endpoint = NativeEndpoint.from_function(endpoint, "",
                                                        function_argument_ignore_prefix=self._function_argument_ignore_prefix,
                                                        ignored_function_arguments=self._ignored_function_arguments,
                                                        generate_shortforms_and_letters=self._generate_shortforms_and_letters,
                                                        parser=self._native_endpoint_default_parser)
            if self._endpoint_calling_func is not None:
                endpoint.set_calling_func(self._endpoint_calling_func)
        else:
            if help_ is None:
                help_ = ""
        add_command_to_structure(path, help_, endpoint, self._structure, create_path=self._add_to_structure,
                                 replace_endpoint=replace_endpoint, separator=self._path_separator)

    def _parse_pre_args(self, arguments: list[str], skip_first_arg: bool) -> tuple[list[str], list[str], EndpointProtocol | None, _Node]:
        """Resolve path-prefix tokens before endpoint argument parsing.

        :param arguments: Raw CLI tokens.
        :param skip_first_arg: Whether to drop program/script token first.
        :return: Tuple of ``(matched_path_tokens, remaining_tokens, endpoint, substructure)``.
        """
        current_level: _Node = self._structure
        if skip_first_arg:
            arguments = arguments[1:]
            current_level: _Node = current_level[current_level.keys()[0]]  # Skip base node
        i: int = 0
        for i, ix in enumerate(arguments):
            if ix not in current_level:
                break
            current_level = current_level[ix]
        return arguments[:i], arguments[i:], current_level.get_content(), current_level

    def parse_cli(self, arguments: list[str] | None = None, *, skip_first_arg: bool = True
                  ) -> tuple[str, tuple[list[_ty.Any], dict[str, _ty.Any]]]:
        """Parse CLI input, dispatch path, and parse endpoint arguments.

        :param arguments: Raw CLI tokens, or ``None`` to use ``sys.argv``.
        :param skip_first_arg: Whether to skip first token during parsing.
        :return: ``(resolved_path, parsed_endpoint_arguments)``.
        :raises SystemExit: On automatic help output paths.
        """
        if arguments is None:
            arguments = sys.argv
        if len(arguments) == 1:  # TODO: Fix properly?
            arguments.append("")  # Fixes parsing when we have no structure
        (pre_args, args_to_parse, endpoint, substructure) = self._parse_pre_args(arguments, skip_first_arg)
        endpoint: EndpointProtocol | None = endpoint or self._default_endpoint
        path: str = self._help_separator.join(pre_args)

        if endpoint is None:  # No path endpoint and also no default endpoint
            print(structure_help(substructure, separator=self._help_separator))
            sys.exit(0)
            return path, (list(), dict())

        for arg in args_to_parse:
            if arg in self._automatic_help_args:
                if (len(substructure.get_available_paths()) > 1
                        and arg not in self._automatic_long_help_args):  # Paths are available after this node
                    print(structure_help(substructure, separator=self._help_separator))
                else:  # Only one endpoint or no endpoint and no paths
                    print(endpoint.generate_help(prog=path, automatic_help_args=self._automatic_help_args
                                                                                + self._automatic_long_help_args))
                sys.exit(0)
                return path, (list(), dict())

        # We do the help ourselves
        parsed_arguments: tuple[list[_ty.Any], dict[str, _ty.Any]] = endpoint.parse(args_to_parse,
                                                                                    skip_first_arg=skip_first_arg,
                                                                                    automatic_help_args=tuple())

        return path, parsed_arguments
