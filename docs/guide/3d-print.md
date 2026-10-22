# 3D Print and STEP export

3D Print exports the part or assembly you are looking at and opens it in your
slicer in one step. This page covers what to click, which slicer and format are
used, what goes into the file, where the file is saved and what it is called.
It ends with File > Export STEP, which writes the same exact geometry for other
CAD systems.

## Printing

Select a part or an assembly and press **3D Print** on the toolbar (or File > 3D
Print, Ctrl+P): the viewer exports it and opens it in your slicer. An assembly
goes in the configuration its Components tab shows, a part in the one the
instance you opened it from uses, or else its active one.

You can also right-click what you want printed:

- a part or an assembly in the document list (details or icons): 3D Print and
  its name, in its active configuration (or as the details show it, for the one
  selected);
- a row of the Components tab (an instance, or a file of the Files table), of
  the BOM tab or of the References tab: 3D Print for that row's file, in the
  configuration the row uses (a file used in several configurations goes in its
  active one);
- a drawing's views and models, on its Components tab: 3D Print for the model, a
  view's in the configuration the view shows;
- a component in the 3D view: 3D Print Part for the part under the pointer, in
  its instance's configuration, and 3D Print Sub-assembly for each sub-assembly
  it is in, the nearest first;
- empty space in an assembly's 3D view: 3D Print This Assembly, in the
  configuration shown (a part's view offers 3D Print This Part);
- a file in the 3D view's legend: 3D Print for that file.

Each works exactly as the button does, with the same program, format and
Cancel.

Some components need a word of explanation:

- A virtual component, which has no file of its own, is printed from inside the
  assembly that stores it, or from inside the sub-assembly that does.
- A part the 3D view read from a sub-assembly's own file (when the assembly does
  not list that sub-assembly's components, so no row stands for it) is printed
  from the file its mesh was read from. One drawn from what its sub-assembly
  keeps of it, its own file not found, offers only the sub-assembly.
- A component whose file was not found is not printed: its 3D Print entry is
  greyed with the reason, as Show in folder list is, and its tooltip says why,
  with the path the assembly stored for it.

The export is prepared in a process of its own, so the rest of the viewer keeps
working meanwhile. While it runs, the button and every right-click 3D Print
entry read **Cancel 3D Print**: choose it to stop the export, and nothing is
sent. Closing the viewer stops it too.

The program is started with the file as its one argument and nothing else. When
something goes wrong (no program chosen, the program is gone, the export failed)
a message says so.

## Choosing the slicer and the format

The first time, the viewer uses Bambu Studio if it is installed, and the status
line says so with the result, and where to change it. Otherwise it asks which
program to use, from the slicers it finds on this computer (Bambu Studio,
OrcaSlicer, PrusaSlicer and UltiMaker Cura, in their usual install folders or the
registry's App Paths) or any other program you pick. It remembers the choice in
`Viewer.ini`.

To change it, open **Settings > 3D Print Program**: it lists the programs found,
**Choose Another Program...** picks any program file (`.exe`), and **Send as
3MF**, **Send as STL** or **Send as STEP** chooses the format, from those the
program takes. Settings > 3D Print shows the program and offers the same formats
beside it.

- Bambu Studio, OrcaSlicer and PrusaSlicer take 3MF, STL and STEP.
- UltiMaker Cura takes 3MF and STL.
- Any other program you pick is offered all three.

Every program gets 3MF until you choose another format, and the choice is
remembered in `Viewer.ini` with the program. When you switch to a program that
does not take the format you chose (Cura, after STEP), it gets its first format,
3MF, and the status line says so.

Which formats a slicer opens is what its makers document, where they do, and
otherwise an assumption:

| Program | 3MF | STL | STEP |
|---|---|---|---|
| Bambu Studio | documented | documented (Bambu Lab's wiki, its Overview Tool page) | documented (Bambu Lab's wiki on importing STEP) |
| OrcaSlicer | documented | documented | documented (its wiki's Import and Export page) |
| PrusaSlicer | documented | documented | documented (Prusa's Supported file formats article), since 2.5 (PrusaSlicer 2.5.0's release notes) |
| UltiMaker Cura | documented | documented | not offered: only with UltiMaker's STEP and IGES plug-in |
| any other program | assumed | assumed | assumed |

With Cura's STEP plug-in installed, choose Cura's program file with Choose
Another Program... and it is offered STEP too. That a program opens the file
given as its one command-line argument is assumed for every program. Bambu
Studio and OrcaSlicer may ask, as they open a STEP, how finely to turn it into
triangles.

## What goes into a 3MF or STL

The export is made from the part's own solid bodies, tessellated more finely
than the 3D view draws them (a quarter of its tolerance, never coarser than
0.01 mm), closed and consistently oriented, in millimetres. A 3MF of an assembly
holds each component file once, placed for each of its instances, in the
document's own coordinates, and the slicer puts it on the plate.

A part with no solid body to export is sent as the display mesh SOLIDWORKS
saved, and so is an assembly's component whose part file is not in the folder
you opened (or holds no solid body, or passes a limit). The status line and the
object's name in the slicer mark it, because it may not be closed. Only an
instance with no mesh at all is left out (a part of surfaces only, say), and the
status line counts those.

## What goes into a STEP

Sent as STEP, a part goes as its exact faces and edges, as
[File > Export STEP](#exporting-step-for-other-cad-systems) writes them, and the
slicer makes the triangles itself: its solid bodies in the configuration shown,
without the ones SOLIDWORKS hides, as a STEP file SOLIDWORKS writes leaves them
out. An assembly goes as STEP too, each of its parts placed where the assembly
puts it.

A part the STEP export refuses is sent as 3MF instead:

- geometry STEP cannot hold without loss;
- an approximation it cannot bring within 0.001 mm;
- a part past its 300-second or 200,000-face limits, or whose STEP file would
  pass 2 GiB;
- nothing to write, as for a part of surfaces only.

So is an assembly with a component it cannot write (one not found in the folder
you opened, or placed in a configuration whose bodies its part file does not
store). The status line, and the result, say it went as 3MF and why. A STEP with
some of its bodies left out because they could not be written is never sent.

A part that stores no bodies of the configuration asked for goes in its active
configuration, as a 3MF of it does, and the status line says which.

## Other 3D formats

A 3D file of another format prints the same way.

- As 3MF or STL it goes from its geometry: a mesh file's own triangles, or a
  B-rep file's bodies tessellated.
- As STEP, a Parasolid file's part or assembly goes through the same STEP export
  as a SOLIDWORKS part or assembly, its exact faces and edges. Every other format
  goes as 3MF, the status line saying why: a mesh file holds triangles, not the
  exact geometry a STEP is made of, and SolidSeas writes STEP only from
  Parasolid bodies, so a STEP, ACIS or Alibre Design file goes as 3MF too.

A file goes by what it holds, whatever its name says: a STEP file saved with a
`.SLDPRT` name goes as 3MF for being a STEP, and a Parasolid file saved as
`.step` goes as STEP.

## Opening 3MF and STL files as they are

With **Settings > Open 3MF and STL Files As They Are** on (it is off unless you
turn it on), a 3MF or STL file is opened in the program as it is, with nothing
written, when it would be sent in its own format:

- a 3MF when 3MF is chosen, and when STEP is, since a 3MF then goes as 3MF (the
  status line says so);
- an STL when STL is.

An STL asked for as 3MF or STEP goes as a new 3MF, and a file whose name says
another format than it holds (an STL saved as `.3mf`) is always exported to a
new file, since the slicer would read it by its name. A STEP is always a new
file.

A file opened as it is goes to the program without the checks an export makes of
where it is: a cloud placeholder is downloaded when the program opens it, and a
file reached through a link or a junction is opened through it. The slicer then
has your own file open, and saving there replaces it.

## Where the 3D print file goes, and its name

The file is saved in the same folder as the model it was made from: the part's
or assembly's own file, or for a virtual component the assembly (or
sub-assembly) that stores it. A component found outside the folder you opened,
on a drive of this computer (a shared library folder, say), gets its print file
next to its own file there.

The file is named after the document and the date it was made, in your
computer's local time:

| Example | When |
|---|---|
| `bracket 2026-10-03.3mf` | the usual name (`.stl` or `.step` when the program gets STL or STEP) |
| `frame (Lite) 2026-10-03.3mf` | an assembly or part printed in a configuration other than its active one (a very long name is shortened, never the configuration) |
| `bracket 2026-10-03 (2).3mf` | a second print of it that day, then `(3)` and so on |
| `frame (assembly) 2026-10-03.3mf` | an assembly that has a part of the same name in its folder, so the two are never numbered as one |
| `frame (STL) 2026-10-03.3mf` | a 3D file of another format, `frame.stl`, whose folder holds a document of the same name in another format (`frame.SLDPRT` or `frame.step`, say, as exports of each other often sit together): its extension says which one the print came from, while a SOLIDWORKS document's print keeps the plain name |
| `Part12_frame 2026-10-03.3mf` | a virtual component, after the name the viewer shows for it (`Part12^frame`), with characters a file name should not hold made `_` |

A part that stores no solid bodies of the configuration asked for is exported in
its active configuration, as the 3D view draws it: the file is named after the
configuration it holds, and the status line says which it is.

**The higher the number, the newer the file.** A new print always takes one more
than the highest number of that day's prints of the same name in the folder,
even if you deleted some of the earlier ones, so the file without a number is
the first of the day and the one with the highest number the latest. Each name
counts on its own: another configuration, the `(assembly)` mark, the mark of a
source's extension and each format (`.3mf`, `.stl` and `.step`) have their own
numbers, so compare numbers only between files whose names match up to the
number. In the temporary folder below, documents of the same name from different
folders share one count. A file that is there is never replaced, renamed or
changed, and two prints made at once never take the same name.

While it is written the file has a temporary name,
`.solidseas-print-<16 letters and digits>.part`; an export that fails or is
cancelled leaves nothing behind. Should the viewer end while one is written (a
crash, End task, a power cut), that file may stay next to the model until your
next 3D Print, which removes it, and only it, by its own name.

The status line says where the file was saved, with its full path, and that it
was opened in your slicer.

### When the model's folder cannot take the file

The file then goes to a `SolidSeas Print` folder in the system's temporary
folder instead, named the same way, and the status line says why:

- the folder is read-only, or Windows refused a new file there;
- it, or a folder it is in, is a link or a junction;
- it is a cloud placeholder whose files are not on this computer;
- it is on a network share or drive outside the folder you opened (which
  SolidSeas never touches);
- on Linux and macOS, it is on a file system without hard links, such as a FAT
  or exFAT drive or some network shares: SolidSeas names a new file there
  through a hard link, which is how it makes sure the file never replaces one.

A folder Windows marks read-only only to keep its icon, as it does Documents and
Desktop, takes the file like any other.

To send every print to the temporary folder, turn off **Settings > Save 3D Print
Files Next to the Model** (also in Settings > 3D Print; it is on by default and
kept in `Viewer.ini`); the status line then says the setting is why. Prints
older than a week are removed from that temporary folder, and only from there:
SolidSeas never removes a file next to your models but its own unfinished one.

## From the command line

`solidseas export FILE --format 3mf|stl|step` writes the same file ([API.md](../API.md)
sections 3.17, 3.19 and 7.1). See [The command line](command-line.md).

## Exporting STEP for other CAD systems

**File > Export STEP** writes the part or assembly shown, in the configuration
shown, as a STEP AP214 file for other CAD systems: its exact faces and edges, not
triangles, without SOLIDWORKS. Ordinary fillets, which the part stores as
cylinders and tori, are written exactly. Where STEP has no exact form
(intersection curves, rolling blends) the export writes B-splines measured to lie
within 0.001 mm of the true geometry and says so. A body it cannot write within
that is never written broken: the viewer names the body and asks whether to
write the file without it.

Before you send the file, know what it holds:

- every solid body of the part SOLIDWORKS shows: the bodies it hides are left
  out, as its own STEP leaves them out, and the viewer lists them (from the
  command line, `--include-hidden` writes them too); only where the part does
  not say whether a body is hidden (some imported bodies) are all written, and
  the export says so;
- a face that goes all the way round a hole or a shaft as two faces, cut at its
  seams as SOLIDWORKS writes it, so that other programs need not cut it
  themselves;
- the bodies the part stores, which can differ from what SOLIDWORKS last
  displayed; the viewer says so when it notices;
- surface bodies only when the part shows no solid, hidden solids aside (from
  the command line, `--sheets` writes them beside solids); wire bodies never;
- no colours yet.

An assembly is written with each of its parts once and every instance placed
where the assembly puts it, its component files found in the folder you opened,
as the 3D view finds them, and each sub-assembly is an assembly of its own in the
file, as SOLIDWORKS writes it. A component that is not found, or that is placed
in a configuration whose bodies its part file does not store, is never written in
some other form: the viewer names it and asks whether to write the file without
it.

`solidseas export FILE --format step` does the same from the command line
([API.md](../API.md) 3.19). A Parasolid transmit file's part (`.x_t`, `.x_b`) is
written the same way, through the same mapping of its bodies. For a 3D file of
any other format Export STEP is off, its tooltip saying why, and the command line
answers `not_implemented`.
