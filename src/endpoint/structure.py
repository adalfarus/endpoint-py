from functools import reduce

# Internal imports
from .endpoints import EndpointProtocol

# Standard typing imports for aps
import typing_extensions as _te
import collections.abc as _a
import typing as _ty

if _ty.TYPE_CHECKING:
    import _typeshed as _tsh
import types as _ts

__all__ = ["StructureError", "Structure", "add_command_to_structure", "rename_structure", "structure_help"]


class StructureError(Exception):
    """TBA"""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class _Node:
    def __init__(self, parent: _ty.Self | None = None, name: str | None = None, help_: str | None = None) -> None:
        self._parent: _ty.Self | None = parent
        self._name: str | None = name
        self._help: str | None = help_
        self._content: EndpointProtocol | None = None
        self._children: dict[str, _ty.Self] = dict()

    def get_name(self) -> str | None:
        return self._name

    def set_name(self, name: str | None) -> None:
        self._name = name

    def get_parent(self) -> _ty.Self | None:
        return self._parent

    def set_parent(self, parent: _ty.Self | None):
        self._parent = parent

    def get_help(self) -> str:
        return self._help

    def set_help(self, help_: str) -> None:
        self._help = help_

    def get_content(self) -> EndpointProtocol | None:
        return self._content

    def set_content(self, content: EndpointProtocol | None) -> None:
        self._content = content

    def get_available_paths(self, base: str | None = None, *, separator: str = " -> ") -> list[tuple[str, _ty.Self]]:
        if self._name is None:  # Root
            return list(self._children.values())[0].get_available_paths(separator=separator)

        if not base:
            base = self._name
        else:
            base += separator + self._name
        rest: list[tuple[str, _ty.Self]] = reduce(lambda x, y: x + y, [c.get_available_paths(base, separator=separator) for c in self._children.values()], [])
        if self._help is not None:
            return [(base, self)] + rest
        return rest

    def update(self) -> None:
        for name, child in self._children.items():
            child.set_parent(self)
            child.set_name(name)
            child.update()

    def keys(self) -> list[str]:
        return list(self._children.keys())

    def values(self) -> list[_ty.Self]:
        return list(self._children.values())

    def __getitem__(self, item: str) -> _ty.Self | None:
        return self._children.get(item)

    def __setitem__(self, key: str, value: _ty.Self):
        self._children[key] = value

    def __delitem__(self, key: str):
        del self._children[key]

    def __contains__(self, item: str) -> bool:
        return item in self._children.keys()

    def __str__(self) -> str:
        def to_dict(node: "_Node"):
            result = {}

            # include content if present (optional)
            if node._content is not None:
                result["_content"] = repr(node._content)

            for key, child in node._children.items():
                result[key] = to_dict(child)

            return result

        return str(to_dict(self))


def Structure(name: str) -> _Node:
    base_node = _Node(None)
    command_base = _Node(base_node)
    base_node[name] = command_base
    return base_node


def _parse_command_path(command_path: str, separator: str = "::") -> list[str]:
    path: list[str] = []
    last_separator: int = 0
    separator_i: int = 0
    skip_next: bool = False

    for i, x in enumerate(command_path):
        if skip_next:
            continue

        if x == "\\":
            skip_next = True
        elif x == separator[separator_i]:
            separator_i += 1
            if separator_i == len(separator):
                path.append(command_path[last_separator:i + 1 - separator_i])  # We need to add +1 as slices add -1 per default
                if path[-1] == "":
                    raise StructureError(f"Path '{command_path}' cannot have an empty segment.")
                separator_i = 0
                last_separator = i + 1  # We want to target the start of the token not the end of the separator
        else:
            separator_i = 0
    path.append(command_path[last_separator:])

    if path[-1] == "":
        raise StructureError(f"Path '{command_path}' cannot terminate at ''.")
    return path


