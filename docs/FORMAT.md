# SOLIDWORKS file format

This is the byte-level specification behind `solidseas.formats.solidworks`.
It covers both container generations and every stream SolidSeas decodes. It
was worked out by black-box analysis of files only: no SOLIDWORKS binary was
disassembled, decompiled, debugged or hooked.

## Evidence labels

Every claim carries one label.

- **VERIFIED (n)**: checked by code on n items (files, streams, members or
  bodies, as stated), with no counter-example unless a count of them is given.
- **HYPOTHESIS**: consistent with all data seen, but not proven.
- **UNKNOWN**: not worked out.

## Where the evidence comes from

- **Development corpus.** 3,527 real SOLIDWORKS files from the maintainers'
  own project folders: 3,150 parts, 325 assemblies and 26 drawings that could
  be read, plus 26 files held open by SOLIDWORKS during the survey, which were
  never opened. Of the readable 3,501, 2,911 use the 2015+ container and 590
  the legacy OLE container. Saves span 2013 to 2026, mostly SOLIDWORKS 2016
  to 2024. The corpus stays outside this repository; only numbers derived from
  it appear here. "Whole corpus" below means all 3,501 readable files.
- **Synthetic fixtures** in `tests/fixtures`: 14 parts, 3 assemblies and 2
  drawings made through the SOLIDWORKS 2024 SP1 API by the fixture kit (a
  generator that lives outside this repository), one controlled change at a
  time, plus SOLIDWORKS' own Parasolid, STEP, STL and 3MF exports of some of
  them, and `ground_truth.json`, what SOLIDWORKS itself reported about each
  document: the properties, materials, mass properties and bodies of each
  configuration, the component tree of each assembly configuration (instance
  names, referenced files and configurations, suppression, excluded from BOM,
  virtual, hidden, parent, and `Transform2.ArrayData`), and each drawing's
  sheets, views, referenced documents and BOM table cells. Their ground truth
  is in `tests/fixtures/README.md`. "The fixtures" below means these 19
  documents. The first eight (o01 to o08) were made again on 2026-10-01 with
  the same recipes, together with the other eleven, and every fixture claim
  below was measured again on the files now committed unless it says
  otherwise. Where a claim is about something the library reports
  (configurations and the active one, property types, values and links,
  units, bodies per stored partition, component flags and placements, nested
  virtual parts, a drawing's models, sheets and views, reference resolution,
  and the paths and user names a document reveals), `tests/test_ground_truth.py`
  and `tests/test_components_ground_truth.py` check it against
  `ground_truth.json` on every test run; byte-level claims rest on the
  measurements described here and on the reader tests.
- Every file was opened read-only with full sharing. After every corpus run
  all files still had their recorded size and modification time.
- The library was checked against the analysis scripts it was ported from on
  the whole corpus: identical stream lists and decoded bytes (3,501 files),
  identical metadata, references, versions and previews (3,501), identical
  display meshes (2,309 files with a display list), and byte-identical
  Parasolid bodies (3,143 parts; 7 parts with a partition stream block over
  20 MB were not compared).
- **Independent re-check.** A second reader was written from this document
  alone and run on a 361-file holdout the analysis had never sampled, and then
  on the whole corpus. Where it disagreed, the text below says so and gives
  both counts. Claims it could not check are marked as resting on the original
  analysis only.

Integers are little-endian unless stated. Offsets are in bytes.

## 1. Telling a SOLIDWORKS document apart

| Bytes | Container | Evidence |
|---|---|---|
| 0 to 7 = `D0 CF 11 E0 A1 B1 1A E1` | legacy OLE compound file (MS-CFB) | VERIFIED (590 files) |
| 4 to 7 = `00 00 00 04` | 2015+ container | VERIFIED (2,911 files) |
| anything else | not a SOLIDWORKS document | |

Detect the container by these bytes, never by the saving version: version
8000 (SOLIDWORKS 2015) occurs in both containers (section 7). VERIFIED
(3,501 files: detection agreed with the survey in every case).

## 2. The 2015+ container

### 2.1 Overview

The file is an 8-byte header followed by a PKZIP archive (PKWARE APPNOTE)
with method 8 (raw DEFLATE) members. It deviates from ordinary ZIP in four
ways. VERIFIED (2,911 files, 117,565 members).

1. Every stored offset is relative to file offset 8: absolute = 8 + stored.
2. The record signatures `PK\3\4`, `PK\1\2` and `PK\5\6` are replaced by
   4-byte values that are constant within a file and derived from the key in
   the header (section 2.7).
3. Every byte of a member name is nibble-swapped (section 2.6).
4. Decoy records and random filler surround the real records (section 2.8).

The byte run `14 00 06 00 08 00` that several open-source readers scan for is
not a marker: it is the version-needed (20), flags (6) and method (8) fields
of a local header, a central-directory record or a decoy.

### 2.2 File header (8 bytes)

| Offset | Size | Field | Evidence |
|---|---|---|---|
| 0 | 4 | key: the low bytes of four consecutive MSVC `rand()` outputs (section 2.7). Not unique: 921 distinct values in 2,911 files, up to 15 files share one | VERIFIED (2,911) |
| 4 | 4 | `00 00 00 04`, constant from version 7000 to 17000. Its meaning is UNKNOWN; reading it as a big-endian version number is a HYPOTHESIS | VERIFIED (2,911) |

### 2.3 Local file header, at 8 + local header offset

| Offset | Size | Field | Evidence |
|---|---|---|---|
| 0 | 4 | signature, one value per file | VERIFIED (2,911 files) |
| 4 | 2 | version needed = 20 | VERIFIED (117,565) |
| 6 | 2 | flags = `0x0006` (deflate "super fast"; no encryption, no data descriptor, UTF-8 bit clear) | VERIFIED (117,565) |
| 8 | 2 | method = 8 | VERIFIED (117,565) |
| 10 | 2 | "time": opaque, not the save time | UNKNOWN meaning (see 2.9) |
| 12 | 2 | "date": opaque, not the save date | UNKNOWN meaning |
| 14 | 4 | CRC-32 of the decoded data | VERIFIED (117,543 of 117,565; the other 22 members, in 2 files from a third-party writer, all store `0x74610FB1`) |
| 18 | 4 | compressed size; the deflate stream ends exactly there | VERIFIED (117,565) |
| 22 | 4 | uncompressed size, exact | VERIFIED (117,565) |
| 26 | 2 | name length | VERIFIED |
| 28 | 2 | extra length = 0 | VERIFIED (117,565) |
| 30 | n | name, nibble-swapped | VERIFIED (117,565) |
| 30 + n | | member data | VERIFIED |

Every field equals its copy in the central directory. VERIFIED (117,565).

### 2.4 Central-directory record, 46 + n bytes

The records start at 8 + `cd_offset` and are contiguous; there are exactly
as many as the end record says. VERIFIED (2,911 files).

