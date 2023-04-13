# Server

[![PyPI](https://img.shields.io/pypi/v/server.svg)][pypi status]
[![Status](https://img.shields.io/pypi/status/server.svg)][pypi status]
[![Python Version](https://img.shields.io/pypi/pyversions/server)][pypi status]
[![License](https://img.shields.io/pypi/l/server)][license]

[![Read the documentation at https://server.readthedocs.io/](https://img.shields.io/readthedocs/server/latest.svg?label=Read%20the%20Docs)][read the docs]
[![Tests](https://github.com/DallanQ/server/workflows/Tests/badge.svg)][tests]
[![Codecov](https://codecov.io/gh/DallanQ/server/branch/main/graph/badge.svg)][codecov]

[![pre-commit](https://img.shields.io/badge/pre--commit-enabled-brightgreen?logo=pre-commit&logoColor=white)][pre-commit]
[![Black](https://img.shields.io/badge/code%20style-black-000000.svg)][black]

[pypi status]: https://pypi.org/project/server/
[read the docs]: https://server.readthedocs.io/
[tests]: https://github.com/DallanQ/server/actions?workflow=Tests
[codecov]: https://app.codecov.io/gh/DallanQ/server
[pre-commit]: https://github.com/pre-commit/pre-commit
[black]: https://github.com/psf/black

## Features

- TODO

## Requirements

- python 3.10
- Poetry: `curl -sSL https://install.python-poetry.org | python3 - --version 1.4.0`
- pipx: `pip install --user pipx`
- nox: `pipx install nox && pipx inject nox nox-poetry`

## Installation

```console
poetry install
python -m spacy download en_core_web_sm
```

## Usage

```console
uvicorn src.server.main:app --reload
```

## Development

These command-line utilities check code quality.

```console
pre-commit run -a
pytest
nox
```

## Contributing

Contributions are very welcome.
To learn more, see the [Contributor Guide].

## License

Distributed under the terms of the [MIT license][license],
_Server_ is free and open source software.

## Issues

If you encounter any problems,
please [file an issue] along with a detailed description.

## Credits

This project was generated from [@cjolowicz]'s [Hypermodern Python Cookiecutter] template.

[@cjolowicz]: https://github.com/cjolowicz
[pypi]: https://pypi.org/
[hypermodern python cookiecutter]: https://github.com/cjolowicz/cookiecutter-hypermodern-python
[file an issue]: https://github.com/DallanQ/server/issues
[pip]: https://pip.pypa.io/

<!-- github-only -->

[license]: https://github.com/DallanQ/server/blob/main/LICENSE
[contributor guide]: https://github.com/DallanQ/server/blob/main/CONTRIBUTING.md
[command-line reference]: https://server.readthedocs.io/en/latest/usage.html
