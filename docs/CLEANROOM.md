# Clean-room rules for the native part generator

SolidSeas writes native SOLIDWORKS parts (`.sldprt`) with no SOLIDWORKS
present, from a design described in `ParametricDocumentIR`. The generator
that does it, `solidseas.nativewrite.generate`, is built clean room: every
byte it writes is computed by SolidSeas' own code from a written
specification, and that specification comes only from observing files and
published documentation. This document is the rulebook. It applies to
people and to agents alike.

## 1. Two roles

| | Analysis | Implementation |
|---|---|---|
| Who | Agents or people who study SOLIDWORKS files | A separate agent or person, who has not done analysis on this format |
| May read | Files made through the published SOLIDWORKS API on a licensed copy, SolidSeas' readers and `research/`, hex dumps, diffs, SOLIDWORKS' public API documentation, open-source projects whose provenance is clean (section 3) | This document, the generation specification (`docs/sldprt-spec/`, section 15 of `docs/NATIVE_SLDPRT_WRITER.md`), `docs/FORMAT.md`, the IR (`ir.py`), the container writer (`container.py`), and the results of the generator's tests |
| Must not read | Anything section 3 forbids | Any SOLIDWORKS-made file or fixture, any dump or diff of one, `research/`, `tests/fixtures/`, `tests/test_sldprt_spec.py`, `src/solidseas/formats/solidworks/` beyond its public API, the seed writer, the rest of `docs/NATIVE_SLDPRT_WRITER.md` |
| Writes | The specification: grammars, constants with their evidence, which fields come from the design and which are defaults, and the questions still open | `src/solidseas/nativewrite/generate/` and its unit tests |
| Hands over | Specification text, and for a failing test, a description of the difference in specification terms ("the extrusion record's end condition field is 1, the specification says 0 for blind") | Questions about the specification, which analysis answers by amending it |

A test that compares the generator's output with a SOLIDWORKS-made file
belongs to analysis: it runs in `tests/` outside the implementation's view,
and only its verdict and a specification-level description of any
difference cross the wall. The PC's SOLIDWORKS check is the same: a verdict,
volumes and feature types, never the file's bytes.

## 2. What the generator may emit

- Values computed from the IR: geometry, dimensions, names, relations.
- Structure the specification defines: record layouts, field order, class
  names, version numbers, flags and other constants. Each constant in the
  generator's source carries a comment naming the specification section
  that gives it (`# spec 15.4.2`). A constant without one fails review.
- Defaults the specification chooses where SOLIDWORKS needs a value the
  design does not give (units, a material of none, plane display sizes):
  neutral values, chosen by SolidSeas and listed in the specification.
- Identity the generator makes up for each file: creation times from the
  clock, new random ids, the document name from the design.

It may not emit a byte run copied from a SOLIDWORKS-made file, a template,
a seed part or any document SOLIDWORKS saved. No such file is packaged with
SolidSeas, and the generator opens no file while it runs.

## 3. Sources

Allowed for analysis:

- Documents made through the published SOLIDWORKS API, one controlled
  change at a time, on a licensed copy, from templates SOLIDWORKS installs,
  under a neutral account (section 5).
- What SOLIDWORKS reports about a file through its published API.
- SOLIDWORKS' public API documentation, public specifications (PKWARE
  APPNOTE, MS-CFB, MFC's documented `CArchive` behaviour, the Parasolid XT
  format reference).
- Open-source projects whose authors state their work is not derived from
  disassembly, and only as descriptions: their code is not copied
  (`docs/FORMAT.md` section 18 and `docs/NATIVE_SLDPRT_WRITER.md` section
  11 record which were used and how).

Forbidden for everyone:

- Disassembling, decompiling, debugging, hooking or patching any Dassault
  Systèmes binary, or reading symbols or strings out of one.
- Using code or findings from a project that did, such as openswx and
  projects ported from it (SWFormat).
- Circumventing licensing, or using an unlicensed copy.
- Customer, corpus or other people's files as generator input or as
  specification evidence. The private corpus may be used only to measure
  the readers, as before.

## 4. Provenance

- Every claim in the specification carries an evidence label
  (`docs/FORMAT.md`'s VERIFIED, HYPOTHESIS, UNKNOWN) and names the fixtures
  or checks it rests on.
- Every commit to `generate/` is by the implementation role, and its
  message names the specification sections it implements.
- `tests/test_cleanroom.py` holds the generator to the rules a program can
  check: it reads no file while generating; its source names no fixture,
  `research` module or reader internals; its output shares no run of 32 or
  more bytes with any SOLIDWORKS-made fixture member, other than runs the
  specification lists as constants and runs of one repeated byte; and its
  output carries no account, path or identity value (section 5).

## 5. Personal information

- A generated file carries nothing about the person who made it or the
  machine: no account or user name, no path, no host name, no e-mail, no
  licence or serial data. Its author fields are empty or name SolidSeas.
  `solidseas.formats.solidworks` `path_report()` must find no path, no
  account and no identity value in it, and the test checks that.
- Fixtures are made under a Windows account with a neutral name, in folders
  that carry no person's name, so no committed file carries PII. The
  fixture kit's scrub report is checked before any fixture is committed.
- Reports from the PC, specifications and commit messages name no person
  and no private machine.

## 6. Review

Before a change to `generate/` is merged: the change cites its
specification sections, `tests/test_cleanroom.py` passes, the author is the
implementation role, and nothing in it came from a SOLIDWORKS-made file. A
reviewer who finds a constant without a citation, a copied run or a source
on the forbidden list holds the change.
