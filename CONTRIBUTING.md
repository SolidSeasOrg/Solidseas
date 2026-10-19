# Contributing to SolidSeas

Thanks for taking an interest. Bug reports, fixes, new format readers, better
documentation and plain questions are all welcome. This page covers how to get
a working checkout, what the checks are, and what helps a pull request get
merged quickly.

`AGENTS.md` is the full rulebook for the repository (it is written for people
and coding agents alike). You do not need to memorise it, but skim the scrub
rules and the safety rules for CAD files before your first change.

## Setting up

You need Python 3.11 or newer. SOLIDWORKS is not needed for the library, the
command line or the default test suite, and everything runs on Linux as well
as Windows.

With pip:

```bash
python -m venv .venv
.venv\Scripts\activate          # on Linux or macOS: source .venv/bin/activate
pip install -e ".[dev]"
scripts/install-git-hooks.sh    # once per clone, from Git Bash on Windows
```

With uv:

```bash
uv venv
uv pip install -e ".[dev]"
scripts/install-git-hooks.sh
```

Add other extras as your change needs them, for example `".[dev,app]"` for the
desktop viewer (PySide6) or `".[dev,image]"` for Pillow. `pyproject.toml` lists
them all.

The git hook bumps the patch version in `src/solidseas/__init__.py` on every
commit, which is how this project numbers its versions. If the hook gives you
trouble, skip it and say so in your pull request; a maintainer will set the
version when merging.

## Running the checks

```bash
python -m pytest -q
python -m ruff check .
```

Both have to pass before a change is merged. Ruff uses a line length of 110 and
the rule set in `pyproject.toml`. CI runs the same two commands on Linux and
Windows for every pull request.

### Tests that are skipped by default

Some tests need things that are not in the repository, and they skip unless an
environment variable points at them:

- tests that drive a real SOLIDWORKS (`SOLIDSEAS_SWAPI_SOLIDWORKS`), which only
  run on a Windows machine with SOLIDWORKS installed;
- tests against the maintainers' private corpus of real CAD files
  (`SOLIDSEAS_CORPUS_MANIFEST`), which is never shared;
- the Open CASCADE oracle (`SOLIDSEAS_OCCT_PYTHON`).

You do not need any of these to contribute. `tests/README.md` explains each
one. If your change touches code those tests cover, say so in the pull request
and a maintainer will run them.

## Commits

- Write the subject as a plain English sentence in sentence case, with no
  trailing period and no prefix such as `fix:` or `feat:`. For example:
  `Read the material name from parts saved in SOLIDWORKS 2024`.
- Use the body to explain what you found, what you changed and anything you
  deliberately left alone. A last line with the test count and lint state is
  appreciated, for example `1,204 tests, ruff clean.`
- Keep each commit to one change where you can.

## Changelog

A change someone using SolidSeas would notice gets an entry under
`[Unreleased]` in `CHANGELOG.md`, written as plain prose for that person rather
than as a note about the code. Look at the entries already there for the tone.

## What never goes in the repository

- Real CAD files from a customer, an employer or anyone else who has not agreed
  to publish them, and their names or contents.
- Personal paths, host names, IP addresses, credentials, tokens or API keys.

Test fixtures are synthetic parts made for the purpose. `tests/fixtures/README.md`
describes them, and `tests/test_fixture_paths.py` checks them on every run.

## Good issues

A useful bug report says:

- the SolidSeas version (`solidseas --version`, or the title bar of the viewer);
- your operating system and Python version;
- the file type involved (part, assembly, drawing, STEP, STL and so on) and,
  if you know it, the SOLIDWORKS version that saved it;
- what you ran, what you expected and what happened, with the full error text.

Please do not attach confidential CAD files. If a problem only shows up with
one file, describe it, or try to reproduce it with a simple part you made
yourself and can share.

A feature request is most useful when it starts with the problem you are trying
to solve rather than the solution you have in mind.

Security problems are different: please report them privately, as `SECURITY.md`
explains, and not in a public issue.

## Good pull requests

- Open an issue first for anything large, such as a new format, a new
  dependency or a change to a public API, so we can agree on the approach.
- Keep the pull request to one topic.
- Add or update tests for the behaviour you changed.
- Update the documentation the change affects, including `CHANGELOG.md`.
- Make sure `pytest` and `ruff` pass locally.
- Fill in the pull request template, including which opt-in tests, if any,
  you could not run.

The library's public names, JSON output, exit codes and REST routes follow the
stability policy in `docs/API.md` section 9. A change there needs a good reason
and a note in the changelog.

## Design documents

Design documents live in `docs/`. Start with `docs/ARCHITECTURE.md` for how the
modules fit together and `docs/ROADMAP.md` for what is planned. `docs/API.md`
is the reference for the library, the command line and the REST service, and
`docs/FORMAT.md` records what is known about the SOLIDWORKS file format. Format
work is black-box: analyse files and use public documentation and open-source
prior art, but never disassemble or decompile SOLIDWORKS binaries.

## Licence of contributions

SolidSeas is licensed under the Apache License 2.0. There is no contributor
licence agreement to sign. As section 5 of the licence says, anything you
intentionally submit for inclusion is offered under the same Apache-2.0 terms,
with no additional conditions. Only submit work you have the right to submit.

## Conduct

Everyone taking part is expected to follow `CODE_OF_CONDUCT.md`.
