"""``python -m solidseas_app [FOLDER]``: the SolidSeas Viewer preview.

Absolute imports only: PyInstaller runs this file as a script, outside its package.
``freeze_support`` comes first: in the executable, the 3D view's mesh process
(:mod:`solidseas_app.viewer.meshproc`) is this program started again, and it
must turn into that process before anything else runs. So is the assistant's
script runner (``--assistant-child``, :mod:`solidseas_app.assistant.child`), which
turns into it before the viewer is imported.

``--assistant`` opens the modeling assistant's window on its own
(:func:`solidseas_app.assistant.window.main`), so the executable can open it without
the viewer: ``SolidSeasViewer.exe --assistant``.

``--mcp`` makes it an MCP server for Claude Desktop, Claude Code or another client that
starts it, on standard input and output (:mod:`solidseas_app.assistant.mcp_server`):
``SolidSeasViewer.exe --mcp``, with ``--send-names`` to let the chat read typed names.
"""

import multiprocessing
import sys

ASSISTANT_FLAG = "--assistant"
CHILD_FLAG = "--assistant-child"
MCP_FLAG = "--mcp"


def main(argv: list[str]) -> int:
    """Run what ``argv`` asks for: the assistant's script runner, the assistant's window
    or the viewer."""
    if argv[1:2] == [CHILD_FLAG]:
        from solidseas_app.assistant.child import main as child_main

        child_main()  # ends the process
        return 0
    if argv[1:2] == [MCP_FLAG]:
        from solidseas_app.assistant.mcp_server import main as mcp_main

        return mcp_main(argv[2:])
    if argv[1:2] == [ASSISTANT_FLAG]:
        from solidseas_app.assistant.window import main as assistant_main

        return assistant_main(argv[:1] + argv[2:])
    from solidseas_app.viewer.app import main as viewer_main

    return viewer_main()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main(sys.argv))
