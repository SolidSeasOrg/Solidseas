# 15. Generation specification: a native part from a design

This folder is section 15 of `docs/NATIVE_SLDPRT_WRITER.md`: the
specification the clean-room generator, `solidseas.nativewrite.generate`, is
written from. It is what the implementation role reads (`docs/CLEANROOM.md`
section 1), together with `docs/FORMAT.md`, `ir.py` and `container.py`, and
nothing else from the analysis side.

Every claim carries an evidence label from `docs/FORMAT.md`: VERIFIED (what
it rests on), HYPOTHESIS or UNKNOWN. Every listing in `listings/` has been
assembled with the slot values of SOLIDWORKS-made parts and gives their
members byte for byte; the files and parts each one was proved on are named
in its section.

## 15.0 How to read it

### 15.0.1 What a generated part holds

The generator writes a 2015+ container (`docs/FORMAT.md` section 2) whose
members are the ones below, in this order. The display caches and the
Parasolid partition are left out on purpose: SOLIDWORKS builds the body from
the features when it opens a part with no partition, and opens a part with
no display lists or previews (VERIFIED in SOLIDWORKS 2024 SP1, 2026-10-19:
parts without them opened with no warning, rebuilt to their features, took a
dimension edit and saved).

| # | Member | Section | Listing |
|---|---|---|---|
| 1 | `Contents/3DExperienceExchange2` | 15.3 | `3dexperience-exchange2.srl` |
| 2 | `Contents/3DExperienceExchange_ConfigHeader` | 15.3 | `3dexperience-configheader.srl` |
| 3 | `Contents/CMgr` | 15.2 | `cmgr.srl` |
| 4 | `Contents/CMgrHdr2` | 15.2 | `cmgrhdr2.srl` |
| 5 | `Contents/CnfgObjs` | 15.1 | `cnfgobjs.srl` |
| 6 | `Contents/Config-0` | 15.4 | `config-0.srl` |
| 7 | `Contents/Config-0-LWDATA` | 15.2 | `config-0-lwdata.srl` |
| 8 | `Contents/Config-0-ModelHeader` | 15.2 | `config-0-modelheader.srl` |
| 9 | `Contents/Config-0-ResolvedFeatures` | 15.5 | `config-0-resolvedfeatures.srl` |
| 10 | `Contents/CusProps` | 15.2 | `cusprops.srl` |
| 11 | `Contents/Definition` | 15.2 | `definition.srl` |
| 12 | `Contents/OleItems` | 15.1 | `oleitems.srl` |
| 13 | `Contents/eModelLic` | 15.1 | `emodellic.srl` |
| 14 | `Header2` | 15.2 | `header2.srl` |
| 15 | `ModelStamps` | 15.1 | `modelstamps.srl` |
| 16 | `OleItemInformation/OLE_Item_Data` | 15.1 | `ole-item-data.srl` |
| 17 | `SwDocContentMgr/SwDocContentMgrInfo` | 15.1 | `swdoccontentmgrinfo.srl` |
| 18 | `ThirdPty/Animator` | 15.2 | `animator.srl` |
| 19 | `ThirdPty/CMMotionLoadMapU` | 15.1 | `cmmotionloadmapu.srl` |
| 20 | `ThirdPty/CM_MOTION_LOAD_1` | 15.1 | `cm-motion-load-1.srl` |
| 21 | `ThirdPty/SWA_Schedules` | 15.1 | `swa-schedules.srl` |
| 22 | `ThirdPtyStore/VisualStates` | 15.2 | `visualstates.srl` |
| 23 | `[Content_Types].xml` | 15.1 | `content-types.srl` |
| 24 | `_DL_VERSION_17000/DLUpdateStamp` | 15.1 | `dlupdatestamp.srl` |
| 25 | `_MO_VERSION_17000/Biography` | 15.2 | `biography.srl` |
| 26 | `_MO_VERSION_17000/History` | 15.1 | `history.srl` |
| 27 | `_rels/.rels` | 15.1 | `rels.srl` |
| 28 | `docProps/Config-0-Properties.xml` | 15.1 | `config-0-properties.srl` |
| 29 | `docProps/ISolidWorksInformation.xml` | 15.1 | `isolidworksinformation.srl` |
| 30 | `docProps/OpenTime.xml` | 15.1 | `opentime.srl` |
| 31 | `docProps/app.xml` | 15.1 | `app.srl` |
| 32 | `docProps/core.xml` | 15.1 | `core.srl` |
| 33 | `docProps/custom.xml` | 15.1 | `custom.srl` |
| 34 | `swXmlContents/Features` | 15.1 | `features-xml.srl` |
| 35 | `swXmlContents/KeyWords` | 15.1 | `keywords.srl` |

