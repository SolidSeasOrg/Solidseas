"""A feature's span read as class tokens with a typed reading of the bytes between them.

``python -m swnative.annotate part.sldprt Sketch1 [--to Boss-Extrude1]`` prints each class
token of the span (a new class or a reference to one) and, between tokens, the typed items
of :mod:`.typedump`. It is the view the field-by-field decoding of
``docs/NATIVE_SLDPRT_WRITER.md`` works from; it reads the file and writes nothing.
"""

from __future__ import annotations

from solidseas.nativewrite.container import read_document

from . import objdiff as OD
from . import typedump as TD


def lines(path, first: str, last: str | None = None, stream: str = "Contents/Config-0-ResolvedFeatures"):
    doc = read_document(path)
    data = doc.data(stream)
    out = []
    for tok in OD.tokens(doc, first, last, stream):
        if tok.kind == "raw":
            for it in TD.items(data, tok.offset, tok.offset + len(tok.data)):
                out.append("    " + it.text())
        else:
            mark = "new" if tok.kind == "def" else "ref"
            out.append(f"{tok.offset:6d} [{mark} {tok.cls} #{tok.index}]")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="A feature span as class tokens and typed fields.")
    ap.add_argument("path")
    ap.add_argument("first")
    ap.add_argument("--to", dest="last")
    args = ap.parse_args(argv)
    print("\n".join(lines(args.path, args.first, args.last)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
