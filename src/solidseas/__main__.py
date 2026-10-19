"""``python -m solidseas``: the command line interface."""

from .cli import main

if __name__ == "__main__":  # the worker processes of list and batch start with spawn
    raise SystemExit(main())