| Offset | Size | Field | Evidence |
|---|---|---|---|
| 0 | 4 | signature, one value per file | VERIFIED (2,911) |
| 4 | 2 | version made by = 0 | VERIFIED (2,911) |
| 6 to 15 | 10 | version needed, flags, method, time, date: as in the local header | VERIFIED (117,565) |
| 16 | 4 | CRC-32 | VERIFIED |
| 20 | 4 | compressed size | VERIFIED |
| 24 | 4 | uncompressed size | VERIFIED |
| 28 | 2 | name length | VERIFIED |
| 30, 32, 34 | 2 each | extra length, comment length, disk number: all 0 | VERIFIED (2,911) |
| 36 | 2 | internal attributes: 0 or 1 (1 on 34,221 members) | values VERIFIED; meaning HYPOTHESIS (a writer's text flag: 1 on most XML members, but 0 on 335 XML members and 1 on some binary ones: 1,856 by the original classifier, 3,034 by the independent one, which counts the 1,178 empty members as binary) |
| 38 | 4 | external attributes = 0 | VERIFIED (2,911) |
| 42 | 4 | local header offset, relative to byte 8 | VERIFIED (117,565) |
| 46 | n | name, nibble-swapped | VERIFIED |

Directory order equals local-header order (VERIFIED, 2,911). Names are
byte-sorted in one run (2,009 files) or exactly two runs (902 files), with no
duplicates. VERIFIED. That the second run holds members written by a later
SOLIDWORKS version is a HYPOTHESIS: in all 902 files the time/date pairs of
the two runs are disjoint.

### 2.5 End of central directory (EOCD), 22 bytes

| Offset | Size | Field | Evidence |
|---|---|---|---|
| 0 | 4 | signature, one value per file | VERIFIED |
| 4, 6 | 2 each | disk numbers = 0 | VERIFIED (2,911) |
| 8, 10 | 2 each | entries on this disk = total entries, 11 to 96 | VERIFIED (2,911) |
| 12 | 4 | `cd_size`: covers the real records plus the decoy records that precede the real EOCD | VERIFIED (2,911) |
| 16 | 4 | `cd_offset`, relative to byte 8 | VERIFIED (2,911) |
| 20 | 2 | comment length = 0 | VERIFIED (2,911) |

**Finding the real EOCD.** It is the only position p in the file where bytes
p+4 to p+7 are zero, the two entry counts are equal and non-zero, and
`8 + cd_offset + cd_size == p`. VERIFIED (2,911 of 2,911 files, every byte of
every file scanned; none of the 34,663 decoy end records satisfies it). The
real EOCD starts 22 to 820 bytes before the end of the file, followed by 0 to
798 bytes of decoys. Search backwards from the end of the file for this
self-locating record. How SOLIDWORKS itself finds the record is UNKNOWN.

### 2.6 Member names

Each stored byte is `((b << 4) | (b >> 4)) & 0xFF`, a nibble swap: its own
inverse, not keyed, identical in every file. The decoded bytes are UTF-8
although the ZIP UTF-8 flag is clear. VERIFIED (117,565 names; 7 contain
non-ASCII text, all of them names of virtual or imported components, some in
Cyrillic). Example: stored
`05 27 56 67 96 56 77 05 E4 74` decodes to `PreviewPNG`.

Names use `/` and OPC-style paths: `Contents/...`, `docProps/*.xml`,
`swXmlContents/...`, `ThirdPty/...`, `ThirdPtyStore/...`, `_MO_VERSION_<n>/...`,
`_DL_VERSION_<n>/...`, `[Content_Types].xml`, `_rels/.rels`. 994 distinct names
in the corpus. In 51 files the member `ThirdPty/Animator__ZLB` keeps the legacy
`__ZLB` suffix and its data is still ZLB-wrapped (section 4.1). VERIFIED (51).

### 2.7 Record signatures and the key

Let R[i] be the low byte of output i of the MSVC C runtime `rand()`, counting
from zero (R[0] is the first output), started from its default seed 1 (`state = state * 214013 + 2531011 mod 2^32`,
`output = (state >> 16) & 0x7FFF`). Then for some k from 1 to 999:

- key = R[16k] to R[16k+3];
- local-header signature = R[16k+7], R[16k+6], R[16k+5], R[16k+4] (byte-reversed);
- central-directory signature = R[16k+11] down to R[16k+8];
- end-record signature = R[16k+15] down to R[16k+12].

VERIFIED: 920 of the 921 distinct keys occur in that sequence at an index that
is a multiple of 16 (only with zero-based indexing); the signatures follow the key in 2,908 of 2,911 files;
all 19 fixtures obey the rule. The exception is one third-party writer (3 files)
with the fixed key `82 5D 07 04` and fixed signatures; that SOLIDWORKS carries
an opened file's key forward on re-save is a HYPOTHESIS. How k is chosen is
UNKNOWN; it is not sequential within one SOLIDWORKS session (VERIFIED on the
fixtures). A reader does not need the signatures; SolidSeas only checks that
each file uses one signature per record type.

### 2.8 Decoys and filler

Every byte of every file is accounted for by the real records and three kinds
of decoy unit, with no byte left unexplained. VERIFIED (2,911 files).

| Decoy | Size per file | Content | Count |
|---|---|---|---|
| local unit | 85 to 100 bytes | 5 to 14 pad bytes, then a fake local header without signature, a name (copied from a real member in 32,365 of 43,967), filler | 43,967 |
| directory unit | 101 to 116 bytes | 5 to 14 pad bytes, then a 42-byte fake directory record without signature whose local offset equals the last real member's (17,337 of 17,337), then its name and filler | 17,337 |
| end unit | 42 to 57 bytes | 5 to 14 pad bytes, then an 18-byte fake end record without signature that never satisfies the self-location rule, then filler | 34,663 |

- 3 to 9 local units precede the first real member, so the first real local
  header sits at byte 8 to 908. Between two real members there are 0 or 1
  units; none follow the last member. Directory and end units fill the slack
  inside `cd_size` before the real EOCD, all directory units before all end
  units, and end units follow the real EOCD to the end of the file. VERIFIED
  (the independent tiler accounts for every byte of 2,875 of 2,875 decoy files
  with these rules).
- Decoy sizes are fake, so walking forward over declared sizes cannot work.
  Always read EOCD, then the directory, then each local header.
- Filler in the units before the real EOCD (lead, between-member, directory
  and in-slack end units) is consecutive `rand()` low bytes. VERIFIED (130,023
  of 130,023 runs of 6 bytes or more, independent check over all 2,875 decoy
  files; the original analysis sampled lead units only). Filler in the end
  units after the real EOCD is not always consecutive: 11,001 of 52,156 runs
  are not, in 2,814 of 2,875 files. Its generator is UNKNOWN.
- Each key has a single (local, directory, end) unit-size triple. VERIFIED (918
  of 918 keys that have decoys, independent count; the original analysis
  grouped differently and reported 896 of 921). How sizes and filler lengths
  are chosen is UNKNOWN. None of this matters for reading.
- 36 files have no decoys at all: all are version 7000 or 8000 (7000 only from
  the third-party writer), written by the first SOLIDWORKS 2015 builds (build date codes 2014271 and 2014346) or by the
  third-party writer. Every file at 9000 or above has decoys. VERIFIED.

### 2.9 Member data

- Raw DEFLATE (RFC 1951). Each member inflates to exactly its declared size and
  the final block ends exactly at its compressed size. VERIFIED (117,565).
- The encoder is byte-identical to zlib level 1, memLevel 8, default strategy,
  raw. VERIFIED (11,151 of 11,151 non-empty members in a sample of 300 files
  under 20 MB, drawn with `random.Random(20260930)`).
  On the fixtures, every member, empty ones included, compresses to its
  stored bytes this way (VERIFIED, 773 members), which is what lets
  `solidseas.nativewrite` write a member unchanged in stored form.
- Empty members are the two bytes `03 00`, size 0, CRC 0. VERIFIED (7,664).
- Already-compressed payloads are compressed again like everything else:
  all 1,773 PNG members in modern files are smaller stored than decoded, and no
  depth-1 nested document has a compressed size above its size. Whether a
  payload ends up in stored deflate blocks is zlib level 1 behaviour, not a
  rule of the format. VERIFIED (independent check).
- Payloads are not keyed: re-saving a document with a new key leaves unchanged
  members byte-identical in stored form. VERIFIED (35 of 35 unchanged members,
  fixtures o02 and o03).
- The opaque time/date fields cluster by saving version and build, and the
  high bit of "time" toggles. They do not decode to the save time on the
  fixtures (saved 2026-10-01): 0 of the 773 member pairs of the 19 fixtures
  decode to a valid DOS date and time in 1995 to 2026. Across the corpus, how
  many decode depends on the test: 3,281
  of 117,565 pairs give a valid date and time in 1995 to 2026, and looser tests
  give 28,778 to 33,665. Their rule, and whether SOLIDWORKS checks them, is
  UNKNOWN.
- The largest member in the corpus is 129,610,386 bytes (`Contents/DisplayLists`).
  SolidSeas caps any decoded stream at 1 GiB and refuses a member whose declared
  size exceeds the cap before inflating it.

### 2.10 Nested documents

Members named `VirtualComp/<name>` (virtual components) and `ImportedComp/<name>`
(imported components) of an assembly are complete documents in the same
container generation as their parent, nested up to 5 deep. VERIFIED (677 in
66 modern assemblies, 29,444 streams; 4 in legacy assemblies, 124 streams).
Large nested documents are often visible verbatim inside the parent's
compressed data (about 90% of sampled 64-byte slices), small ones mostly not
(0 of about 200 slices in documents of about 35 KB), which is why
marker-scanning readers sometimes find streams of the nested documents too.
How much is visible is a side effect of zlib level 1, not a rule. A nested
document may be an older version than its parent (24 of 428 depth-1 documents).

### 2.11 Reading algorithm (as implemented)

1. Check bytes 4 to 7.
2. Find the EOCD by its self-location rule: scan the last 2 KiB, 64 KiB,
   1 MiB and 16 MiB, then the rest of the file in 16 MiB chunks, nearest to the
   end first, examining at most 1,000 candidates (real files need 1, always in
   the first 2 KiB, since the EOCD ends at most 820 bytes before the end). Each
   candidate's first directory record is checked from a 46-byte read before the
   whole directory is read, and the directory bytes read across all candidates
   are capped at twice the file size, so a file planted with many fake
   candidates fails fast.
3. Parse `entries` directory records sequentially; require one signature,
   non-empty names, offsets inside the data area, no ZIP64 or multi-disk fields.
4. Read each local header, in one read with the name its directory copy
   gives; require the file's single local signature and every field equal to
   the directory copy.
5. Require member data below the directory and non-overlapping.
6. Inflate as a stream (1 MiB in, at most 4 MiB out per step), stop at
   min(declared size, cap), and check the size and CRC. If a file with 3 or more
   members gives every member the same CRC, CRCs are skipped with a warning
   (2 files) but sizes are still checked.

Robustness. On the reference implementation this library was ported from:
1,247 truncations, 3,000 random corruptions, 786 targeted record corruptions,
deflate bombs and 18-level nesting, each either decoded exactly or raised a
SolidSeas error within 5 s. On the library itself, an independent fuzz of 541
cases (truncations, byte flips, entity bombs, 200,000-deep XML, ZLB chunks
declaring 3 GiB, 18-level nesting) raised no other exception type and took at
most 0.3 s per case. Crafted files found by review (a Parasolid pointer cycle,
a flood of fake end records, runaway strings in `Header2`, bodies declaring
gigabytes, a schema that drops a field) are now handled within 0.3 s and
37 MB, and are covered by `tests/test_hardening.py`. VERIFIED (as stated).

## 3. The legacy OLE container

### 3.1 Compound file

A standard MS-CFB version 3 file: minor version `0x3E`, byte order `FFFE`,
512-byte sectors, 64-byte mini sectors, mini-stream cutoff 4096, zero header
CLSID. `olefile` reads every one unaided. VERIFIED (590 files).

Streams under 4096 bytes live in the mini stream. One open-source converter
reads them from the regular FAT instead and so gets every small stream wrong
(171 of 171 small partition streams in the corpus); readers must honour the
mini FAT.

SolidSeas lets `olefile` parse the header, the FAT and the directory, and reads
stream bytes itself from the sector chains: only the sectors a read needs, with
contiguous runs read at once. The decoded size of a `__ZLB` stream comes from
its chunk headers alone, and a `peek` at a stream's head reads only that head.
On the whole corpus this gives the same stream list, decoded bytes and heads as
reading every stream through `olefile` (19,759 streams in 590 files). VERIFIED.

### 3.2 Stream names

- The exact UTF-16 directory names joined with `/`. VERIFIED (19,759 streams).
- The property sets keep their leading `\x05`: `\x05SummaryInformation`,
  `\x05DocumentSummaryInformation`.
- `Config-<n>-...` is written in lower case (`config-<n>`) in 36 files.
- A name ending in `__ZLB` marks the ZLB wrapper (section 4.1). Name and wrapper
  correlate in 100% of streams.
- 159 distinct names. The independent count finds the same 159 with or without
  the storage paths of nested documents; an earlier figure of 248 including
  them did not reproduce, and its counting rule was not recorded.
- SolidSeas accepts `SummaryInformation` for `\x05SummaryInformation`, `<name>`
  for `<name>__ZLB`, and a unique case-insensitive match.

A legacy `<X>__ZLB` stream holds the same content as the 2015+ member `<X>`
(for example `Contents/DisplayLists`, `swXmlContents/KeyWords`,
`ThirdPtyStore/VisualStates`). VERIFIED on content heads.

### 3.3 Document kind from the root CLSID

The root entry CLSID is `{83A33D3x-27C5-11CE-BFD4-00400513BB57}` with x = 0
for a part (503 files), 6 for an assembly (50) and 4 for a drawing (4); it is
null in 33 files. The same GUID is in `Contents/Definition` in both generations
(section 6). VERIFIED.

## 4. Framings shared by both generations

### 4.1 The ZLB wrapper

| Offset | Size | Field |
|---|---|---|
| 0 | 16 | magic `23 1D D5 71 DA 81 48 A2 A8 58 98 B2 1B 89 EF 99` |
| 16 | 8 + c, repeated | chunk: u32 decoded size, u32 compressed size c, then c bytes of zlib (RFC 1950, header `78 01`) |
| end | 8 | terminator: two zero u32 |

Every chunk inflates to exactly its declared size with a valid Adler-32.
VERIFIED (independent count: 4,201 `__ZLB` streams in legacy files plus the 51
modern `ThirdPty/Animator__ZLB` members, every chunk with a `78 01` header and
no trailing bytes; an earlier count of 4,229 used a rule that was not
recorded). It is the legacy
container's compression, and inside both generations the wrapper of embedded
Parasolid data.

### 4.2 The ZLB chain

A sequence of `u32 L` followed by L bytes holding one ZLB block, up to the end
of the stream; L may be 0. Used by `Contents/Config-<n>-Partition` and
`Contents/Config-<n>-GhostPartition` in both generations. VERIFIED (2,619 +
751 modern streams, 816 + 3 legacy). 203 blocks have more than one zlib chunk.

### 4.3 MFC serialisation

Many binary streams are MFC `CArchive` output: a new class appears as
`FF FF, u16 schema, u16 name length, ASCII class name` and later references to
it as a 2-byte tag with the high bit set; Unicode strings are `CString`s:
`FF FE FF`, a u8 length (`FF` means a u16 length follows, `FFFF` a u32), then
UTF-16LE characters. VERIFIED on the streams decoded below.

### 4.4 Other framings

`ThirdPty/MOLDFLOWXpress` (23 legacy streams): u32 2, u32 (length minus 8),
u32 decoded size, then zlib. VERIFIED. One more such stream is 0 bytes long and
outside the framing. Not decoded further.

## 5. Stream catalogue

| Stream | Kinds | Presence | Content |
|---|---|---|---|
| `Contents/Definition` | all | 3,501 | document-type GUID (section 6) |
| `Header2` | all | 3,500 | users and referenced paths (sections 11, 12) |
| `_MO_VERSION_<n>/History` | all | 3,501 | version history (section 7) |
| `_MO_VERSION_<n>/Biography` | all | 3,501 | per-save session records with paths (section 13) |
| `swXmlContents/KeyWords` | all | 3,408 | one prefix byte (`0x86`; `0x85` in one version-14000 part) then UTF-8 XML: configurations, comments, material; the root's `id` is a part's or assembly's creation time, and in a drawing its template's timestamp (section 11.7) |
| `ModelStamps` | all | 3,409 | a u32 at offset 0: a part's or assembly's creation time, and in a drawing its drawing template's timestamp (section 11.7) |
| `swXmlContents/Features` | parts | 3,017 | UTF-8 XML feature tree with configurations |
| `swXmlContents/COMPINSTANCETREE` | assemblies | 324 of 325 | UTF-8 XML component tree |
| `swXmlContents/MATERIALTREE` | parts | 212 | UTF-16 XML material definitions |
| `docProps/custom.xml` | 2015+ | 2,911 | custom properties |
| `docProps/Config-<n>-Properties.xml` | 2015+ parts, assemblies | 2,739 | configuration properties |
| `docProps/ISolidWorksInformation.xml` | 2015+ | 2,851 | units, active configuration, SOLIDWORKS summary fields |
| `docProps/core.xml`, `app.xml` | 2015+ | 2,851 | OPC core properties |
| `\x05SummaryInformation`, `\x05DocumentSummaryInformation`, `ISolidWorksInformation`, `Config-<n>-Properties` | legacy | 562, 588, 557, 578 | MS-OLEPS property sets |
| `Contents/CusProps` | 2015+ from 11000 | 2,611 | binary custom-property store |
| `Contents/Config-<n>-Partition` | parts | 3,137 of 3,150 | Parasolid partition and deltas (section 10) |
| `Contents/Config-<n>-ResolvedFeatures` | parts | 15 of 15 fixture streams (not counted in the corpus) | the feature tree of configuration n as MFC `CArchive` objects (section 5.1) |
| `Config-<n>-FeatureBodies/LocalBodies` | parts | 1,801 | Parasolid bodies of imported features |
| `PreviewPNG`, `Preview` | all | 2,294 | preview images (section 8) |
| `Contents/DisplayLists` | all | 2,309 | display tessellation (section 9) |
| `Contents/Config-<n>-MatesList` | assemblies | 320 of 325 | mates |
| `FaceTessellations/*` | 2024-era assemblies | 113 | component tessellation |
| `VirtualComp/*`, `ImportedComp/*` | assemblies | 70 (66 2015+, 4 legacy) | nested documents |
| `Images/Sheet_<n>`, `SheetPreviews/SheetNames`, `DWG/DWG_HEADER`, `Contents/VBLists` | drawings | 26 of 26 (`DWG/DWG_HEADER` 22 of 26) | sheets |

Counts are files in the whole corpus (VERIFIED). Streams that are part- or
assembly-only never occur in the other kinds: `Config-<n>-Partition` occurs in
0 assemblies and 0 drawings; `COMPINSTANCETREE` and `Config-<n>-MatesList`
only in assemblies; the drawing streams only in drawings. VERIFIED.

### 5.1 The feature stream

`Contents/Config-<n>-ResolvedFeatures` is the feature tree of configuration
n, every folder, plane, sketch and feature, as MFC `CArchive` objects after a
u32 and a u16, the u16 being the number of top-level features. Each feature
object starts with a class record or reference and a named node (a class
reference, `04 80` in 12 fixture parts and `05 80` in o09 and o10, then the
name as a `CString`). A driving dimension's value is a double in metres 22
bytes after its `moLengthParameter_c` name (`D1`), and the feature named
before it is its owner, so the parameters read this way are SOLIDWORKS'
`D1@Boss-Extrude1`, `D1@Fillet1` and so on and equal the KeyWords text. A
sketch point is two doubles in metres after `F0 3F`, eight zero bytes and
`1E 00`. VERIFIED (14 fixture parts, 15 streams; 9 parameters in 6 parts;
the points of 3 parts). The stream continues the archive of `Config-<n>`:
counted the MFC way from 2 (3 with an imported body) through `Config-<n>`,
the load map reaches the feature stream's header u32, and the stream's class
references all name classes defined before them. VERIFIED (13 streams in 12
parts; the two parts with an imported body come out 8 short, UNKNOWN why).
Relations, end conditions and every other field are not decoded; `docs/NATIVE_SLDPRT_WRITER.md`
section 4 has the measurements and the hypotheses.

## 6. Document type

`Contents/Definition` holds `{83A33D3x-27C5-11CE-BFD4-00400513BB57}` in
little-endian GUID byte order at byte 20 (byte 16 in versions 3100 and 4100),
with x = 0 part, 6 assembly, 4 drawing. It matches the file extension in every
document. VERIFIED (3,501 files of both generations).

## 7. Saving version

### 7.1 `_MO_VERSION_<n>`

Every document has exactly one stream-name prefix `_MO_VERSION_<n>/`; n is
the internal version of the last save. VERIFIED (3,501). The fixtures, saved
by SOLIDWORKS 2024 SP1 (revision 32.1.0), have 17000. VERIFIED (19).

Corpus distribution: 3100: 1, 4100: 6, 4400: 39, 4700: 30, 5000: 73,
6000: 354, 7000: 63, 8000: 164, 9000: 98, 10000: 4, 11000: 13, 12000: 22,
13000: 1,128, 14000: 568, 15000: 4, 16000: 10, 17000: 924. VERIFIED.

### 7.2 `_MO_VERSION_<n>/History`

An MFC `moVersionHistory_c`: u32 count, then per entry three u16 (meaning
UNKNOWN), a u32 Unix time (when the document first reached that version), an
empty CString, a u32 version, and a `moDateCodeHistory_c` object (class
definition the first time, a 2-byte back-reference after) holding u32 m and m
u32 words. The low 24 bits of each word are a build date code; the high byte is
a flag of UNKNOWN meaning. A 22-byte trailer follows. Parses in every file.
VERIFIED (3,501).

- The last entry's version equals n in 3,499 files; the 2 exceptions are the
  third-party writer's files. VERIFIED.
- Histories are not monotonic: saving to an older format with "Save as
  previous version" appends the older version after the newer one (33 files).
  Such documents carry the older n but the newer build code and Parasolid
  schema. VERIFIED.
- A document created from a template inherits the template's history: the
  histories of the fixture assemblies (o08, o15, o16) start at version 10000
  (2016), as that of the shipped MBD assembly template they were made from
  does, and those of the fixture drawings (o18, o19) at 3919, as that of the
  shipped `ansi.drwdot` does (44 entries). The fixture parts, made from a part
  template whose history holds only 17000, have that single entry. VERIFIED (19
  fixtures and their three templates).

### 7.3 Build date codes

The codes read as `YYYYDDD`, year and day of year of the build. The last code
of the last entry is the build that last saved the file: 2024016 for
SOLIDWORKS 2024 SP1. VERIFIED (19 fixtures). Every code in the corpus passes the
YYYY/DDD range check and no code is later than its file's modification year.
VERIFIED (3,501). Reading them as dates, and mapping codes other than 2024016 to
service packs, is a HYPOTHESIS.

### 7.4 Version to release

| n | Release | Evidence |
|---|---|---|
| 17000 | SOLIDWORKS 2024 | VERIFIED (19 fixtures) |
| 9000 to 16000, multiples of 1000 | SOLIDWORKS (2007 + n / 1000) | HYPOTHESIS |
| 8000, 7000, 6000, 5000 | 2015, 2014, 2013, 2012 | HYPOTHESIS |
| 4700, 4400, 4100, 3800, 3400, 3100, 2800, 2500, 2200 | 2011, 2010, 2009, 2008, 2007, 2006, 2005, 2004, 2003 | HYPOTHESIS |
| 1950, 1750, 1500 | 2001Plus, 2001, 2000 | HYPOTHESIS |

Support for the hypothesis: for every release version, the earliest build
code found in any History stream falls in August to October of the year
before the label, and codes continue for about 13 months. Other values (for
example 16800, 10191, 4058) occur only inside histories and are pre-release
builds (HYPOTHESIS). 18000 (SOLIDWORKS 2025) is not in the corpus: UNKNOWN.
A release gets a VERIFIED row here only after the check in
`tests/fixtures/README.md` ("Checking a new SOLIDWORKS release") has run on it.

### 7.5 Secondary stamps

The first u32 of `ThirdPtyStore/VisualStates` equals n (VERIFIED, 3,468 of
3,468), as do `swVersion` on the root of `swXmlContents/Features` (3,017 of
3,017) and `COMPINSTANCETREE` (324 of 324). In drawings the first u32 of
`ThirdPtyStore/VisualStates_DisplayPane` does (26 of 26). The first u32 of
`ThirdPty/Animator` lags (1,836 of 2,099 equal).

### 7.6 Fields that do not carry the version

- Header bytes 4 to 7 (constant, VERIFIED 2,911).
- `docProps/app.xml` `<AppVersion>`: always `23.0000` (VERIFIED 2,851). All
  2,851 are valid UTF-8 (independent check); the reader still falls back to
  cp1252 for an XML stream that is not.
- Legacy `SummaryInformation` has no application name or revision (VERIFIED 562).
- `_DL_VERSION_<n>` often differs from `_MO_VERSION_<n>` (older in 1,181 files);
  that it marks the version that last regenerated the display data is a
  HYPOTHESIS.

### 7.7 Layout changes between versions

- Container: legacy up to 7000, 2015+ from 9000; 8000 in both (26 legacy files
  whose traits suggest a third-party writer, HYPOTHESIS), and 7000 also in the
  2015+ container in 2 files from the third-party writer. VERIFIED counts.
- The root object of `Contents/Config-0` (`moPart_c`, `moAssembly_c`) is
  followed by one u32 and then the nested `moHeader_c` class in versions 4100
  to 10000. From version 11000 (SOLIDWORKS 2018) it is followed by three u32
  (the second always 0, the third a version number that is the save version in
  only 574 of 2,576 files) and then `moNodeName_c`, not `moHeader_c`. The 3100
  file has no u32 at all. VERIFIED (old layout: 810 files at 4100 to 10000 in
  the independent count, which the original analysis put at 724; new layout:
  2,576 of 2,576 files at 11000 to 17000). The boundary rests on only 2 files
  at 10000 and 12 at 11000. A reader written against 2024 files misreads this
  object in every file from 2017 or earlier.
- Metadata moved from OLE property sets to OPC XML with the 2015+ container;
  `Contents/CusProps` and `docProps/OpenTime.xml` appear at 11000, and
  `docProps/Config-<n>-Cutlist-Properties.xml` at 12000. VERIFIED by presence.
- `Contents/Config-<n>-ModelHeader` appears at 11000, `Contents/3DExperienceExchange2`
  at 13000; `_MO_VERSION_<n>/AssyVisualData` and `Contents/View Orientation Data`
  are gone at 16000 and 17000. VERIFIED by presence; boundaries rest on small
  groups (10000: 4 files, 11000: 8, 15000: 4, 16000: 9).
- The Parasolid schema follows the release (section 10.3).

## 8. Preview images

| Stream | Content | Evidence |
|---|---|---|
| `PreviewPNG` | PNG, 640 x 480, 8-bit RGBA, fully opaque | VERIFIED (2,294 of 2,294) |
| `Preview` | u32 length (= stream size minus 4), then a packed DIB: BITMAPINFOHEADER, 8 bpp, BI_RLE8, bottom-up, sized like the SOLIDWORKS graphics area at save time (87 distinct sizes, most often 2560 x 994) | VERIFIED (2,294 of 2,294, decoded with Pillow) |
| `Config-<n>-PreviewPNG`, `Config-<n>-Preview` | per-configuration previews | VERIFIED (9 streams, 8 files) |
| `Images/Sheet_<n>` | drawing sheet, PNG 640 x 480 | VERIFIED (26 drawings) |

- `PreviewPNG` and `Preview` occur together or not at all: 2,294 documents have
  both, 1,207 neither (34.5%). By kind: parts 1,951 of 3,150, assemblies 317 of
  325, drawings 26 of 26. VERIFIED. A missing preview almost always comes with a
  missing `Contents/DisplayLists` (1,178 of 1,207); that such parts were saved
  without ever being displayed (for example through an assembly) is a
  HYPOTHESIS.
- Legacy `\x05SummaryInformation` holds no thumbnail. VERIFIED (no image
  signature in any of them).
- `Contents/OleItems` holds EMF data of embedded OLE objects, not a preview.
- SolidSeas returns the PNG by default, and the DIB as a complete `.bmp` file
  (a BITMAPFILEHEADER is prefixed) on request.

## 9. Display tessellation

`Contents/DisplayLists` (legacy `__ZLB`) holds one table per displayed face,
made of six descriptors. Each descriptor is u32 item size, u32 kind, u32
flags = 2, u32 count, then item size x count bytes:

| # | (item size, kind) | Content |
|---|---|---|
| 1 | (4, 8) | strip lengths L, each at least 3 |
| 2 | (12, 100) | C = sum(L) float32 xyz positions, metres, model coordinates |
| 3 | (12, 100) | normals: 0 or C float32 xyz |
| 4 | (4, 8) | E = sum(2L - 2) per-strip-edge values, or 0 (meaning HYPOTHESIS: edge tags) |
| 5 | (4, 8) | one value per strip, each 2L - 2 |
| 6 | (1, 8) | E bytes, or 0 when descriptor 4 is empty (meaning UNKNOWN) |

- Strip vertices are consecutive and expand with OpenGL triangle-strip winding.
  On fixture o02 the oriented triangle set equals SOLIDWORKS' own STL export to
  0.1 um, with mesh volume 6.0e-6 m^3 and area 0.0022 m^2. VERIFIED (1 fixture, 12 triangles).
- Corpus: 1,944 files yield at least one table (1,765 of 3,150 parts, 56.0%;
  179 assemblies); 1,843,083 faces. Every position is finite. VERIFIED (both
  counts). The finer counts depend on the counting rule: the independent count
  finds normals in every table (33,297,968, all unit length), 22,659,210
  triangles of which 930 are degenerate, and winding that agrees with the
  stored normals for 99.74% of non-degenerate triangles; the original analysis
  reported 30,339,474 normals, 22,658,365 triangles and 99.77%.
- Meshes are per face and mostly not watertight (456 of 1,932 closed). It is
  the tessellation of the configuration and display state at save time, not an
  exact B-rep.
- 203 parts have a `DisplayLists` stream with no table at all; 1,182 parts have
  no such stream.
- Tables are not back to back. There is about one optional block per table
  (1,843,522): u32 1, a descriptor (8, 100) of n 2-float pairs, and in
  1,759,098 of them a second u32 1 and two (12, 100) descriptors of n vectors.
  1,826,219 of the blocks start 128 bytes after the end of the previous table,
  which suggests a 128-byte per-face record between tables whose layout is
  UNKNOWN. n = 0 in 1,740,863 blocks; where n > 0 it equals the preceding
  table's vertex count in 102,635 of 102,659. VERIFIED (independent count; the
  original statement that the block follows the table directly, with
  18,520 of 18,520, did not reproduce). That it is texture mapping data is a
  HYPOTHESIS. Locate tables by their descriptor signature, as SolidSeas does,
  not by walking from one table to the next.
- The stream starts with u32 1, then u32 1 (u32 0 in 26 of 2,309 streams), and
  six float64 that look like a bounding box centre and maximum; they match the
  mesh only in 831 of 1,944 files, so SolidSeas does not use them.
- The same table grammar appears in `FaceTessellations/<nnn-nnn-nnn>` of
  2024-era assemblies (component coordinates), `Contents/VBLists` (drawings) and
  `Contents/Config-<n>-ShrinkWrap`. VERIFIED by descriptor counts.
- Per-face colours are not decoded. UNKNOWN.

## 10. Parasolid geometry

### 10.1 Where it is

- `Contents/Config-<n>-Partition` (same name in both generations, no `__ZLB`
  suffix) is a ZLB chain (section 4.2) of two Parasolid transmits: a partition
  (`TRANSMIT FILE (partition)`, root node WORLD) and a deltas transmit
  (`TRANSMIT FILE (deltas)`). VERIFIED (3,745 streams with both, 5 with only the
  partition). Assemblies and drawings have none at top level.
