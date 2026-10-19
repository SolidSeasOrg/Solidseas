"""Alibre Design parts and assemblies (provisional, ``docs/formats/alibre.md``,
``docs/API.md`` 3.20.8).

An Alibre Design file is an OLE compound file of named streams: the document's
identity (``VERSION``), its properties and thumbnail (``PROP_DATA``), its design
database (``STEP_DATA``, ISO 10303-21 text), and for a part the exact B-rep
(``SAB_DATA``, ACIS SAB) and a display tessellation (``MESH_DATA``). An assembly
names its documents by GUID with a placement each. Every module here reads
untrusted bytes within :class:`~solidseas.formats.Limits`.
"""

from .document import AlibreDocument, open

__all__ = ["AlibreDocument", "open"]
