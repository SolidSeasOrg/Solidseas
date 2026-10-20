"""Making extension packages and the core's list of the ones it accepts
(``docs/EXTENSIONS.md`` section 8), for the release build.

:func:`build_package` writes ``<id>-<version>.zip`` from a folder holding the helper and
what it needs: the core's manifest for that extension with the helper's details, every
file's SHA-256 and the notices filled in, then each file. The zip is the same bytes for
the same files (names in order, every entry dated 1980-01-01 and marked as made on Unix),
so a package's SHA-256 says exactly which files it holds.

:func:`write_accepted` writes ``accepted.json`` from the packages a release builds: each
extension's id and the SHA-256s of its packages. The release build runs it before it
builds the core, and the core reads the file (:data:`ACCEPTED_FILE`) when it starts, so a
core accepts the packages of its own release and no others.

``python -m solidseas_app.extensions.package build --id ID --from FOLDER --out DIR`` and
``python -m solidseas_app.extensions.package accept ZIP... --out accepted.json`` run them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from collections.abc import Iterable

from . import CATALOG, MANIFEST, ExtensionError, _package_path, current_id, manifest

ACCEPTED_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "accepted.json")
_ZIP_DATE = (1980, 1, 1, 0, 0, 0)


def _files(folder: str) -> list[str]:
    out = []
    for base, dirs, names in os.walk(folder):
        dirs.sort()
        for name in sorted(names):
            path = os.path.join(base, name)
            if os.path.islink(path):
                raise ExtensionError(f"{path} is a link; a package holds plain files only")
            out.append(_package_path(os.path.relpath(path, folder).replace(os.sep, "/")))
    if MANIFEST in out:
        raise ExtensionError(f"the folder already holds a {MANIFEST}; the package's is written here")
    return out


def _digest(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_package(
    extension_id: str,
    folder: str,
    out_dir: str,
    *,
    protocol: int = 1,
    memory_mb: int = 2048,
    seconds: int = 600,
    notices: Iterable[str] = (),
) -> str:
    """Write the package of ``extension_id`` from ``folder`` into ``out_dir`` and return its
    path (module notes). The helper program the core names must be in ``folder``. A
    former id builds the extension it became, under its current id."""
    core = CATALOG.get(current_id(extension_id))
    if core is None or core.kind != "packaged":
        raise ExtensionError(f"{extension_id!r} is not a packaged extension")
    names = _files(folder)
    program = core.helper["program"]
    if program not in names:
        raise ExtensionError(f"{folder} has no {program}")
    raw = core.to_json()
    raw["helper"] = {
        "program": program,
        "protocol": protocol,
        "memory_mb": memory_mb,
        "seconds": seconds,
        "files": {n: _digest(os.path.join(folder, *n.split("/"))) for n in names},
    }
    raw["notices"] = list(notices)
    manifest(raw)  # the same checks a core makes when the package is added
    os.makedirs(out_dir, exist_ok=True)
    target = os.path.join(out_dir, f"{core.id}-{core.version}.zip")
    tmp = target + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in [(MANIFEST, None), *((n, n) for n in names)]:
            info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o644 << 16
            if data is None:
                z.writestr(info, (json.dumps(raw, indent=1, sort_keys=True) + "\n").encode("utf-8"))
            else:
                with open(os.path.join(folder, *name.split("/")), "rb") as src, z.open(info, "w") as dst:
                    for chunk in iter(lambda src=src: src.read(1 << 20), b""):
                        dst.write(chunk)
    os.replace(tmp, target)
    return target


def write_accepted(packages: Iterable[str], out: str = ACCEPTED_FILE) -> dict[str, list[str]]:
    """Write ``accepted.json`` for ``packages`` (module notes) and return what it holds."""
    accepted: dict[str, list[str]] = {}
    for path in packages:
        with zipfile.ZipFile(path) as z:
            mid = manifest(json.loads(z.read(MANIFEST).decode("utf-8"))).id
        accepted.setdefault(mid, []).append(_digest(path))
    data = {k: sorted(set(v)) for k, v in sorted(accepted.items())}
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "accepted": data}, fh, indent=1)
        fh.write("\n")
    os.replace(tmp, out)
    return data


def read_accepted(path: str = ACCEPTED_FILE) -> dict[str, frozenset[str]]:
    """What ``accepted.json`` at ``path`` lists, as the core reads it."""
    import json as _json

    try:
        with open(path, encoding="utf-8") as fh:
            raw = _json.load(fh)
    except (OSError, ValueError):
        return {}
    listed = raw.get("accepted") if isinstance(raw, dict) and raw.get("version") == 1 else None
    if not isinstance(listed, dict):
        return {}
    out: dict[str, frozenset[str]] = {}
    for k, v in listed.items():
        if isinstance(k, str) and current_id(k) in CATALOG and isinstance(v, list):
            out[current_id(k)] = out.get(current_id(k), frozenset()) | frozenset(v)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m solidseas_app.extensions.package")
    sub = ap.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="write an extension's package from a folder")
    b.add_argument("--id", required=True)
    b.add_argument("--from", dest="folder", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--protocol", type=int, default=1)
    b.add_argument("--memory-mb", type=int, default=2048)
    b.add_argument("--seconds", type=int, default=600)
    b.add_argument("--notice", action="append", default=[], help="a notice file to carry, its text")
    a = sub.add_parser("accept", help="write the core's list of the packages it accepts")
    a.add_argument("packages", nargs="+")
    a.add_argument("--out", default=ACCEPTED_FILE)
    args = ap.parse_args(argv)
    try:
        if args.command == "build":
            notices = []
            for path in args.notice:
                # utf-8-sig: a byte order mark, which Windows PowerShell writes, is not text;
                # the FSF's licence texts break pages with form feeds, which are not either
                with open(path, encoding="utf-8-sig") as fh:
                    notices.append(fh.read().replace("\f", ""))
            path = build_package(
                args.id,
                args.folder,
                args.out,
                protocol=args.protocol,
                memory_mb=args.memory_mb,
                seconds=args.seconds,
                notices=notices,
            )
            print(f"{path} {_digest(path)}")
        else:
            for mid, hashes in write_accepted(args.packages, args.out).items():
                print(mid, *hashes)
    except (ExtensionError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["ACCEPTED_FILE", "build_package", "main", "read_accepted", "write_accepted"]