- The partition alone is a complete, self-contained Parasolid partition of the
  configuration's saved state. The deltas are not needed. VERIFIED on the
  fixtures (section 10.4); this contradicts open-source notes that model the
  deltas as filling in partition topology.
- 1,608 of 3,160 top-level part partitions hold no bodies. Most of those parts
  (1,565 of 1,590 files) keep their bodies as part transmits in
  `Config-<n>-FeatureBodies/LocalBodies` (section 10.6), under feature names
  such as `Imported1`, which points to imported STEP, IGES or STL geometry
  (HYPOTHESIS).
- Only configurations that have a stored partition can be extracted: fixture
  o06 has two configurations but only `Config-0-Partition`. VERIFIED. Fixture
  o13, whose two configurations differ in geometry and were both rebuilt before
  saving, stored only `Config-0-Partition` when saved as a copy and both
  partitions when saved again without Copy (`generation.log`); the committed
  file has both. VERIFIED (1 fixture). Which save options store which
  partitions in general is UNKNOWN.
- The `<n>` of `Config-<n>-Partition` equals the `id` of a KeyWords
  `<Configuration>` element, which names it. HYPOTHESIS, consistent with 198 of
  198 sampled files (`random.Random(20260930).sample` of 200 parts, 2 without
  KeyWords) and with fixtures o06 and o13 (`Config-1-Partition` is `Tall`,
  id 1).

### 10.2 Transmit format

Every embedded transmit is Parasolid neutral binary as described in the
publicly published Parasolid XT Format Reference: `PS\0\0`, i16 modeller
string length and the string (`: TRANSMIT FILE (partition) created by modeller
version NNNNNNN`), i32 schema length and the schema key
`SCH_<modeller>_<schema>_13006`, i16 maximum node types, i32 user-field size
(0), the nodes with embedded-schema edit scripts against the base schema
SCH_13006, and the terminator `00 01 00 01`. All integers big-endian. VERIFIED
(4,838 partitions parse to the terminator with no trailing bytes and re-serialise
byte-identically). There are no text transmits and no `SCH_` strings outside
transmit headers in the corpus. VERIFIED.

**Embedded schema.** The first node of each type is preceded by its schema
information, a u8 n:

- n = `0xFF`: the type's layout is identical to the base schema.
- Otherwise, for a type in the base schema, an edit script of one-byte ASCII
  operations applied to the base field list in order: `C` copies the next base
  field, `D` drops it, `I` and `A` each add a field definition that follows the
  operation, and `Z` ends the script. The resulting layout must have n fields.
- For a type not in the base schema, a full definition: a name string, a
  description string and n field definitions.
- A field definition is a name string, a u16 pointer class, an element count
  in the index encoding used for node indices, a type string when the pointer
  class is 0, and a u8 transmit code when the element count is 1 (a
  variable-length field).

**What this rests on.** The node layouts of the base schema SCH_13006 itself
are not reproduced here. SolidSeas takes them from the table in sldprt2step
(Apache-2.0, credited in `NOTICE`), checked against the public XT Format
Reference, which leaves some base fields untyped (the later fields of
`ATTRIB_DEF`) or describes them only in prose (the variable field of
`ATTRIBUTE`). The node-level claims in sections 10.1 to 10.7 (parsing to the
terminator and re-serialising byte for byte, partitions without bodies, the
87-node match, node type 150, `current_id` below `highest_id`, and the ghost
and stock body counts) therefore depend on that table, and were checked only by
the original analysis. The independent re-check confirmed everything above the
node level on all 6,309 top-level partition and deltas transmits and 14,872
LocalBodies transmits: the `PS\0\0` header, the i16 modeller string, the i32
schema key on base 13006, user-field size 0 and the `00 01 00 01` terminator;
no `SCH_` string outside headers; 3,152 chains of a partition and deltas and 5
of a partition alone. For o02 and o07 it also found the same multiset of
doubles in SOLIDWORKS' own `.x_b`, SolidSeas' `.x_b` and the raw partition.

### 10.3 Schema versions

42 distinct schema keys, modeller 1901261 to 3501256 (Parasolid V19.0 to
V35.1), all on base 13006. VERIFIED (4,838 partitions). Per saving version:
4100 = V19.01, 4400 = 21.0, 4700 = 22.01, 5000 = 24.0, 6000 = 24.01, 7000 =
25.01, 8000 = 27.0, 9000 = 28.0, 10000 = 29.0, 11000 = 30.0, 12000 = 31.0,
13000 = 31.01, 14000 = 32.01, 15000 = 33.01, 16000 = 34.01, 17000 = 35.01.
VERIFIED (3,134 partitions), except for documents saved with "Save as previous
version", which keep the newer schema (section 7.2): 6 of 9 partitions at 16000
and 1 of 4 at 15000 carry 35.01. The independent count finds 41 distinct schema
keys where the original found 42. SOLIDWORKS 2024 SP1 writes
`SCH_3501251_35102_13006`, the same key as its own `.x_b` export. One
LocalBodies transmit uses `SCH_1800141_18007`, which embeds no schema and needs
the non-public schema file; SolidSeas reports it as a problem.

Node type 150 occurs, flagged "identical to base", in 4 partitions, but has no
layout in the public base schema. A 48-byte layout (point and unit vector)
makes all 4 parse and validate; 41 bytes also parses. SolidSeas uses 48 bytes
and flags the body. HYPOTHESIS.

### 10.4 Converting a partition to standalone part files

SolidSeas copies each BODY and everything it points to (breadth-first, in
field order) into a part transmit whose root, index 1, is that BODY, as the
reference prescribes for part files. It cuts `BODY.owner`, `next` and
`previous`, re-chains `ATTRIB_DEF.next` and drops "(partition)" from the
modeller string. On the fixtures:

- o02 to o06 against SOLIDWORKS' own `o02_boxA.x_b`, and o07 against
  `o07_boxB_h31.x_b`: 87 model nodes matched, every non-pointer field equal,
  every pointer mapping equal; header and per-type schema information equal.
  VERIFIED (6 fixtures). o07 against o02's export differs in 17 fields, as it
  must (z = 0.031 instead of 0.03).
- o11 (fillets, so cylindrical and toroidal faces) against SOLIDWORKS' own
  `o11_curved.x_b`: 185 model nodes matched, every field equal. VERIFIED (1
  fixture).
- Node numbering and order differ from SOLIDWORKS' export, and its export
  drops or renumbers some SOLIDWORKS attributes.
- Text output: parsing SOLIDWORKS' own `o02_boxA.x_t` and writing it again
  reproduces it record for record, including number formatting (`%.15g`, no
  leading zero, short exponent, `1000.0000000000001` written `1e3`) and the
  80-character record wrapping. VERIFIED. Text keeps 15 significant digits, as
  Parasolid's own text output does.
- Corpus: 14,727 partition bodies convert to part transmits with no dangling
  pointers, consistent loop and fin back-pointers and symmetric fins, and every
  written file re-parses. VERIFIED. 199 of 200 sampled bodies were accepted by
  an independent open-source XT-to-STEP mapper (`random.Random(20260930).sample`
  of 200 parts with transmits up to 2 MB).
- The written files load in a real Parasolid kernel. VERIFIED on the first
  generation of the fixtures (2026-09-30): the `.x_b` and `.x_t` written for
  each of the 6 fixture parts with a body (12 files) import into SOLIDWORKS
  2024 SP1 (`LoadFile4`, in a separate SOLIDWORKS instance) with no error, and
  the imported volume and surface area equal the ground truth and SOLIDWORKS'
  own export: 6.0e-6 m^3 and 0.0022 m^2 for o02 to o06, 6.2e-6 m^3 and 0.00226
  m^2 for o07. The import was not repeated on the regenerated fixtures, but
  their bodies, and SOLIDWORKS' new exports, are B-rep identical to the first
  generation's (`compare_brep`). Whether bodies with curved faces (o11),
  multi-body parts (o12) and corpus bodies load is UNKNOWN: they have not been
  imported yet.

### 10.5 Deltas

The second chain block has the same header form, `TRANSMIT FILE (deltas)`. Its
first nodes are types 3 and 4 flagged identical to base, which the public base
schema does not describe, so it cannot be parsed. That it holds roll-back
history (lists of node type and index pairs) is a HYPOTHESIS: o02 and o07 have
different partitions but byte-identical deltas.

### 10.6 `Config-<n>-FeatureBodies/LocalBodies`

- u32 entry count, then per entry a CString feature name (for example
  `Imported1`) and either {u32 0, u32 n, n body records} or exactly one body
  record; one stream in the corpus uses a third form (a few bytes, then u32 L and
  a ZLB block of L bytes). A body record is u32 flag, u8 0, u32 L + 5, u8 0,
  u32 L, then a ZLB block of exactly L bytes holding a Parasolid part transmit.
  The flag is 0 or 1 (1 in 791 of 14,873 top-level records); its meaning is
  UNKNOWN.
- Telling the forms apart: after the name, a single body record has u8 0 at +4
  and +9, u32 at +5 equal to u32 at +10 plus 5, and the ZLB magic at +14.
  Anything else is the list form, or the third form when its u32 L and ZLB
  block are found within a few bytes.
- VERIFIED (independent count: with a flag of 0 or 1 accepted, 1,817 of 1,818
  streams parse and the other is the third form; written with a flag of 0 only,
  the grammar fails on 224 streams. The original count, 18,667 transmits with 0
  framing errors and 18,666 parsing and validating, came from code that never
  checked the flag.)
- When a configuration's partition holds no bodies, SolidSeas returns its local
  bodies instead. That they are then the final geometry is a HYPOTHESIS. One
  fixture is such a part: o09, box A imported from STEP through 3D Interconnect
  with no other feature, has an empty partition and one local body under the
  feature name `o02_boxA.step<1>`, whose eight vertices span the 10 x 20 x 30 mm
  box SOLIDWORKS reported for the part. After one cut (o10) the body is in the
  partition. VERIFIED (2 fixtures). Where a partition does hold bodies, the local
  bodies differ from them in 202 of 220 files, so they are feature inputs then.
  SolidSeas never falls back when a partition could not be read.
- With this fallback, 3,124 of 3,150 parts (99.17%) yield at least one
  structurally valid body: 1,547 from partitions, 1,577 from local bodies. The
  other 26: 25 have an empty partition and no local bodies (11 of them only ghost
  bodies), 1 has only the schema-less transmit. VERIFIED. With the 20 MiB
  transmit cap of the corpus sweep, 3,121 parts yield a body and 3 are over the
  cap (section 17).

### 10.7 Other Parasolid data in a document

- `Contents/Config-<n>-GhostPartition`: partitions of 10,258 wire bodies and 557
  sheet bodies. `Contents/Config-<n>-StockBodies`: 15 partitions, 33 solids.
  VERIFIED counts.
- Part transmits embedded in `ResolvedFeatures`, `Config-<n>` (legacy),
  `MatesList`, `CnfgObjs`, `CMgr`, `Definition`, attachments and weldment storage
  parse and validate (VERIFIED on up to 15 streams per family, same seed). That
  they are feature inputs (sketch profiles, tool bodies, mate geometry) is a
  HYPOTHESIS. SolidSeas does not return them.
- `WORLD.current_id` is below `highest_id` in 1,941 of 4,838 partitions (never
  above). Whether those hold a rolled-back state is UNKNOWN.

### 10.8 What tessellating the bodies relies on

`solidseas.tessellate` (`docs/API.md` 3.15) reads the bodies as `parasolid()`
returns them. These are the conventions it relies on. Samples:
`random.Random(20261002).sample` of 400 parts (1,610 bodies, 93,110 faces,
382,972 fins on faces) for the layout and conventions, `random.Random(20261004)`
of 900 parts for the parametrisations, the fixtures, and, for the newer
counts, the same 400 parts again (marked "400 parts"). Lengths are metres;
"within tolerance" means within max(1 um, the vertex's or edge's own
tolerance), a tolerance field holding NULL_DOUBLE (-3.14158e13) meaning
exact.

**Layouts.** Over the 1,610 bodies every topology and geometry type has one
layout, except that later schemas add fields to BODY (`lattice`,
`boundary_lattice`), REGION (`frame`), INTERSECTION (`intersection_data`, in
86 of the 134 bodies that have one) and LIMIT (`term_use`). Fields are
therefore read by name through the transmit's own schema. VERIFIED (1,610).

**Topology.**

- The faces of a body are reached from BODY `region`, REGION `next` and
  `shell`, SHELL `next`, then SHELL `face` with FACE `next` and SHELL
  `front_face` with FACE `next_front`, each face once: 93,110 of 93,110 faces.
  VERIFIED. A transmit can hold several BODY nodes (SOLIDWORKS' own
  `o12_multibody.x_b` holds two), so the walk starts from each.
- A LOOP's `halfedge` starts a ring of fins (HALFEDGE, the reference's FIN)
  linked by `forward`; every ring closes, with `backward` its inverse and
  `loop` pointing back: 100,332 of 100,332. VERIFIED. The first loop of a face
  is its outer loop in only 41,669 of 42,369 planar faces, so the outer loop
  is found by orientation (below), not by order. A face with no loop is a
  whole closed surface (22 spheres and 1 torus in the sample).
- A fin's `vertex` is its end vertex; its start is the end of the fin before
  it. With this reading every LINE fin of o11 runs from its start to its end
  with the curve's sense (32 of 32, 24 without it), and every edge on a
  TRIMMED_CURVE starts at its `point_1` and ends at its `point_2` (35,874 of
  35,881 edges, never the other way round; the other 7 lie inside the trimmed
  range). VERIFIED. `other` pairs the two fins of an edge (`other.other` is
  the fin itself). A sheet's boundary edge has a second fin outside any loop
  (7,608 in sheets, none in solids). A ring edge (closed, with no vertex) has
  fins with `vertex` 0 that are their own `forward`.
- An edge runs in its curve's natural direction times the curve's `sense`; a
  fin runs along its edge when its own `sense` is '+'. VERIFIED: with the
  curve's sense all 32 LINE fins of o11 and its 8 fillet arcs (90 degrees
  each, 4 of them 270 without it) run from their start to their end, and
  `parm_1 < parm_2` in all 50,931 trimmed curves whose basis has sense '+',
  `parm_1 > parm_2` in all 7,071 whose basis has sense '-'. A TRIMMED_CURVE's
  own sense is '+' (58,002 of 58,002), and its edge runs from `parm_1` to
  `parm_2` of its basis, so trimmed edges need no inversion.
- A tolerant edge (EDGE `tolerance` set: 20,979 of 382,972 fins) has no curve
  of its own in 20,902 cases; then each of its fins carries a TRIMMED_CURVE
  over an SP_CURVE in that fin's face's surface (20,979 of 20,979; the surface
  is the fin's face's in 4,194 of 4,194 checked), which runs in the fin's
  direction in 4,124 of 4,170. HYPOTHESIS for the other 46: nearly closed
  edges, where the test is ambiguous.
- Ring edges lie on closed curves: on the 400 parts, 4,820 ring fins on
  CIRCLEs, 46 on ELLIPSEs, 64 on INTERSECTIONs, 12 on trimmed circles, 4 on
  B_CURVEs and 31 on tolerant edges, none on a LINE. VERIFIED counts. A fin
  with no edge (11 on the 400 parts) is alone in its loop, an isolated vertex
  (11 of 11); SolidSeas leaves such a loop out of the face's boundary, as it
  would a ring on a line, which has no extent. HYPOTHESIS: an isolated vertex
  marks a point of the face, such as an apex.

**Orientation.** A face's outward normal (out of the solid, into its front
shell) is the surface's natural normal `Su x Sv` times the surface's own
`sense` times the face's `sense`, and the face's outer loop runs
counter-clockwise about it, the others clockwise. VERIFIED on o02's six faces,
o10's hole (a CYLINDER of face sense '-') and o11's fillets, and on the
corpus: in 42,369 planar faces bounded by lines, circles and ellipses exactly
one loop runs counter-clockwise, the largest; 294 of them lie on PLANEs of
sense '-', where the rule holds only with the surface's sense (0 of 294
without it). Surfaces of sense '-' are common (2,182 CYLINDER, 402 CONE, 366
PLANE and 110 B_SURFACE nodes in the 400 parts), so leaving the surface sense
out would turn faces inside out. Sheets have no inside; their faces keep the
same rule.

**Parametrisations.** X is `x_axis`, A the axis or normal, Y = A x X:

| Surface | S(u, v) |
|---|---|
| PLANE | P + u X + v Y |
| CYLINDER | P + v A + r (cos u X + sin u Y) |
| CONE | P + v A + (r + v tan a)(cos u X + sin u Y), tan a = `sin_half_angle` / `cos_half_angle`; apex at v = -r / tan a |
| SPHERE | C + r (cos v (cos u X + sin u Y) + sin v A), poles at v = +-pi/2 |
| TORUS | C + (R + r cos v)(cos u X + sin u Y) + r sin v A |
| B_SURFACE | a B-spline, below |
| SWEPT_SURF | section(u) + v sweep |
| SPUN_SURF | profile(u) turned by v, right hand, about the line (base, A) |
| OFFSET_SURF | base(u, v) + offset times the base's unit normal times the base's own sense |

VERIFIED (900 parts): an SP_CURVE's (u, v) end points, pushed through these
formulas, land on the TRIMMED_CURVE's stored `point_1` and `point_2` within
0.1 um for PLANE 68,827 of 68,870, CYLINDER 13,906 of 13,913, CONE 573 of 580,
SPHERE 245 of 245, TORUS 1,375 of 1,375, B_SURFACE 33,856 of 33,875,
SPUN_SURF 1,436 of 1,436, SWEPT_SURF 398 of 398 and OFFSET_SURF 44 of 44 (40
of 44 without the base's sense in the offset's direction; the 4 that need it
have a base of sense '-'). An
offset goes the way of its base's natural normal times the base's sense: of the
866 fin vertices on the loops of offset faces in the one corpus part that has
them, every one lies on the offset surface so read, and the 60 whose base has
sense '-' only with that sense. VERIFIED (1 part, 866 vertices). Those 60
offsets have sense '-' themselves too, so that it is the base's sense and not
the offset's that decides is a HYPOTHESIS. Curves:
LINE `P + t D`, CIRCLE `C + r (cos t X + sin t Y)` with Y = N x X, ELLIPSE
`C + a cos t X + b sin t Y`, B_CURVE a B-spline, SP_CURVE its surface along a
two-dimensional, never rational B-spline (3,986 of 3,986). VERIFIED by the
vertices lying on them (9,091 of 9,091 on lines, 3,692 of 3,692 on circles,
2,272 of 2,273 on B-curves).

**B-splines.**

- A NURBS_SURF's control points are stored with v varying fastest (index
  `i_u n_v + i_v`): under this order 3,956 of 3,965 sampled vertices lie on
  their surfaces, under the other none. Rational control points are
  homogeneous, `(w x, w y, w z, w)` with `vertex_dim` 4. VERIFIED.
- The knot vector is the KNOT_SET values repeated by the KNOT_MULT counts,
  `n + degree + 1` long (1,395 of 1,395 surfaces). Both arrays can end in
  entries of multiplicity 0 that hold no knot: 612 of 36,636 KNOT_MULT nodes
  in the 400 parts. VERIFIED.
- Of the 4,612 B_SURFACE nodes in the 400 parts, 18 are flagged periodic or
  closed (7 in u, 11 in v), and 2 more close on themselves without the flag:
  their first and last rows of control points coincide within a tenth of
  1e-3 of their body's size (none within a nanometre). SolidSeas treats those
  as closed. A boundary row of control points collapsed to one point is a
  pole: 128 rows collapse within a nanometre, and 574 more within 1e-3 of their
  body's size, which SolidSeas treats as poles too (a face whose loop would
  then lie wholly on poles is tried again with the exact ones only). VERIFIED
  counts; that the 574 are meant as poles is a HYPOTHESIS.

