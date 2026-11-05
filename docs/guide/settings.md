# Settings and the 3D view

This page covers the Settings window, how the viewer keeps each folder's index,
and the interactive 3D view: how assemblies are drawn, exploding them, picking
components, making them see-through, the mouse and keyboard controls, the view
cube and rotation.

## The Settings window

Settings (Ctrl+,) opens one window with every setting SolidSeas has, its pages
listed on the left: General, 3D View, 3D Print, Drawings (with each Drawing
Settings page under it), AI Assistant and Extensions. OK and Apply save them
all. AI Settings, Drawing Settings and Tools > Extensions open the same window
on their page.

The Settings menu also has quick toggles for:

- the 3D view, its boxes for missing meshes and its view cube;
- the mouse style, reversed wheel zoom and the 3D view's rotation;
- the 3D Print program, and whether 3D print files are saved next to the model;
- whether a 3MF or STL file goes to the slicer as it is (Open 3MF and STL Files
  As They Are, off by default);
- SOLIDWORKS lock files;
- remembering the last folder and window layout.

The Settings window also sets the 3D view's triangle limit, the thumbnail size
and whether the list starts as details or icons.

### Where referenced files are looked for

An assembly or a drawing names each file it uses by the path that file had when
it was saved. The viewer looks for it in the folder you opened and its
subfolders and, when the stored path is outside that folder but on a drive of
this computer, at that path too: a file found there is shown as found there,
and drawn in 3D, printed, exported and opened from there, read-only like every
read. A network path is never looked at.

**Settings > General > Look for referenced files only in the opened folder**
(off by default) keeps every one of those reads inside the folder you opened:
the details tabs, the 3D view, 3D Print, File > Export STEP, File > Convert and
Export for 3D Printing, and drawings of assemblies. A file that is only outside it is then
shown as not found, and the message for it says the setting is on. Turning the
setting on closes a document that was found outside the folder, and Back no
longer returns to one; the document shown is read again.

Settings are kept in `%APPDATA%\SolidSeas\Viewer.ini`, never next to your files;
a damaged or hand-edited value falls back to its default. With Remember Last
Folder off, the viewer also puts back Qt's record of the last folder its folder
dialogs showed. Windows' own folder dialog keeps a recent folder for each
program, which the viewer cannot clear.

