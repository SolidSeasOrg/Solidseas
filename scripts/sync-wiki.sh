#!/usr/bin/env bash
# Copy the user guide (docs/guide/*.md) into a checkout of the GitHub wiki, with its links
# rewritten for the wiki's flat page names, and commit it there. Pushes only with --push.
# scripts/wiki_sync.py does the work; docs/guide/building.md describes it.
#
# Usage: scripts/sync-wiki.sh WIKI_CHECKOUT [--push]
#
# WIKI_CHECKOUT is cloned from the wiki when it does not exist. Safe to run again: an
# unchanged guide makes no commit.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"
exec "$PYTHON" "$HERE/wiki_sync.py" "$@"