**Intersection curves.** An INTERSECTION is the polyline through its CHART's
points. Its parameter grows along the chart: of 1,030 trimmed intersection
curves in the 400 parts, 1,025 trim from `parm_1` to `parm_2` in the chart's
order (up the chart when `parm_1 < parm_2`, down it otherwise) and 4 more wrap
round a closed chart that way; 1 does neither (HYPOTHESIS: a trimmed end at
the chart's own end, where the test is ambiguous). VERIFIED. A closed chart
can end a few microns short of its start: of the 6,831 charts, 224 end
exactly where they start, 15 within 5 percent of their longest segment of it,
and 6,592 at least a segment away. LIMIT `type` 'H' at both ends goes with a
closed chart (231 of 231; the 8 other closed ones are 'T' at both ends, as are
6 open ones); the open ones are 'L'/'L' (5,818), 'L'/'T' (667), 'T'/'L' (92),
'L'/'B' (7), 'T'/'T' (6) and 'T'/'B' (2). VERIFIED counts; what the types mean
is UNKNOWN. The chart's
`chordal_error` reaches 5.4 mm, so a chart can be coarser than a tessellation
wants; SolidSeas uses it as it is.

**Rolling blends.** A BLENDED_EDGE has no closed form, and Parasolid's own
(u, v) of it is UNKNOWN (10.9), so the tessellator draws the B-spline the STEP
export writes for it (10.9), built from the blend's spine, its two supports and
its ranges alone. On the 222 corpus parts whose active configuration has
blends (4,280 blend faces: 3,989 of `blend_type` R, 291 of type E, the cliff
edges; none on an offset of a blend), what that rests on:

- A face's outer loop runs counter-clockwise about its outward normal on a
  blend too, so on a blend that does not close on itself the sign of the
  largest loop's area in the approximation's (u, v) gives the face's side. Of
  the 3,564 such faces (each of one loop) whose side the export's rule, a face
  met tangentially, gives too, 3,557 agree; on the other 7, in two parts, the
  loops' side is the one whose edges meet the neighbouring faces' each the
  other way round, and the export's would have turned them inside out (both
  parts are refused by the export for other reasons). 36 more meet no face
  tangentially. The export's rule is kept for blends closed round their spine,
  whose loops wrap round it.
- A tolerant edge's fins each carry an SP-curve in their own face (above),
  and where one face is a blend its curve is in the blend's unknown (u, v):
  such an edge is sampled along the other fin's curve. 98 faces beside blends
  (64 B-surfaces, 24 cylinders, 6 tori and 4 planes) were lost to it before,
  none now. A tolerant edge between two blends has no other curve: its faces
  are not drawn (`unsupported_curve`, 60 faces in 17 parts).
- Measured at the middle of each span alone, as the tessellator measures it
  for speed, the deviation was up to 2.4 times too low (10.9); fitted to 4% of
  the chord tolerance so measured, a blend lies within about a tenth of it.
- Following a foot on a support from the last one, rather than searching the
  support afresh whenever the point moved more than its distance from it (as
  the export does), kept feet from jumping to another part of a B-spline
  support: on one part 96 of its 192 blend faces were refused searching afresh
  so and none following the foot; on another, 6 of its 97 searching afresh
  only past three times that distance and 2 following the foot, in less than
  half the time.

**Transforms.** Coordinates are the part's own: no TRANSFORM node is reachable
from any of the 1,610 bodies. VERIFIED.

**What is not known.** Why a part's stored display mesh sometimes shows far more
faces than its stored partition holds (UNKNOWN; consistent with a rolled-back
partition, 10.7). SOLIDWORKS does mark a hidden body (10.9, Hidden bodies); the
tessellator does not read the mark yet, so hidden bodies are tessellated. That
the bodies missing from some parts' own display meshes are hidden ones is a
HYPOTHESIS.

### 10.9 What the STEP export relies on

`solidseas.step` (`docs/API.md` 3.19) writes the bodies `parasolid()` returns
as STEP. Beyond 10.8 it relies on the facts below. Samples: the fixtures, and
`random.Random(20261003).sample` of 400 readable parts of the corpus, each
exported in its active configuration (marked "400 parts"; counts of bodies,
blends and curves are over the 358 parts written).

- **Body names.** A BODY's ATTRIBUTE whose ATTRIB_DEF identifier is
  `SWIMPLICITBODYNAME_ID_U` holds, in its first field (UNICODE_VALUES), the
  body name SOLIDWORKS reports (`Boss-Extrude1`, `Fillet2`, an imported
  body's `o02_boxA.step<1>`). VERIFIED: every fixture part's solid names
  equal the ground truth's, and SOLIDWORKS names the solid of its own STEP of
  o02 the same. On the 400 parts 168 of 617 bodies carry one; the export
  names the others `Body`, `Body2` and so on.
- **Hidden bodies.** A BODY's ATTRIBUTE whose ATTRIB_DEF identifier is
  `BODY_IN_LIGHTWEIGHT_PERM` holds, in its second field (INT_VALUES, one
  value; the first field is empty), 1 for a body SOLIDWORKS shows and 0 for one
  it hides. SOLIDWORKS' own STEP leaves hidden bodies out, and so does the
  export. VERIFIED against SOLIDWORKS' own counts of solid and surface bodies,
  and of the hidden ones, measured through its API in a separate SOLIDWORKS
  instance on 179 corpus parts in their active configurations: 280 bodies carry
  1 (205 solids, 75 sheets), 4 carry 0 (the hidden solid of each of the 4 parts
  SOLIDWORKS reports one in), 20 carry none (2 solids, 18 sheets, all imported
  local bodies, 10.6); in 178 parts the counts agree, the 5 with unmarked
  bodies among them (SOLIDWORKS shows those), and in the other SOLIDWORKS counts
  no body where the partition holds one marked shown. In each of the 4 parts the
  body marked 0 is the one whose volume SOLIDWORKS' mass properties leave out.
  Every fixture body made in SOLIDWORKS carries 1; o09's imported body carries
  none. On the corpus (3,173 parts, active configurations) every partition body
  carries the mark (3,488 solids, 134 of them hidden in 86 parts; 319 sheets, 2
  hidden), as do 6,562 of 10,164 local-body solids (1 hidden) and 2,850 of
  3,137 local-body sheets (3 hidden); no part hides every solid, and 5 of the
  461 parts with several solids have a solid without the mark, all local bodies.
  What the name refers to, and whether the mark follows a display state other
  than the one saved, is UNKNOWN.
- **Faces round a closed surface: SOLIDWORKS cuts them at their seams.**
  SOLIDWORKS' own STEP of o10 and o11, written with its "split periodic faces"
  option on (`swStepExportSplitPeriodic`), writes each face that goes all the
  way round its surface (a hole's cylinder, the torus of the fillet round o11's
  hole) as two, cut along the surface's iso-parameter curves at u = 0 and u =
  pi: o11's cylinder (x axis +x) along the lines x = 25 and x = 15, its torus
  (x axis -x) along its cross-sections through x = 14 and x = 26, o10's hole
  along x = 7.5 and x = 2.5, every ring edge they cross cut there too. VERIFIED:
  the export's STEP of each has the same vertices, edges (their ends, curve
  kinds and middle points) and faces as SOLIDWORKS' as point sets (14 faces, 34
  edges and 22 vertices for o11, 8, 18 and 12 for o10), compared outside the
  repository, whose tests hold those counts and seam lines. What SOLIDWORKS does
  where a hole or a vertex lies on one of those lines, and on B-spline and
  revolved surfaces, spheres and cones, is UNKNOWN: no fixture has one.
- **Caps whose loop passes close to the pole are written whole.** A cap's two
  seams meet at the pole, which becomes a vertex of both halves; where the cap's
  loop passes close to the pole, a seam there is that short, the pole that close
  to the halves' other edges, and the half between them a sliver. Two corpus
  parts have such caps, sphere caps whose rim passes 51 and 59 nm from the
  sphere's pole (rows 1726 and 1070): cut, seams of 0.05 to 0.56 um and halves
  OCCT 7.9.3 read with no area, saying "Improperly connected shell split into
  parts", row 1726's file invalid (valid whole), and SolidSeas' own reader
  skipping those halves. On 875 synthetic tilted caps of spheres of 1.27 and 50
  mm, cut whatever the pole's distance, OCCT read the halves with edges it had
  to correct ("Edges were intersecting, corrected"), meshes left open or faces
  of no area in 34 of the 489 whose rim came within 0.05 % to 7 % of the
  farthest it reaches from the pole (7 % only on the largest caps), and in
  none of the 386 from 8.4 % to 27 %, rims passing close to the sphere's other
  pole among them; written whole, it read all of the 180 it was given without
  fault. VERIFIED (outside the repository; the tests hold caps 0.5 um off, and
  at 0.03 %, 5 %, 10 % and 25 % of their reach). The export therefore cuts a cap
  only when its loop keeps a micrometre, and 15 % of the farthest it reaches,
  from its pole, and a seam shorter than a micrometre moves to the next pair of
  values. With the two parts' caps whole, OCCT reads both files valid and
  without those messages, and SolidSeas' reader skips no face of them. The
  other 20 caps cut in the 424 corpus parts compared (8 parts) have their pole
  at the middle of their loop, as far from its nearest point as from its
  farthest.
- **What OCCT makes of the cut faces.** On 180 corpus parts (the 179 SOLIDWORKS
  measured and one of 2,061 faces), 167 written before and after, read by OCCT
  7.9.3 with its default healing, the export cuts 602 faces; OCCT then adds 6
  seams to 6 files, where it added 638 to 66 before, each to a face still
  written whole (3 bands whose edge crosses every iso-parameter line more than
  once, 1 band whose holes cover every one, 2 faces on apple tori); the same 5
  files fail its validity check before and after, and its volumes and areas
  move by at most 1.1e-6 and 6e-8 of themselves, the parts with hidden bodies
  aside. Its transfer gives one message the files with faces whole did not get:
  one more "Edges were intersecting, corrected" on row 1633 (on one half of a
  cut cylinder whose loop runs through an ellipse; healed, the file valid). Its
  pcurves stray more than 1e-3 mm from the edges' curves in 13 of the 14 files
  the OCCT evaluation listed, the same faces and edges by count and by the same
  largest amount, file by file, before and after (fewer in the 2 with a hidden
  body, whose faces are no longer written):
  the largest, 0.17 mm (row 1662), on sphere faces bounded by circles, which go
  round nothing and are written whole either way; in 2 files on circle and
  ellipse edges of B-spline surfaces; in the rest on B-spline edges of
  cylinders, planes and B-spline surfaces. A file's own pcurves would not help,
  since OCCT's default reader computes its own (a SURFACE_CURVE's pcurve
  deliberately written 0.1 mm off changed nothing). Its Gauss-Kronrod volume
  integration, its high-accuracy one, became slower on 8 corpus parts whose
  cylinders and cones were cut (and on one its sphere caps), CPU time of one
  integration at a time: 2 to 12 times on 5 (rows 297, 1233, 1341, 2093 and
  3273, to between 2.5 and 60 s), and from under a second to 52, 192 and 615 s
  on 3 (rows 3158, 736 and 1595); the volumes it gives move by at most 2.3e-9.
  Its default integrator and its mesher took 133 and 113 s in all over the 165
  of the 180 parts both versions wrote and OCCT read, against 134 and 119 s
  before.
- **Colour.** Some faces in the fixtures' transmits (`o12_multibody.x_b`, for
  one) carry `SDL/TYSA_COLOUR` attributes of three reals (REAL_VALUES).
  Whether and how they follow SOLIDWORKS' appearances is UNKNOWN; the export
  writes no colour.
- **The spun surface's parameters.** SPUN_SURF is profile(u) turned by v
  (10.8), ISO 10303-42's SURFACE_OF_REVOLUTION the swept curve's v turned by
  u: the parameters swap, so the natural normal of the STEP surface is the
  reverse of Parasolid's. VERIFIED by the orientation oracle on a synthetic
  spun cylinder (`tests/test_step_approx.py`); sldprt2step kept Parasolid's
  normal.
- **Spun surfaces that cover themselves twice.** A SPUN_SURF whose profile is
  a circle centred on its axis, in a plane through it, sweeps a sphere twice:
  each point has two parameters, with opposite natural normals. Which half of
  the profile a face uses is not on the surface (where Parasolid keeps it is
  UNKNOWN; SolidSeas' tessellator follows the face's loops), and a STEP reader
  could take such a face either way round, so the export refuses it
  (`unsupported_surface`), as it does a profile that crosses its axis. Found
  in 4 of the 400 parts.
- **The lemon torus.** A TORUS with a negative major radius R (a lemon) is
  ISO's DEGENERATE_TOROIDAL_SURFACE with major radius -R, its x axis reversed
  and `select_outer` false: Parasolid's point (u, v) is ISO's point
  (u, pi - v), so the natural normal turns round. VERIFIED numerically and by
  the orientation oracle on synthetic lemon bands; sldprt2step kept
  Parasolid's normal, which writes such faces inside out.
- **Rolling blends.** A BLENDED_EDGE's spine lies on each of its two
  supports offset by that support's `range`, along its natural normal times
  its own sense: 743 of the 745 blend surfaces fitted on the 400 parts (cliff
  edges aside) had their spine on that choice of the four sign combinations,
  and 2 fitted another better at their chart points. Parasolid's own (u, v)
  of a blend is UNKNOWN: of 828 blend faces, the face's sense times the
  surface's agreed with the natural normal of the export's surface (u along
  the spine, v from the first support to the second) for 342 and was its
  reverse for 486, so the export takes each blend face's side from a face it
  meets tangentially.
