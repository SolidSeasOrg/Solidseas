"""A stand-in MCP server on standard input and output, for tests of
:class:`solidseas.helpers.McpHelper` and the SolidCraft extension: it lists three tools
over two pages, answers ``echo`` with what it was given and an image, fails ``broken``
with a tool error, and with ``--version V`` claims that MCP revision."""

import json
import sys

version = sys.argv[sys.argv.index("--version") + 1] if "--version" in sys.argv else None
PAGES = [
    [{"name": "echo", "description": "Say it back", "inputSchema": {"type": "object"}}],
    [
        {"name": "broken", "description": "Always fails", "inputSchema": {"type": "object"}},
        {"name": "crash_reports", "description": "Crash reports", "inputSchema": {"type": "object"}},
    ],
]
initialized = False
for line in sys.stdin:
    m = json.loads(line)
    if "id" not in m:
        initialized = initialized or m.get("method") == "notifications/initialized"
        continue
    method, params = m.get("method"), m.get("params") or {}
    if method == "initialize":
        result = {
            "protocolVersion": version or params.get("protocolVersion"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake-mcp", "version": "1"},
            "argv": sys.argv[1:],
        }
    elif method == "tools/list":
        page = int(params.get("cursor") or 0)
        result = {"tools": PAGES[page]}
        if page + 1 < len(PAGES):
            result["nextCursor"] = str(page + 1)
    elif method == "tools/call" and params.get("name") == "echo":
        text = json.dumps({"args": params.get("arguments"), "initialized": initialized, "argv": sys.argv[1:]})
        result = {
            "content": [
                {"type": "text", "text": text},
                {"type": "image", "data": "iVBORw==", "mimeType": "image/png"},
            ]
        }
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "it broke"}], "isError": True}
    else:
        sys.stdout.write(
            json.dumps(
                {"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32601, "message": "no such method"}}
            )
            + "\n"
        )
        sys.stdout.flush()
        continue
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": result}) + "\n")
    sys.stdout.flush()
