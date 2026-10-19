"""The video extension's helper: frames to an animated GIF or an MP4 (``docs/EXTENSIONS.md``
sections 6 and 9).

It runs as a program of its own in the extension's package, beside the ffmpeg the package
carries, and speaks the helpers' JSON lines (:mod:`solidseas.helpers`): a ready line, then
``encode`` and ``shutdown`` requests. ``encode`` takes the folder the core rendered the
frames into (``frame00000.png`` on), the frame rate, the format and a plain file name, and
writes that file into the folder the core gave it for the result, never over a file; the
core moves it to where the person chose. For MP4 it takes the first H.264 encoder its
ffmpeg has of Windows' own (``h264_mf``) and OpenH264, else MPEG-4 part 2, so the package
needs no GPL encoder.

``SOLIDSEAS_FFMPEG`` names the ffmpeg to use (for a source checkout or a test); a packaged
helper uses the one beside it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

PROTOCOL = 1
FRAME_PATTERN = "frame%05d.png"
_NAME = re.compile(r"[A-Za-z0-9 ._()+\-]{1,120}\.(gif|mp4)")
_PREFERRED = ("h264_mf", "libopenh264", "mpeg4")


def ffmpeg_path() -> str:
    env = os.environ.get("SOLIDSEAS_FFMPEG")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
    return os.path.join(here, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")


def _encoder(ffmpeg: str) -> str:
    try:
        listed = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=60, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        listed = ""
    names = {
        line.split()[1] for line in listed.splitlines() if len(line.split()) > 1 and line.startswith(" V")
    }
    return next((e for e in _PREFERRED if e in names), "mpeg4")


class Refused(ValueError):
    pass


def encode(args: dict) -> dict:
    frames, out_dir, name = args.get("frames"), args.get("out_dir"), args.get("name")
    fps, fmt = args.get("fps"), args.get("format")
    if not isinstance(frames, str) or not os.path.isdir(frames):
        raise Refused("frames is the folder the frames are in")
    if not isinstance(out_dir, str) or not os.path.isdir(out_dir):
        raise Refused("out_dir is the folder to write into")
    if not isinstance(name, str) or not _NAME.fullmatch(name) or os.path.basename(name) != name:
        raise Refused("name is a plain .gif or .mp4 file name")
    if fmt not in ("gif", "mp4") or not name.lower().endswith("." + fmt):
        raise Refused("format is gif or mp4, as the name ends")
    if isinstance(fps, bool) or not isinstance(fps, int) or not 5 <= fps <= 60:
        raise Refused("fps is a whole number from 5 to 60")
    target = os.path.join(out_dir, name)
    if os.path.lexists(target):
        raise Refused(f"{name} is already there")
    ffmpeg = ffmpeg_path()
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-n", "-framerate", str(fps)]
    command += ["-i", os.path.join(frames, FRAME_PATTERN)]
    if fmt == "gif":
        encoder = "gif"
        command += ["-filter_complex", "[0:v]split[a][b];[a]palettegen[p];[b][p]paletteuse", "-loop", "0"]
    else:
        encoder = _encoder(ffmpeg)
        command += ["-c:v", encoder, "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        if encoder == "mpeg4":
            command += ["-q:v", "3"]
    command.append(target)
    done = subprocess.run(command, capture_output=True, text=True, check=False)
    if done.returncode != 0 or not os.path.isfile(target):
        raise Refused(
            "ffmpeg could not write the clip: " + (done.stderr.strip()[-400:] or f"code {done.returncode}")
        )
    return {"path": target, "bytes": os.path.getsize(target), "encoder": encoder}


def main() -> int:  # pragma: no cover - runs as the helper's own process
    out = sys.stdout

    def say(message: dict) -> None:
        out.write(json.dumps(message) + "\n")
        out.flush()

    say({"event": "ready", "protocol": PROTOCOL, "helper": "video", "operations": ["encode", "shutdown"]})
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except ValueError:
            say({"id": None, "ok": False, "error": {"code": "invalid_request", "message": "not JSON"}})
            continue
        rid, op = message.get("id"), message.get("op")
        if op == "shutdown":
            say({"id": rid, "ok": True, "result": {}})
            return 0
        if op != "encode":
            say({"id": rid, "ok": False, "error": {"code": "unknown_op", "message": f"no operation {op!r}"}})
            continue
        try:
            say({"id": rid, "ok": True, "result": encode(message.get("args") or {})})
        except Refused as exc:
            say({"id": rid, "ok": False, "error": {"code": "refused", "message": str(exc)}})
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = ["FRAME_PATTERN", "PROTOCOL", "Refused", "encode", "ffmpeg_path", "main"]