- **Blends round a closed spine.** A blend's faces can go all the way round a
  spine that closes (a CIRCLE or an ELLIPSE): a ring of blend between two ring
  edges, or a ring and arcs. Their loops, followed round the spine in its
  parameter, say so: one comes back a whole turn further on. Lofted only over
  the span of its edges' sample points plus a margin, as the export first did,
  such a surface stopped short of a turn by up to a sampling step (on one
  corpus part by 0.3 degrees, the face's boundary circle then 16 um off it),
  which no vertex check sees; the export now lofts it round the whole spine,
  its last section its first. VERIFIED on a synthetic ring of blend
  (`tests/test_step_approx.py`) and on that part, whose edges then lie within
  61 nm of the blend (none of the 400 parts below has such a blend).
- **Where a blend's loft strays.** Between two exact sections the loft's error
  peaks at the middle where the spans are even and the section keeps its angle
  (a blend round a circle), but as near as a fifth of the span from either end
  where the section's angle changes along the spine. Measured at the middle
  alone, the deviation of a synthetic cylinder cut at 50 degrees and rounded
  was reported as 93 nm where it is 224 nm, and on corpus parts up to 2.4
  times too low; measured at seven points along every span it is within 1% of
  the true one on the synthetic cuts and within 3% on the corpus part checked.
  The sides of a lofted blend can also drift along the canal surface from the
  true lines of contact while staying on it: on one corpus part by about 20
  um, which the measure now includes (that body is refused).
- **Edges off their faces.** Between its vertices an edge can lie off one of
  its faces by more than Parasolid's resolution in the source itself, with no
  tolerance declared or beyond the one declared: exact B-curves 94 nm and 214
  nm from their B-surfaces on parts of other samples. The export checks points
  along every edge on its faces as written, accepts such a gap up to
  `max_deviation_m` as the source's own (in `max_gap_m` and the uncertainty)
  and refuses a body with a larger one: on the 400 parts 660 points accepted,
  and 2 parts refused, one with an exact edge 3.1 um off a B-surface, one with
  tolerant edges up to 1.3 um off a face where they declare 0.44 um.
- **Trimmed past the end.** A TRIMMED_CURVE's `parm_1` or `parm_2` can lie
  past the end of its basis's range when the basis closes without being
  flagged periodic; the trimmed curve then runs across the basis's end, read
  as periodic. VERIFIED on the 400 parts: 3 curves in 2 parts, all on bases
  that close.
- **Gaps.** A vertex can lie off its own curve or surface by more than twice
  Parasolid's resolution with no tolerance declared on it or its edge: on the
  400 parts 7 vertices in 4 parts, at most 509 nm off. The export writes them
  as they are and its uncertainty covers them.

On the 400 parts (read-only at below-normal priority, every STEP file kept in
memory, no corpus file changed; `test_corpus_step` in `tests/test_corpus.py`
measures them again) the export made 356 files, 248 exact and 108 with
approximations (intersection curves in 93 parts, other SP-curves in 30, blends
in 15, blend boundaries in 11), every approximation within 915 nm of the
geometry, every accepted gap at most 983 nm and every file's uncertainty at
most 2 um. It refused 20 parts (15 with a fit that stayed above 1e-6 m, one of
them a blend whose sides strayed about 20 um from where its sphere touches its
supports, 2 with a spun surface that covers itself twice, 1 with a blend whose
support no face uses, and 2 with an edge more than 1e-6 m off one of its
faces), stopped 3 at `max_seconds` (300 s; one of them, refused within a
minute before for its spun surface, now spends that time measuring its blends)
and found nothing to export in 21 (17 of sheets only, 4 whose active
configuration's bodies the part does not store). Mapping took a median of 0.04
s (90th percentile 4.0 s, at most 229 s); files are a median of 25 KB, at most
25.8 MB. The tests' own Part 21 reader and checker (`tests/step_support.py`)
re-read 343 of the 356 files (checking the other 13 took more than 600 s): no
syntax or topology problem, no vertex or point of an edge beyond the file's
uncertainty or the tolerances, each of 20,378 curved edges (those sampled
between their ends) on its own arc, and 30,607 of 30,607 faces agreeing with
SolidSeas' tessellation of the source, by area over triangles spread across
each face.

**Read by another kernel (the OCCT oracle, `tests/README.md`).** Open CASCADE
7.9.3 reads the export with its basic STEP reader, in a child process, and
measures it with Gauss-Kronrod volume and adaptive area. VERIFIED on every
fixture part with bodies (14 configurations, `tests/test_occt_oracle.py`):

- **Clean read.** Every file reads with no check failing, into the solids
  SOLIDWORKS counts, closed and valid.
- **Healing.** None: with the faces that go round a closed surface cut at
  their seams (above), OCCT adds no seam edge to any fixture. Written whole, as
  they were before, they gave its only healing message, "Missing seam-edge
  added", 1 on o10 and 2 on o11.
- **Exact against SOLIDWORKS.** Volume, area and centre of mass agree with
  SOLIDWORKS' own values within 7.6e-16, 3.3e-16 and 1.5e-16 (the last relative
  to the box's diagonal). The box agrees within 2.7e-9 of the diagonal: OCCT's
  box of a circle runs a few nanometres wide.

SOLIDWORKS' STEP of o02 gives the same.

On the corpus, `test_occt_corpus_step_export` covers the 179 parts whose
SOLIDWORKS measurements the `sw_oracle` job recorded (read-only at below-normal
priority, every STEP file deleted as soon as OCCT and SolidSeas' reader had read
it, no corpus file changed). Each part is exported as File > Export STEP exports
it: its solid bodies, or, for the 22 parts that have none, their sheets, which
are then what goes to a supplier. The export wrote 166 of them (117 exact) and
refused 13, all not representable. These figures were measured before the
export cut faces at their seams and left hidden bodies out; what those changed
is said above. OCCT:

- **Read.** It read all 166 with no check failing, into as many closed solids
  as the export wrote, and each part of sheets into as many free shells.
- **Valid** except:
  - rows 1662, 2103 and 2455, where its own pcurves, projected because the
    export writes none, leave wires wrongly nested or oriented;
  - rows 213 and 234, parts of one degenerate sheet whose area SOLIDWORKS
    measures as 3.5e-21 square metres.
- **Healing.** It added 587 seam edges, and corrected poor vertex projections
  70 times and intersecting edges 41 times; 42 and 12 of those are on the parts
  of sheets.

SolidSeas' own reader read all 144 files of solids back, each shell of the sign
of OCCT's at its place. None of these parts has a cavity, so for a void's
orientation the export rests on the synthetic part with a cavity
(`docs/formats/step.md` section 11).

Against SOLIDWORKS' own measurements:

- **Volume and area,** on the 137 parts with a valid mass and no hidden body:
  - volume: median 1.5e-14, 90th percentile 6.6e-6, at most 1.9e-4;
  - area: median 1.2e-14, 90th percentile 2.0e-6, at most 2.0e-4.
- **Parts of sheets.** The sheet area on the 18 SOLIDWORKS gives one for (not
  row 242, whose sheet it measures as 0, nor row 1965, which it did not
  measure): median 3.0e-9, 90th percentile 1.2e-5, at most 2.0e-5. Row 239's
  4.6e-6 is still unexplained. The box of all bodies on 19 of them is within
  4.0e-7 of its diagonal, except row 242 at 7.4e-4.
- **Hidden bodies.** The 4 parts with hidden bodies, which the export then
  writes, match the box of all their bodies within 1e-9 of its diagonal.

The run took 29 minutes on 2 workers.

**Read back by SOLIDWORKS.** On 2026-10-05 SolidSeas' STEP of the fixture parts
and of 175 of the corpus parts SOLIDWORKS measured earlier (the `sw_oracle`
sample) was imported into SolidSeas' own SOLIDWORKS 2024 through the bridge
(`import_file` with `insert`, `docs/API.md` 3.22) and measured there with
`mass_properties` against SOLIDWORKS' measures of each part itself: off-hours,
read-only and numbers only, each STEP file deleted once measured, no corpus
file changed. VERIFIED:

- **Fixtures.** The 12 fixture parts that imported come back exact: volume
  and box as SOLIDWORKS measures the parts, and the area within 2.2e-16 of it.
  o01 has no body to export, and o12's insert of its two solids faulted
  (below).
- **Corpus.** The export wrote 162 of the 175 and refused 13, not
  representable. 21 imports faulted inside SOLIDWORKS (`RPC_E_SERVERFAULT`, on
  parts of several bodies or of sheets: a known issue of the bridge's insert,
  `src/solidseas/swapi/README.md`), 2 came back empty and 9 as surfaces. The
  130 that came back as solids are within 7.5e-15 of SOLIDWORKS' volume at the
  median, 1.3e-6 at the 90th percentile and 1.7e-4 at most, on most parts at
  least as close as SOLIDWORKS' own STEP round trip of the part. These were
  measured on the export before it cut faces at their seams.
- **Faces.** With the faces round a closed surface cut at their seams, the
  imported parts have the face count of SOLIDWORKS' own STEP round trip on 106
  of the 139 parts both give one for, against 78 with those faces written
  whole.

**Read back as components.** On 2026-10-14 SolidSeas' STEP of 25 corpus parts
of several solids (2 to 17) and of 12 corpus assemblies (1 to 74 solids), the
first the export writes in a `random.Random(20261014)` order of the corpus,
was imported into SolidSeas' own SOLIDWORKS 2024 with `import_file`'s
`component` method, which takes the files of several bodies the insert above
faulted on, and measured with `mass_properties` against SOLIDWORKS' measures
of each original, opened read-only in the same instance just before: no other
SOLIDWORKS running, numbers only, no corpus file changed, and the STEP files
removed once the run ended. VERIFIED:

- **Every one imported**, at the origin, with the original's count of shown
  solids (3 of the parts hide a body, which the export leaves out), and no
  sheet in the sample.
- **Parts.** Volume within 2.9e-9 of SOLIDWORKS' at the median, 4.5e-6 at the
  90th percentile and 4.4e-5 at most; area within 2.5e-9, 1.4e-6 and 4.8e-5;
  the centre of mass within 2.5e-6 m and the box of all bodies within 1.6e-7
  m; no fault in Check3 either way.
- **Assemblies.** Volume within 3.7e-6 at the median, 1.6e-4 at the 90th
  percentile and 3.5e-4 at most, of the order of the largest above; area
  within 1.2e-6, 5.5e-5 and 1.2e-4; the centre of mass within 1.2e-5 m and the
  box within 9.1e-10 m. Check3 found faults in 3 of them: 0 in the original
  and 1 read back, 2 and 0, 6 and 6. An original with 4 suppressed components
  came back without them, as the export leaves them out.
- **The sample.** Of the parts tried on the way, 236 had one body and the
  export refused 31 (not representable, or nothing to export); it refused 32
  assemblies.

## 11. Properties, configurations, material and units

### 11.1 Custom properties, 2015+ files

`docProps/custom.xml`, property section `UserDefinedProperties`: each
`<property name pid [IsEquation] [TypeID]>` holds one `vt:*` element with the
evaluated value. The value's type comes from that element: `vt:lpwstr`,
`vt:lpstr` or `vt:bstr` text, `vt:i4`, `vt:i2`, `vt:r8` or `vt:r4` number,
`vt:bool` yes or no, `vt:filetime` or `vt:date` date. VERIFIED on fixtures o04
to o06 (`PartNo` and `Description` text, `Qty` = 42 as `vt:i4`) and o14 (text
as `vt:lpstr`, `7` as `vt:i4`, `3.25` as `vt:r8`, `Yes` as `vt:bool`, a date
as `vt:filetime`). Corpus: 561 modern files carry 3,018 properties. A date
entered as 3/15/2024 in a UTC-4 session is stored as `2024-03-15T16:00:00Z`,
noon local time in UTC. VERIFIED (fixture o14).

`TypeID` does not give the type. Across all 3,734 visible properties in
`custom.xml` and the configuration property streams it is 0 on 1,479 (holding
text, integer and real values), 30 on 612, and absent on 1,643. 3, 11 and 64
occur only on the API-made fixtures: 3 on `Qty` (o04 to o06) and on o14's
`NumberProp` and `DoubleProp`, 11 on o14's yes-or-no property and 64 on its
date. VERIFIED (independent count). SOLIDWORKS stored the property the API
asked for as type 5 (double) as 3, holding a `vt:r8` value, so no fixture has
5. That 30, 3, 11 and 64 follow SOLIDWORKS' `swCustomInfoType_e` (text,
number, yes or no, date) is a HYPOTHESIS, and so is reading 0 as its "unknown"
value. SolidSeas reports `TypeID` but types every value by its `vt:*` element.

- **Linked values.** A property linked to an expression (for example
  `"SW-Mass@Part.SLDPRT"`) stores the expression as a second, hidden property with
  an empty name and pid `0x01000000 | pid`; the visible property holds the
  evaluated value. VERIFIED (20 file-level and 25 configuration-level linked
  properties in 27 files; the same convention in legacy property sets; fixture
  o14's `Mass` and `Material`, pids 8 and 9 with hidden pids `0x01000008` and
  `0x01000009`). Every one of the 45 hidden expressions is a quoted reference:
  34 name a value with `@` (32 of them an `SW-` property, as in
  `"SW-Mass@Part.SLDPRT"`) and 11 are `$PRP:` references to an `SW-` property.
  One more, in a legacy file, holds the same text as the visible property and
  links nothing. VERIFIED.
- The evaluated value is a cache and can be stale: 2 files store a material name
  that disagrees with the assigned material. VERIFIED.
- `<FPVals>` holds full-precision values in `<$code$value$>` segments, for
  example a mass shown as 0.19 with 0.1908689933280414 in FPVals. The codes are
  a HYPOTHESIS (0 text, 5 mass, 1 linked dimension), consistent with fixture
  o14 (`Mass` shown as 16.20 g holds `<$5$0.0162000000000000$>`, in kg;
  `Material` holds `<$0$1060 Alloy$>`); SolidSeas does not expose FPVals yet.
- `IsEquation` is `False` or absent in all 2,961 occurrences.
- `Contents/CusProps` is a second, binary store (MFC classes `moCusPropMgr_c`,
  `moCusPropContainer_c` and others) with the recurring element u32 9, CString
  name, u32 kind, CString expression, CString evaluated value. It agrees with the
  XML in 150 of 150 matched properties (VERIFIED, 85 files) and also holds
  weldment cut-list properties. Which container or configuration each element
  belongs to is UNKNOWN; SolidSeas uses it only as a cross-check and as a source
  of expressions that the XML lacks.
- **What makes a property linked.** CusProps keeps a value as it was typed,
  and stores a typed value with its expression and evaluated text equal: on
  o14 the date is `3/15/2024` and the real number `3.25` in both fields, where
  the XML holds `2024-03-15T16:00:00Z` (a FILETIME) and `3.250000`. A link is
  stored with a different evaluated value beside it (`Mass`: the expression
  `"SW-Mass@o14_property_types.SLDPRT"`, evaluated `16.20`). On the corpus
  CusProps holds 150 of the properties it was matched with, all text: 147
  store a typed value and 3 a link, which a hidden property holds as well. No
  corpus number or date property has a CusProps element. VERIFIED. SolidSeas
  therefore reports a property as linked when the carrier that stores its
  expression stores a different evaluated value beside it, the hidden property
  against the visible one in the same stream or a CusProps element against its
  own evaluated text, and the expression is not a literal of the property's
  type (a number that parses to the value, a yes or no that means it). It
  never compares one carrier's expression with the other's text, which is what
  made o14's date and real number read as linked before. A typed date or a
  number with a decimal comma (`3,25`) in a hidden property is not taken for a
  literal and would read as linked: no fixture or corpus file stores one there
  (all 45 hidden expressions are quoted references), and a date as typed
  depends on the saving machine's locale. This agrees with SOLIDWORKS on all
  29 fixture properties, o14's `DateProp` and `DoubleProp` unlinked and `Mass`
  and `Material` linked, and gives the same 45 corpus links as before. That
  SOLIDWORKS can store a link in CusProps alone, without the hidden property,
  is a HYPOTHESIS; SolidSeas reads one as linked (tested on a crafted variant
  of o14).

### 11.2 Legacy property sets

Standard MS-OLEPS streams: `\x05DocumentSummaryInformation` with custom
properties in the user-defined section (FMTID `D5CDD505-2E9C-101B-9397-08002B2CF9AE`,
names in the dictionary), and top-level `Config-<n>-Properties` for
configuration properties. Code page 65001 (UTF-8) in 3,542 of 3,553 sections,
1252 in 11. 0 parse errors over 588 + 562 + 557 + 629 property-set streams;
77 legacy files carry 287 custom properties. VERIFIED, with one qualification:
in the version-3100 file, `DocumentSummaryInformation` declares a 1,009-byte
user section inside an 827-byte stream. A strict MS-OLEPS parser rejects it;
SolidSeas parses it leniently and recovers its 16 properties, and the counts
above use that lenient parse.

### 11.3 Configuration properties

`docProps/Config-<n>-Properties.xml` (2015+) and `Config-<n>-Properties`
(legacy) use the custom-property schema; n is the configuration id. VERIFIED
on fixture o06 (`OracleAlt` has id 1 and `CfgOnly` = `ALT-VALUE`; `Default`,
id 0, has none) and in the corpus (760 configuration properties; 1 file has an
n that matches no configuration). `docProps/Config-<n>-Cutlist-Properties.xml`
exists from 12000 and is not decoded. UNKNOWN.

### 11.4 Configurations

Names, ids and the most-recent flag come from `swConfigurationList` in
`swXmlContents/Features` (parts) or `COMPINSTANCETREE` (assemblies); comments
and material from the KeyWords `<Configuration id Name Comment Material>`
elements; the active configuration at save from `SW-Configuration Name` in
`ISolidWorksInformation`. VERIFIED on fixture o06 (`Default` active,
`OracleAlt` with comment `oracle alt config`). Corpus: the tree and KeyWords
name the same configurations in 3,341 of 3,341 files; the active configuration
equals the most-recent flag in 3,340 of 3,341 (1 third-party file). 119 files
have no configuration carrier, including all 26 drawings. VERIFIED.

- Configuration names come only from the tree and KeyWords. MATERIALTREE can
  name configurations that neither lists (in 8 legacy version-4400 parts, a
  lower-case variant of an existing name or a name absent from KeyWords), so
  SolidSeas uses it only to attach materials, and uses its names only when a
  file has no tree and no KeyWords.
- A file can carry the English `SW-Configuration Name` and a localised copy
  with different values (1 legacy file, where the English one is stale).
  SolidSeas then takes the value that the tree marks as most recently used.
- In drawings `SW-Configuration Name` holds the save date (the same text as
  `SW-Long Date`), not a configuration, in 22 of the 22 corpus drawings that
  store it and in fixtures o18 and o19 (the date in long form). VERIFIED.
  Drawings therefore have no active configuration, and SolidSeas reports none.

### 11.5 Material

The material per configuration is the KeyWords `Material` attribute, unless
that attribute is missing or holds the localised placeholder (`Material <not
specified>` in English); then the configuration's entry in MATERIALTREE's
`configurationslist` is used. `swXmlContents/MATERIALTREE` (UTF-16 XML) adds
the database, material id, property definitions (density and so on) and that
configuration map, whose values are `DB|name|id` or just `DB|name` (no id in 19
of 27 holdout files). With no material assigned, KeyWords holds the placeholder
and MATERIALTREE has no entry; SolidSeas then reports no material, and it never
reports a placeholder as a material. VERIFIED on fixtures (o05 and o06: `1060
Alloy` from `SOLIDWORKS Materials`; o02 and o04: none) and in the corpus: in 6
of 212 files with MATERIALTREE, KeyWords lacks the material (5) or holds the
placeholder while MATERIALTREE names one (1).

### 11.6 Units

`ISolidWorksInformation` holds `SW_UnitSystem`, `SW_UnitsLinear`,
`SW_UnitsAngular`, `SW_UnitsMassPropMass` and about 25 more, as the public API
enumerations: system 1 CGS, 2 MKS, 3 IPS, 4 custom, 5 MMGS; length 0 mm, 1 cm,
2 m, 3 in; mass 1 mg, 2 g, 3 kg, 4 lb. VERIFIED on the fixtures (MMGS, mm, g;
the two drawings, made from `ansi.drwdot`, IPS, in, lb, the system SOLIDWORKS
reported for them) and in the corpus (in 820 of 820 non-custom files the system implies the
expected length and mass units). The other enum names are a HYPOTHESIS from the
API documentation. Units are UNKNOWN for all legacy files and for 1,220 modern
files without these properties: the binary units objects in `Contents/Config-0`
are not decoded. The fixtures cannot decode them: all 19 state their units in
`ISolidWorksInformation` (the 17 parts and assemblies MMGS, the 2 drawings IPS),
so none is a file whose units are unknown, and every part shares one system, so
no byte of `Config-0` can be told to follow the units. VERIFIED (19 fixtures).
Section 16 item 8 (one part saved in IPS, CGS, MKS and MMGS, nothing else
changed), the same part saved as SOLIDWORKS 2014 or earlier for the legacy
layout, and a part saved with a custom system whose length and mass units differ
from every standard one would let the units objects be found by comparison.

### 11.7 Title, author and dates

- `docProps/core.xml` accumulates one (lastModifiedBy, created, modified) group
  per earlier save, in no reliable order: the newest `modified` is the last save;
  `created` = 1601-01-01 means unset. VERIFIED.
- Legacy files use `\x05SummaryInformation` (title, author, last author,
  FILETIME dates).
- `ISolidWorksInformation` adds `SW-Title`, `SW-Author`, `SW-Last Saved By`,
  `SW-Created Date` and `SW-Last Saved Date` as local-time text in the saving
  machine's locale, and `SW-File Name` and `SW-Folder Name` (section 13).
  Localised names such as `SW-Autor(Author)` usually carry the English name in
  parentheses. One Russian-locale assembly also has a localised name without
  it, beside English-suffixed duplicates.
- The last-saved user agrees between core.xml or SummaryInformation and
  ISolidWorksInformation in 3,400 of 3,407 files. VERIFIED.
- `swCreationTime` in the XML tree (Unix time) is the creation time; core.xml
  `created` follows it by 0 to 120 s in 2,251 of 2,265 files. VERIFIED.
- A part or an assembly stores its own creation time in three places, which
  always agree: element 0 of `ModelStamps` (a u32), its own `swFile` entry's
  `swCreationTime` (the `swFile` whose `swModel` is a configuration of the
  document, in `swXmlContents/Features` for a part and `COMPINSTANCETREE` for an
  assembly) and the `id` attribute of the `swXmlContents/KeyWords` root. Of the
  3,501 readable corpus files, `ModelStamps` holds a non-zero value in 3,409,
  the own tree entry in 3,341 and KeyWords in 3,408; `ModelStamps` equals the
  tree value in 3,341 of 3,341, KeyWords equals it in 3,341 of 3,341, and
  `ModelStamps` equals KeyWords in 3,408 of 3,408. `ModelStamps` gives a value
  for 68 of the 160 files without a tree value (the 26 drawings among them); 92
  files (91 parts and 1 assembly) carry none. VERIFIED. `ModelStamps` is within
  a day of core.xml `created` in 1,973 of 1,986 corpus parts and 319 of 321
  assemblies that have both.
- **A drawing carries its template's identity, not its own creation time.** In
  a drawing, `ModelStamps` element 0 and the KeyWords root `id` hold the values
  the drawing template it was made from stores in the same places: fixtures o18
  and o19, made from the shipped `ansi.drwdot` on 2026-10-01, both store
  1196966037 (2007-12-06T18:33:57Z), which is what that template file stores
  (read once from the installed template, read-only; it is the file whose
  SHA-256 `ground_truth.json` records), while its file time is the
  installation's, 2024-01-17. VERIFIED on that one template: `ground_truth.json`
  does not record the identity a template stores, so the tests pin 1196966037
  only for that template; for any other they check only that drawings from one
  template share a value that is not their own creation time. An earlier
  generation, made from a template saved in the generating account, carried
  2024-03-30, equal to that template's file time, which is consistent with the
  same rule; that template's stored identity was never read. On the corpus
  `ModelStamps` is within a day of core.xml `created` in 0 of 26 drawings (25
  are older by more than 30 days), and the 26 drawings hold only 8 distinct
  values; 23 share theirs with another drawing (the largest group is 9).
  VERIFIED (corpus counts).
  A drawing's identity therefore marks its template lineage: every drawing made
  from one template has the same one. Nothing resolves a drawing as a candidate
  today; anything that would must not read this value as the drawing's creation
  time.
- Save As keeps the creation time: fixtures o03 to o06 carry o02's value. It
  identifies a lineage (a document and its Save As or Explorer copies), not one
  file. VERIFIED (5 fixtures). A document that references another stores the
  referenced file's creation time too (section 12), which is how SolidSeas tells
  a moved file from an unrelated one with the same name.

## 12. Assembly references

### 12.1 `swXmlContents/COMPINSTANCETREE`

UTF-8 XML in the swSolidWorks schema (legacy: `__ZLB`), holding the whole
component hierarchy:

- `swFile`: id, `swPath` (absolute path at save time), `swDocType` (for example
  `PART`), `swCreationTime`;
- `swModel`: a document in one configuration, with `swFileRef` and
  `swBoundingBox`, and on some the configuration's alternate name
  `swConfigurationAlternateName` (12.7);
- `swReference`, one per instance under its parent `swModel`: `swName`,
  `swReferenceNumber`, `swModelRef`, `swConfigurationName`, `swSuppressed`,
  `swHidden`, `swExcludeFromBOM`, `swIsVirtualComponent` and `swTransform`, 16
  numbers in metres.

VERIFIED: present in 324 of 325 assemblies; 4,791 referenced files and 8,688
instances. On fixture o08 it names `o02_boxA.SLDPRT` with instances
`o02_boxA-1` and `o02_boxA-2`, and the translations (elements 12 to 14 of
`swTransform`) differ by exactly +0.05 m in X, as placed through the API.

**Virtual counts.** 744 instances (`swReference` elements with
`swIsVirtualComponent` = `YES`) use 640 distinct virtual files (`swFile`
entries) in 60 assemblies. "640" counts files and "744" instances; an earlier
figure of 640 "virtual references" meant the files. VERIFIED (325 assemblies).
Section 12.4 says where those files are stored.

**`swTransform`.** Elements 0 to 2, 4 to 6 and 8 to 10 are the images of the
component's X, Y and Z axes in the parent's frame, so they are the columns of
the rotation R in `p_parent = R p + t`; elements 12 to 14 are t in metres;
element 15 is a scale; elements 3, 7 and 11 are zero. Read as a 4 x 4 matrix
stored row by row, it is the row-vector form `p_parent = p M`. The numbers are
those of SOLIDWORKS' `IMathTransform.ArrayData` with zeros inserted at 3, 7 and
11. Each transform is relative to the parent instance: composing it with the
parents' transforms gives the top-level placement that `Component2.Transform2`
reports. VERIFIED on fixtures o08, o15 and o16 (o08's rotations are identity),
against the `ArrayData` SOLIDWORKS reported for all 30 component placements in
their configurations, to 6e-17: a part turned 90 degrees about X, one turned
+90 degrees about Z and placed at (0.1, 0, 0) m (o16's `o02_boxA-2`, stored
`0 1 0 0 -1 0 0 0 0 0 1 0 0.1 0 0 1`, X axis to (0, 1, 0), Y axis to
(-1, 0, 0); the transposed reading would swap them), a sub-assembly turned 40
degrees about (1, 1, 1), and the parts inside it, which store the same
transforms as in the sub-assembly's own file. The suppressed, excluded-from-BOM
and virtual flags equal what SOLIDWORKS reported for every instance of those
fixtures. On the corpus all 8,688 stored transforms are proper rotations with
elements 3, 7 and 11 zero and element 15 equal to 1. VERIFIED. No file has a
scale other than 1, so how SOLIDWORKS would apply one is UNKNOWN.
`tests/test_ground_truth.py` and `tests/test_components_ground_truth.py` repeat
the fixture check on every test run.

**`swBoundingBox` of a component's model** is six numbers, the low corner then
the high corner, in metres and in that component's own coordinates (the
assembly's own models hold a configuration's box, section 12.3). On fixtures
o08 and o16 the model of o02 holds the box of o02's own display mesh to
1e-6 m, and o15's model in o16 holds o15's own box. Placed with each
instance's composed transform, every part model's box gives the box SOLIDWORKS
reported for that instance (`Component2.GetBox`) to 1e-6 m, for every part
instance of o08, o15 and o16 in their four configurations (parts turned 90
degrees, and the parts inside the sub-assembly turned 40 degrees about
(1, 1, 1)), and o15's gives SOLIDWORKS' box of the sub-assembly. VERIFIED
(fixtures; `tests/test_geometry_subassemblies.py` repeats it). On the corpus,
of the 5,384 placed instances whose model stores a box (8 store none), the
instance's mesh has that box to 1% of its diagonal in 4,729: in 4,586 of the
5,008 drawn from the assembly's own meshes, and in 143 of the 376 drawn from
part files, which often changed after the assembly was saved (section 12.3).
Where a section's box differs from it, the section's box lies inside the
stored one in all 113 files counted in 12.3. VERIFIED as measurements;
what a model's box takes in beyond the display mesh is UNKNOWN. SolidSeas
reports it, placed, as a placeholder for an instance it cannot draw
(`docs/API.md` 3.14).

**`swHidden`** is `YES` on every suppressed instance (402 of 402 on the corpus),
whatever SOLIDWORKS shows, so the flag means "hidden or suppressed". VERIFIED.
Each `swConfiguration` may also store a display state:
`swDisplayStateList/@swCompNameList` lists the `swID` of each top-level
instance (ids restart inside each sub-assembly) and
`swDisplayState/@swShowState` says `Yes` or `No` for each, in the same order.

What the fixtures settle is narrow: o16 stores `swHidden` = `YES` for its
suppressed instances (`o07_boxB_h31-1` in both configurations, `o15_sub_asm-1`
in `Lite`), and SOLIDWORKS reports them visible, both in `Default`, whose
display state says `Yes` for `o07_boxB_h31-1`, and in `Lite`, which stores no
display state at all. VERIFIED (fixture o16). The fixtures cannot test more:
SOLIDWORKS reports every instance of o08, o15 and o16 visible in every
configuration, so neither way an instance becomes hidden has been compared with
it, and the plain rule "`swHidden` and not suppressed" explains the fixtures as
well as the display state does.

SolidSeas takes the display state for a top-level part instance it lists, and
otherwise, for a sub-assembly instance as well, reports an instance hidden
when `swHidden` is `YES` and it is not suppressed. That the display state
decides for a part, and that `swHidden` hides an unsuppressed instance, are a
HYPOTHESIS. On the corpus the rule decides real cases (every stored
configuration of the 328 corpus assemblies, counted on 2026-10-02): 205
unsuppressed top-level instances are hidden (12 of them sub-assemblies, by
`swHidden`), 76 unsuppressed instances inside sub-assemblies (which no display
state lists) by `swHidden`, and 15 suppressed ones are hidden. Before
sub-assemblies followed `swHidden` the same count gave 213, 20, 76 and 16. For
unsuppressed top-level instances the display state agrees with the flag in
3,922 of 3,933 (counted on the earlier corpus snapshot of 3,501 readable files;
of the 330 suppressed top-level instances there, the display state listed 284
and showed 268). Where a configuration stores several display states they
never differ on the corpus (6 lists). Section 16 item 17 lists the file that
would settle it.

A sub-assembly's `swShowState` does not say whether SOLIDWORKS shows it. In
every configuration that stores a display state, the corpus has 11
unsuppressed sub-assembly instances whose display state says `No` while
`swHidden` is `NO`, and each of them has an instance inside it that is hidden
or suppressed; the reverse does not hold (24 with something hidden inside say
`Yes`), and 3 unsuppressed sub-assembly instances say `Yes` while `swHidden`
is `YES`. The box SOLIDWORKS stores for the active configuration (12.3) leaves
hidden instances out, so it tells which way is right: in the 6 corpus
assemblies where the display state of a sub-assembly (8 instances) or of a part
(1) disagrees with `swHidden` in the active configuration, the union of the
placed component blocks matches the stored box to 0.1 percent of its diagonal
in all 6 when `swHidden` decides for sub-assemblies (3 of them to 0.1 mm), and
in 2 when the display state decides. Letting the display state decide only
when it says `Yes` matches 5 of 6: the miss is a sub-assembly that says `Yes`
with `swHidden` `YES`, whose parts lie outside the stored box. So `swHidden`
decides for a sub-assembly. VERIFIED (6 corpus assemblies, against the stored
box). What `swShowState` `No` means for a sub-assembly is UNKNOWN; for a part
the one disagreement does not change the box, so either rule fits it.

An instance whose parent `swModel` is not the assembly itself belongs to a
sub-assembly; SolidSeas marks it `direct=False`. Matching by file name,
direct references are found among the `Header2` paths in 3,187 of 3,199 cases;
the 12 misses (3 files) are components renamed after insertion, whose old names
remain in `Header2`. Matching by full path (case-insensitive) finds 3,050; 137
of the other 149 have the same file name in another folder. VERIFIED.

### 12.2 `Header2`

Starts with `moHeader_c`, then an `su_CStringArray` of user names that usually
ends with the last saver (3,307 of 3,412, HYPOTHESIS for the meaning), and
CStrings with absolute paths of referenced documents. In parts these are mostly
earlier names of the same document (save-as lineage), so SolidSeas does not
report them as references. HYPOTHESIS.

**The reference record.** After each referenced path's CString come an
optional u16 class tag, a CString with the document's name, 3 bytes, and a u32
creation time in Unix seconds (layout read on fixture o08, whose
`Contents/Config-0-ModelHeader` holds the same values at the same offsets). In
assemblies the creation time equals the component tree's `swCreationTime` for
the same path in 3,426 of the 3,512 records whose path the tree also names;
the other 86, in 53 assemblies, differ by more than a day and equal no file's
creation time in that tree (why is UNKNOWN). VERIFIED with those 86
counter-examples. In drawings, which have no tree, this record is the only
place the model's creation time is stored: each of the 20 corpus drawing models
that reference resolution finds on disk carries the creation time its drawing
stores (the other 6 are not found). VERIFIED (20). The fields after the
creation time are a HYPOTHESIS and are not read.

### 12.3 Assembly tessellation

An assembly stores a display mesh of its components, in each component's own
coordinates, in one of two places. Neither is an assembled model: each mesh
must be placed with its instance's composed transform (section 12.1).
SolidSeas reads both (`solidseas.geometry`, `docs/API.md` 3.14).

**`FaceTessellations` (SOLIDWORKS 2023 and later).** 113 of the 325 corpus
assemblies (112 saved by 2024, 1 by 2023) and the three fixture assemblies
have `FaceTessellations/Directory` and 1 to 8 streams
`FaceTessellations/<nnn-nnn-nnn>` (1 in 89 of them; 157 streams in all), and
keep no tables in `Contents/DisplayLists`. VERIFIED (116 assemblies).

- **Directory**: u32 2 (113 of 113), u32 the highest stream number (it equals
  the largest `<nnn-nnn-nnn>` named, 113 of 113), u32 n, then n records. A
  record is u32 its number, a CString with the instance's path from the top
  (`o15_sub_asm-1@o16_asm_features/o02_boxA-1@o15_sub_asm`: each instance name
  followed by `@` and the name of the document it sits in, which is the name
  of the assembly when it was made, `Assem1` on o08, not necessarily its file
  name), a u16 (meaning UNKNOWN), 10 zero bytes (1,972 of 1,972), 8 bytes
  *shares*, 8 bytes its own id, a CString naming the stream that holds its own
  block (empty when it has none), an i32 block number (-1 when none), a u32 k
  and k triples of u32 (k is 0 to 216; meaning UNKNOWN). All 113 directories
  parse to their last byte. VERIFIED as a parse; the field meanings are a
  HYPOTHESIS.
- **Which records**: one per instance of the configuration active at save,
  most suppressed ones included (116 of 132 suppressed part instances have a
  record, 41 of them a mesh), and records for component pattern features (no
  mesh). 1,869 of the 1,972 corpus records name an instance of the active
  configuration, and a sub-assembly instance has a record in 4 of 90 cases and
  never a mesh. VERIFIED (1,972 records). o16 has no record numbered 5; that
  the missing number was its sub-assembly's is a HYPOTHESIS. Of the active
  configuration's part instances shown (neither they nor a parent suppressed
  or hidden, as `display_geometry` counts them), 1,255 have a mesh, 18 no
  record and 3 a record without one; counting only each instance's own hidden
  flag, 1,582, 18 and 3. VERIFIED (113 assemblies).
