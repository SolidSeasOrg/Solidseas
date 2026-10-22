# Gridfinity bins from photos

Take a photo of your tools lying on a sheet of paper, and a chat in Claude Desktop or Claude
Code makes a [Gridfinity](https://gridfinity.xyz) bin with a pocket shaped to each tool,
ready to print. The sheet of paper is the scale: its known size gives every outline's size
in millimetres, whatever the camera.

[Tracefinity](https://github.com/tracefinity/tracefinity) (MIT), running in Docker on a
server of yours or on your PC, does the image work and makes the bin: it finds the paper's
corners, takes the perspective out, traces the tools and builds the STL. SolidSeas drives it
for the chat, lays the tools out in the smallest bin they fit, and saves the files. The
tools are part of SolidSeas' MCP server (`docs/MCP.md`); the code is
`solidseas_app/gridfinity/`.

## Setting up

Tracefinity is published only as a Linux container. Run it on a Linux server with Docker
(an Unraid box, say), where it is always on and costs your PC nothing, or on your PC under
Docker Desktop. Either way it runs without a sign-in, so it listens only on its own
machine's loopback: SolidSeas reaches a server's Tracefinity through an SSH tunnel it opens
itself, and nothing else on your network reaches it at all.

### On a server (an SSH tunnel)

1. Run, from the SolidSeas folder in PowerShell, with the server as ssh takes it:

   ```
   scripts\tracefinity-server.ps1 -Server root@nas
   ```

   It makes an SSH key for the tunnel, `%USERPROFILE%\.ssh\solidseas_tracefinity`, then
   signs in to the server once with ssh (type the server's password when ssh asks for it) and
   there:

   - lets that key open a tunnel to Tracefinity's port and nothing else: no shell, no
     command (the key has no passphrase so SolidSeas can use it unattended, which is why it
     can do nothing more). On Unraid the key also goes in `/boot/config/ssh/root.pubkeys`, so
     it survives a reboot;
   - starts Tracefinity (about 3.5 GB to download the first time) as the container
     `tracefinity`, on the server's `127.0.0.1:3077` only, with `AUTH_MODE=open`, its
     library and tracing model in `/mnt/user/appdata/tracefinity` (`-AppData` for another
     folder) owned by `99:100` (`-Owner`), started again with Docker; it shows on Unraid's
     Docker page beside your other containers;
   - downloads the tracing model (about 170 MB) once, so no chat waits for it.

   Last it opens the tunnel with the new key and checks Tracefinity answers. Run it again to
   start a stopped container; it does not add the key twice.
2. Set `SOLIDSEAS_TRACEFINITY_SSH` to the server (`root@nas`) in SolidSeas' entry of the
   MCP client's settings (`docs/MCP.md`).

SolidSeas opens the tunnel, 127.0.0.1:3077 on your PC to 127.0.0.1:3077 on the server, the
first time a chat needs Tracefinity, opens it again if it drops (after the PC slept, say),
and closes it when the chat's SolidSeas ends. ssh never asks anything there and never
accepts a server key it has not seen before. While it is open, Tracefinity's own pages are
at `http://127.0.0.1:3077` on your PC, where you can also edit an outline or a bin by hand.

### On your PC (Docker Desktop)

1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it.
2. Start Tracefinity, from the SolidSeas folder in PowerShell:

   ```
   scripts\tracefinity.ps1
   ```

   The first run downloads Tracefinity's image (about 3.5 GB). The script makes a container
   named `tracefinity` that:

   - listens on `127.0.0.1:3077` only, so nothing else on your network reaches it;
   - runs with `AUTH_MODE=open`: one library and no sign-in, which is safe only because of
     the line above;
   - keeps its library (your tools, bins and the photos you traced) in
     `%LOCALAPPDATA%\SolidSeas\tracefinity\storage`, and its tracing model in `...\models`,
     so neither is lost with the container. The script has Tracefinity download the model
     from GitHub (about 170 MB) the first time, so no chat waits for it;
   - starts again whenever Docker Desktop does (start Docker Desktop after a restart unless
     it starts when you sign in).

   Run the script again to start it if it is stopped. `scripts\tracefinity.ps1 -Remove`
   deletes the container and keeps both folders. Tracefinity's own pages are at
   `http://127.0.0.1:3077`, where you can also edit an outline or a bin by hand.

Then connect SolidSeas to Claude as `docs/MCP.md` says. The Gridfinity tools come with it.

## Taking the photos

- Lay the tools flat on a plain sheet of A4, Letter, A3 or Tabloid paper, apart from each
  other.
- Put the paper on a plain surface darker than it, with all four corners in view.
- Take the photo from straight above, in even light without hard shadows.
- A tool may reach past the paper's edge as long as it lies on the same surface.
- One photo can hold several tools.

Put the photos in `%USERPROFILE%\Pictures\Gridfinity` (JPEG, PNG, WebP, HEIC or GIF, up to
20 MB). The folder is made the first time the chat looks for photos. A phone's camera
folder synced to the PC works too: name it in `SOLIDSEAS_GRIDFINITY_PHOTOS` (below).

## In a chat

Ask for what you want, for instance "Make a bin for the tools in my newest Gridfinity
photo; they are on Letter paper and about 10 mm thick." The chat then:

1. lists the photos (`gridfinity_photos`);
2. traces one (`gridfinity_trace`), which takes a few seconds. It shows each outline's
   length, width and area, and a drawing of the outlines, numbered left to right. Check the
   sizes, and tell the chat what each tool is;
3. saves the outlines that are tools into the library, by name (`gridfinity_save_tools`);
4. lays the bin out and shows you a drawing of it from above, before anything is made
   (`gridfinity_preview_bin`). Change it in words: "turn the pliers 90 degrees", "put the
   knife on the left" (see Placing tools by hand below);
5. makes the bin (`gridfinity_make_bin`) and shows a drawing of it from above. The STL is
   saved in `%USERPROFILE%\Documents\Gridfinity bins`, named after the bin and its size, as
   in `wrench and socket 5x2x3.stl` (5 units across, 2 deep, 3 high). A bin larger than your
   printer's bed (256 mm unless you say) also comes as a zip of parts that fit. Ask for a
   label too ("with its name on it") and the bin carries text (see Labels below).

Saved tools stay in the library, so a later bin can use them without a new photo
(`gridfinity_tools`).

| Tool | What it does |
|---|---|
| `gridfinity_photos` | The photos in the photos folder, newest first: file name, when it was changed, size. |
| `gridfinity_trace` | Has Tracefinity trace one photo, given the paper's size: a trace id, each outline's length, width and area in mm, a drawing of the outlines, and the address of the trace in Tracefinity. Nothing is saved to the library yet. |
| `gridfinity_save_tools` | Saves outlines of a trace into the library, each with a name and a finger scoop (unless asked not to). |
| `gridfinity_tools` | The library, newest first: id, name, length and width. |
| `gridfinity_edit_tool` | Renames a tool, or adds or takes off the finger scoop SolidSeas placed. |
| `gridfinity_preview_bin` | Lays tools out as `gridfinity_make_bin` would and makes nothing: returns the grid, where each tool goes (its turn, its centre and its pocket in mm), the room for pockets and a drawing. Takes the same arguments, and each tool can be turned (`turned_deg`) or placed by hand (`centre_mm`). |
| `gridfinity_make_bin` | Lays tools out and has Tracefinity make the bin, with a text label if asked; saves its files and returns the grid, the file names, a drawing and the bin's address in Tracefinity. |

## How a bin is made

- **Pockets.** Each tool gets a pocket of its outline grown by the clearance (1 mm unless
  asked), as deep as you say. Ask the chat for a different depth for one tool if it is
  thicker; the bin is made as tall as the deepest pocket needs (Tracefinity keeps 4.75 mm of
  base and 2 mm of floor under it), or you give the height in units of 7 mm.
- **Layout.** Each tool is turned so its smallest bounding rectangle is square to the bin,
  lying across or along the bin's depth, whichever packs better. Tools are packed in rows,
  tallest first, with 3 mm of bin between pockets unless asked, and the smallest bin they
  fit in is kept: the fewest grid cells, then the squarest. Ask for a grid (units across,
  units deep, 42 mm a unit) to fit a drawer; if the tools do not fit in it, the chat is told
  the smallest bin they do fit in. A tool listed twice gets two pockets.
- **Finger scoops.** A round scoop lets you lift a tool out. On a tool at most 28 mm wide at
  the middle of its length, it goes across the middle and reaches at least 6 mm past each side; on a
  wider tool it sits half over one long edge, at the middle. The scoop belongs to the tool in
  the library, so every bin with that tool has it, and Tracefinity's editor shows it.
- **The rest** follows Tracefinity's defaults: magnet holes in the base (6 x 2.4 mm), a
  stacking lip, a 1.6 mm wall. The chat can turn magnets or the lip off, or allow half grid
  units (a half-grid base has no magnet holes).
- **By hand.** The bin opens in Tracefinity exactly as laid out, at the address the chat
  gives, label included, to move a tool or a label, add a finger hole, and download again
  from there. The chat can also place tools by hand before the bin is made (below).

## Placing tools by hand

Before the bin is made the chat shows you its layout (`gridfinity_preview_bin`), and you can
change it in words, as you would drag tools in Tracefinity's editor:

- **Turn a tool.** "Turn the pliers 90 degrees" turns them that far, clockwise seen from
  above unless you say otherwise. In a layout SolidSeas made, the other tools are then laid
  out around them again, in the smallest bin they fit; in one placed by hand, they stay
  where they are.
- **Move tools.** "Put the knife on the left" or "move the pliers to the front": the chat
  then gives every tool's place, as the last layout had them with the ones you asked about
  moved, and SolidSeas puts each tool exactly there. The bin is the smallest that holds
  them, or the grid you asked for.

A layout by hand is checked, not changed: every pocket must stay inside the bin's walls or
stacking lip, and at least the gap between pockets (3 mm unless you said) from every other
pocket, its finger scoop included. Pockets are compared by their own shapes, so a small tool
can sit in the crook of a larger one, where the automatic layout, which keeps whole
rectangles apart, never puts it. If a pocket does not fit, nothing is made, and the chat is
told which pocket and by how many millimetres, so it can move it and show you the layout
again. A label along the back edge needs a strip free of pockets there; with tools placed by
hand, the chat is told how far forward to move them if there is not one.

The layout the chat showed you is the bin it makes: making a bin with the same arguments
lays it out the same way.

## Labels

Ask the chat to put a name on the bin and it adds a text label, which Tracefinity cuts into
the STL. A bin with a label also comes as a 3MF, with the letters as a body of their own, so
a slicer can print them in another colour.

- **On the lip.** The usual place: one label along the back edge of the bin's top, the edge
  at the top of the drawing, just inside the stacking lip. It says the tool's name, or for a
  bin of several tools the bin's name, unless you give it other text. The layout keeps a
  strip free of pockets for it, which can make a bin a unit deeper than it would be without
  a label.
- **On the floor.** Each tool's name goes in the floor of its own pocket, along the tool, so
  you see what belongs there when the tool is out. A pocket too small for its name at the
  smallest size, or one given a depth of its own, gets none, and the chat says which.
- **Sunk or raised.** A label is debossed (sunk into the surface) unless you ask for it
  embossed (raised from it), 0.6 mm either way unless you say, from 0.4 to 1.5 mm. Raised
  letters on the top of a stacking bin can keep a bin stacked on it from sitting flat, so
  the lip label is sunk by default.
- **Its size.** Capital letters 6 mm tall unless you ask for another height, up to 20 mm.
  A label too long for the room is made smaller, down to 4 mm, the smallest that prints
  clearly. A lip label still too long at 4 mm makes a bin of no set grid wider; in a grid you
  gave, the chat says so and asks for shorter text or a wider grid.
- **Its letters.** Up to 40 letters, digits, spaces and plain punctuation. Accents are taken
  off (é becomes e) and other characters are left out, so the font Tracefinity draws with has
  every letter.

The chat's drawing of the bin shows where each label goes. To move one or change its text,
open the bin in Tracefinity.

## What stays on your PC

- **Your photos.** SolidSeas sends a photo only to your Tracefinity, under the name
  `photo.jpg` (or the photo's own extension), so even the file's name stays here; to a
  server, only inside the SSH tunnel, encrypted. The chat gets outlines' sizes, ids, the file
  names in the photos folder, and drawings SolidSeas makes from the outlines; never a photo.
- **Loopback only.** SolidSeas itself connects to a loopback address only, with no proxy and
  the address checked on every call; it refuses a Tracefinity address that is not on this
  PC. A server's Tracefinity is reached through ssh, your own client, with a key that can do
  nothing but that one forward. With no cloud keys set (the scripts set none), Tracefinity
  traces with the IS-Net model on its own machine and names nothing online; it reaches the
  internet only to download its models once.
- **The machine policy.** Under `LocalProviderOnly` these tools refuse, like every tool of
  the server.
- **Files.** SolidSeas writes only into the bins folder, never over a file: an existing name
  gets ` (2)` and so on. A bin's name from the chat keeps only letters, digits, spaces and
  `_-.,()+` in the file's name. Photos are read only from the photos folder itself, by the
  name of a plain file there, never through a link.

## Settings

Set them in the viewer: Tools > Extensions, Gridfinity's Settings... (each field empty for its
default). Gridfinity is an extension (`docs/EXTENSIONS.md`), on until you switch it off there;
while it is off, a chat has none of its tools. A setting can also come from the `env` of
SolidSeas' entry in the MCP client's settings (`docs/MCP.md`); a variable set there comes first:

| Variable | Default |
|---|---|
| `SOLIDSEAS_GRIDFINITY_PHOTOS` | `%USERPROFILE%\Pictures\Gridfinity` |
| `SOLIDSEAS_GRIDFINITY_BINS` | `%USERPROFILE%\Documents\Gridfinity bins` |
| `SOLIDSEAS_TRACEFINITY_SSH` | none: Tracefinity runs on this PC. A server as ssh takes it (`root@nas`): Tracefinity runs there, through the tunnel |
| `SOLIDSEAS_TRACEFINITY_SSH_KEY` | `%USERPROFILE%\.ssh\solidseas_tracefinity` when it exists, else ssh's own choice |
| `SOLIDSEAS_TRACEFINITY_URL` | `http://127.0.0.1:3077` (loopback addresses only; with a tunnel, its port is used at both ends) |

The folders and the key must be full paths. Pictures and Documents are wherever Windows keeps
them for you, a OneDrive folder included.

## What was checked

With Tracefinity 0.10.0 on Windows, a 3000 x 2250 photo of an A4 sheet seen askew (turned
4 degrees, with a slight keystone) holding a 176 x 36 mm wrench shape and a 22 mm disc:
traced as 175.9 x 35.9 mm and 21.8 x 21.6 mm. The bin made of them, with 10 and 14 mm
pockets, came out 5 x 2 x 3 units, its STL 209.5 x 83.5 x 25.4 mm (21 mm and the stacking
lip), and read back in Tracefinity's editor exactly as laid out.

The same on an Unraid server set up by `scripts\tracefinity-server.ps1`, through the
tunnel: the same sizes, the trace in 2.8 s with the tunnel's opening, the STL the same size
to the byte. There the tunnel key could not run a command, and a forward to another port of
the server was refused ("administratively prohibited").

`tests/test_gridfinity.py` covers the rest against a Tracefinity held in memory: the
loopback rule, the tunnel (through a stand-in for ssh: its options, opening again after a
drop, ssh's reason when it cannot sign in, a server name that could pass for an option, and
ssh ending with a server that is killed), ids and photo names, tracing, the library, the
layout (every pocket inside the bin and apart from the others, no smaller bin that fits, the
placement the way Tracefinity's editor rebuilds it), labels (a lip label inside the lip and
clear of the pockets, a floor label inside its pocket and clear of the scoop, sunk or raised
as asked, made smaller and then refused when too long), files never written over,
cancelling, and the tools as the MCP server serves them. Placing by hand is tested the same
way: a turn kept by the layout, each tool placed where it is asked in the smallest bin that
holds it, a pocket past the room or too near another refused with by how much, a tool in the
crook of another, finger scoops counted, a packed layout given back by hand making the same
bin, a preview that makes nothing and matches the bin made from the same arguments, and the
lip label's strip with tools placed by hand. The label's size is worked out from
the widest of the fonts Tracefinity may draw with; the letters themselves are drawn by
Tracefinity and were not checked against a running one.