The pages for [3D Print](3d-print.md#choosing-the-slicer-and-the-format),
[Drawings](drawings.md#drawing-settings) and the
[AI Assistant](assistant.md#setting-up-the-ai) are described with those
features.

## Folders and their indexes

The viewer keeps each folder's index, the list it read, with every document's
thumbnail, in its cache folder, never beside your files. Opening a folder again
shows that list at once instead of reading every file again.

- A bar above the list says how old it is ("This folder's index is 3 h 12 min
  old") with **Re-index**; Reload (F5) does the same.
- A re-index keeps the list on screen until the new one is read, then swaps it
  in.
- In Settings > General you choose whether indexes are kept, how old one may get
  before it is read again in the background when its folder opens (Never, 1 hour
  to 7 days, 1 day by default), and how many recent folders File > Recent
  Folders lists (10 by default, up to 20), with Clear Recent Folders there.

The same index answers [Where Used](where-used-and-bom.md#where-used).

## The 3D view

**Settings > Interactive 3D View** (off by default) adds a 3D view of parts and
assemblies to the Preview tab, drawn with OpenGL from the display meshes
SOLIDWORKS saved. It is off until you turn it on because it costs time:

- starting OpenGL holds the window for about 0.6 seconds: when you turn the
  setting on, and each time the viewer starts with it on, before its window
  appears;
- a very large part or assembly takes a few seconds to read.

Meshes are read in a separate process, so the window keeps responding meanwhile,
and selecting another document stops a read at once. While the 3D view is off
the viewer never reads a mesh or starts OpenGL. A part above the triangle limit
(1,000,000 by default) is not drawn, and the view says so.

Your choice of Image or 3D holds from one document to the next. Drawings show
their stored preview, with the 3D button off, and the next part or assembly is
in 3D again.

## Assemblies in 3D

An assembly is drawn from the meshes it stores of its components (SOLIDWORKS
keeps one for each component, in recent versions and in older ones alike). Where
it has none, the mesh comes from the component's own file, found as the
References tab finds it: in the folder you opened, or at its stored path on a
drive of this computer (never a network path, and not with Look for referenced
files only in the opened folder on: see
[Where referenced files are looked for](#where-referenced-files-are-looked-for)),
read-only like every read.
Failing that, it comes from the meshes a sub-assembly keeps in its own file.

A part saved with no display mesh anywhere is drawn from its own geometry: the
viewer turns the Parasolid bodies the part stores into triangles, which takes a
moment for a large part (about 30 seconds a part at most, reading its bodies
included, and no part is started after a minute for the whole assembly). The
viewer keeps those triangles while it runs, so showing the assembly again,
another configuration of it, another assembly with the same parts, or one of
those parts on its own does not make them again. A part saved again since is
read again, and selecting another document while an assembly is still being
read lets go of what was kept. A
sub-assembly whose components the assembly does not list is read from its own
file, and a file it shares with the assembly is the same file in the view: one
colour, one row of the legend.

### The legend

Each component file is read once and drawn for every instance of it, in its own
colour. The **Legend** button shows or hides the list of files and their colours
over the view's corner.

- The legend keeps to a third of the view's height and scrolls beyond that.
- An assembly of more than twelve files starts with it hidden until you choose.
- Clicking a file in it picks every instance of that file.
- While it is shown, fitting puts the model in the part of the view the legend
  leaves free, left of it or below it, so the legend never covers the model.

### Configurations

The Configuration list on the bar is the Components tab's: choose a
configuration in either and both show it. Another configuration keeps the view
as you left it: turned, panned and zoomed as it was, or, if it was fitted,
fitted to the new configuration from the same direction. Only when none of the
new configuration would be in view, or the view is zoomed out to more than 50
times its size, is it fitted, from the same direction.

### Boxes for missing meshes

An instance with no mesh drawn (its file is not found, it stores neither display
data nor bodies, its bodies could not be tessellated, or a limit of the 3D view
left it out) is drawn as the box SOLIDWORKS stored for it in the assembly, in
translucent grey with dark edges so it never passes for real geometry. On the
development corpus that is 245 of the 271 instances still without a mesh.

- A stored box no model could have (more than 10 km from the origin, or reaching
  more than ten times the assembly's own box past it) is taken as damaged and
  not drawn, and the line under the view says so.
- A box explodes, picks, opens its file and comes back with Back like any other
  component.
- The legend's last row stands for the boxes: click it to pick them all.
- **Settings > Boxes for Missing Meshes**, on by default and also in Settings >
  3D View, turns them off.

A line under the view counts the boxes by reason and names the instances that
could not be shown at all and why (a file not found, no saved mesh, the triangle
limit).

### Limits

The triangle limit counts every component file's mesh once over the whole
assembly. The view also draws at most twenty times that limit in all, counting
each instance's mesh again (20 million triangles at the default), so a file with
thousands of instances of a large part cannot stall the graphics card; a higher
limit draws more. Drawn this way, every assembly of the development corpus fits
under the default limit, and the largest draws in about 2 ms a frame.

## Exploding an assembly

The **Explode** bar under the view moves an assembly's components apart. Drag
the slider (or click its track, or use the arrow keys on it) and the components
move away from the assembly's centre, each twice as far out at 100 percent:

- each top-level component as one (a sub-assembly with its parts), or
- with **Every part**, each part on its own.

Components sitting at the centre slide apart along the assembly's longest side
instead, and the largest of them stays. A component still inside another when
fully exploded (a pin in a bore, a part in a housing) is moved out of it the
shortest way.

While you drag the slider or step it with the keys, the view follows it closely;
a page step, Collapse and Back ease there. **Collapse** puts everything back. An
assembly with a single top-level component starts at Every part, since grouped
by top-level component nothing would move, and the bar says so; with a single
part the slider is off. The view keeps the whole assembly in sight while it
moves, until you turn or zoom it yourself.

This exploded view is the viewer's own and for display only: the exploded views
saved in SOLIDWORKS are not read (where SOLIDWORKS keeps their steps is not
decoded yet, [FORMAT.md](../FORMAT.md) 12.6), and nothing in the file changes.
The amount holds while you switch configurations, and the next document starts
collapsed.

### Choosing which sub-assemblies explode

Right-click a part of a sub-assembly in the 3D view for a check item "Explode
sub-assembly NAME" for each sub-assembly it is in, from the part up, or
right-click a sub-assembly's row on the Components tab for "Explode this
sub-assembly".

- Off, the sub-assembly moves as one piece even when the bar is set to Every
  part.
- On, its components spread out even at Top-level components, so a connector
  panel can explode while the circuit board assembly next to it stays together.

The bar's level is the default for every sub-assembly you have not chosen for,
and a nested sub-assembly has its own switch. Switched on inside one that stays
together only by the bar's level, it is pulled out of that one: its components
spread out and the rest of the one around it moves as one piece. A sub-assembly
switched off moves as one piece with everything inside it, so the switches of
those inside it are greyed, their tooltips naming it, until it explodes.

The bar counts the groups that move as your choices make them and names the
choices that hold in the configuration shown. The choices are kept for that
document with its looks (see
[Transparency, Hide and Isolate](#transparency-hide-and-isolate)), through
configuration switches and Back, and from one run of the viewer to the next,
until Reset appearance.

## Picking components

Click a component in an assembly's 3D view to pick it: it turns a selection blue
while the others fade, a note in the view's corner names it, and its row becomes
the current one on the Components tab. Picking a row there picks it in the view
as well: an instance, all the parts of a sub-assembly, or, on the Files table,
every instance of that file.

- Double-click a component to open its file, exactly as double-clicking its row
  does; Back then returns to the assembly with the same pick, explode, camera
  and tab.
- Right-click a component for Open, Show in File Explorer, Go to file, Show in
  folder list, Show on Components tab, [3D Print](3d-print.md) for its part and
  for each sub-assembly it is in, and how it looks (below).
- Hover over one to see its name.
- Press Esc or click empty space to let go.

Picking finds whatever is drawn in front under the pointer, exploded or not, and
a click up to three pixels off a component still picks it. A box in front of a
component is picked where it covers it, while a component inside a box, or
reaching into it, is picked through the box.

When an assembly does not list a sub-assembly's components, the 3D view reads
them from the sub-assembly's own file, and the Components tab then lists them
under the sub-assembly's row, with a tooltip saying where they were read.
Picking one selects its row, a double-click opens its file, and Back puts the
pick back. When its file is not in the folder, the message that says so offers
to open the sub-assembly instead. A part past the rows the tab shows has no row:
picking it leaves no row selected, the note names the sub-assembly's row that
stands for it, and a double-click opens that sub-assembly.

## Transparency, Hide and Isolate

To look inside a housing, make it see-through. The menu of a component in the 3D
view, of its row on the Components tab, and of a file in the legend or the Files
table (every instance of that file; for a sub-assembly's file, every part of
every instance of it) has:

- **Transparency**: Opaque, 25, 50, 75 or 90 percent;
- **Hide**, which becomes Show once all of it is hidden;
- **Isolate**, which hides everything else;
- **Show all** and **Reset appearance**.

A part's menu in the view has the same for each sub-assembly it is in, under
that sub-assembly's name, and right-clicking empty space offers them after 3D
Print This Assembly. A row whose component the view does not draw (suppressed,
or not in this configuration) offers them greyed, with the reason.

The right-click picks the component, and choosing how it looks lets go of that
pick, so the parts inside a housing made see-through are not drawn faded. Reset
appearance puts every component back as the file draws it, shown and opaque, and
every sub-assembly exploding as the bar's level says. The latest choice wins: a
file made transparent, then one of its instances made opaque again, leaves that
one opaque until the file is chosen again.

A transparent component is drawn over what is behind it, the farthest first,
together with the grey boxes, so a part inside a see-through housing shows
between the housing's far and near walls from any side, and a box's edges behind
it show through it; a grey box made transparent fades its edges with its faces.
It can still be picked and right-clicked: as with a box, it ranks at the far
side of its bounding box, so a click picks anything within that box or in front
of it through it (a part inside the housing, or behind a wall of an L-shaped
bracket), and picks the component itself where only what lies beyond its box, or
nothing, is behind it.

A hidden component is not drawn or picked, and picking its row on the Components
tab fades nothing. The view fits what is shown and the exploded view spreads what
is shown; with everything hidden, the note in the corner says so.

The Components tab greys the rows of hidden instances with an eye struck through
and marks transparent ones with a half filled square, and the legend greys a file
all hidden. The choices hold through explodes, picks, configuration switches (for
the components still there) and Back, and they are kept for each document: show
another document and come back, or close the viewer and open it again, and the
document looks as you left it, until Reset appearance. The viewer keeps them in
`ViewerLooks.json` beside `Viewer.ini`, never beside your files, for the 200
documents whose looks you changed last, each under a digest of its file's path
rather than the path itself.

## Mouse and keyboard controls

| | Standard (default) | SOLIDWORKS style |
|---|---|---|
| Rotate | left-drag | middle-drag |
| Pan | right-drag or middle-drag | Ctrl+middle-drag (or press Ctrl during it) |
| Zoom in with the wheel | roll it away from you | roll it toward you |
| Zoom with a drag | | Shift+middle-drag (or press Shift during it) |
| Turn with a touchpad | two-finger swipe across | two-finger swipe across |
| Fit | double-click (empty space, in an assembly) or F | double-click (empty space, in an assembly) or F |
| Pick a component of an assembly | click | click |
| Open a component's file | double-click it | double-click it |
| A component's menu | right-click it without dragging | right-click it |
| Turn 15 degrees (90 with Shift) | arrow keys | arrow keys |
| Roll 15 degrees (90 with Shift) | Page Up, Page Down | Page Up, Page Down |
| Pan with the keys | Ctrl+arrow keys | Ctrl+arrow keys |
| Front, Back, Left, Right, Top, Bottom, Isometric | Ctrl+1 to Ctrl+7 | Ctrl+1 to Ctrl+7 |
| Isometric view | R | R |
| Look from a face, an edge or a corner | click it on the view cube | click it on the view cube |
| Home: the view the document opened with | Home, or the cube's house | Home, or the cube's house |

The wheel zooms toward the pointer in both styles, and **Reverse Wheel Zoom**
flips its direction in either, like the matching option in SOLIDWORKS. The keys
work once you have clicked the 3D view, so a touchpad without a middle button can
still turn the model.

A sideways two-finger swipe on a touchpad (or a tilted wheel) turns the model as
the Left and Right keys do, its front following your fingers, and Page Up and
Page Down roll it about the line of sight (a turntable only rolls looking
straight down or up). In the SOLIDWORKS style, pressing Ctrl or Shift after a
middle-drag has started switches it to panning or zooming from there, and
letting go turns again, as SOLIDWORKS does.

## The view cube

The view cube over the view's top-right corner turns with the model, as in
Fusion 360, with the axes SOLIDWORKS uses: Front looks along -Z, Top along -Y
with the front of the model at the bottom of the screen, and the corner of Front,
Top and Right is the SOLIDWORKS isometric view, so its faces and that corner give
exactly what Ctrl+1 to Ctrl+7 give.

- Click any of its 6 faces, 12 edges or 8 corners to look from there, upright
  and fitted. Looking straight at a face, its edges and corners are still there
  as its border, which is how the far side is reached.
- Looking at a face square on, four arrows beside the cube step to the next face.
- Looking straight at one however the view is rolled, two arrows at its top-right
  roll the view to the next quarter turn, which squares up a view rolled part of
  the way (a turntable only rolls looking straight down or up).
- A double-click on the cube counts as one click. Drag the cube to turn the
  model.
- Its house is Home: the view the document opened with, the isometric unless you
  right-click the cube and choose **Set Current View as Home**, which holds for
  that document while the viewer runs.

The cube's clicks, Home, R, Isometric and Ctrl+1 to Ctrl+7 ease the view there in
a fraction of a second. Drag, wheel or press a key meanwhile and it stops where
it is; pressed during a drag they act at once and the drag goes on from there.

The cube fades while the pointer is away from it, the legend sits below it, and
**Settings > View Cube** in the 3D View hides it. Without the legend, a fit that
would put the model under the cube puts it left of the cube or below it instead,
unless that would draw it more than a fifth smaller.

## Rotation

Rotation is free by default, as in SOLIDWORKS: a drag across turns the model
about the screen's vertical axis and a drag up or down about its horizontal axis,
with no limit, so every view can be reached, upside down included, and the arrow
keys turn it the same way.

**Settings > Rotation** in the 3D View (or Settings > 3D View in the Settings
window) switches to **Turntable**, which turns about the model's vertical axis
and tilts no further than straight above or below, never rolling. Switching to it
sets a view turned upside down upright again, looking from the same side. The
standard views are the same in both.

Either way a drag turns the model about the point of it under the pointer where
the drag starts, as Fusion 360 and SOLIDWORKS do, so a detail you zoomed in on
stays where it is while you turn it; a blue dot marks that point while you turn.

The model instead turns about the point of the screen a fit centres it on (the
middle of the view, or of the part of it the legend or the view cube leaves
free), at the depth of the model's centre, which fitting, panning and zooming
set:

- where nothing is under the pointer;
- with the arrow keys;
- with Settings > Rotation in the 3D View > Turn About the Point Under the
  Pointer off.

That point stays put while you turn, so turning back undoes a turn and a drag
turns the model the same however fast you make it.
