"""Count what the corpus documents in which SolidSeas finds no configuration do hold.

SolidSeas takes a document's configurations from its component tree (swXmlContents
COMPINSTANCETREE or Features), its KeyWords and its MATERIALTREE (docs/FORMAT.md 4).
A part or an assembly where none of those names one reports no configuration, and its
BOM rows say bom_configurations_unknown. This script reads the manifest named by
SOLIDSEAS_CORPUS_MANIFEST, opens every part and assembly read-only, and for each that
reports no configuration counts which carriers it has and what they hold, so the next
reader change can be aimed at the right one. It prints numbers only: no file name, path
or value from a file leaves the machine.

    python scripts/corpus-no-configurations.py            # every row of the manifest
    python scripts/corpus-no-configurations.py --json     # the same counts as JSON
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import Counter

TREES = ("swXmlContents/COMPINSTANCETREE", "swXmlContents/Features")
CARRIERS = (*TREES, "swXmlContents/KeyWords", "swXmlContents/MATERIALTREE")
CONFIG_PROPS = re.compile(r"(docProps/)?Config-\d{1,9}-Properties(\.xml)?$")


def _rows(manifest: str) -> list[str]:
    with open(manifest, encoding="utf-8-sig", newline="") as fh:
        return [
            r["path"]
            for r in csv.DictReader(fh)
            if r.get("format") in ("modern", "ole")
            and os.path.splitext(r["path"])[1].lower() in (".sldprt", ".sldasm")
        ]


def _carriers(doc) -> list[str]:
    """What the document holds that could carry a configuration, as plain labels."""
    names = set(doc.container.names())
    out = [f"stream {c.split('/')[-1]}" for c in CARRIERS if c in names]
    for c in CARRIERS:
        if c in names:
            try:
                text = doc.container.read(c, max_bytes=64 << 20)
            except Exception:  # unreadable: say so, never the text
                out.append(f"{c.split('/')[-1]} unreadable")
                continue
            if b"swConfiguration " in text or b"<swConfiguration" in text:
                out.append(f"{c.split('/')[-1]} names swConfiguration")
            if b"Configuration" in text:
                out.append(f"{c.split('/')[-1]} mentions Configuration")
    props = [n for n in names if CONFIG_PROPS.search(n)]
    if props:
        out.append("config property streams")
    md = doc.metadata
    if md.sources.get("configuration_properties_unmatched"):
        out.append("config properties with no configuration")
    if md.active_configuration:
        out.append("SW-Configuration Name set")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="print the counts as JSON")
    args = parser.parse_args(argv)
    manifest = os.environ.get("SOLIDSEAS_CORPUS_MANIFEST")
    if not manifest:
        sys.stderr.write("set SOLIDSEAS_CORPUS_MANIFEST to the corpus manifest CSV\n")
        return 2
    from solidseas import open_document

    totals: Counter = Counter()
    carriers: Counter = Counter()
    patterns: Counter = Counter()
    versions: Counter = Counter()
    warnings: Counter = Counter()
    for path in _rows(manifest):
        totals["documents"] += 1
        try:
            with open_document(path, hold_open=True) as doc:
                if doc.configurations:
                    totals["with configurations"] += 1
                    continue
                totals["without configurations"] += 1
                totals[f"without, {doc.format} {doc.doc_type}"] += 1
                found = _carriers(doc)
                carriers.update(found)
                patterns[" + ".join(sorted(found)) or "none of them"] += 1
                v = doc.saved_version
                versions[v.release or f"format {v.format_version}"] += 1
                warnings.update(w.code for w in doc.warnings)
        except Exception as exc:  # the type only: the text can quote a path
            totals[f"not read ({type(exc).__name__})"] += 1
    out = {
        "totals": dict(totals),
        "carriers": dict(carriers.most_common()),
        "patterns": dict(patterns.most_common()),
        "saved_by": dict(versions.most_common()),
        "reader_warnings": dict(warnings.most_common()),
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        for section, counts in out.items():
            print(section)
            for key, n in counts.items():
                print(f"  {n:6,}  {key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
