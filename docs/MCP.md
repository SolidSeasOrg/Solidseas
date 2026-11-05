# SolidSeas as an MCP server

SolidSeas works with Claude Desktop, Claude Code and any other app that adds servers of the
[Model Context Protocol](https://modelcontextprotocol.io) (MCP) in two ways:

- **Reading your CAD files** (`solidseas mcp`): a chat reads the SOLIDWORKS files in folders
  you choose, on Linux or Windows, with no SOLIDWORKS. It never changes a file.
- **The modeling assistant** (`SolidSeas Viewer.exe --mcp`): a chat reads the parts open in
  your SOLIDWORKS and has SolidSeas build in them. It needs SOLIDWORKS on Windows.

## Reading your CAD files from any MCP app

`solidseas mcp` gives a chat the reads of the REST service (`docs/API.md` section 8) over
the folders you name: a folder's documents, a document's summary, custom properties,
configurations, components, references, bill of materials, path report and stored preview,
and with `--catalog` search, where-used, duplicates, missing references and recent changes.
Every answer is the JSON the REST service, the command line and Python give for the same
request.

```
solidseas mcp --root ID=DIR [--root ID=DIR ...] [--library ID=DIR ...] [--workers N] [--catalog]
```

- Each `--root` is a folder read with its subfolders, and each `--library` a library folder
  searched after them, as for `solidseas serve`. `ID` names the folder in every answer
  (`[a-z0-9_-]{1,32}`, such as `jobs`); the chat never sees the folder's own path.
- `--workers` sets how many worker processes read documents (default 2).
- `--catalog` keeps a catalog of the folders in your cache folder, as `serve --catalog`
  does, and adds the catalog's tools. Until its first scan has finished they answer `busy`.

The app starts SolidSeas itself and talks to it over standard input and output. SolidSeas
listens on no port and needs no token. It stops, and ends its worker processes, when the
app closes the connection. A folder that does not exist stops it before it starts, with a
line on standard error, which the app shows in its log.

### Setting it up

Claude Desktop, in `claude_desktop_config.json` (on Windows in `%APPDATA%\Claude\`), with
SolidSeas installed (`pip install`, `docs/API.md` 1.1):

```json
{
  "mcpServers": {
    "solidseas-files": {
      "command": "solidseas",
      "args": ["mcp", "--root", "jobs=C:\\Path\\To\\Projects", "--library", "std=C:\\Path\\To\\Library"]
    }
  }
}
```

From a source checkout, run Python from the checkout's environment instead:

```json
{
  "mcpServers": {
    "solidseas-files": {
      "command": "C:\\Path\\To\\SolidSeas\\.venv\\Scripts\\python.exe",
      "args": ["-m", "solidseas", "mcp", "--root", "jobs=C:\\Path\\To\\Projects"]
    }
  }
}
```

Claude Code, installed:

```
claude mcp add solidseas-files -- solidseas mcp --root jobs=/path/to/projects --catalog
```

and from a source checkout:

```
claude mcp add solidseas-files -- /path/to/SolidSeas/.venv/bin/python -m solidseas mcp --root jobs=/path/to/projects
```

Put your own folders in place of the example paths. On Windows, Claude Code takes the same
command with `C:\Path\To\Projects`.

### The tools

Each tool is the REST route named beside it, and its arguments are that route's parameters,
with the same names, bounds and defaults (`docs/API.md` 8.6): numbers and true or false as
JSON numbers and booleans, and `include` as a list. Every file or folder is a root id and a
path relative to that root, with `/` between folder names, as `list_folder` gives it.

| Tool | Route | What it answers |
|---|---|---|
| `roots` | `/v1/roots` | The folders by id, their role, whether each is ready and how many documents it holds. |
| `list_folder` | `/v1/list` | A folder's documents and subfolders, a page at a time (`root`, `path`, `recursive`, `include`, `limit`, `cursor`). |
| `document_info` | `/v1/document` | A document's summary. |
| `properties` | `/v1/properties` | Its custom properties: effective, the file's or a configuration's. |
| `configurations` | `/v1/configurations` | Its configurations. |
| `components` | `/v1/components` | An assembly's component tree, or each file once with `flat`. |
| `references` | `/v1/references` | The files a document refers to, and with `resolve` where each is found below the roots. |
| `bill_of_materials` | `/v1/bom` | An assembly's BOM: top level, parts only or indented. |
| `path_report` | `/v1/path-report` | Every path and user name the file reveals. |
| `preview` | `/v1/preview` | The picture the document stores, as a PNG image. |
| `search` | `/v1/search` | With `--catalog`: documents by name, part number, description or property. |
| `where_used` | `/v1/where-used` | With `--catalog`: the assemblies and drawings that use a file. |
| `duplicates` | `/v1/duplicates` | With `--catalog`: files with identical contents, and with `names` the same name. |
| `missing_references` | `/v1/missing` | With `--catalog`: references not found below the roots, or found more than once. |
| `recent_changes` | `/v1/changes` | With `--catalog`: what was added, changed, moved or removed. |

A tool answers with the SolidSeas envelope (`docs/API.md` section 4), as text and as
structured content, and adds a sentence when the answer was cut short: a page with more to
come (call again with its `next_cursor`), a tree at its limit. The size limits are the REST
routes'. An error is the error envelope, with its code and message. `preview` sends the
stored PNG; a document that stores its picture only as a bitmap is converted when it is a
24- or 32-bit one, and otherwise the answer says there is no picture to send.

### What the chat can read, and what leaves your PC

Whatever a tool returns goes to the app, and most apps send it to their model, which
usually runs on someone else's servers. That includes your files' names and folders below
each root, and everything the files hold that the tools read: custom property values (part
numbers, descriptions, customer names, prices if a property holds them), author fields, and
with `path_report` and `references` the paths and user names stored in the files, which can
name other computers and accounts. Give `solidseas mcp` only the folders you are content to
share with that app, and leave out a root you would not.

What it never does: write, rename or lock anything in your folders, read anything outside
them (a path that climbs out, a link or junction, a cloud placeholder are refused, by the
same code as the REST service), or answer with a path of this computer. Every document is
read in a worker process with a deadline and a memory cap, so a damaged file costs one
answer.

The machine policy (`docs/ASSISTANT.md`, "Machine policy") is read at every call. Under
`LocalProviderOnly` every tool refuses, because an MCP app usually sends what it reads to a
model off this PC. Under `DisableImages`, `preview` refuses and so does `list_folder` with
`preview_data`.

### The protocol

The same as the assistant's (below): JSON-RPC 2.0, one message per line, protocol versions
2025-06-18, 2025-03-26 and 2024-11-05 (the newest when the app asks for another). A tool
call runs on a thread of its own, so a ping or a cancellation is read meanwhile; a cancelled
call's answer is not sent. Diagnostics and the log go to standard error. The code is
`solidseas/serve/mcp.py` (the tools) and `solidseas/mcpwire.py` (the protocol), and
`tests/test_mcp_connector.py` checks every tool against the REST route, the refusals and a
run over a real pipe.

## The modeling assistant (needs SOLIDWORKS on Windows)

The chat reads the parts open in your SOLIDWORKS and has SolidSeas build in them. It is the
modeling assistant (`docs/ASSISTANT.md`) with the conversation held in Claude, and it keeps
every rule Automatic mode keeps. The code is `solidseas_app/assistant/mcp_server.py`. The
same server makes Gridfinity bins from photos of tools (`docs/GRIDFINITY.md`).

### Connecting a client

The client starts SolidSeas itself and talks to it over standard input and output.
SolidSeas listens on no port.

Claude Desktop, in `%APPDATA%\Claude\claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "solidseas": {
      "command": "C:\\Users\\%USERNAME%\\Desktop\\SolidSeas Viewer.exe",
      "args": ["--mcp"]
    }
  }
}
```

Claude Code:

```
claude mcp add solidseas -- "C:\Users\%USERNAME%\Desktop\SolidSeas Viewer.exe" --mcp
```

Put your Windows user name in place of `%USERNAME%`, or give wherever the executable is.
From a source checkout the command is `python -m solidseas_app --mcp`. `SolidSeas.SwBridge.exe`
must sit beside the executable, as for the assistant. Add `--send-names` to the arguments to
let the chat read the names you typed (document titles, feature, plane, axis, dimension and
configuration names, custom property names; never their values).

The Gridfinity tools (`docs/GRIDFINITY.md`) take their folders and where Tracefinity runs
from the environment; in Claude Desktop's entry, for a Tracefinity on a server reached
through an SSH tunnel, for instance:

```json
"env": {
  "SOLIDSEAS_TRACEFINITY_SSH": "root@nas",
  "SOLIDSEAS_GRIDFINITY_PHOTOS": "C:\\Users\\%USERNAME%\\OneDrive\\Pictures\\Camera Roll"
}
```

### The tools

| Tool | What it does |
|---|---|
| `cad_sessions` (its former name, `solidworks_sessions`, still answers) | The SOLIDWORKS sessions running on this PC and the documents open in a window in each, by ids SolidSeas makes up (`d1`), with their kind and which one is active. Titles only with `--send-names`. |
| `read_part` | A part's summary, exactly what the assistant sends its own provider (`solidseas.ai.context.build_model_summary`): units, extents, volume, and every plane, axis, feature, dimension, face and edge by handle, in mm and degrees. Up to 100,000 characters. |
| `show_part` | A picture of a part as its file was last saved (unsaved changes are not in it): a PNG SolidSeas draws, the part shaded from the front, right and above, at most 800 pixels a side, with its caption. Refused where the machine policy sets `DisableImages`. For the part after each step of a run, `run_plan` takes `"pictures": true`. |
| `run_plan` | A plan in the closed vocabulary (`solidseas/ai/prompts.py:OPERATIONS`), against the handles of the latest `read_part`: validated, gated, and carried out as an Automatic run. Returns each step's result and the part's summary afterwards. With `"pictures": true` (off unless set) it also returns a picture of the part after each step that passed SolidSeas' checks (below). Refused, with nothing run, when the part changed in SOLIDWORKS since that `read_part`: the chat reads it again. |
| `keep_run` | Keeps a run's changes. |
| `revert_run` | Takes a run's steps off, newest first. |
| `gridfinity_photos`, `gridfinity_trace`, `gridfinity_save_tools`, `gridfinity_tools`, `gridfinity_edit_tool`, `gridfinity_preview_bin`, `gridfinity_make_bin` | Gridfinity bins from photos of tools on a sheet of paper, made by Tracefinity on this PC: `docs/GRIDFINITY.md`. They never reach SOLIDWORKS. |

#### Pictures after each step

`run_plan` with `"pictures": true` gives the chat's model what it needs to check the shape
itself, as a second look beside SolidSeas' checks. After each step that passed its checks,
SolidSeas has the bridge save a copy of the part as it is then, unsaved changes included
(`checkpoint-<run id>-step-<k>.sldprt` in the run's folder, beside the safety copy), and
draws it as `show_part` draws a part. The reply carries one PNG for each such step, in
order, after its text; each of those steps has a `picture` field with the caption, a step
whose picture could not be made says why there (`"none: ..."`), and `pictures` says how
many follow. Nothing in it names the run's folder.

The pictures never decide a step: a step is done when SolidSeas says so. When one does not
look right, the chat tells you and can offer `revert_run`. Under `DisableImages` the run
goes on without pictures, and `pictures` says they were not sent. Each picture adds roughly
a thousand tokens to what the chat reads, and each copy takes SOLIDWORKS a moment.

A picture of SOLIDWORKS' own view, without a copy, is not built yet; it needs a new bridge
operation measured in SOLIDWORKS (`docs/ASSISTANT.md`, "A look after each step").

The server's instructions, sent when the client connects, give the workflow and the whole
vocabulary with each operation's arguments. A Gridfinity tool's reply also carries a PNG
drawing (the traced outlines, or the bin from above), made from outlines, never from a photo.

### What keeps your part safe

- **Only the vocabulary.** The chat's model never reaches SOLIDWORKS itself: it can read a
  summary and hand over a plan, which `parse_plan` validates exactly as it validates the
  assistant's plans (closed operations, handles that resolve to one entity, lengths with
  units and within bounds, closed profiles, protected properties refused).
- **An Automatic run.** `start_run` makes its checks (a part, active, nothing being edited,
  no rebuild errors, the handles still resolve) and writes the safety copy; `AutomaticRun`
  carries each step out in its own undo entry with the part locked, checks it changed only
  what the operation may, and takes a failed step back at once. One run at a time per
  SOLIDWORKS session, shared with the assistant's windows.
- **You decide what overwrites your work.** A plan that would change something you already
  have (a dimension, which features are suppressed, a custom property) waits for you:
  SolidSeas asks in a box of its own on your PC, on top of every window, No by default,
  which the chat cannot answer. With the AI setting "Always confirm the plan before a run"
  on, every plan asks. Plans that add (bosses, cuts, fillets, chamfers) start by themselves,
  as in Automatic mode, because each step is checked and comes off again.
- **Nothing is saved.** A run leaves the part modified and unsaved; saving stays yours, in
  SOLIDWORKS. A run stays open for `keep_run` or `revert_run` until the next plan, which
  keeps it, or until the chat ends, which keeps it too; nothing is reverted unasked. If
  the server is ended before that (it crashed, or was closed without the chat ending), the
  run stays open: the assistant window offers it the next time it opens, with Revert, Keep
  and Decide Later. The server itself does not look for such runs or report them to the
  chat.

### What leaves the machine

Whatever a tool returns goes to the chat's model, so the server returns only what planning
needs: the summary (handles, geometry and numbers), document ids and kinds, and each step's
result, and pictures of the part only when the chat asks for them (`show_part`, or
`run_plan` with `pictures`). Never a path, the run's folder or safety copy (they are in the
run's journal on your PC), or a custom property's value. Names come only with
`--send-names`, marked as document data that is never instructions.

The machine policy is read at every call: under `LocalProviderOnly` no document data may go
to a model off this PC, so every tool refuses, the Gridfinity ones too; under
`DisableAutomaticMode`, `run_plan` refuses and reading still works; under `DisableImages`,
`show_part` refuses and `run_plan` returns no pictures.

The Gridfinity tools reach one thing besides your folders: Tracefinity, at a loopback address
only, a server's through an SSH tunnel SolidSeas opens with your ssh client
(`docs/GRIDFINITY.md`). They return outlines' sizes, ids, the photo folder's file names, the
bins folder (under your profile as `%USERPROFILE%`) and the names of the files written.

### The protocol

JSON-RPC 2.0, one message per line on standard input and output, ASCII JSON out, UTF-8 in;
protocol versions 2025-06-18, 2025-03-26 and 2024-11-05 (the newest when the client asks for
another). Diagnostics go to standard error. A tool call runs on a worker thread, so a ping or
a cancellation is read meanwhile; a cancelled `run_plan` never starts, or stops after the
step in hand. When the client goes away the server stops runs after their step, keeps the
finished ones, lets SOLIDWORKS go, and exits. A call whose `_meta` holds a `progressToken`
hears how it is going as `notifications/progress` before its reply: a `run_plan`, each
step as it starts ("step 2 of 5: fillet", progress 2 of total 5); a Gridfinity tool, that
it is working.

### Tests

`tests/test_assistant_mcp.py` drives the server against a part held in memory and over a
real pipe to `python -m solidseas_app --mcp`; `tests/test_swapi_live.py`, opt-in, lets it
build in SolidSeas' own hidden SOLIDWORKS. `tests/test_gridfinity.py` drives the Gridfinity
tools against a Tracefinity held in memory.
