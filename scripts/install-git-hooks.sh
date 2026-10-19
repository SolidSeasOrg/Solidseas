#!/usr/bin/env bash
# Install the version-bump pre-commit hook by chaining onto whatever hook is
# already active. Safe to run more than once.
#
# Respects core.hooksPath, so an existing hook keeps running and ours is
# appended inside marker lines. Re-running replaces only the block between the
# markers. When core.hooksPath is a folder the repository tracks (beads keeps
# its hooks in .beads/hooks), nothing in it is edited: the hooks move to a
# folder of this clone's own inside the git directory, each one a wrapper that
# runs the tracked hook of its name, and pre-commit then bumps the version.
# Re-run it after the tracked folder gains a hook. On Windows, run it from Git
# Bash.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HOOKS_PATH="$(git config --get core.hooksPath || true)"
if [ -z "$HOOKS_PATH" ]; then
  HOOKS_PATH="$(git rev-parse --git-common-dir)/hooks"
fi
case "$HOOKS_PATH" in
  /*|?:*) ;;
  *) HOOKS_PATH="$ROOT/$HOOKS_PATH" ;;
esac
mkdir -p "$HOOKS_PATH"

# The tracked folder this clone's hooks wrap: found now, or remembered from an earlier run
# (core.hooksPath then names this clone's own folder).
TRACKED="$(git config --get solidseas.trackedhooks || true)"
if [ -z "$TRACKED" ] && [ -n "$(git ls-files -- "$HOOKS_PATH" 2>/dev/null)" ]; then
  TRACKED="${HOOKS_PATH#"$ROOT"/}"
fi
if [ -n "$TRACKED" ]; then
  HOOKS_PATH="$(cd "$(git rev-parse --git-common-dir)" && pwd)/solidseas-hooks"
  mkdir -p "$HOOKS_PATH"
  for tracked_hook in "$ROOT/$TRACKED"/*; do
    [ -f "$tracked_hook" ] || continue
    name="$(basename "$tracked_hook")"
    [ "$name" = "pre-commit" ] && continue  # written below, with the version bump after it
    printf '%s\n' '#!/usr/bin/env sh' \
      "# Written by scripts/install-git-hooks.sh: runs the tracked hook $TRACKED/$name." \
      "exec \"\$(git rev-parse --show-toplevel)/$TRACKED/$name\" \"\$@\"" >"$HOOKS_PATH/$name"
    chmod +x "$HOOKS_PATH/$name"
  done
  printf '%s\n' '#!/usr/bin/env sh' \
    "# Written by scripts/install-git-hooks.sh: runs the tracked hook $TRACKED/pre-commit," \
    "# then the block the installer keeps below." \
    "tracked=\"\$(git rev-parse --show-toplevel)/$TRACKED/pre-commit\"" \
    "if [ -x \"\$tracked\" ]; then \"\$tracked\" \"\$@\" || exit \$?; fi" >"$HOOKS_PATH/pre-commit"
  git config solidseas.trackedhooks "$TRACKED"
  git config core.hooksPath "$HOOKS_PATH"
  echo "core.hooksPath now $HOOKS_PATH (wrapping the tracked $TRACKED)"
fi

HOOK="$HOOKS_PATH/pre-commit"
BEGIN="# --- BEGIN SOLIDSEAS VERSION BUMP ---"
END="# --- END SOLIDSEAS VERSION BUMP ---"

BLOCK="$(cat <<EOF
$BEGIN
# Added by scripts/install-git-hooks.sh. Runs the repository's version bump
# after any hook logic above it. Re-run the installer to refresh this block.
if [ -f "\$(git rev-parse --show-toplevel)/scripts/git-hooks/pre-commit-version" ]; then
  bash "\$(git rev-parse --show-toplevel)/scripts/git-hooks/pre-commit-version" || exit \$?
fi
$END
EOF
)"

if [ ! -f "$HOOK" ]; then
  printf '#!/usr/bin/env bash\n\n%s\n' "$BLOCK" >"$HOOK"
  chmod +x "$HOOK"
  echo "installed $HOOK"
  exit 0
fi

TMP="$(mktemp)"
awk -v begin="$BEGIN" -v end="$END" '
  $0 == begin { skip = 1; next }
  $0 == end { skip = 0; next }
  !skip { print }
' "$HOOK" >"$TMP"
printf '\n%s\n' "$BLOCK" >>"$TMP"
mv "$TMP" "$HOOK"
chmod +x "$HOOK"
echo "updated $HOOK"
