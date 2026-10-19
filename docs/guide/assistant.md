# The modeling assistant

The modeling assistant drafts SOLIDWORKS API code from a plain description of a
change, shows you that code, and runs it only when you say so. It is
experimental, in preview, and works in Review mode. [ASSISTANT.md](../ASSISTANT.md)
has the design and its safety rules, and [MCP.md](../MCP.md) describes the
server that lets a chat client use the same tools.

## Opening it

Tools > Modeling Assistant (Ctrl+Shift+A), or the Assistant button on the
viewer's toolbar, opens the assistant's window, which stays on top of SOLIDWORKS
while you model. `SolidSeasViewer.exe --assistant` and
`python -m solidseas_app.assistant` open it on its own.

While SOLIDWORKS is busy or shows a dialog, the window stops staying on top so it
never covers the dialog.

## Drafting a change

1. Pick the SOLIDWORKS session and the document.
2. Describe a change ("fillet the four top edges 2 mm") and press **Draft**.
   The AI model you set up drafts code into the console, with its explanation.
3. Read the code, change it if you like, or type your own.

**What the AI sees** shows exactly what is sent before it goes. The part is
described by numbers and handles only: your file names, paths and property
values never leave the computer, and your feature names only when you tick
"Send my feature and property names".

## Running it

Nothing runs until you press **Run**. Then:

- SOLIDWORKS writes a safety copy of the part and opens one undo entry;
- the script runs in a separate process with a memory cap and a time limit;
  **Stop** ends it at once.

One Ctrl+Z in SOLIDWORKS takes its changes off, but anything it does outside the
SOLIDWORKS undo list, such as writing a file, changing an option or editing a
custom property, cannot be reverted, as the console says beside Run.

The separate process is not a sandbox: the script runs with your own rights and
can do anything you can, so read it before you press Run. The AI is asked to
draft code that works through `solidseas.swapi.live` ([API.md](../API.md) 3.22),
the SOLIDWORKS operations SolidSeas offers, but nothing stops a script from doing
more.

Attaching to a running SOLIDWORKS comes with the live operations of the bridge
in a later stage. Until then the window says so, and runs only scripts that do
not use SOLIDWORKS.

## Setting up the AI

Open Settings > AI Settings (or the assistant's AI Settings button) and set:

- **the provider:** Anthropic, OpenAI, Gemini, or Ollama on your own server. For
  Ollama on another computer give it an `https://` address, since over `http://`
  what is sent, your part's summary included, crosses the network unencrypted;
- **the model,** which is filled in with a default you can change;
- **the API key,** which is kept in Windows Credential Manager and never shown
  again; the page only says whether one is stored.

**Test Connection** checks it, and the monthly budget caps what the assistant
may spend. These settings, never the key, are kept in `AI.json` beside
`Viewer.ini`.

With no AI provider set up, the drafting controls are hidden, the window says so
with a button to AI Settings, and typed code still runs. A provider your
administrator does not allow stays visible, greyed, saying "Set by your
administrator".
