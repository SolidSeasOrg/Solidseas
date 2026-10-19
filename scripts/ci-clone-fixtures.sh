#!/usr/bin/env bash
# CI: clone the private SOLIDWORKS fixtures (SolidSeas/SolidSeas-fixtures) into $1 with the
# read-only deploy key in FIXTURES_DEPLOY_KEY, then copy them in with scripts/fetch-fixtures.py.
# Without the key, as in a fork's pull request, it says so and does nothing: the test modules
# that need the fixtures are left out of the run; with FIXTURES_REQUIRED=1 (a release build)
# it fails instead. The key is written to a file only this
# user can read, used once with GitHub's host key pinned, and removed.
set -euo pipefail

dest="${1:?usage: scripts/ci-clone-fixtures.sh DEST}"
if [ -z "${FIXTURES_DEPLOY_KEY:-}" ]; then
    if [ "${FIXTURES_REQUIRED:-}" = 1 ]; then
        echo "no FIXTURES_DEPLOY_KEY, and this build needs the private fixtures" >&2
        exit 1
    fi
    echo "no FIXTURES_DEPLOY_KEY: the tests that need the private fixtures are left out"
    exit 0
fi
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
umask 077
printf '%s\n' "$FIXTURES_DEPLOY_KEY" > "$work/key"
# GitHub's ed25519 host key, as https://api.github.com/meta publishes it
echo "github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl" > "$work/known_hosts"
GIT_SSH_COMMAND="ssh -i \"$work/key\" -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=\"$work/known_hosts\"" \
    git -c credential.helper= clone -q --depth 1 git@github.com:SolidSeas/SolidSeas-fixtures.git "$dest"
python scripts/fetch-fixtures.py --from "$dest"
