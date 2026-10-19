#!/usr/bin/env bash
# Write requirements/build-windows.txt, the hash-locked list of everything the Windows
# executable bundles: the library's dependencies and the "build" extra of pyproject.toml
# with their dependencies, resolved for 64-bit Windows and CPython 3.12, every version
# exact and every file's SHA-256 listed. scripts/build-viewer.ps1 installs from it with
# pip --require-hashes. Runs on Linux or Windows with uv installed.
#
# Usage: scripts/lock-build-deps.sh [uv pip compile options]
#
# With no options, versions already in the lock are kept and only what pyproject.toml
# now asks for is added or changed. --upgrade moves everything to its newest release,
# --upgrade-package NAME just that package.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
exec uv pip compile pyproject.toml --extra build \
  --python-platform x86_64-pc-windows-msvc --python-version 3.12 \
  --generate-hashes --custom-compile-command "scripts/lock-build-deps.sh" \
  --quiet --output-file requirements/build-windows.txt "$@"
