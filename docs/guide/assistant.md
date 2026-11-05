# The modeling assistant

The modeling assistant drafts SOLIDWORKS API code from a plain description of a
change, shows you that code, and runs it only when you say so (Review mode).
In Automatic mode it plans a goal and carries the plan out step by step, from a
fixed set of operations SolidSeas checks. It is experimental: check what it does
to your part before you save it. [ASSISTANT.md](../ASSISTANT.md)
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

## Showing the AI a picture of the part

Tick **Show the AI a picture of the part** to send a picture of the part with
your request, so the model sees its shape as well as its numbers. It is off
until you tick it. The picture is drawn by SolidSeas: the part in grey, seen
from the front, right and above, with no text, file name or dimension in it.
It shows the part as it was last saved, so changes you have not saved in
SOLIDWORKS are not in it. What the AI sees shows a line where the picture goes.

When **Automatic** is ticked (the model plans your goal once and SolidSeas
carries the plan out step by step), you can also tick **Show it the part after
each step**. After each step passes SolidSeas' own checks, SolidSeas saves a
copy of the part as it is at that moment, unsaved changes included, draws it,
and asks the model whether the part looks the way that step should leave it.

- If the model says it looks right, or cannot tell, the run goes on.
- If the model says it does not look right, the run stops after that step and
  the log says why. The step stays in the part, since it passed the checks:
  choose **Keep** or **Revert** as after any run.
- The model's look never lets through a step that SolidSeas' checks refused.
  If a look cannot be made, the log says so and the run goes on.

Each look is one more request to the AI, with a picture, so it counts against
your budget, and each copy takes SOLIDWORKS a moment. The copies are kept in
the run's folder, beside its safety copy. SolidSeas removes a run's folder once
the run has ended and nothing in the folder has changed for 7 days, the next
time the assistant or its MCP server starts.

## A run that did not finish

If SolidSeas closed in the middle of an Automatic run, or before you chose
**Keep** or **Revert**, the run is still open. The next time you open the
assistant, a box at the top shows it: the part, your goal, each step of the
plan and whether it was done, how far the run got, and where the safety copy
is. If more than one run is open, they come one at a time, oldest first.
Nothing happens to the run until you choose:

- **Revert** takes the run's steps off the part in SOLIDWORKS, newest first,
  the way Revert does after a run. The part has to be open in SOLIDWORKS and
  still exactly as the run's last step left it. If you closed it, changed it,
  or SolidSeas closed while a step was running and that step changed it,
  Revert changes nothing and says what is different. The safety copy then
  holds the part as it was before the run: open it in SOLIDWORKS as a separate
  document.
- **Keep** leaves the part as it is and closes the run.
- **Decide Later** does nothing. The run is offered again the next time the
  assistant opens, until SolidSeas removes its folder 7 days after its last
  change; the box gives the date.

Neither choice saves the part: save it in SOLIDWORKS when you are ready. A run
that another SolidSeas window, or the MCP server, is still working on is never
shown. The MCP server does not show or report these runs itself; they wait for
the assistant window.

Both boxes are greyed out, with "Set by your administrator", where your
administrator has turned pictures off.

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

The assistant reaches the SOLIDWORKS running on your PC through the CAD Bridge
extension (Tools > Extensions), on Windows. Without it the window says why, and
runs only scripts that do not use SOLIDWORKS.

## Automatic mode

Tick **Automatic** and describe a goal instead of a change. The AI model plans
the goal once, as steps from a fixed set of operations (a dimension's value,
an extruded boss or cut from a sketch, a fillet, a chamfer, a shell, a linear
or circular pattern, suppressing or unsuppressing a feature, and a custom
property), and SolidSeas checks every step before anything runs. The plan appears in the Plan panel, with where each value came from.

- A plan that only adds to the part, or sets only dimension values you gave,
  starts by itself. A plan that suppresses or unsuppresses a feature, writes a
  custom property or sets a value you did not give waits for **Run plan**.
- SolidSeas writes a safety copy of the part first, then carries out each step in
  its own undo entry and checks that it changed only what it should. A step that
  fails its checks is taken off at once and the run stops.
- **Stop** ends the run between two steps.
- Afterwards, **Keep** leaves the part as it is and **Revert** takes the run's
  steps off, newest first.

Automatic mode never runs code the AI wrote, and never saves your part: save it
in SOLIDWORKS when you are happy with it. Your administrator can turn Automatic
mode off; the box is then greyed, saying "Set by your administrator".

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

## For administrators: restricting SolidSeas on a PC

An administrator can restrict SolidSeas for everyone who uses a PC with the
machine policy: values under `HKLM\SOFTWARE\Policies\SolidSeas`, which
SolidSeas reads again each time it checks them, so a change needs no restart.
[ASSISTANT.md](../ASSISTANT.md) ("Machine policy") has the details.

| Value | What it does |
|---|---|
| `DisableAutomaticMode` | 1 makes Automatic mode unavailable |
| `LocalProviderOnly` | 1 lets the assistant use only an Ollama server on this PC, or on a host listed in `AllowedProviderHosts` |
| `AllowedProviderHosts` | host names or addresses that also count as local, for an approved Ollama server |
| `DisableImages` | 1 stops pictures of a part going to any model |
| `DisableExtensions` | 1 switches every extension off |
| `AllowedExtensions` | the only extensions that may be switched on |

Group Policy or Intune deploys them to many PCs. On one PC, run SolidSeas as
administrator with `--set-policy` and the values to set, from a prompt started
with **Run as administrator**:

```
SolidSeasViewer.exe --set-policy DisableAutomaticMode=1 LocalProviderOnly=1 AllowedProviderHosts=ollama.example.internal | more
```

- Values you do not name stay as they are. `--remove NAME` removes one, and
  `--remove-all` removes the whole key, so SolidSeas is no longer restricted.
- Every value is checked before any is written: a DWORD is 0 or 1, a list is
  separated by commas. A mistake writes nothing.
- Each change also records who made it and when, as `SetBy` and `SetAt`.
- SolidSeas then reads the policy back and shows it as it reads it. The
  program has no console of its own, so `| more` shows what it says.
- The exit code is 0 when the policy reads as asked, 1 when it could not be
  written or does not read as asked, 2 for a mistake in the command, and 3
  when SolidSeas was not run as administrator. After 2 or 3 nothing is
  written. After `| more` the exit code a prompt shows is `more`'s; to get
  SolidSeas' own, wait for it from PowerShell:
  `(Start-Process SolidSeasViewer.exe -ArgumentList '--set-policy','LocalProviderOnly=1' -Verb RunAs -Wait -PassThru).ExitCode`.
- Run it from the all-users installation, under `C:\Program Files`, never from
  a copy in your own folders: it runs elevated, so its files must be ones only
  administrators can change.

Group Policy writes its own values again at its next refresh, so remove or
change a value Group Policy sets in Group Policy itself.