The container itself (key, signatures, each member's directory fields) is
section 15.1.1. Sections, by subject:

| Section | File | Subject |
|---|---|---|
| 15.0 | this file | conventions, the listing language, the slots every section shares |
| 15.1 | `15.1-container-and-text.md` | the container, the XML and text members, the small fixed members |
| 15.2 | `15.2-header-streams.md` | the binary header streams: `Header2`, the model header, the configuration manager, custom properties, the biography, the definition, the light-weight data, visual states, the animator |
| 15.3 | `15.3-3dexperience.md` | the two 3DEXPERIENCE exchange members |
| 15.4 | `15.4-config-archive.md` | `Contents/Config-0`: the document's settings archive |
| 15.5 | `15.5-feature-stream.md` | `Contents/Config-0-ResolvedFeatures`: the feature tree |
| 15.6 | `15.6-design-to-slots.md` | how a `ParametricDocumentIR` part becomes the slot values, and what the generator refuses |

### 15.0.2 Slots

A listing is the same for every part; what differs from one part to the next
comes in through **slots**, named values the generator computes before it
assembles the listings. Every slot is one of four kinds, and each section's
slot table says which:

| Kind | Where its value comes from |
|---|---|
| design | the design: names, geometry, depths, the order of features (section 15.6 derives each from the IR) |
| derived | a formula over other slots, written in the listing itself as an expression (`=...`) or in the section's table |
| identity | made up for each file: times from the clock, new random ids, the key. The table gives the type, the range and the value the generator uses |
| free | a value SOLIDWORKS writes that changes between saves with no structural reason the fixtures show (a session counter). The table gives the value the generator writes and why that value is safe |

Slot names are dotted paths, and one dict holds them all: every listing is
assembled with the same slot dict, and a value has one name wherever it is used.
The slots below are shared by more than one section; a section adds its own under
its own prefix (`meta.` 15.1, `hdr.`, `lw.`, `cmgr.`, `anim.`, `bio.`, `def.` 15.2,
`exch.` 15.3, `config0.` 15.4). Section 15.6 gives the rule or the generator's value
for every slot, shared or not, and its tables name every slot a listing reads.

| Slot | Kind | Type | Meaning, and where its rule is |
|---|---|---|---|
| `doc.name` | free | text | the part's internal document name, `PartN` in SOLIDWORKS' parts (15.6.6) |
| `doc.unix` | identity | u32 | the save time, Unix seconds (UTC) (15.6.6) |
| `doc.iso` | derived | text | `doc.unix` as ISO 8601 UTC, `YYYY-MM-DDTHH:MM:SSZ` (15.6.5) |
| `doc.filetime` | derived | u64 | `doc.unix` as a Windows FILETIME (100 ns since 1601-01-01 UTC); no listing reads it, but it is the value the generator gives most time slots (15.6.5) |
| `doc.created` | identity | u32 | when the part was created, Unix seconds (15.1.2.1) |
| `doc.changed` | identity | u32 | when the model last changed, Unix seconds (15.1.2.1) |
| `doc.stamp`, `doc.stamp2` | free | u32 each | the document's two change stamps (`ModelStamps` elements 1 and 2; `doc.stamp` also in `DLUpdateStamp`, `SwDocContentMgrInfo`, `Features`, `Header2`, `CMgr`, `CMgrHdr2` and `Config-0-LWDATA`); the one rule for both is in 15.6.6 |
| `doc.author` | identity | text | the saving account; the generator writes `SolidSeas` (15.0.6, 15.6.6) |
| `tpl.unix`, `tpl.unix2` | identity | u32 each | the times SOLIDWORKS' part template carries on its own nodes (15.2.2.2, 15.6.6) |
| `features` | design | list | the feature timeline after the template's records; one schema for every section, 15.6.2 |
| `sketches` | derived | list | the sketch items of `features`, in timeline order (15.6.5) |
| `bodies` | derived | list | the solid bodies, one per extrusion, in timeline order; schema 15.6.4 |
| `model.solid` | derived | bool | the part has at least one extrusion (15.6.3) |
| `model.min`, `model.max`, `model.centre` | derived | 3 f64 each | the model's box in metres and its centre (15.6.3) |
| `model.sphere` | derived | 4 f64 | the bounding sphere's centre and radius (15.6.3) |
| `model.origin_refs` | derived | u32 | the number of sketches whose first corner is the origin (15.6.3) |
| `planes.front`, `planes.top`, `planes.right` | derived | fields `hu`, `hv`, `min`, `max`, `centre`, `radius` | each reference plane's display rectangle (15.6.3) |
| `fixed.id_base` | derived | u32 | the first feature id the template's records take once the part has a feature (15.5.4, 15.6.5) |
| `fixed.<key>.time` | identity | u64 | a template record's time, a FILETIME (15.5.3, 15.6.6) |

Inside `@for x in $list` the loop variable's fields are `$x.field` and its
position in the iteration is `$x_index` (from 0; with `reversed`, 0 is the last
item of the list).

### 15.0.3 The listing language

A listing (`listings/*.srl`) is UTF-8 text, one field per line. `#` starts a
comment, outside a quoted string. Values are written as literals (`7`,
`0x1F`, `-2`, `0.03`, `"text"` with JSON escapes), as a slot (`$doc.unix`) or
as an expression (`=17+2*len($features)`: integers and floats, `+ - * / // %`,
comparisons, `and`, `or`, `not`, `len min max abs int float round`, and
slots; no spaces inside an expression). All numbers are little-endian unless
the type says `be`.

| Line | Bytes |
|---|---|
| `u8 V...`, `u16`, `u32`, `u64`, `i8`, `i16`, `i32`, `i64` | each value as that integer |
| `u16be V...`, `u32be`, `u64be` | big-endian integers |
| `f32 V...`, `f64 V...`, `f64be V...` | IEEE floats; a literal is written with enough digits to round-trip |
| `f64bits V...` | a double given by its bit pattern as a u64 (for values a decimal literal cannot spell, such as a NaN) |
| `hex AA BB ...` | those bytes, an opaque constant (spaces ignored) |
| `rep N BB` | the byte `BB` (hex) N times |
| `cstr V` | MFC's Unicode `CString`: `FF FE FF`, the length in UTF-16 units as a u8 (when 254 or less), else `FF` and a u16 (when 65,534 or less), else `FF FF FF` and a u32; then UTF-16LE |
| `astr V` | MFC's narrow `CString`: the same length forms without `FF FE FF`, then Latin-1 bytes |
| `utf8 V`, `utf16 V`, `latin1 V` | the text alone, no length (`utf16` is UTF-16LE) |
| `bytes $slot` | a slot holding bytes the section computes by a rule it gives |
| `class NAME SCHEMA` or `class NAME SCHEMA as LABEL` | one object of MFC class `NAME` (15.0.4); `as` names the object for `objref` |
| `objref LABEL` | the archive index of a labelled object, as a u16 (a label may be `$slot`) |

Directives:

| Directive | Meaning |
|---|---|
| `@section ID` | the specification section the following lines belong to; cite it in the generator (`# spec ID`) |
| `@member NAME` | the member this listing is; no bytes |
| `@archive start N` | begin a new `CArchive` whose next index is N (15.0.4) |
| `@archive continue` | go on with the archive the previous listing left (the feature stream continues `Config-0`) |
| `@archive set NAME` | no bytes; the archive's next index at this point becomes the value `$_archive.NAME` for later lines (the feature stream's header, 15.5.1) |
| `@let NAME =EXPR` | a derived value later lines can use as `$NAME` |
| `@define NAME P1 P2 ...` ... `@end` | a named block; inside it `%P1` is replaced by the argument's text |
| `@use NAME P1=VALUE ...` | the block with its parameters replaced by the values' text (values are tokens such as `$x.id`, `=$a+1`, `3` or `"Top"`; a quoted value is one token and may hold spaces: `NAME="Front Plane"`, and keeps its quotes when substituted) |
| `@for X in $LIST` ... `@endfor` | the block once per item, in the list's order |
| `@for X in $LIST reversed` ... `@endfor` | the same, from the last item to the first |
| `@sized TYPE NAME` ... `@endsized` | the length in bytes of the block's output, as the integer `TYPE` (such as `u32`), then the block. The length counts the block alone, not the length field. After the block, `$NAME` is that length. Blocks may contain any other line; `Contents/Config-0` uses two in a row (15.4.1) |
| `@if V` ... `@else` ... `@endif` | the first block when V is true, else the second |
| `@include FILE` | another listing's lines, here |
| `@text ENC [eol=lf or crlf] [final=yes or no] [bom=yes]` ... `@endtext` | the lines between as text in `utf8`, `utf16` or `latin1`, joined by `eol`, ending with `eol` unless `final=no`, after `${slot}` or `${=expression}` is replaced by its value. A slot that goes into XML is escaped by the section that defines it |
| `@zlb level=N` ... `@endzlb` | the block's bytes in one ZLB wrapper (`docs/FORMAT.md` 4.1): one chunk of zlib at level N, then the terminator |

