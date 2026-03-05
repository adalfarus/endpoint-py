import sys

# Internal import
from .endpoints import EndpointProtocol, NativeEndpoint
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
    """A command-line argument parser that uses structured arguments and endpoints.

    Argumint is designed to parse CLI arguments using a predefined argument structure.
    It allows users to define and manage argument paths, replace the argument structure,
    and execute endpoints based on parsed arguments.
    """

    def __init__(self, interface_name: str, default_endpoint_or_message: EndpointProtocol | _a.Callable | str | None = None,
                 endpoint_calling_func: _a.Callable | None = None,
                 automatic_help_args: tuple[str, ...] = ("-?", "-h", "--?", "--help"),
                 automatic_long_help_args: tuple[str, ...] = ("--?", "--help"), help_separator: str = " -> ",
                 structure: _Node | None = None, add_to_structure: bool = True, *, path_separator: str = "::",
                 generate_shortforms_and_letters: bool = True, native_endpoint_default_parser: str = "native") -> None:
        self._interface_name: str = interface_name
        # if default_endpoint_or_message is None:
        #     default_endpoint = AutoEndpoint(lambda: print("This is not a valid endpoint."), "")
        if isinstance(default_endpoint_or_message, str):
            default_endpoint = NativeEndpoint.from_function(lambda: print(default_endpoint_or_message), "",
                                                            generate_shortforms_and_letters=generate_shortforms_and_letters,
                                                            parser=native_endpoint_default_parser)
        elif not isinstance(default_endpoint_or_message, EndpointProtocol):
            default_endpoint = NativeEndpoint.from_function(default_endpoint_or_message, "",
                                                            generate_shortforms_and_letters=generate_shortforms_and_letters,
                                                            parser=native_endpoint_default_parser)
        else:
            default_endpoint = default_endpoint_or_message
        self._default_endpoint: EndpointProtocol | None = default_endpoint  # Print structure help if None
        self._endpoint_calling_func: _a.Callable | None = endpoint_calling_func
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
        self._generate_shortforms_and_letters: bool = generate_shortforms_and_letters
        self._native_endpoint_default_parser: str = native_endpoint_default_parser

    @staticmethod
    def _error(i: int, command_string: str) -> None:
        """Displays a caret (`^`) pointing to an error in the command string.

        Args:
            i (int): Index in the command string where the error occurred.
            command_string (str): The command string with the error.
        """
        print(f"{command_string}\n{' ' * i + '^'}")

    @staticmethod
    def _lst_error(
        i: int, arg_i: int, command_lst: list[str], do_exit: bool = False
    ) -> None:
        """Displays an error caret in a list of command arguments.

        This method calculates the error position in a CLI argument list, displaying
        a caret to indicate where the error was found. Optionally, it can exit
        the program.

        Args:
            i (int): Index of the problematic argument in the list.
            arg_i (int): Position within the argument string to place the caret.
            command_lst (list[str]): List of command-line arguments.
            do_exit (bool, optional): If True, exits the program. Defaults to False.
        """
        length = sum(len(item) for item in command_lst[:i]) + i
        print(" ".join(command_lst) + "\n" + " " * (length + arg_i) + "^")
        if do_exit:
            sys.exit(1)

    def _check_path(self, path: str) -> bool:
        """Verifies if a specified path exists within the argument structure.

        This method traverses the structure to confirm whether each segment of the
        path is valid and points to an existing command or subcommand.

        Args:
            path (str): The dot-separated path to check within the argument structure.
            separator (str): To change the separator to use.

        Returns:
            bool: True if the path exists, False otherwise.
        """
        try:
            add_command_to_structure(path, None, None, self._structure, create_path=False,
                                     separator=self._path_separator)
        except StructureError:
            return False
        return True

    def path(self, path: str, endpoint: EndpointProtocol | _a.Callable | None = None, help_: str | None = None, /, replace_endpoint: bool = True) -> None:
        """
        This method checks if the specified path exists in the argument structure
        before replacing the existing endpoint with the new one. If the path does
        not exist, an error is raised.

        Args:
            path (str): The path where the endpoint will be replaced.
            help_ (str): The help string for the path.
            endpoint (EndpointProtocol): The new endpoint to assign to the specified path.
            replace_endpoint (bool): If the new Endpoint should be able to replace another endpoint.

        Raises:
            StructureError: If the specified path does not exist in the argument structure.
        """
        if endpoint is not None:
            if not isinstance(endpoint, EndpointProtocol):
                endpoint = NativeEndpoint.from_function(endpoint, "",
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
        """Parses CLI arguments and calls the endpoint based on the parsed path.

        This method processes command-line input, navigates the argument structure,
        and calls the relevant endpoint function. If the path is unmatched, it calls
        the `default_endpoint`.

        Args:
            arguments (list, optional): Arguments to be parsed, if set to None sys.argv is used.
            skip_first_arg (bool): Defaults to true, this is to skip the path of the file that was called as that
                is often not what you want to get parsed. This parameter also influences if the base node is skipped.
        """
        if arguments is None:
            arguments = sys.argv
        (pre_args, args_to_parse, endpoint, substructure) = self._parse_pre_args(arguments, skip_first_arg)
        endpoint: EndpointProtocol | None = endpoint or self._default_endpoint
        path: str = self._help_separator.join(pre_args)

        if endpoint is None:  # No path endpoint and also no default endpoint
            print(structure_help(substructure, separator=self._help_separator))

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
