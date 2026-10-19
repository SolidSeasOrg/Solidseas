"""The trademark notice SolidSeas shows: in the README, ``NOTICE``, the viewer's About box
and the command line's help.

SolidSeas names other companies' products only to say which files and programs it works
with. :data:`DISCLAIMER` is the one text of that notice, so each place says the same
thing; ``tests/test_trademarks.py`` checks that the README and ``NOTICE`` carry it word
for word.
"""

INDEPENDENT = (
    "SolidSeas is an independent project. It is not affiliated with, endorsed by, sponsored by "
    "or connected to Dassault Systèmes, Dassault Systèmes SolidWorks Corporation or Siemens "
    "Industry Software Inc."
)

DISCLAIMER = (
    f"{INDEPENDENT} SOLIDWORKS, eDrawings, 3DEXPERIENCE and ACIS are trademarks or registered "
    "trademarks of Dassault Systèmes or its subsidiaries in the US and other countries. Parasolid "
    "is a trademark or registered trademark of Siemens Industry Software Inc. or its subsidiaries "
    "or affiliates. Other product names are trademarks of their owners. They are used here only "
    "to name the files and programs SolidSeas works with."
)

__all__ = ["DISCLAIMER", "INDEPENDENT"]
