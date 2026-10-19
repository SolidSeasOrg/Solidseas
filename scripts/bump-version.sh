#!/usr/bin/env bash
# Bump the package version in src/solidseas/__init__.py, the single source of
# truth for the SolidSeas version.
#
# Usage: scripts/bump-version.sh [patch|minor|major|--set X.Y.Z|--current]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FILE="$ROOT/src/solidseas/__init__.py"

# Tolerates CRLF working-tree files on Windows: the pattern never anchors at
# the end of the line.
CUR="$(sed -n 's/^__version__ = "\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\)".*/\1/p' "$FILE")"
if [ -z "$CUR" ]; then
  echo "could not read __version__ from $FILE" >&2
  exit 1
fi
IFS=. read -r MAJOR MINOR PATCH <<<"$CUR"

case "${1:-patch}" in
  --current) echo "$CUR"; exit 0 ;;
  --set)
    NEW="${2:?usage: bump-version.sh --set X.Y.Z}"
    if ! [[ "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
      echo "not a X.Y.Z version: $NEW" >&2
      exit 2
    fi
    ;;
  major) NEW="$((MAJOR + 1)).0.0" ;;
  minor) NEW="$MAJOR.$((MINOR + 1)).0" ;;
  patch) NEW="$MAJOR.$MINOR.$((PATCH + 1))" ;;
  *) echo "usage: bump-version.sh [patch|minor|major|--set X.Y.Z|--current]" >&2; exit 2 ;;
esac

sed -i "s/^__version__ = \"$CUR\"/__version__ = \"$NEW\"/" "$FILE"
echo "$NEW"
