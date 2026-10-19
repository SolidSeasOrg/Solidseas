"""The modeling assistant (``docs/ASSISTANT.md``). Importing this package imports no Qt.

It holds the window in Review mode (:mod:`.window`) with its script runner
(:mod:`.runner`, :mod:`.child`) and session interface (:mod:`.session`), the AI
settings page (:mod:`.settings_dialog`) and its file, ``AI.json``
(:mod:`.aisettings`, no Qt), and the start of Automatic mode: :mod:`.automatic`
(``start_run``, the only entry to Automatic mode, and the confirmation gate) and
:mod:`.writer` (one writer per SOLIDWORKS session). :mod:`.live_sessions` reaches a
running SOLIDWORKS through the bridge's live operations; the step loop comes in a later
stage.
"""
