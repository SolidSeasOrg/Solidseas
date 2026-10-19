"""Gridfinity bins from photos of tools on a sheet of paper, for a chat (``docs/GRIDFINITY.md``).

Tracefinity (https://github.com/tracefinity/tracefinity, MIT), running in Docker on the
person's server or on this PC, does the image work and makes the files: it finds the paper's
corners in a photo, takes the perspective out so the paper gives the scale, traces the tools'
outlines, and makes a bin's STL. SolidSeas drives it through its HTTP API on loopback only
(:mod:`.tracefinity`), a server's through an SSH tunnel (:mod:`.tunnel`), lays the tools out
in the smallest bin they fit (:mod:`.layout`), draws what it did (:mod:`.png`), and serves it
all to a chat as MCP tools beside the SOLIDWORKS ones (:mod:`.connector`,
:mod:`solidseas_app.assistant.mcp_server`).

The photos go only to that Tracefinity, and the chat gets outlines, sizes and drawings made
from the outlines, never a photo.
"""
