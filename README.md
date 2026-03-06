[![Active Development](https://img.shields.io/badge/Maintenance%20Level-Actively%20Developed-brightgreen.svg)](https://gist.github.com/cheerfulstoic/d107229326a01ff0f333a1d3476e068d)
[![CI Test Status](https://github.com/Adalfarus/endpoint-py/actions/workflows/test-package.yml/badge.svg)](https://github.com/Adalfarus/endpoint-py/actions)
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)
[![PyPI Downloads](https://static.pepy.tech/badge/endpoint.cli)](https://pepy.tech/projects/endpoint.cli)
![coverage](https://raw.githubusercontent.com/Adalfarus/endpoint-py/refs/heads/main/coverage-badge.svg)

# end.

endpoint is a refined, full scale solution to CLIs .

## Compatibility
🟩 (Works perfectly); 🟨 (Untested); 🟧 (Some Issues); 🟥 (Unusable)

| OS                       |   |
|--------------------------|---|
| Windows                  | 🟩 |
| MacOS                    | 🟩 |
| Linux (Ubuntu 22.04 LTS) | 🟩 |

## Features

- Easy to use for beginners, but not lacking for experts
- Efficient
- Fully cross-platform
- Regular updates and support
- Comprehensive documentation

## Installation

You can install endpoint via pip:

```sh
pip install endpoint.cli --pre --upgrade
```

Or clone the repository and install manually:

```sh
git clone https://github.com/Adalfarus/endpoint-py.git
cd endpoint-py
python -m pip install .
```

If you have problems with the package please use `py -m pip install endpoint.cli[dev] --pre --upgrade --user`

## 📦 Usage

The examples below are grouped by capability so you can copy only what you need.

### 1. Route commands with `Interface`

```python
from endpoint.interface import Interface


def hello(name: str = "world") -> None:
    print(f"hello {name}")


app = Interface("my-cli", default_endpoint_or_message="Unknown command")
app.path("greet", hello, "Print a greeting")
app.path("math::sum", lambda a: print(sum(map(int, a))), "Sum integers")

# Simulate: my-cli greet --name Ada
app.parse_cli(["my-cli", "greet", "--name", "Ada"], skip_first_arg=True)
```

### 2. Build endpoints from function signatures

```python
from endpoint.endpoints import NativeEndpoint
from endpoint.native_parser import NativeParser


def deploy(env: str, *, dry_run: bool = False, retries: int = 1) -> None:
    """Deploy app.
    env: Deployment target.
    dry_run: Validate only.
    retries: Retry count.
    """
    print(env, dry_run, retries)


endpoint = NativeEndpoint.from_function(
    deploy,
    name="deploy",
    parser=NativeParser({}),
)

# Simulate: deploy production --dry-run --retries 3
endpoint.parse(["deploy", "production", "--dry-run", "--retries", "3"], skip_first_arg=True)
```

### 3. Define arguments manually (all core knobs)

```python
from endpoint.endpoints import NativeEndpoint
from endpoint.native_parser import NativeParser, NArgsMode, NArgsSpec, ArgumentParsingError


def run(input_file: str, **kwargs) -> None:
    print(input_file, kwargs)


ep = NativeEndpoint("run", "Manual argument model", function=run, parser=NativeParser({}))

ep.add_argument("input_file", types=[str], positional_only=True, required=True, help_="Input path")
ep.add_argument("count", types=[int], default=1, choices=[1, 2, 3], help_="How many times")
ep.add_argument("verbose", types=[bool], default=False, help_="Enable verbose output")
ep.add_argument("tags", types=[list[str]], default=[], nargs=NArgsMode.ZERO_OR_MORE(NArgsSpec.MANY))
ep.add_argument("mode", types=[str], default="safe", kwarg_only=True, help_="Execution mode")

def validate_count(arg, value):
    if value < 1:
        return ArgumentParsingError("count must be >= 1")
    return value

ep.change_argument("count", checking_func=validate_count)
ep.guess_letters_and_shortforms()

# Simulate: run file.txt --count 2 --verbose --mode fast --tags a,b
ep.parse(["run", "file.txt", "--count", "2", "--verbose", "--mode", "fast", "--tags", "a,b"], skip_first_arg=True)
```

### 4. Wrap endpoint invocation (logging, timing, tracing, auth)

```python
from endpoint.endpoints import NativeEndpoint


def add(a: int, b: int) -> int:
    return a + b


def wrapper(endpoint, fn, *args, **kwargs):
    print(f"calling {endpoint!r} with {args=} {kwargs=}")
    return fn(*args, **kwargs)


ep = NativeEndpoint.from_function(add, "add")
ep.set_calling_func(wrapper)
ep.parse(["add", "2", "3"], skip_first_arg=True)
```

### 5. Use parser backends

`NativeEndpoint` accepts any parser implementing `Parser`.

```python
from endpoint.endpoints import NativeEndpoint
from endpoint.native_parser import NativeParser
from endpoint.parser_collection import LightParser, TokenStreamParser, StrictDFAParser, FastParser, TinyParser


def task(value: int, flag: bool = False) -> None:
    print(value, flag)


NativeEndpoint.from_function(task, "native", parser=NativeParser({}))
NativeEndpoint.from_function(task, "light", parser=LightParser({}))
NativeEndpoint.from_function(task, "stream", parser=TokenStreamParser({"repeatable_collections": True}))
NativeEndpoint.from_function(task, "dfa", parser=StrictDFAParser({}))
NativeEndpoint.from_function(task, "fast", parser=FastParser({"FAST_ALLOW_POSITIONALS": True}))
NativeEndpoint.from_function(task, "tiny", parser=TinyParser({}))
```

### 6. Use `ArgparseEndpoint` when you want argparse behavior

```python
from endpoint.endpoints import ArgparseEndpoint


ep = ArgparseEndpoint(prog="my-cli", description="Argparse-backed endpoint")
ep.add_argument("--value", type=int, required=True)
ep.set_calling_func(lambda *, value: print(value))

ep.parse(["my-cli", "--value", "5"], skip_first_arg=True, automatic_help_args=())
```

### 7. Convert native endpoint definitions to argparse

```python
from endpoint.endpoints import NativeEndpoint


ep = NativeEndpoint.from_function(lambda count=1: print(count), "tool")
argparse_parser = ep.to_argparse()
argparse_ep = ep.to_argparse_endpoint()

ns = argparse_parser.parse_args(["--count", "3"])
print(ns.count)

_, parsed = argparse_ep.parse(["tool", "--count", "3"], skip_first_arg=True, automatic_help_args=())
print(parsed["count"])
```

### 8. Inspect callables and types

```python
from endpoint.functional import analyze_function, get_analysis, break_type, pretty_type


def sample(a: int, b: str = "x") -> bool:
    """sample function"""
    return True


print(analyze_function(sample))
print(get_analysis(sample).to_dict())
print(break_type(list[int]))
print(pretty_type(dict[str, int]))
```

### 9. Build command trees manually

```python
from endpoint.structure import Structure, add_command_to_structure, structure_help
from endpoint.endpoints import NativeEndpoint


tree = Structure("demo")
add_command_to_structure("ops::health", "Check health", NativeEndpoint("health"), tree)
add_command_to_structure("ops::version", "Show version", NativeEndpoint("version"), tree)
print(structure_help(tree["demo"]))
```

### 10. Project CLI entrypoint

The package installs `endpoint-cli` for project workflows:

```bash
endpoint-cli help
endpoint-cli tests run tests/ --minimal
```

---

## Naming convention, dependencies and library information
[PEP 8 -- Style Guide for Python Code](https://peps.python.org/pep-0008/#naming-conventions)

For modules I use 'lowercase', classes are 'CapitalizedWords' and functions and methods are 'lower_case_with_underscores'.

## Contributing

We welcome contributions! Please see our [contributing guidelines](https://github.com/adalfarus/endpoint/blob/main/CONTRIBUTING.md) for more details on how you can contribute to endpoint.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a pull request

### Aps Build master

You can use the aps_build_master script for your os to make your like a lot easier.
It supports running tests, installing, building and much more as well as chaining together as many commands as you like.

This example runs test, build the project and then installs it

Windows:
````commandline
call .\aps_build_master.bat 234
````

Unix:
````shell
sudo apt install python3-pip
sudo apt install python3-venv
chmod +x ./aps_build_master.sh
./aps_build_master.sh 234
````

## License

endpoint is licensed under the GPL-3.0 License - see the [LICENSE](https://github.com/adalfarus/endpoint-py/blob/main/LICENSE) file for details.
