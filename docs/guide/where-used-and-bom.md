# Where Used and bills of materials

The viewer indexes every folder you open, so it can say which assemblies and
drawings use a document, and it shows an assembly's bill of materials as
SOLIDWORKS numbers it. The same answers are on the command line as
`solidseas where-used` and `solidseas bom` (see
[The command line](command-line.md)).

## Where Used

The viewer indexes each folder you open, in the background and in a process of
its own, below normal priority; the status bar says how far it got. The index
lives in your cache folder (`%LOCALAPPDATA%\SolidSeas\catalogs`), never next to
your files, and opening the folder again reads only the files that changed.

The Where Used tab then shows, for the selected document:

- the assemblies that use it directly, and those that use it inside a
  sub-assembly (with the chain);
- how many in each configuration, and how many unsuppressed and in the BOM;
- the drawings that show it or an assembly that holds it;
- references that may name it;
- references to its name that found nothing.

A row goes to its document on a double-click or Enter, and Back returns. For a
document in the folder you opened, its right-click menu has Open and Show in
File Explorer too. View > Where Used (Ctrl+Shift+U) shows the tab.

Once the folder is indexed, the filter above the list also finds documents by
part number, description or property value.

Settings > Index Opened Folders turns indexing off, and Settings > Clear Index
deletes the opened folder's index. [Folders and their indexes](settings.md#folders-and-their-indexes)
covers how old an index may get and how it is refreshed. For files of other
formats, see [Every 3D format](formats.md#how-such-a-file-shows).

## Bills of materials

An assembly's BOM tab shows its bill of materials as SOLIDWORKS draws its BOM
tables: Top-level only, Parts only or Indented (3.1 and 3.2 under item 3). The
columns are:

- ITEM NO.;
- PART NUMBER (the document name);
- DESCRIPTION (the component's Description property);
- QTY.;
- then the total quantity in the whole assembly, the configuration each row
  uses and where its file was found.

The configuration is the Components tab's: choosing one on either tab shows it
on both. A row goes to its file on a double-click or Enter, as an instance's
row does. A row whose file was not found or could not be read says why in
Notes, as does a row whose configuration stores another name SOLIDWORKS may
show as its part number.

**Export BOM** (on the tab, or in the File menu) writes the BOM shown as a CSV
file (UTF-8, for Excel and ERP imports) or as JSON, into a folder you choose
outside the one you opened. It is off while another configuration's BOM is
being read.