- **Blocks**: a stream holds the blocks of its records back to back, from
  offset 0 in block order: 156 of the 157 streams, every one a record names
  (one more stream, in one assembly, is named by no record). A block starts
  with u32 its number, the record's 8-byte id and u32 a face count, and holds
  the face tables of section 9. Each of the 981 records with a block of its own
  has it at the expected place, and the block's table count equals its face
  count in 970. VERIFIED (981 blocks in 156 streams).
- **Sharing**: a record without a block of its own names in *shares* the id
  of the record whose block it uses; all 821 such ids name a record of the same
  directory. Instances of one file in one configuration share a block, across
  sub-assemblies too (o16's `o07_boxB_h31-2` uses the block of the o07 inside
  `o15_sub_asm-1`). VERIFIED (821 shares; 3 fixture assemblies).
- **Coordinates**: the component's own. On o08, o15 and o16, every instance's
  block placed with its composed transform has the box SOLIDWORKS reported for
  it (`Component2.GetBox`) to 1e-6 m, in both configurations of o16 (rotations
  of 90 degrees about X and about Z, a sub-assembly turned 40 degrees about
  (1, 1, 1) and the parts inside it), and o08's block is o02's own display mesh
  triangle for triangle. VERIFIED (3 fixture assemblies, 4 configurations). On
  the corpus, for the 106 assemblies whose every shown part instance has a
  block, the union of the placed blocks lies inside the stored `swBoundingBox`
  of the active configuration (to 1e-6 of its diagonal) in 99; built as
  SOLIDWORKS builds an assembly's box (a sub-assembly's own box carried into
  the top frame) it is within 0.1 mm of the stored box in 68, within 0.1% of
  its diagonal in 76 and within 1% in 99. Hidden instances are left out of the
  stored box: counting them, the union lies inside it in only 78. VERIFIED (106
  assemblies) as measurements; that curved faces tessellate inside their exact
  surface, and so inside the stored box, is a HYPOTHESIS.
- **Against the part files**: of 872 corpus instances whose part file
  reference resolution found with a mesh of its own, the block has the same box
  in 676 and as many triangles in 387. VERIFIED (872 instances) as counts; why
  the others differ (the part changed after the assembly was saved, another
  tessellation quality, or another configuration) is UNKNOWN: the causes were
  not told apart.
- **Configuration**: one record per instance means one mesh per instance, so
  the blocks describe one configuration, taken to be the one active at save.
  HYPOTHESIS: the fixtures cannot tell, and the 3 corpus assemblies with
  blocks and more than one configuration match their active configuration as
  well as another. SolidSeas uses a block for another configuration only where
  that configuration has the same file in the same configuration at every level
  down to the instance.

**Older assemblies: sections of `Contents/DisplayLists`.** Of the 212 corpus
assemblies without `FaceTessellations`, 179 have face tables in their own
`Contents/DisplayLists` (23 have the stream without tables, 10 none). These
are their components' meshes, a section per component file: a header that
holds, among other CStrings, the file's stored path (as the component tree
stores it, compared case-insensitively), then that file's face tables in its
own coordinates. HYPOTHESIS from the corpus alone (no fixture has this
layout):

- 2,140 of the 2,571 part files these assemblies reference have a section, and
  sections follow the order of the files in the component tree in 174 of the
  179 assemblies.
- A section runs from its file's path to the next stored path of any file the
  tree names: a sub-assembly, a part used in several configurations or a path
  two files share ends it as well as the next file used. Counting only the
  paths of the files SolidSeas uses would let 75 of the sections it uses on the
  corpus run on into the next file's tables (20,722 triangles in all).
  SolidSeas ends sections at the path of every file the component tree names,
  in any configuration, the assembly's own excepted; counting only the files
  of the configuration shown instead changes no section on the corpus.
- Some headers name a file of the tree under another folder, where it was when
  that section was written: 3 sections used on the corpus held such a path,
  with tables after it (251, 1,812 and 80), always of another file of the tree
  (the same file name, 19, 3 and 4 such files), never the section's own. None
  of the tables after it equals a table of the section's own part file, while
  13,888 of the 21,382 before it do. SolidSeas ends a section at a path that
  names a file of the tree by its file name in another folder, unless that is
  the section's own file; the tables after it go to no file. That changes 2
  drawn instances on the corpus, from 25,580 triangles to 21,382 and from
  22,069 to 11,779, and the gap between their sections' boxes and the boxes
  stored for their models from 8.6% and 47.9% of the diagonal to 0.0% and
  1.2%. VERIFIED as measurements; why SOLIDWORKS keeps such a header is
  UNKNOWN.
- Of the 225,258 tables in those sections that equal a face table of a part
  file reference resolution found, 224,930 equal one of the section's own file
  (328, 0.15%, another file's). Of the 548 files with a section used and a mesh
  of their own, the section is the file's own mesh exactly in 349 and for at
  least 90% of its tables in 416; the others differ as the blocks above do.
- A path can open several sections. Of the 2,250 part files SolidSeas may take
  a section for (a part the tree uses in one configuration, under a path no
  other file has; counted once per assembly, on the 328-assembly corpus), the
  path opens one section for 2,065 (96 of them without tables) and several for
  185. Of those 185, exactly one section holds face tables in 154 and none in
  31; two or more never do. The others are the path written again with no
  tables after it. Why SOLIDWORKS writes it again is UNKNOWN. SolidSeas takes
  the one section with tables (it refuses a file with two), and that places
  1,377 instances that a single-section rule left to the part files or skipped:
  597 inside sub-assemblies and 224 at the top level that were skipped, and 556
  that came from part files (552) or from virtual components stored inside the
  assembly (4).
- Against the part files: 552 of those 1,377 instances have a part file with a
  mesh of its own. Where that file still has the box the assembly stores for
  its model (`swBoundingBox`, 12.1; 342 instances), the section is the file's
  mesh exactly (as many triangles, the same box to 1e-6 of its diagonal) in
  304, and has its box to 1% in all 342 (the other 38 differ in the box by
  more than 1e-6 or in the triangle count). In 203 the part file no longer has
  that box, having changed after the assembly was saved: the section has it in
  184 and neither does in 19; the other 7 store no box. In no instance does
  the file have the stored box and the section not. Per file, the sections
  taken among several have their part file's triangle count in 40 of 49 and
  its box to 1% in 45, against 376 and 466 of 517 for files with one section.
  Against the stored model box alone, a section taken among several has it to
  1% in 1,227 of 1,370 instances (140 of 149 files), a single section in 2,222
  of 2,355 (1,807 of 1,911 files); where not, the section's box lies inside
  the stored one (9 of 9 files and 104 of 104). VERIFIED as measurements.
- Placed with their instances' transforms, the sections of the 122 assemblies
  whose every shown part has one used give a box inside the stored box (to
  1e-6 of its diagonal) in 119, reaching within 0.1% of its diagonal of every
  side of it in 61 and within 1% in 83 (92, 90, 48 and 67 with one section a
  file, on the 325-assembly corpus). Of the 13 older assemblies whose every
  shown part is placed now and was not with one section a file, the union lies
  inside the stored box in 12; in the thirteenth, the four instances placed now
  lie inside it, and the three that do not come from single sections placed
  before as well.
- These counts are VERIFIED as measurements of the layout above: the first
  three items (but the last sentence of the second) on the 179 older
  assemblies with tables of the 325-assembly corpus, the others on the 213
  older assemblies of the 328-assembly corpus. The header's layout, the 14% of
  tables that lie before the first section, and which configuration a section
  shows when the tree uses the file in more than one are UNKNOWN; SolidSeas
  uses a section only for a file that the tree uses in one configuration, and
  of several sections only the one with tables.

These tables are why the earlier reading found that an older assembly's
display tables match its bounding box in only 10 of 179 files: they were never
placed.

**A sub-assembly's own meshes.** A sub-assembly's file keeps meshes of its own
components in the same two layouts, in their own coordinates, for its active
configuration. SolidSeas uses them for an instance the top assembly holds no
mesh of, by the same rules: the record of the instance's path below the
sub-assembly, or the section of its file, where the sub-assembly's active
configuration has the same files in the same configurations down to the
instance (`docs/API.md` 3.14). On the fixtures, o15's own blocks placed through
o16's transforms give SOLIDWORKS' boxes of o15's two parts inside o16, and
o16's give them when o16 is itself a sub-assembly. VERIFIED (2 fixture assemblies). On the
corpus they add little: alone they place 564 instances inside sub-assemblies
(338 from `FaceTessellations`, 226 from sections); the top assembly's own
meshes hold 563 of them as well, and the part file of the other is found.
SolidSeas tries them after the part's own file. Of the 671 instances inside
sub-assemblies still skipped, all in older assemblies, the sub-assemblies above
them store no display lists for 283, have no section for the file in 289 and
an empty one in 48, and are not found in 51. VERIFIED as measurements.

**`swBoundingBox` of a configuration** is the box of the configuration active
at save, for the others possibly a stale copy: o16 stores for `Lite` the box of
`Default`, while SOLIDWORKS reports `Lite`'s own, smaller box (the turned
sub-assembly is suppressed there). VERIFIED (1 fixture).

