# Connect other apps to SolidSeas

SolidSeas Viewer can let other programs on your PC read the folder you have open:
a script, a spreadsheet or an in-house tool through the local API, and an AI app
such as Claude Desktop through the Model Context Protocol (MCP). Both only read.
Neither writes, renames or locks anything in your folder, and neither needs the
command line.

Everything here is on the **Connector** page of the Settings window (Ctrl+,).

## The Connector page

- **Let other apps on this PC read the open folder** (off until you turn it on)
  starts the local API, below. It reads the folder open in the viewer and its
  subfolders, follows you when you open another folder, and stops when you turn
  it off or close the viewer.
- **Port** is where the local API listens, on this PC only. It is 8765 unless you
  change it.
- The **status** line says whether the local API is running (with its address and
  the folder it reads), starting, stopped, or what went wrong: a port another
  program already uses, a folder that cannot be shared, or a service that ended
  unexpectedly, with the last lines it wrote in a box below.
- **Copy Address** copies the local API's address, such as
  `http://127.0.0.1:8765/v1/`.
- **Show Token File** opens the folder that holds the token file in File
  Explorer. SolidSeas never shows the token itself.
- **Save API Description...** saves the local API's OpenAPI description, which
  HTTP tools and code generators read. The local API does not need to be running.
- **Copy Example** copies a short PowerShell example that calls the local API.
- **AI apps (MCP)** shows the configuration an AI app needs to read the open
  folder, with **Copy Configuration**.

OK or Apply on the Settings window saves the page and starts or stops the local
API to match. SolidSeas never changes another app's settings files: you paste
the configuration yourself.

## The local API

With the option on, the viewer runs the SolidSeas REST service for the open
folder at `http://127.0.0.1:8765/` (or the port you chose). It answers programs
on this PC only, and only those that send a token.

The token sits in a file only your Windows account can read, created the first
time the local API starts:

```
%APPDATA%\SolidSeas\Connector\serve-tokens
```

It holds one line, `default:` followed by the token. A program reads the token
from that file and sends it in a header. Keep it out of command lines, scripts
you share and URLs. Copy Example gives you this, with your own file's path:

```powershell
$line = Get-Content -LiteralPath "$env:APPDATA\SolidSeas\Connector\serve-tokens" | Where-Object { $_ -like 'default:*' }
$auth = @{ Authorization = "Bearer " + $line.Substring(8) }
Invoke-RestMethod -Headers $auth "http://127.0.0.1:8765/v1/roots"
```

The open folder is the root named `folder`, so the next calls ask for documents
below it:

```powershell
Invoke-RestMethod -Headers $auth "http://127.0.0.1:8765/v1/list?root=folder&include=properties"
Invoke-RestMethod -Headers $auth "http://127.0.0.1:8765/v1/document?root=folder&path=Example/bracket.SLDPRT"
```

Every route, parameter and answer is in [API.md](../API.md) section 8. The
description that HTTP tools and code generators read comes from three places,
all the same document: Save API Description... on the Connector page,
`GET /v1/openapi.json` from the running local API (with the token), and the
`solidseas openapi` command ([API.md](../API.md) 8.19).

If the status says the port is in use, another program already listens there:
choose another port on the page and click Apply.

## AI apps (MCP)

An AI app that speaks MCP, such as Claude Desktop or Claude Code, starts
SolidSeas itself and asks it about the folder over a private pipe: no port and
no token, and the local API option above does not need to be on. The Connector
page shows the configuration for the folder you have open, ready to copy. For
Claude Desktop it goes in `claude_desktop_config.json` (in `%APPDATA%\Claude\`),
and looks like this, with your own paths:

```json
{
  "mcpServers": {
    "solidseas-files": {
      "command": "C:\\Path\\To\\SolidSeasViewer.exe",
      "args": ["--cli", "mcp", "--root", "folder=C:\\Path\\To\\Projects"]
    }
  }
}
```

If the file already has an `mcpServers` block, add the `solidseas-files` entry
inside it rather than a second block. Restart the app afterwards. The
configuration names the folder, so it keeps reading that folder when you open
another one in the viewer: copy it again to change it.

The AI app can list the folder's documents, read their summaries, custom
properties, configurations, components, references, bills of materials and
stored previews. [MCP.md](../MCP.md) lists every tool.

When your administrator sets the machine policy that keeps document data on this
PC (`LocalProviderOnly`, see [the modeling assistant](assistant.md)), the
Connector page says so, its AI apps part is greyed, and SolidSeas refuses every
request from an AI app.

## What each option shares, and with whom

- **The local API** shares the open folder with any program on this PC that has
  the token. Your Windows account can read the token file, so any program you
  run can too. The answers include file and folder names below the open folder,
  custom property values (part numbers, descriptions, and whatever else your
  properties hold), author fields, and the paths and user names stored inside the
  files. Nothing leaves your PC unless a program you gave the token sends it on.
- **An AI app** gets everything it asks SolidSeas for, custom property values
  included, and usually sends it to its AI model, which runs on someone else's
  servers. Configure it only with a folder you are content to share with that
  app.

Neither option ever sends the folder's own path on this PC, and neither reads
anything outside the folder.

## Turning it all off

- Clear **Let other apps on this PC read the open folder** and click OK. The
  local API stops at once, and does not start again when you open the viewer.
- Remove the `solidseas-files` entry from the AI app's configuration and restart
  the app.
- To stop every program that had the token from using it again, delete the
  token file (Show Token File shows where it is) while the local API is off. A
  new token is made the next time it starts.
