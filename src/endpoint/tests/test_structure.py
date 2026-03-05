from __future__ import annotations

from ..structure import (
    Structure,
    StructureError,
    add_command_to_structure,
    rename_structure,
    structure_help,
)
from ..endpoints import NativeEndpoint


def test_structure_add_and_rename() -> None:
    struct = Structure("cli")
    ep = NativeEndpoint(name="hello", help_str="say hello")

    struct = add_command_to_structure("greet::hello", "Greet user", ep, structure=struct)
    help_text_before = structure_help(struct)
    assert "greet -> hello" in help_text_before

    rename_structure(struct, "tool")
    help_text_after = structure_help(struct)
    assert "tool" in help_text_after


def test_add_command_to_structure_errors_on_duplicate_without_replace() -> None:
    struct = Structure("cli")
    ep = NativeEndpoint(name="hello", help_str="say hello")
    struct = add_command_to_structure("greet::hello", "Greet user", ep, structure=struct)

    try:
        add_command_to_structure("greet::hello", "Again", ep, structure=struct)
    except StructureError:
        ...
    else:
        raise AssertionError("Expected StructureError for duplicate endpoint path")


def test_add_command_to_structure_escaped_separator() -> None:
    struct = Structure("cli")
    ep = NativeEndpoint(name="hello", help_str="say hello")

    struct = add_command_to_structure(r"group\::name::cmd", "Help", ep, structure=struct)
    text = structure_help(struct)
    assert "group::name -> cmd" in text

