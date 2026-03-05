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
    """Raised when command-tree structure operations fail."""

    def __init__(self, message: str) -> None:
        """Initialize structure error.

        :param message: Human-readable failure reason.
        :return: None.
        """
        super().__init__(message)


class _Node:
    """Internal tree node used to represent command-path hierarchy."""

    def __init__(self, parent: _ty.Self | None = None, name: str | None = None, help_: str | None = None) -> None:
        """Initialize node metadata and children map.

        :param parent: Parent node, or ``None`` for root.
        :param name: Node segment name.
        :param help_: Optional help text associated with this node.
        :return: None.
        """
        self._parent: _ty.Self | None = parent
        self._name: str | None = name
        self._help: str | None = help_
        self._content: EndpointProtocol | None = None
        self._children: dict[str, _ty.Self] = dict()

    def get_name(self) -> str | None:
        """Return node name.

        :return: Node segment name or ``None``.
        """
        return self._name

    def set_name(self, name: str | None) -> None:
        """Set node name.

        :param name: New node segment name.
        :return: None.
        """
        self._name = name

    def get_parent(self) -> _ty.Self | None:
        """Return parent node.

        :return: Parent node or ``None``.
        """
        return self._parent

    def set_parent(self, parent: _ty.Self | None):
        """Set parent node.

        :param parent: New parent node.
        :return: None.
        """
        self._parent = parent

    def get_help(self) -> str:
        """Return node help text.

        :return: Help text.
        """
        return self._help

    def set_help(self, help_: str) -> None:
        """Set node help text.

        :param help_: Help text.
        :return: None.
        """
        self._help = help_

    def get_content(self) -> EndpointProtocol | None:
        """Return endpoint content attached to this node.

        :return: Endpoint or ``None``.
        """
        return self._content

    def set_content(self, content: EndpointProtocol | None) -> None:
        """Attach endpoint content to this node.

        :param content: Endpoint value or ``None``.
        :return: None.
        """
        self._content = content

    def get_available_paths(self, base: str | None = None, *, separator: str = " -> ") -> list[tuple[str, _ty.Self]]:
        """Collect reachable path strings and terminal nodes.

        :param base: Existing prefix while recursing.
        :param separator: Path separator for rendered output.
        :return: List of ``(path, node)`` tuples.
        """
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
        """Rebind child parent/name metadata recursively.

        :return: None.
        """
        for name, child in self._children.items():
            child.set_parent(self)
            child.set_name(name)
            child.update()

    def keys(self) -> list[str]:
        """Return child-key list."""
        return list(self._children.keys())

    def values(self) -> list[_ty.Self]:
        """Return child-node list."""
        return list(self._children.values())

    def __getitem__(self, item: str) -> _ty.Self | None:
        """Get child by key.

        :param item: Child key.
        :return: Child node or ``None``.
        """
        return self._children.get(item)

    def __setitem__(self, key: str, value: _ty.Self):
        """Set child node under key.

        :param key: Child key.
        :param value: Child node.
        :return: None.
        """
        self._children[key] = value

    def __delitem__(self, key: str):
        """Delete child node by key.

        :param key: Child key.
        :return: None.
        """
        del self._children[key]

    def __contains__(self, item: str) -> bool:
        """Return whether a child key exists.

        :param item: Child key.
        :return: ``True`` if key exists.
        """
        return item in self._children.keys()

    def __str__(self) -> str:
        """Return nested dict-like debug view of subtree.

        :return: String representation.
        """
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
    """Create a new structure with one named base command node.

    :param name: Root command name.
    :return: Root wrapper node.
    """
    base_node = _Node(None)
    command_base = _Node(base_node)
    base_node[name] = command_base
    return base_node


def _parse_command_path(command_path: str, separator: str = "::") -> list[str]:
    """Split command path into segments (legacy parser).

    :param command_path: Raw path string.
    :param separator: Segment separator token.
    :return: Path segments.
    :raises StructureError: If path contains empty segments.
    """
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
    """Split command path into segments with escape handling.

    Backslash escapes suppress separator interpretation for the next character.

    :param command_path: Raw path string.
    :param separator: Segment separator token.
    :return: Parsed path segments.
    :raises StructureError: If path contains empty segments.
    """
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
    """Insert/update a command path in the structure tree.

    :param command_path: Path to add.
    :param help_: Optional help text for terminal node.
    :param endpoint: Endpoint to attach.
    :param structure: Existing structure root, or ``None`` for a new tree.
    :param create_path: Whether missing intermediate segments may be created.
    :param replace_endpoint: Whether existing endpoint may be overwritten.
    :param separator: Path separator.
    :return: Updated structure root.
    :raises StructureError: If path is invalid or disallowed by options.
    """
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
    """Rename top-level command key in structure.

    :param structure: Structure root node.
    :param new_name: Replacement root key.
    :return: None.
    """
    current_name: str = structure.keys()[0]
    current_base: _Node = structure[current_name]
    del structure[current_name]
    structure[new_name] = current_base
    current_base.set_name(new_name)


def structure_help(structure: _Node, *, separator: str = " -> ") -> str:
    """Render command-tree help output.

    The tree is interpreted as a command hierarchy:

        root -> base -> (tree nodes...)* -> leaf nodes...

    - The root node and the base node occur only once.
    - Any deeper nodes may occur multiple times.
    - A node is considered a *leaf command* if it has content (`get_content() is not None`).
    - The displayed command path is built by joining node names with `separator`
      (e.g. "root::base::sub::cmd").

    :param structure: Root :class:`_Node` of command structure.
    :param separator: Separator used for displayed command paths.
    :return: Formatted multi-line command help text.
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
