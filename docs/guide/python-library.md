# The Python library

The `solidseas` package is what ERP, invoicing and project-tracking systems
import to show previews and pull metadata from `.sldprt` and `.sldasm` files. It
needs no SOLIDWORKS installation, stays pure Python and runs on Linux and
Windows. [API.md](../API.md) is the full reference, shared with
[the command line and the REST service](command-line.md).

## Installing

Python 3.11 or newer, on Linux or Windows; SOLIDWORKS is not needed. SolidSeas
is not on PyPI yet, so install it from a checkout:

```bash
python -m pip install /path/to/SolidSeas
```

## Reading a document

```python
from solidseas import open_document, scan

with open_document("D:/Jobs/Example/frame.SLDASM") as doc:
    print(doc.doc_type, doc.active_configuration, doc.property_values())
    tree = doc.components()                  # the assembly's component tree
    bom = doc.bom(bom_type="indented")       # its bill of materials, as SOLIDWORKS numbers it
    image = doc.preview()                    # the stored thumbnail, or None

listing = scan("D:/Jobs/Example", include=("properties", "preview")).listing()
```

Documents are opened read-only: nothing in the library writes to, locks or
modifies a source document.

## Writing native parts (research)

`solidseas.nativewrite` is early research into writing `.sldprt` files that
open in SOLIDWORKS with editable features, from designs made elsewhere, such
as SolidCraft. It never changes an existing file: everything it writes is a
new file. SOLIDWORKS opens the test parts it writes as editable native
features, but it covers only rectangles extruded from the Front Plane, one
round hole and a few fillets so far, so do not use it for real work, and expect
its names to change. The `solidseas sldprt` command
([The command line](command-line.md#solidworks-parts-from-a-design)) says what it
writes. What it can do today, and
what is still being measured, is in
[NATIVE_SLDPRT_WRITER.md](../NATIVE_SLDPRT_WRITER.md).

## Stability

The library's public API is stable since 0.2.0. Its public names and JSON change
only under the stability policy in [API.md](../API.md) section 9, apart from what
that document marks provisional, such as reading other 3D formats (API.md 3.20).

For a document the JSON is the same whichever way you ask; folder listings and
reference resolution differ a little between the library, the command line and
the REST service (where paths start, a few defaults), as API.md section 1.2
lists.

## Further reading

- [ARCHITECTURE.md](../ARCHITECTURE.md): how the library, the command line and
  the viewer fit together.
- [FORMAT.md](../FORMAT.md): what is known of the SOLIDWORKS file format.
- [ROADMAP.md](../ROADMAP.md): the phases.
- [NATIVE_SLDPRT_WRITER.md](../NATIVE_SLDPRT_WRITER.md): the native part
  writer's design and status.
