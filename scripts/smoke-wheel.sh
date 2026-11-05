#!/usr/bin/env bash
# Check a built SolidSeas wheel the way someone installing it from a package index meets it:
# install it, with its dependencies from PyPI, into a new virtual environment for each Python
# given, away from the source tree, and run the installed `solidseas` command there.
#
# In each environment it checks that pip check finds no broken dependency, that the package
# is imported from the environment and not the checkout, that the serve viewer's files and
# three.js were installed, and that these commands work: `version --json`, `info --json` and
# `list --json` on tests/fixtures/o02_boxA.STL, `openapi` (valid OpenAPI JSON), `serve --port 0
# --json --viewer` answering /v1/health and /viewer/ and stopping cleanly on SIGINT, and
# `mcp` answering initialize and tools/list over a pipe.
#
# Usage: scripts/smoke-wheel.sh WHEEL [PYTHON...]
#   WHEEL   the .whl that `uv build` wrote
#   PYTHON  versions or interpreters for `uv venv --python` (default: 3.11 3.12 3.13)
# Needs uv. Prints PASS or FAIL for each Python and exits non-zero if any failed.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
wheel="$(realpath "${1:?usage: scripts/smoke-wheel.sh WHEEL [PYTHON...]}")"
shift
pythons=("$@")
[ ${#pythons[@]} -gt 0 ] || pythons=(3.11 3.12 3.13)
fixture="$ROOT/tests/fixtures/o02_boxA.STL"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

check_one() {
    local py="$1" env="$work/venv-$1" data="$work/data-$1"
    set -e
    uv venv --quiet --seed --python "$py" "$env"
    uv pip install --quiet --python "$env/bin/python" "$wheel"
    "$env/bin/python" -m pip check
    mkdir -m 700 "$data"
    cp -f "$fixture" "$data/"
    cd "$work"
    local exe="$env/bin/solidseas"
    "$exe" version --json | "$env/bin/python" -c 'import json,sys; d=json.load(sys.stdin); print("version", d["data"]["solidseas"], "on Python", sys.version.split()[0])'
    "$exe" info --json "$data/o02_boxA.STL" | "$env/bin/python" -c 'import json,sys; assert json.load(sys.stdin)["ok"]'
    "$exe" list --json --formats stl "$data" | "$env/bin/python" -c 'import json,sys; assert json.load(sys.stdin)["ok"]'
    "$exe" openapi | "$env/bin/python" -c 'import json,sys; assert json.load(sys.stdin)["openapi"].startswith("3.")'
    "$env/bin/python" -I - "$exe" "$data" <<'EOF'
import json, os, signal, subprocess, sys, urllib.request
import solidseas, solidseas.serve.server as server

exe, data = sys.argv[1], sys.argv[2]
assert "site-packages" in solidseas.__file__, solidseas.__file__
for rel in ("index.html", "viewer.js", "viewer.css", "three/build/three.module.min.js", "three/LICENSE"):
    assert os.path.isfile(os.path.join(server.VIEWER_DIR, rel)), rel

# The REST service on a free port, with its token file in a private folder.
serve = subprocess.Popen(
    [exe, "serve", "--port", "0", "--json", "--viewer", "--root", f"box={data}",
     "--token-file", os.path.join(data, "tokens.txt"), "--workers", "1"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
try:
    started = json.loads(serve.stdout.readline())
    url = started["data"]["url"]
    with urllib.request.urlopen(url + "health", timeout=30) as r:
        assert json.load(r)["kind"] == "health"
    with urllib.request.urlopen(url.removesuffix("v1/") + "viewer/", timeout=30) as r:
        assert b"<html" in r.read().lower()
finally:
    serve.send_signal(signal.SIGINT)
    code = serve.wait(timeout=60)
assert code == 0, f"serve exited {code}: {serve.stderr.read()[-2000:]}"

# The MCP server: initialize, initialized, tools/list, then end of input.
lines = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "1"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
]
out = subprocess.run([exe, "mcp", "--root", f"box={data}"], input="".join(json.dumps(m) + "\n" for m in lines),
                     capture_output=True, text=True, timeout=120)
assert out.returncode == 0, out.stderr[-2000:]
replies = {m["id"]: m for m in map(json.loads, out.stdout.splitlines())}
assert replies[1]["result"]["serverInfo"], replies[1]
tools = [t["name"] for t in replies[2]["result"]["tools"]]
print(f"serve: health and viewer answered, stopped cleanly; mcp: {len(tools)} tools")
EOF
}

failed=0
for py in "${pythons[@]}"; do
    echo "== Python $py"
    # A subshell of its own, outside any condition, so that set -e stops at the first failure.
    ( check_one "$py" )
    if [ $? -eq 0 ]; then echo "PASS $py"; else echo "FAIL $py"; failed=1; fi
done
exit $failed
