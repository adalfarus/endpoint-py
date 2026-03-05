[![Active Development](https://img.shields.io/badge/Maintenance%20Level-Actively%20Developed-brightgreen.svg)](https://gist.github.com/cheerfulstoic/d107229326a01ff0f333a1d3476e068d)
[![CI Test Status](https://github.com/Adalfarus/endpoint-py/actions/workflows/test-package.yml/badge.svg)](https://github.com/Adalfarus/endpoint-py/actions)
[![License: GPL-3.0](https://img.shields.io/github/license/Adalfarus/endpoint-py)](https://github.com/Adalfarus/endpoint-py/blob/main/LICENSE)
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
cd endpoint.py
python -m pip install .
```

If you have problems with the package please use `py -m pip install endpoint.cli[dev] --pre --upgrade --user`

## 📦 Usage

Here are a few quick examples of how to use `endpoint`.

## TBA

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

endpoint is licensed under the GPL-3.0 License - see the [LICENSE](https://github.com/adalfarus/endpoint/blob/main/LICENSE) file for details.
