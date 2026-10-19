"""Analysis-side research on the native SOLIDWORKS part format (docs/CLEANROOM.md).

Not part of the shipped ``solidseas`` package. It reads SOLIDWORKS-made fixtures, edits
their records in place, builds the experiment candidates and holds the seed writer the
first experiments used. The clean-room generator (``solidseas.nativewrite.generate``)
must never import from here.
"""