A line's bytes depend only on the line and the slots, so an implementation
may turn listings into code any way it likes. What it must keep is the
order, every value and every citation.

### 15.0.4 Counting objects the way MFC does

`Contents/Config-0` and `Contents/Config-0-ResolvedFeatures` are one MFC
`CArchive`. Each object of a class is written as:

- the class's **first** object in the archive: `FF FF`, the class's schema as
  a u16, the class name's length as a u16, the ASCII name. The class takes the
  archive's next index, and its object the index after that.
- every later object of a class already written: the u16 `0x8000 | index of
  the class`. The object takes the next index.

An `objref` writes a labelled object's index (below `0x7FFF`) as a u16. The
archive's next index starts at the value `@archive start` gives. VERIFIED
(13 feature streams in 12 parts: counting this way through `Config-0` gives
exactly the u32 at the head of the feature stream, and every class reference
in either stream names a class defined before it).

### 15.0.5 What the specification is proved on

`tests/test_sldprt_spec.py` (analysis side) assembles each listing with the
slot values of each part it names and compares the result with that part's
member. Design slots come from what the part is known to be (its kit
instructions); identity and free slots are read from the part when the test
runs and are never stored in this repository. A listing passes only when
every byte agrees.

The parts are SOLIDWORKS 2024 SP1 parts made through the published API from
the installed part template (`docs/FORMAT.md`, where the evidence comes
from): an empty part, boxes from a corner rectangle on the Front Plane
extruded blind, the same box at another depth, and two boxes. A listing is
claimed for exactly the parts it was proved on.