def _parse_command_path_escaped(command_path: str, separator: str = "::") -> list[str]:
    path: list[str] = []
    separator_i: int = 0
    skip_next: bool = False
    current_segment_buffer: str = ""

    for i, x in enumerate(command_path):
        if skip_next:
            current_segment_buffer += x
            skip_next = False
            continue

        if x == "\\":
            skip_next = True
        elif x == separator[separator_i]:
            separator_i += 1
            if separator_i == len(separator):
                if current_segment_buffer == "":
                    raise StructureError(f"Path '{command_path}' cannot have an empty segment.")
                path.append(current_segment_buffer)
                current_segment_buffer = ""
                separator_i = 0
        else:
            current_segment_buffer += separator[:separator_i]
            current_segment_buffer += x
            separator_i = 0
    if separator_i != 0:
        current_segment_buffer += separator[:separator_i]
    path.append(current_segment_buffer)

    if path[-1] == "":
        raise StructureError(f"Path '{command_path}' cannot terminate at ''.")
    return path


def add_command_to_structure(command_path: str, help_: str | None, endpoint: EndpointProtocol | None = None,
                             structure: _Node | None = None, *, create_path: bool = True,
                             replace_endpoint: bool = False, separator: str = "::") -> _Node:
    if structure is None:
        structure = Structure("command")
    path: list[str] = _parse_command_path_escaped(command_path, separator)

    current_level: _Node = structure[structure.keys()[0]]  # Skip base node
    for ix in path:
        if ix != path[-1]:
            if ix in current_level:
                current_level = current_level[ix]
                continue
            elif create_path:
                current_level[ix] = _Node()
                current_level = current_level[ix]
            else:
                raise StructureError(f"Path '{command_path}' not found. Failed at part '{ix}'.")
        else:
            if not current_level[ix]:
                if not create_path:
                    raise StructureError(f"Path '{command_path}' not found. Failed at part '{ix}'.")
                current_level[ix] = _Node()
            if current_level[ix].get_content() is not None and not replace_endpoint:
                raise StructureError(f"Path '{command_path}' already has an Endpoint.")
            if help_ is None and endpoint is not None:
                help_ = endpoint.get_help_str()
            if help_ is not None:
                current_level[ix].set_help(help_)
            current_level[ix].set_content(endpoint)
    structure.update()
    return structure


def rename_structure(structure: _Node, new_name: str) -> None:
    current_name: str = structure.keys()[0]
    current_base: _Node = structure[current_name]
    del structure[current_name]
    structure[new_name] = current_base
    current_base.set_name(new_name)


def structure_help(structure: _Node, *, separator: str = " -> ") -> str:
    """
    Create an argparse-like help text for a command tree built from `_Node`.

    The tree is interpreted as a command hierarchy:

        root -> base -> (tree nodes...)* -> leaf nodes...

    - The root node and the base node occur only once.
    - Any deeper nodes may occur multiple times.
    - A node is considered a *leaf command* if it has content (`get_content() is not None`).
    - The displayed command path is built by joining node names with `separator`
      (e.g. "root::base::sub::cmd").

    Args:
        structure:
            Root `_Node` of the command structure.

        separator:
            String used to join command path segments.

    Returns:
        A formatted help string listing commands and (if available) each endpoint's
        short description.

    Notes:
        This function assumes:
        - Each endpoint object (BaseEndpoint) may provide `.help()` (string) and/or
          a docstring. If neither is available, it shows an empty description.
        - Root/base names are taken from the first two levels of keys under `structure`.
    """
    output: str = "commands:"
    paths: list[tuple[str, _Node]] = structure.get_available_paths(separator=separator) or ["(no commands registered)"]
    max_len: int = max(len(p) for (p, _) in paths)
    for (path, node) in paths:
        content: EndpointProtocol | None = node.get_content()
        content_help: str
        if content is None:
            content_help = ""
        else:
            content_help = " " + content.generate_help(prog="").strip().splitlines()[0].strip().removeprefix("usage:  ")
        output += "\n  " + path.ljust(max_len, " ") + content_help + " " * 5 + node.get_help()
    return output