### 12.4 Virtual and imported components

Nested documents (section 2.10) open like any other document. Counts below are
over the 325 corpus assemblies; "opens" means it opens as a document of the
type the tree stores, and "identity" that it carries the creation time the tree
stores for that file (section 11.7).

**Virtual files the assembly uses directly** (129 of the 640, in 55
assemblies) are stored in the assembly as the nested document
`VirtualComp/<stored file name before the caret>` (120), or that name followed
by `-` and the extension without its dot (5; fixture o16, saved by
SOLIDWORKS 2024 SP1, stores `Part12^o16_asm_features.SLDPRT` as
`VirtualComp/Part12-sldprt`). All 125 open and match identity. VERIFIED (125
of 129); the other 4 have no such stream, UNKNOWN why. Counting these direct
files, an assembly's virtual files equal its `VirtualComp` documents in 54 of
55 assemblies.

**Virtual files used only inside sub-assemblies** (511 of the 640, in 30
assemblies) are stored in that sub-assembly's own file, not in the top
assembly. For each one, the sub-assembly that uses it was opened (a nested
document of the top assembly, or the file reference resolution found on disk)
and its own direct virtual files mapped as above: 445 of the 446 whose
sub-assembly could be opened are a nested document there, 1 is not, and 65
could not be checked because their sub-assembly was not found. VERIFIED (445,
with 1 counter-example). This is why counting every virtual file against the
`VirtualComp` documents agrees in only 29 of 60 assemblies.

**Imported components** carry `swImportedPath`, the file they were made from:
555 referenced files in 54 assemblies (142 direct, 9 also virtual). The
assembly holds 300 `ImportedComp/` nested documents in 27 assemblies. For 239
of the 555 the stream `ImportedComp/<stored file name>` exists (the whole name,
extension included; the name without its extension matches none), and all 239
open and match identity. VERIFIED (239). Of the 308 others that are not virtual,
reference resolution finds 228 as ordinary files on disk (169 at the stored
path, 59 moved) and not the other 80, so an imported component without that
stream is an ordinary file: VERIFIED for those 228, HYPOTHESIS for the 80. What
the at least 61 `ImportedComp/` documents that no imported file names hold is
UNKNOWN.

**A caret is not a virtual marker.** All 640 virtual files have a `^` in their
stored name, but so do 244 files in 13 assemblies that are not virtual:
reference resolution finds 183 of them on disk, 45 are imported components
stored as nested documents, and 16 are not found. VERIFIED. Only
`swIsVirtualComponent` says a file is virtual.

### 12.5 Drawings

Drawings have no tree. SolidSeas reports their `Header2` model paths (except
drawing paths) as references, with no direct or indirect distinction.
HYPOTHESIS (26 of 26 corpus drawings yield one path; on fixtures o18 and o19,
drawings of a part and of an assembly, the paths name exactly the models
SOLIDWORKS reports for their one view each).