### 15.0.6 Text this specification puts in a file

A generated part names SolidSeas and the design, and nothing else: no
person, account, machine, path, e-mail address or licence (`docs/CLEANROOM.md`
section 5). Where SOLIDWORKS writes such a value, the section gives the
neutral value the generator writes instead and says whether the parts show
that value is accepted (VERIFIED) or not yet (HYPOTHESIS).

### 15.0.7 The generator's interface

`solidseas.nativewrite.generate` offers:

| Name | What it does |
|---|---|
| `write_part(doc, *, identity=None, allow_partial=False) -> bytes` | the whole `.sldprt` for a `ParametricDocumentIR` part. A design that needs anything section 15.6 does not support raises `NativeWriteUnsupported` listing each item, unless `allow_partial` is true |
| `plan(doc, *, identity=None, allow_partial=False) -> Plan` | what `write_part` would write: `slots` (the dict of every slot, section by section), `left_out` (each item of the design not written, in words for the person exporting), `names` (the design's feature names and the names they get in the part) |
| `assemble(slots) -> dict[str, bytes]` | every member of section 15.0.1, by name, from a complete slot dict; `write_part` is `plan`, then `assemble`, then the container (15.1.1) |
| `Identity` | the identity values of one file: `when` (a UTC `datetime`), `key_index` (15.1.1.1), the GUIDs `anim_guid`, `exch_front`, `exch_top`, `exch_right`, `exch_doc`, `exch_config`, and `file_stem`. Section 15.6.6 defines each and the default the generator makes when `identity` is `None` (the clock and a random source) |
| `SPEC_CONSTANTS` | every run longer than 31 bytes of output that is the same whatever the design's values and the identity: the listings' constants together with the values section 15.6.6 fixes (such as `SolidSeas`) and values derived only from how many features and bodies there are. Computed by comparing assemblies of the same shape (an empty part, one box, two boxes) made with different sizes and different identities, and keeping the runs that agree, as `bytes`, for the clean-room test (`docs/CLEANROOM.md` section 4) |
| `NativeWriteUnsupported` | a `ValueError` with `items`, the list of what cannot be written |

`assemble` takes the slot dict in the shape the sections define (one dict for
all 35 listings; `Contents/Config-0-ResolvedFeatures` continues the archive
`Contents/Config-0` leaves, 15.6.1), so a slot dict made by the analysis side
from a SOLIDWORKS-made part gives that part's members; that is how the generator
is held to the specification without its author seeing the part. The analysis
side holds itself to the same: one slot dict per part assembles all 35 of its
members, and the rules of 15.6 applied to the part written as an IR design, with
only its identity and free values read from the part, give the same 35 members
(VERIFIED, o01, o02, o03, o07, o12).
