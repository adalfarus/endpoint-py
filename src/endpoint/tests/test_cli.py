from __future__ import annotations

import importlib
import os
import sys
import types
from types import SimpleNamespace


def _load_cli_module(monkeypatch, interface_cls):  # type: ignore[no-untyped-def]
    fake_argumint = types.ModuleType("argumint")
    fake_argumint.Interface = interface_cls
    monkeypatch.setitem(sys.modules, "argumint", fake_argumint)
    sys.modules.pop("endpoint._cli", None)
    return importlib.import_module("endpoint._cli")


def test_execute_silent_python_command_returns_success(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class DummyInterface:
        def __init__(self, name: str) -> None:
            self.name = name

    cli = _load_cli_module(monkeypatch, DummyInterface)
    result = cli._execute_silent_python_command(["-c", "import sys; sys.exit(0)"])
    assert result.returncode == 0


def test_change_working_dir_to_script_location_uses_caller_file(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    class DummyInterface:
        def __init__(self, name: str) -> None:
            self.name = name

    cli = _load_cli_module(monkeypatch, DummyInterface)

    start = os.getcwd()
    try:
        os.chdir(tmp_path)
        cli._change_working_dir_to_script_location()
        assert os.getcwd() == os.path.dirname(__file__)
    finally:
        os.chdir(start)


def test_change_working_dir_to_script_location_uses_frozen_executable(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    class DummyInterface:
        def __init__(self, name: str) -> None:
            self.name = name

    cli = _load_cli_module(monkeypatch, DummyInterface)

    app_dir = tmp_path / "bundle"
    app_dir.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(app_dir / "app"))

    start = os.getcwd()
    try:
        os.chdir(tmp_path)
        cli._change_working_dir_to_script_location()
        assert os.getcwd() == str(app_dir)
    finally:
        os.chdir(start)


def test_cli_registers_paths_and_runs_non_minimal_branch(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: dict[str, object] = {}

    class DummyInterface:
        instance = None

        def __init__(self, name: str) -> None:
            self.name = name
            self.routes: dict[str, object] = {}
            DummyInterface.instance = self

        def path(self, route: str, fn):  # type: ignore[no-untyped-def]
            self.routes[route] = fn

        def parse_cli(self) -> None:
            self.routes["help"]()
            self.routes["tests.run"]("tests", debug=True, minimal=False)

    cli = _load_cli_module(monkeypatch, DummyInterface)

    monkeypatch.setattr(cli, "_change_working_dir_to_script_location", lambda: None)
    monkeypatch.setattr(cli, "_execute_silent_python_command", lambda command: SimpleNamespace(returncode=0))
    monkeypatch.setattr(cli.os, "chdir", lambda path: None)
    monkeypatch.setattr(cli.os.path, "exists", lambda path: path == "test_data")
    monkeypatch.setattr(cli.shutil, "rmtree", lambda path: calls.setdefault("rmtree", path))
    monkeypatch.setattr(cli.os, "mkdir", lambda path: calls.setdefault("mkdir", path))

    def fake_run(command):  # type: ignore[no-untyped-def]
        calls["command"] = command
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    cli._cli()

    assert DummyInterface.instance is not None
    assert "tests.run" in DummyInterface.instance.routes
    assert "help" in DummyInterface.instance.routes
    assert calls["rmtree"] == "test_data"
    assert calls["mkdir"] == "test_data"
    assert calls["command"][:5] == ["pytest", "-s", "-q", "--tb=short", "-p"]


def test_cli_runs_minimal_branch(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: dict[str, object] = {}

    class DummyInterface:
        def __init__(self, name: str) -> None:
            self.name = name
            self.routes: dict[str, object] = {}

        def path(self, route: str, fn):  # type: ignore[no-untyped-def]
            self.routes[route] = fn

        def parse_cli(self) -> None:
            self.routes["tests.run"]("tests", debug=False, minimal=True)

    cli = _load_cli_module(monkeypatch, DummyInterface)

    monkeypatch.setattr(cli, "_change_working_dir_to_script_location", lambda: None)
    monkeypatch.setattr(cli, "_execute_silent_python_command", lambda command: SimpleNamespace(returncode=0))
    monkeypatch.setattr(cli.os, "chdir", lambda path: None)
    monkeypatch.setattr(cli.os.path, "exists", lambda path: False)
    monkeypatch.setattr(cli.os, "mkdir", lambda path: None)

    def fake_run(command):  # type: ignore[no-untyped-def]
        calls["command"] = command
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    cli._cli()

    assert "--maxfail=1" in calls["command"]
