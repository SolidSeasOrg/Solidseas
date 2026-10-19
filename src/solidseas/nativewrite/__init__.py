"""Write native SOLIDWORKS documents without SOLIDWORKS.

``docs/NATIVE_SLDPRT_WRITER.md`` is the design and ``docs/CLEANROOM.md`` the
rules. Nothing here runs or loads SOLIDWORKS, and nothing here writes to a
source document: every function returns bytes or writes a new file that did
not exist before.

- :mod:`.container` lays out or patches a 2015+ container from its members.
- :mod:`.ir` is the source-agnostic ``ParametricDocumentIR``.
- :mod:`.solidcraft` reads SolidCraft designs into the IR.
- ``generate`` (to come) is the clean-room generator: IR to ``.sldprt``,
  written from the specification alone.

The analysis tools and the seed writer of the first experiments live
outside the shipped package, on the analysis side of the clean room.
"""