Their sheets are the names in `SheetPreviews/SheetNames`, which agree with the
sheet count the drawing stores in 22 of 22 corpus drawings that store one.
Each sheet's views come from `swXmlContents/KeyWords`: the view name, the model
configuration it shows (the `View` element's `Description`) and the model's
file name. The sheet names, view names and referenced documents are VERIFIED on
fixtures o18 and o19, as SOLIDWORKS reported them. The view's configuration is
a HYPOTHESIS: every view on the fixtures shows `Default`, the model's active
and first configuration (o16, which o19 shows, also has `Lite`, which no view
shows), and every one of the 42 corpus views (of 57) whose model reference
resolution finds shows a configuration named `Default` of a model that has no
other, so a constant would match as well; it is consistent, not
discriminating. Every corpus drawing has one sheet and one model, so drawings
with more of either are UNKNOWN.

### 12.6 Exploded views

SOLIDWORKS keeps an assembly's exploded views with its configurations, each a
list of explode steps (the components moved, a direction and a distance). Where
a file keeps them was looked for in the fixtures, whole, and in the corpus by
names only:

- Every fixture part and assembly stores an explode view manager in its binary
  configuration stream: one object of class `moExplViewManager_c` in
  `Contents/Config-0` of each of the three assemblies (o16, with two
  configurations, has only that one configuration stream), and one of class
  `moPrtExplViewManager_c` in each `Contents/Config-<n>` of the 14 parts (both
  of o13's). Their `swXmlContents/KeyWords` list a feature of type `Exploded
  Views` with an empty name, the folder SOLIDWORKS shows exploded views in. No
  fixture has an exploded view (the fixture kit made none), so these are empty
  containers. VERIFIED (17 fixtures). No other stream name, XML element or
  XML attribute of the fixtures mentions an explode; the UTF-16 name
  `Explodelines` in `Contents/Definition` and `Contents/DisplayLists` of every
  fixture, drawings included, sits among line-style names (`HIDDEN`,
  `CONTINUOUS`, `PHANTOM`) and is taken to be one. HYPOTHESIS.
- No stream name of the 325 corpus assemblies, and no element or attribute
  name in their 2,587 XML streams (66 distinct element names, 65 attribute
  names), mentions an explode. VERIFIED (325 assemblies; names were compared,
  and only counts kept).

So the steps of an exploded view, where an assembly has one, are taken to be
serialised under that manager in `Contents/Config-<n>`. HYPOTHESIS. Their
layout is UNKNOWN, and since the corpus was searched by names only, so is how
many corpus assemblies have one. SolidSeas reads no explode step. The viewer's
exploded view is its own, made from the placements of section 12.1 and only
drawn (`solidseas_app.viewer.explode`). Section 16 item 19 is the file that
would settle it.

### 12.7 What feeds a bill of materials

SOLIDWORKS builds a BOM table from the component tree and from each
component's own document. Fixture o19 holds two BOM tables SOLIDWORKS made of
o16's configuration `Default` with the default template (`ITEM NO.`, `PART
NUMBER`, `DESCRIPTION`, `QTY.`): top-level only (BOM type 2) and indented
(type 3), recorded cell by cell when they were made and again after the drawing
was reopened, identical both times. `solidseas.bom` (`docs/API.md` 3.16)
rebuilds both from the files alone, cell for cell; `tests/test_bom.py` checks
all four records on every run.

- **Which instances are rows.** An instance counts when neither it nor a
  sub-assembly above it is suppressed (`swSuppressed`) or excluded from the BOM
  (`swExcludeFromBOM`), as `instances_in_bom` already counts (12.1). On o19
  the excluded `o02_boxA-3` and the suppressed `o07_boxB_h31-1` are in neither
  table, and the quantities are those counts: o02 2 at the top and 3 over every
  level, o07 3 at the top. VERIFIED (2 tables, 16 rows). No fixture excludes a
  sub-assembly; that its components go with it is SOLIDWORKS' documented
  behaviour and a HYPOTHESIS here.
- **Grouping and order.** The instances under one parent that use one file in
  one configuration are one row, at the place of the first one the tree
  stores. o16 stores the two instances its linear component pattern made after
  every other instance (`o07_boxB_h31-3` and `-4`, after the virtual part), and
  both tables count them in o07's row 4, after o15 and before o09, where
  `o07_boxB_h31-2` is stored. VERIFIED (the 7 rows of the top-level table and
  the 9 of the indented one, in order, recorded twice). That the stored order
  follows the FeatureManager order when components are reordered, and that one
  part used in two configurations gives two rows (SOLIDWORKS' default "display
  configurations of the same part as separate items"), are a HYPOTHESIS: no
  fixture has either.
- **One component list per sub-assembly configuration.** The tree holds one
  `swModel` per file and configuration, so every instance of a sub-assembly in
  one configuration lists the same components, and an indented BOM can show
  them once under the sub-assembly's row. VERIFIED on the development corpus:
  in the active configuration of all 325 assemblies, the instances of each
  sub-assembly file and configuration list the same components in the BOM (no
  indented row gets the note below). A tree that breaks this (two models of
  one file and configuration, which only a damaged or crafted file has) gets
  every instance's components under the row and the note `bom_children_differ`
  (`docs/API.md` 3.16).
- **Item numbers.** 1, 2... in that order; in the indented table the
  components of item 3 (o15) are 3.1 and 3.2, in o15's own stored order, with
  their quantities in one o15 (1 each). VERIFIED (o19). Whether QTY. in an
  indented table is per parent or for the whole assembly cannot be told from
  o19, whose only sub-assembly is used once; per parent is SOLIDWORKS'
  documented default and a HYPOTHESIS here.
- **PART NUMBER** is the document name, the file name without its extension:
  `Part12^o16_asm_features` for the virtual part (its `swPath` file name),
  `o17_деталь` for the Cyrillic one. VERIFIED (all 16 rows of the two tables,
  recorded twice: 7 distinct documents). Two of the files have custom
  properties that look like part numbers and do not feed the column: o06's
  `PartNo` (`ORACLE-PN-123`) and o09's `Part Number` (`o02_boxA`, written by
  its STEP import). VERIFIED (2 files).
- **The alternate name.** A configuration can tell SOLIDWORKS to use its
  configuration name or a name typed by the user instead ("Part number
  displayed when used in a bill of materials"; the API's
  `Configuration.AlternateName` and `UseAlternateNameInBOM`). Every fixture
  configuration keeps the default: the API reports an empty alternate name for
  all 20 of them, and the models of o08, o15 and o16 store no alternate name.
  Carrier found: an assembly's `swModel` (a component file in one
  configuration, 12.1) can hold `swConfigurationAlternateName`. On the
  development corpus 82 of the 4,819 component models of the 325 assemblies
  hold a non-empty one, in 30 assemblies; it equals the model's
  `swConfigurationName` in 82 of 82 and its document name in none. VERIFIED
  (counts). Bit 0 of `swConfigurationFlags` is set on all 82 and on 107 of the
  4,737 models without one (143 store no flags); whether it records the
  choice is UNKNOWN. That SOLIDWORKS' table shows the stored name for such a
  configuration is a HYPOTHESIS, and where the choice to show it is stored is
  UNKNOWN: no fixture has an alternate name, and SOLIDWORKS was not asked about
  a corpus file. `solidseas.bom` therefore keeps the document name, carries
  the stored name as `alternate_name`, and notes the row
  (`bom_part_number_may_differ`, `docs/API.md` 3.16).
- **DESCRIPTION** is the custom property `Description` of the component's own
  document in the configuration the instance uses, the configuration's own
  property before the file's (names compared case-insensitively). o06 is used
  in its configuration `OracleAlt`, which has no `Description` of its own, and
  both tables show the file's `Oracle test box`; the other six documents (6 of
  the top-level rows, 8 of the indented ones) have no `Description` and show
  nothing. VERIFIED (all 16 rows, recorded twice). That a
  configuration's own `Description` wins is a HYPOTHESIS (no fixture has one),
  as is whether a configuration description marked "use in bill of materials"
  replaces it (UNKNOWN where that mark is stored).
- **Virtual parts** feed the columns from their nested document
  (`VirtualComp/Part12-sldprt`, 12.4): row 7 shows its document name and its
  (empty) description. VERIFIED (o19).
- **Indentation.** SOLIDWORKS' text of an indented table's PART NUMBER cell
  starts with two spaces at level 1 (`"  o02_boxA"`). VERIFIED (2 cells). Four
  spaces at level 2, and whether DESCRIPTION is indented too (both o15 rows are
  empty there), are a HYPOTHESIS.
- **Parts only.** o19 has no parts-only table, so every rule of this type is a
  HYPOTHESIS (0 SOLIDWORKS tables compared; item 20 of section 16 would
  settle them). The rules `solidseas.bom` follows: every part at every level,
  with sub-assemblies left out; one row per file and configuration across the
  whole assembly, in the order the tree lists their first instances, depth
  first; QTY. the count in the whole assembly; item numbers 1, 2... in that
  order. A sub-assembly whose own document lists no component is left out as
  no part. One whose components the tree does not list is kept as a row of
  its own, so that what it stands for is not lost (`bom_children_missing`);
  what SOLIDWORKS shows there is UNKNOWN.
- **Configuration lookups.** A row's configuration is looked up in its
  document; when the document lists configurations but not that one, its
  file-level properties are used (`bom_configuration_missing`), and when
  SolidSeas finds no configuration in the document at all, the same
  (`bom_configurations_unknown`). On the development corpus 61 indented rows
  are of the second kind, on 59 documents, and none of the first. All 59 are
  in the 2015+ format and name no active configuration either; none holds
  configuration properties SolidSeas could not attach, and none has a
  file-level `Description`, so their empty DESCRIPTION is the file's. VERIFIED
  (counts). Why SolidSeas finds no configuration in them, and what SOLIDWORKS
  shows for a configuration a document lacks, are UNKNOWN.

On the development corpus (every assembly's active configuration, the corpus
tree top as the root, nothing looked up outside it) the three BOM types of all
325 assemblies add up to their trees' instances in the BOM, and 3,660 of the
4,005 indented rows find and read their document: 2,844 files on disk, 348
documents stored in the assembly and 468 stored in a sub-assembly. 82 indented
rows carry an alternate name that may be their part number (81 of them on a
document that was not read), and 247 of the 325 BOMs are complete. VERIFIED
(325 assemblies). Two corpus assemblies use a virtual sub-assembly whose own
document lists no component, which a parts-only BOM leaves out, and one uses a
sub-assembly whose components its tree does not list (`docs/API.md` 3.16).

## 13. Paths stored in documents

SOLIDWORKS writes absolute folder paths of the saving account into every
document, and documents inherit more from the template they were created from.
Anyone who receives a file can read them.

| Where | What | Evidence (whole corpus) |
|---|---|---|
| `_MO_VERSION_<n>/Biography` | one record per save session: version, build date code, three u32, Windows version (platform, major, minor, build), a service-pack CString, a locale id, then UTF-16 paths: the Windows system and Windows folders, a working folder (the Desktop, or a project folder in use), the user's temp folder (twice), the template path, and in later records the document's own path at save | present in 3,501 of 3,501; a temp-folder path in 3,500, a Desktop path in 2,603, another path under a user profile (for example a project folder) in 2,986, a network (UNC) path in 532, a template path in 3,397. The record layout is a HYPOTHESIS (read on the fixtures and 6 corpus files); SolidSeas parses no record of it: the path report reads the stream's CStrings, which hold every path it has on the fixtures, so the layout decides nothing it reports |
| `Biography`, inherited | records copied from the template's own history, with the template authors' temp folders and build-machine drive paths | 2,520 of 3,501 Biography streams name two or more Windows user profiles. On the fixtures made from the two shipped templates (o08, o15 and o16 from the MBD assembly template, o18 and o19 from `ansi.drwdot`), the template contributes records from Dassault's own accounts (3 and 12 profile folders) and build drives, and every such path occurs verbatim in the template file. VERIFIED counts; that the extra profiles come from templates rather than from colleagues who re-saved the file is a HYPOTHESIS except on the fixtures |
| `docProps/ISolidWorksInformation.xml` (legacy: `ISolidWorksInformation`) | `SW-Folder Name` and `SW-File Name` at save | the folder property in 3,153 files; a user-profile path in this stream in 1,911 modern files |
| `Header2`, `swXmlContents/COMPINSTANCETREE`, `SwDocContentMgr/SwDocContentMgrInfo`, `Contents/Config-<n>-ModelHeader`, `Contents/DisplayLists` | absolute paths of referenced documents | user-profile paths in `Header2` of 2,291 files and `Config-<n>-ModelHeader` of 2,046 (see the note below the table); all five carry the component path on fixture o08 |
| `Contents/CMgr`, `Contents/Config-<n>`, `swXmlContents/Features`, `ThirdPtyStore/VisualStates` | paths of appearance files, imported files and other resources | user-profile paths in `CMgr` of 2,201 files and `Features` of 1,918 |

Per-stream counts of user-profile paths depend on what counts as one. The
counts in the table come from the original classifier, whose exact rule was not
recorded. The independent re-check, counting any absolute path under a
`Users` folder, finds more: `Header2` 3,055, `ModelHeader` 2,551, `CMgr` 2,935
and `Features` 2,344. The totals below reproduce exactly under both.

Overall, 3,500 of 3,501 files contain at least one temp, Desktop or user-profile
path, and the user name is part of every such path. VERIFIED (scan of every
stream up to 16 MiB for UTF-16 and ASCII strings that look like absolute Windows
paths; 38 files had larger streams that were not scanned, 37 in the independent
run). Removing these paths
would mean rewriting the file, which SolidSeas does not do;
`Document.path_report()` lists them.

**How they are stored.** `Biography`, `Header2`, `SwDocContentMgrInfo`,
`Config-<n>-ModelHeader` and `DisplayLists` hold paths as MFC Unicode CStrings
(`FF FE FF`, a length, then UTF-16LE; section 4.3). Of the UTF-16 paths a scan
of every stream up to 16 MiB finds on the whole corpus, all but 16 of about
691,000 sit in a CString; on the fixtures all of them do (1,156 of 1,156, and
31 more paths are UTF-8 text). VERIFIED (19 fixtures). Where the 16 corpus paths
outside a CString lie is UNKNOWN: a corpus run that prints their streams and
offsets would settle it. The bytes after a CString are whatever field comes
next: for 38,036 of the 690,896 CStrings that end in a path (5.5%) the next
UTF-16 unit reads as a letter, CJK or Hangul in 37,429 of them, so a reader
must stop at the stored length rather than at the first character a path cannot
hold. `FF FE FF` also occurs inside binary data, where the "string" it starts
holds control characters or a byte-order mark and its length can run over real
CStrings (1 corpus case). The component tree (`swPath`, `swImportedPath`),
`docProps/ISolidWorksInformation.xml` and `swXmlContents/Features` hold paths as
UTF-8 XML text. VERIFIED.

Legacy documents keep the folder at save, and any path a property holds, in
property sets (section 11.2), as 8-bit strings with a u32 byte count and a NUL
in the code page their section declares. On the corpus every non-ASCII path in
them is UTF-8 (code page 65001); the 11 sections in code page 1252 hold none.
Elsewhere, 1,688 runs of 8-bit text start like a path and are not UTF-8: 1,324
in sketch bitmaps (`Contents/SketchBitmap<n>`), 124 in `Contents/DisplayLists`,
103 in partitions, 10 in `Contents/3DExperienceExchange<n>`, 117 in streams of
nested documents and 10 in others. None of them is a counted string holding a
path, and none matches a path the same document stores in UTF-16 under any of
the code pages 1250, 1251, 1252, 437, 850 or 936. VERIFIED. `Document.path_report()` reads a
counted 8-bit string with a byte above ASCII whole when it is not UTF-8 or
when its property set section declares an 8-bit code page (1252 when the
section declares none, as section 11.2 reads it). The section's code page
wins even where the bytes would also be valid UTF-8: MS-OLEPS makes it the
string's own, and the property set reader decodes the string the same way.
Outside a property set such a string is read in cp1252. Any other 8-bit text
is left to the UTF-8 reading, which stops at the first byte UTF-8 does not
allow, so binary noise never runs into a path. That legacy SOLIDWORKS wrote
paths in a code page other than UTF-8 is a HYPOTHESIS the corpus neither shows
nor rules out; the 8-bit reading is tested on synthetic legacy files with
cp1252, cp1251 and cp932 property sets.

Non-ASCII paths are common: 1,028 stored reference paths (entries in `Header2`
and the component trees, nested documents included) contain non-ASCII
characters, and an ASCII-only scan reads none of them whole; it cut 474 paths at their first
non-ASCII character and ran 75 past the end of their CString. VERIFIED.

**A drawing's model, view and sheet.** In a drawing, the
`SW-Config-Model-View-Sheet-List` property of `ISolidWorksInformation` holds the
drawn model's absolute path followed by `@<view>@<sheet>`: `@Drawing View1@Sheet1`
on both fixture drawings. VERIFIED (2 fixtures). `Document.path_report()` gives
the string as stored, tail included, with the role `save_location`, though the
path is the model's and not the drawing's own folder; reporting the model's path
without its tail is an open decision. Drawings with several views, sheets or
models (section 16) would show how the list separates its entries.

**Nested documents.** A virtual or imported component's nested document (section
2.10) carries its own `Biography`, `Header2`, `ISolidWorksInformation` and
`core.xml`, and nested documents can hold nested documents of their own. The
parent holds each one compressed, so a byte scan of the parent's streams misses
most of what it holds (section 2.10): in the 70 corpus assemblies that hold
nested documents (681 of them, counted at every depth), 6,362 paths, each
counted once per assembly, are found only by opening the nested documents and
reading them as documents. VERIFIED. `Document.path_report()` reads them that
way, to any depth. `swImportedPath` names the file an imported component was
made from (169 distinct paths). VERIFIED.

**Inherited accounts.** Across the corpus, 26,906 accounts named by paths or
user-name fields, in 2,361 files, appear only in history: save-session paths in
`Biography`, the `Header2` user list or older `core.xml` save records, never in
a current field or another path. On the fixtures every such account is an
author of the shipped template the document was made from;
elsewhere that is a HYPOTHESIS.

Parasolid and STEP files exported by SOLIDWORKS have header fields for the
user and the machine. In the fixtures' exports SOLIDWORKS 2024 SP1 wrote
`USER=unknown` and `MC_ID=unknown` but the processor model in `MC_MODEL`, and
the local save time, in the Parasolid headers, and left the author and
organisation of the STEP header empty. VERIFIED (5 Parasolid exports and 1 STEP export). SolidSeas' own
Parasolid output writes `unknown` in these fields.

## 14. Per-save changes

Saving a document twice without changes (fixtures o02 and o03) gives a new
key, new signatures and new decoys, and changes 6 of 41 members:
`Contents/3DExperienceExchange_ConfigHeader` (a new random GUID),
`Contents/Config-0`, `Contents/Config-0-Partition` (attribute order and node
indices; same length), `_MO_VERSION_17000/Biography` (the saved file name), and
`docProps/ISolidWorksInformation.xml` and `swXmlContents/Features` (they embed
the file name). The other 35 are byte-identical in decoded and stored form.
VERIFIED (2 fixtures, 41 members; the same 6 and 35 in their first generation). Other
pairs: o02 to o04 (properties) changes `CusProps` and `custom.xml` among 10
members in the committed fixtures (also `3DExperienceExchange2` and
`PMISemanticDataDB`), 8 in their first generation and 12 in another
independent generation of the same API steps, which also changed `CMgrHdr2`,
`Config-0-ModelHeader`, `Header2` and `core.xml`, so change counts depend on the
session; o04 to o05 (material) adds `MATERIALTREE`;
o05 to o06 (configuration) adds `docProps/Config-1-Properties.xml` but no
`Config-1-Partition`; o02 to o07 (one dimension) changes 24 members.

## 15. What is not known

1. The time and date fields of the 2015+ container, and whether SOLIDWORKS
   checks them.
2. What bytes 4 to 7 of the 2015+ header mean.
3. How the key slot k is chosen, and how decoy sizes and filler lengths are
   generated.
4. (Settled: SOLIDWORKS 2024 SP1 opens a container written without decoys,
   and one patched in place, with no error or warning;
   `docs/NATIVE_SLDPRT_WRITER.md` section 6.1. The library itself reads only.)
5. The meaning of `internal_attr` and of the two sorted directory runs.
6. Documents over 4 GiB (ZIP64 was never observed; SolidSeas refuses it).
7. Whether extracted Parasolid files with curved faces, and corpus bodies in
   general, load in a Parasolid kernel (the planar fixture bodies do, section
   10.4), and whether multi-body parts should rather be one "array of parts"
   file.
8. The layout of the deltas transmit and of node type 150.
9. Whether local bodies are the final geometry of a part with an empty
   partition (fixture o09 is consistent with it, section 10.6).
10. Whether a partition with `current_id < highest_id` holds a rolled-back state.
11. In `FaceTessellations/Directory` records, the u16 after the instance path
    and the trailing triples; which configuration the stored component meshes
    show; and the header of an older assembly's display-list sections (section
    12.3). (The record layout itself, and the rotation layout of
    `swTransform`, once listed here, are read in sections 12.3 and 12.1.)
12. Per-face colours and appearances, the secondary tessellation block, the
    edge tags and bytes of descriptors 4 and 6.
13. Units of legacy files and of modern files without `SW_Units*` (section 11.6
    says which controlled files would settle it; the fixtures cannot).
14. The meaning of the History u16 fields and date-code flag byte, release
    names below 1500 and from 18000, and service packs other than 2024 SP1.
15. The full Biography record layout and why its first record differs from
    the first History entry in 800 files.
16. `Config-<n>-Cutlist-Properties.xml`, the cut-list containers of
    `CusProps`, and FPVals segment codes.
17. Why 4 of the 129 directly used virtual files have no `VirtualComp`
    document, and what the `ImportedComp` documents that no imported file
    names hold. (Why the virtual-file counts differ from the `VirtualComp`
    document counts, once listed here, is settled in section 12.4: 640 virtual
    files, 744 virtual instances, and 511 of the files stored inside
    sub-assemblies.) The fixtures cannot settle either: o16's one virtual file
    has its `VirtualComp` document, and no fixture holds an `ImportedComp`
    document. VERIFIED (3 fixture assemblies). A corpus run listing, for each of
    the 4 files, its `swPath`, `swIsVirtualComponent` and the nested names the
    assembly does hold, and for each `ImportedComp` document no imported file
    names, its own `Header2`, `ModelHeader` and feature names, would; so would
    section 16 item 3.
18. Feature history, sketches, mates and dimensions: not decoded, beyond the
    feature stream's framing, driving parameters and sketch points
    (section 5.1).
19. The meaning of `swFlexible` and `swComponentReference`, and where a
    component's pattern membership and fixed state are stored (neither is in
    the component tree; fixture o16 has a pattern). On the fixtures
    `swFlexible` is `NO` and `swComponentReference` empty on all 30 instances,
    and none of the 36 attribute names the trees use marks a pattern or a fixed
    component. VERIFIED (3 fixture assemblies). Section 16 item 16 (a flexible
    sub-assembly, a pattern and a fixed component, each made one change at a
    time) would settle them.
20. Why 86 `Header2` reference records store a creation time that matches no
    file in the component tree (section 12.2). On the fixtures every one does
    (11 of 11 records). VERIFIED (3 fixture assemblies). That they name a file
    replaced since the assembly was saved is a HYPOTHESIS; a corpus run giving,
    for each of the 86, whether its path is still in the tree, the tree's
    creation time for that path and the referenced file's own, would test it.
21. Which visibility SOLIDWORKS shows where a configuration's display state and
    `swHidden` disagree (11 corpus instances, section 12.1), and whether either
    hides an instance at all as SolidSeas reads them: the fixtures have no
    hidden instance (the 3 with `swHidden` `YES`, all in o16, are its 3
    suppressed ones). Section 16 item 17 would settle it.
22. Drawings with more than one sheet or model (section 12.5), and whether a
    view's `Description` is the configuration it shows.
23. How an exploded view and its steps are stored: the fixtures hold only
    empty explode view managers, and the corpus was searched by names only
    (section 12.6).
24. Why a part's stored display mesh sometimes shows far more faces than its
    stored partition holds, and what the LIMIT types of an intersection curve's
    chart mean (section 10.8). (Whether SOLIDWORKS marks a body as hidden, once
    listed here, is settled in section 10.9, except for bodies imported without
    the mark.)
25. Where a configuration stores the part number it shows in a bill of
    materials (document name, configuration name or a typed name) and whether
    its description is used there, and how a BOM counts a sub-assembly used
    more than once, groups two configurations of one part and indents deeper
    levels (section 12.7).

## 16. Controlled files that would settle open questions

Each is one more synthetic document made through the API in a separate
SOLIDWORKS instance, like the fixtures.

Six of these items now exist as committed fixtures: item 3 is o16 (with o15 as
its sub-assembly; its component with a Cyrillic file name is o17, and its
imported geometry is the part o09, an ordinary file rather than an
`ImportedComp` document), item 4 is o11 and o12 with their `.x_b` (no loft,
shell or revolve), item 5 is o09 and o10, item 7 is o13, item 9 is o14 (every
property type but a stored double), and item 12 is o18 and o19 (o19 shows o16
rather than o08). Sections 10.1, 10.4, 10.6, 11.1, 11.4, 11.7, 12.1, 12.4,
12.5 and 13 use them, and 12.3 the Directory records. The rest of what they
can settle (body order, CusProps attribution) is not written up yet, so the
items stay listed.

1. One part saved unchanged five times quickly, again after a SOLIDWORKS
   restart and again on another day (key slot, time and date fields).
2. A 2020-era part opened and saved unchanged in SOLIDWORKS 2024 (two-run
   directory, internal attributes, key carry-forward).
3. An assembly with a virtual component, an imported STEP component, a
   component with a Cyrillic name, a sub-assembly, a suppressed and an
   excluded-from-BOM component, and a component rotated 90 degrees about Z
   (nesting, names, `swTransform` rotation layout, Directory records).
4. A part with fillets, a loft, a shell and a revolve, and a multibody part, each
   with SOLIDWORKS' own `.x_b` (geometry beyond planes, body order, array of
   parts).
5. A STEP-imported part saved with no features, and again after one cut
   (LocalBodies as final geometry).
6. A part saved with the rollback bar above the last feature
   (`current_id < highest_id`).
7. A part with two configurations that differ in geometry, both rebuilt before
   saving (`Config-1-Partition`).
8. One part saved as IPS, CGS, MKS and MMGS (legacy and binary units).
9. A part with linked properties (`SW-Mass`, `SW-Material`) and every property
   type (expressions, FPVals, CusProps attribution).
10. A part with face, feature and body colours and a textured appearance
    (per-face colour, the secondary tessellation block).
11. o02 saved as SOLIDWORKS 2023 and 2022 from 2024 (save-as-previous history).
12. A drawing of o02 and of o08 (drawing references).
13. Import SolidSeas' extracted `.x_b` and `.x_t` files of the parts in items 4
    and 5 into a separate SOLIDWORKS instance and compare mass properties with
    the source parts (kernel acceptance beyond planar faces). The fixture
    bodies already pass (section 10.4). Doing this for corpus bodies needs a
    Windows account whose SOLIDWORKS recent-file lists are not the user's,
    because a second instance shares them.
14. A drawing with two sheets, and one showing two different models (sheet and
    model lists beyond one, section 12.5), with a view of a model's non-default
    configuration, such as o16's Lite (whether a view's `Description` is the
    configuration it shows).
15. For reference resolution: a project copied in File Explorer, and the same
    project packed with Pack and Go into one flat folder (stored paths that
    point at the originals, and same-folder references).
16. A component made flexible, a component pattern and a fixed component in
    one assembly (`swFlexible`, `swComponentReference`, and where pattern
    membership and the fixed state are stored).
17. An assembly with a hidden component, a display state that hides an
    unsuppressed component, a suppressed component hidden in its display
    state, and a second display state that differs from the first (how
    `swHidden` and `swShowState` decide what SOLIDWORKS reports as hidden,
    section 12.1). `tests/test_components_ground_truth.py` skips its check that
    the fixtures have a hidden instance until they have one.
18. An assembly with two configurations that use o13 in its two configurations
    (which differ in geometry), saved once with each active, and the same
    assembly saved by SOLIDWORKS 2022 (which configuration `FaceTessellations`
    and an older assembly's display-list sections describe, section 12.3).
19. o16 saved with an exploded view of known steps in each configuration (a
    component moved along X, two moved together along Y, a sub-assembly moved
    along Z, each by a known distance), a second exploded view in `Default`,
    and o12 with an exploded view of its bodies, with SOLIDWORKS' own report of
    each step (how `moExplViewManager_c` and `moPrtExplViewManager_c` hold
    explode steps, section 12.6).
20. An assembly that uses a sub-assembly twice, with a sub-sub-assembly and an
    excluded sub-assembly, one part in two configurations, a configuration
    with its own `Description`, three configurations of one part whose "Part
    number displayed when used in a bill of materials" is Document Name,
    Configuration Name and User Specified Name (with a typed name that differs
    from the configuration's), reordered components, and a drawing with its
    top-level, parts-only and indented BOM tables (what each BOM rule of
    section 12.7 still marked HYPOTHESIS or UNKNOWN does, and which stored
    value records the part number choice).
21. A multibody part with one body hidden, a second configuration in which
    another is hidden, a display state that hides a third, and an imported body
    hidden, with SOLIDWORKS' own STEP of each configuration (the hidden mark of
    section 10.9 beyond the corpus); and a part whose round hole a cross hole
    meets on the line u = 0, a sphere-ended boss and a revolved groove, with
    their STEP (how SOLIDWORKS cuts a face round a closed surface where a hole
    lies on its seam, and on spheres and surfaces of revolution).

## 17. Library coverage on the development corpus

Corpus sweep (`tests/test_corpus.py`, every readable row, 6 worker processes,
Parasolid transmit cap 20 MiB):

| Group | Opened | Preview | Configurations found | Parasolid body (parts) | References (assemblies) |
|---|---|---|---|---|---|
| all | 3,501 of 3,501 | 2,294 (65.5%) | 3,382 (96.6%) | 3,121 of 3,150 (99.1%; 3 over the cap) | 325 of 325 |
| 2015+ | 2,911 of 2,911 | 1,747 (60.0%) | 2,829 (97.2%) | 2,588 of 2,615 (99.0%) | 274 of 274 |
| legacy | 590 of 590 | 547 (92.7%) | 553 (93.7%) | 533 of 535 (99.6%) | 51 of 51 |

By document type: parts open 3,150 of 3,150 (preview 61.9%), assemblies 325 of
325 (preview 97.5%), drawings 26 of 26 (preview 100%; drawings have sheets, not
configurations). Every body returned passed the structural checks (17,151 of
17,151). No source file changed during the sweep, which took 121 s. Without the
cap, 3,124 parts yield a body (section 10.6): the 3 capped parts hold
partitions of 108 to 127 MB, each of which takes minutes and several GiB of
memory to parse in pure Python.

## 18. Prior art

The projects below were evaluated during the analysis. Where a project was
read or run, its claims were checked against the corpus and the fixtures
rather than trusted. Projects marked "not used" contributed nothing to
SolidSeas' code or to this specification.

| Project | Licence | Use in SolidSeas |
|---|---|---|
| [BlinkingSun/sldprt2step](https://github.com/BlinkingSun/sldprt2step) | Apache-2.0 | **Code reused**: the SCH_13006 base node-layout table (`xt_schema.py`), credited in `NOTICE`; the structure of its XT reader was followed. Its XT-to-STEP mapper (commit fa954124) is adapted, modified, in `solidseas/step` (`part21.py`, `entities.py`, `mapper.py`, `bspline.py`, `approx.py`, `blend.py` and `product.py`, each file's header naming what it derives from; credited in `NOTICE`), rewritten over SolidSeas' own transmit reader and evaluators, with every approximation measured and refused above its limit and every body checked before it is written (10.9). Evaluated before that, it reproduced SOLIDWORKS' STEP of the box exactly (the first generation of fixture o02) and accepted 199 of 200 sampled bodies. Corrections found: its legacy reader ignores the mini stream (all 171 small partition streams read wrongly); its multi-chunk ZLB handling is correct (203 of 203 blocks); its mapper writes a lemon torus and a spun surface inside out (10.9), and escapes only apostrophes in strings, where ISO 10303-21 also wants backslashes doubled and characters other than printable ASCII written as `\X2\` or `\X4\`. Differences kept deliberately: SolidSeas takes a face's outer bound from the orientation of its loops (10.8) rather than the largest loop, and writes none on a face whose loops have no outer one (a cylinder's or a torus's two rings), and it keeps Parasolid's knots where sldprt2step rescales them to the curve's length. |
| [mapbox/earcut](https://github.com/mapbox/earcut) | ISC | **Code reused**: a Python port of its ear clipping, in `tessellate/triangulate.py`, credited in `NOTICE`, changed to keep collinear points and points at one place with different point ids, which are samples the next face shares. |
| [cadmpeg/cadmpeg](https://github.com/cadmpeg/cadmpeg) | Apache-2.0 code, [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/) documentation | Consulted, no code used. The description of display tessellation tables in its format notes (`docs/formats/sldprt.md`, section 8, by the cadmpeg authors, CC-BY-4.0) was the starting hypothesis for section 9 here, which was then verified against SOLIDWORKS' own STL export and rewritten; changes: corrected and extended. Refuted for this corpus: its transmit-header reading (`u16 desc_len`, `u8 schema_len`; it is i16 plus string plus i32), `moPart_c +8` as the part version (true only from 11000, and then the save version in 574 of 2,576 files), a KeyWords `SourceIndex` attribute (0 occurrences), and a UTF-16 unit name after `moLengthUserUnits_c` (0 of 226 tokens). Its container scan misses empty members and constant-CRC members. |
| [blussyya/sldprt-format-research](https://github.com/blussyya/sldprt-format-research), [blussyya/sldprt-research-dump](https://github.com/blussyya/sldprt-research-dump) | MIT | Consulted, no code used. Confirmed: geometry in DisplayLists, partitions are Parasolid on base 13006. Refuted: "no `__ZLB` suffix in 2015+ files" (51 files have one). |
| [Wintaru/model_viewer](https://github.com/Wintaru/model_viewer) | MIT (its STEP import dependency occt-import-js is LGPL-2.1) | Run, no code used. Mesh-only; on the first generation of fixture o08 it returns one box instead of two, because it applies no transforms and de-duplicates repeated instances. |
| [schwitters/openswx](https://github.com/schwitters/openswx) | MIT | Not used. Its source states that parts of it were derived from disassembly of a Dassault binary, which SolidSeas' clean-room rules exclude. Only its scanner's observable behaviour was measured (it misses empty and non-ASCII-named members). |
| monozukuri-ai/sldkit | PolyForm-Noncommercial-1.0.0 from v0.2.0 | Not used. |
| XRTC5/sldprt-export | MIT | Not used. |
| Public specifications | | PKWARE APPNOTE (ZIP), Microsoft [MS-CFB] and [MS-OLEPS], the Siemens Parasolid XT Format Reference (2006 edition), and the SOLIDWORKS API documentation (unit and custom-property enumerations). |
