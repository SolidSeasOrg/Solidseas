"""The self-test of every 3D format: ``--self-test-formats --screenshot-dir DIR [--3d]``.

It writes one synthetic file of each format the viewer reads into a temporary
folder of its own (:mod:`.samples`: STL, OBJ, PLY, OFF, glTF and GLB, AMF, 3MF,
STEP part and assembly, Parasolid text and binary, ACIS, Alibre Design part and
assembly, and an IGES file SolidSeas cannot read), points ``SOLIDSEAS_CACHE_DIR``
at another temporary folder (so the thumbnail cache and the folder's catalog never
touch the user's), opens the folder in the real window and checks, for each file:

* **it lists**: a row of status ``ok`` whose Type names its format and whose format
  and document type are the expected ones; the IGES file a row of status
  ``unsupported``, never opened;
* **it previews**: its thumbnail arrived (stored in the 3MF and Alibre files,
  rendered from the geometry for the others), its Preview tab shows an image (the
  same split), and its Overview shows the geometry: the placed items and the size of
  the box, against what the sample was written with;
* **its details fit**: the Components tab lists an assembly's instances (the 3MF,
  STEP and Alibre assemblies) and says a part has none; BOM and Paths are hidden,
  and Where Used is shown and never says the file is not indexed (the index holds
  every format SolidSeas reads); File > Export STEP is on for a
  Parasolid file's part only, and otherwise off with its reason in its tooltip;
* with ``--3d``, **it draws in 3D**: the mesh process reads it, the view is drawn
  and its pixels are read back (a part must cover some of the view); the view cube
  is clicked on its top face and its front, top and right corner and then on Home,
  each ending where it should (:class:`.selftest.NavCheck`, as ``--viewcube``
  checks a SOLIDWORKS document), and a turn drag on the model must keep the point
  under the pointer on its pixel (as ``--pivot``); for an assembly a synthesized
  click on its first instance must pick that instance alone and make its row
  current, exploding it fully must move its components, and hiding that instance
  must leave it out of the id pass, after which Show all brings it back;
* **it exports**: to STL and to 3MF in a temporary output folder, through the
  export's own process as File > Export for 3D Printing does (each file checked
  closed and read back in the window's worker pool), and through 3D Print's export,
  next to the model in the temporary folder (with Open 3MF and STL Files As They Are
  off, so the 3MF and the STL are exported too), as 3MF, as STL and as STEP: a
  Parasolid file's part goes as a STEP file the STEP reader reads back as a part,
  and every other sample as 3MF with the reason (:func:`.printing.step_unavailable`).

The window is saved as a PNG at each step (the listing as details and icons, each
file's Overview, its Components tab for an assembly, its Preview and its 3D view),
and a JSON report lists every check. The run exits 0 when every check passed, else
1. The temporary folders are removed at the end. It writes nothing anywhere else:
its screenshots, report and settings file go where the self-test's own go, through
the same write guards, and its settings never touch the user's.
"""

import json
import os
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from typing import Any

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from solidseas import __version__
from solidseas import cli as _cli

from . import printing, samples
from .details import TABS
from .preview import IMAGE, MODEL
from .selftest import NavCheck, _refused, _slug, click, covered
from .whereused import not_indexed_text

STEP_TIMEOUT_S = 180.0
EXPORT_FORMATS = ("stl", "3mf")  # File > Export for 3D Printing's
PRINT_FORMATS = ("3mf", "stl", "step")  # 3D Print's
# The cube's clicks each 3D view is checked with: a face, a corner, then Home.
CUBE_CHECKS = ("top", "front-top-right", "home")
SIZE_TOLERANCE_MM = 0.01


class FormatsSelfTest(QObject):
    """Drives ``window`` through :data:`.samples.EXPECTED` (see the module notes). The
    checks run as one script of steps (:meth:`_script`), each waiting for the window
    without blocking it."""

    def __init__(
        self,
        window,
        folder: str,
        *,
        shots: str | None,
        report_path: str | None,
        view_3d: bool,
        out_dir: str,
        force: bool = False,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.folder = os.path.abspath(folder)
        self.shots, self.report_path = shots, report_path
        self.view_3d = view_3d
        self.out_dir = out_dir
        self.force = force
        self.shot_no = 0
        self.t0 = time.perf_counter()
        self.report: dict[str, Any] = {
            "solidseas": __version__,
            "platform": QApplication.platformName(),
            "view_3d": view_3d,
            "files": {},
            "screenshots": [],
            "errors": [],
        }
        self._script_gen: Iterator[Any] | None = None
        self._wait: tuple[Callable[[], bool], float] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)

    # -- the driver ---------------------------------------------------------------------
    def start(self) -> None:
        if self.shots:
            os.makedirs(self.shots, exist_ok=True)
        self._script_gen = self._script()
        self._timer.start(0)

    def _tick(self) -> None:
        """Advance the script: a step yields a condition to wait for (or a delay in ms)."""
        if self._wait is not None:
            cond, deadline = self._wait
            try:
                ready = cond()
            except Exception as exc:  # a check that raised is a failed check, never a hang
                self._fail("wait", f"{type(exc).__name__}: {exc}")
                ready = True
            if not ready:
                if time.perf_counter() > deadline:
                    self._fail("timeout", "a step did not finish in time")
                    self._finish()
                    return
                self._timer.start(30)
                return
            self._wait = None
        try:
            step = next(self._script_gen)  # type: ignore[arg-type]
        except StopIteration:
            self._finish()
            return
        except Exception as exc:
            self._fail("script", f"{type(exc).__name__}: {exc}")
            self._finish()
            return
        if callable(step):
            self._wait = (step, time.perf_counter() + STEP_TIMEOUT_S)
            self._timer.start(0)
        else:
            self._timer.start(int(step or 0))

    def _settle(self) -> None:
        for _ in range(3):
            QApplication.processEvents()

    # -- the checks ---------------------------------------------------------------------
    def _script(self):
        w = self.window
        if self.view_3d:
            from .view3d import gl_status

            ok, why = gl_status()
            self.report["opengl"] = {"available": ok, "detail": why}
        w.open_folder(self.folder)
        yield lambda: w.listing_info is not None
        listing = w.listing_info or {}
        self.report["listing"] = {k: v for k, v in listing.items() if k != "error"}
        if not listing.get("ok"):
            self._fail("listing", (listing.get("error") or {}).get("code"))
            return
        rows = {r.entry["path"]: r for r in w.model.rows}
        for name, (fmt, doc_type, _items, _size) in samples.EXPECTED.items():
            rec = self._file(name)
            r = rows.get(name)
            if r is None:
                self._file_fail(name, "listing", "not listed")
                continue
            rec["listed"] = {"status": r.entry["status"], "type": r.display[1], "format": r.format}
            if r.entry["status"] != "ok" or r.format != fmt or r.doc_type != doc_type:
                self._file_fail(name, "listing", f"listed as {r.format} {r.doc_type} ({r.entry['status']})")
        for name in samples.UNREADABLE:
            r = rows.get(name)
            if r is None or r.entry["status"] != "unsupported":
                self._fail("unreadable", f"{name} is not listed as a format SolidSeas cannot read")
        yield lambda: not w.thumbnailer.active and not w.thumbnailer._busy
        self.report["thumbnails"] = w.thumbnailer.report()
        rows = {r.entry["path"]: r for r in w.model.rows}
        for name in samples.EXPECTED:
            r = rows.get(name)
            has = r is not None and r.thumb is not None
            self._file(name)["thumbnail"] = has
            if not has:
                self._file_fail(name, "thumbnail", "no thumbnail")
        w.set_view("icons")
        self._shot("listing_icons")
        w.set_view("details")
        self._shot("listing_details")
        for name in samples.EXPECTED:
            yield from self._document(name)
        yield from self._exports()

    def _document(self, name: str):
        w = self.window
        d = w.details
        rec = self._file(name)
        fmt, doc_type, items, size = samples.EXPECTED[name]
        before = w.generation
        done: list[int] = []
        w.detailsFinished.connect(done.append)
        try:
            if not w.select_document(name):
                self._file_fail(name, "select", "could not be selected")
                return
            yield lambda: any(g > before for g in done) and w._details is None
        finally:
            w.detailsFinished.disconnect(done.append)
        stem = _slug(name.replace(".", "_"))
        sections = {k: bool(v.get("ok")) for k, v in d.sections.items()}
        rec["sections"] = sections
        for k, ok in sections.items():
            if not ok:
                self._file_fail(name, k, "the section could not be read")
        hidden = [t for t in ("BOM", "Paths") if d.tabs.isTabVisible(TABS.index(t))]
        if hidden:
            self._file_fail(name, "tabs", f"shown for a model file: {', '.join(hidden)}")
        where = d.pages["Where Used"]
        rec["where_used"] = where.message_text
        if not d.tabs.isTabVisible(TABS.index("Where Used")) or where.message_text == not_indexed_text(fmt):
            self._file_fail(name, "where used", "the tab says the file is not indexed")
        why = printing.step_unavailable(fmt, doc_type)
        rec["export_step"] = {"enabled": w.act_step.isEnabled(), "tip": w.act_step.toolTip()}
        if w.act_step.isEnabled() != (why is None):
            self._file_fail(name, "export step", f"File > Export STEP is {'on' if why else 'off'}")
        elif why is not None and why[1:] not in w.act_step.toolTip():
            self._file_fail(name, "export step", "its tooltip does not say why it is off")
        g = d.geometry or {}
        rec["geometry"] = {"items": g.get("items"), "size_mm": g.get("size_mm"), "sources": g.get("sources")}
        got = g.get("size_mm") or []
        if (
            g.get("items") != items
            or len(got) != 3
            or any(abs(a - b) > SIZE_TOLERANCE_MM for a, b in zip(got, size, strict=False))
        ):
            self._file_fail(
                name, "geometry", f"read {g.get('items')} items of {got} mm, not {items} of {size}"
            )
        pv = ((d.sections.get("preview") or {}).get("data")) or {}
        rec["preview"] = {"source": pv.get("source"), "width": pv.get("width"), "height": pv.get("height")}
        stored = fmt in ("3mf", "alibre")
        if pv.get("image") is None or pv.get("source") != ("stored" if stored else "rendered"):
            self._file_fail(
                name, "preview", f"preview {pv.get('source')}, not {'stored' if stored else 'rendered'}"
            )
        comp = d.pages["Components"]
        if doc_type == "assembly":
            n = d.instances.topLevelItemCount()
            rec["components"] = n
            if not comp.showing_content or n == 0:
                self._file_fail(name, "components", "the Components tab lists no instance")
        elif comp.showing_content:
            self._file_fail(name, "components", "a part shows components")
        d.tabs.setCurrentIndex(TABS.index("Overview"))
        self._shot(f"{stem}_overview")
        if doc_type == "assembly":
            d.tabs.setCurrentIndex(TABS.index("Components"))
            self._shot(f"{stem}_components")
        d.tabs.setCurrentIndex(TABS.index("Preview"))
        d.preview.set_mode(IMAGE)
        self._shot(f"{stem}_preview")
        if self.view_3d:
            yield from self._model(name, doc_type)
        d.preview.set_mode(IMAGE)
        d.tabs.setCurrentIndex(TABS.index("Overview"))

    def _model(self, name: str, doc_type: str):
        w = self.window
        pane = w.details.preview
        rec = self._file(name).setdefault("view_3d", {})
        pane.set_mode(MODEL)
        yield lambda: pane.mesh_state not in ("idle", "starting", "loading")
        yield 300  # its first frame
        rec["state"] = pane.mesh_state
        info = {k: v for k, v in pane.mesh_info.items() if k != "seconds"}
        rec["info"] = info
        view = pane.view
        if pane.mesh_state != "ready" or view is None:
            self._file_fail(
                name, "3d", f"the 3D view is {pane.mesh_state}: {pane.model_message.text()[:200]}"
            )
            return
        self._settle()
        view.repaint()
        rec["covered"] = round(covered(view), 4)
        if rec["covered"] < 0.01:
            self._file_fail(name, "3d", "nothing is drawn in the 3D view")
        stem = _slug(name.replace(".", "_"))
        self._shot(f"{stem}_3d")
        self._navigation(name, rec, pane, view)
        if doc_type != "assembly" or not pane.instance_ids:
            return
        # A pick: a synthesized click where the view draws the first instance.
        ident = pane.instance_ids[0]
        point = view.pixel_of(0)
        if point is None:
            self._file_fail(name, "pick", "the first instance is not drawn")
            return
        click(view, point)
        self._settle()
        picked = [pane.instance_ids[g] for g in sorted(view.selected)]
        row = w.details.selection().get("instances")
        rec["pick"] = {"instance": ident, "picked": picked, "row": row}
        if picked != [ident] or row != ident:
            self._file_fail(name, "pick", f"a click on {ident} picked {picked}, row {row}")
        pane.drop_pick()
        # The exploded view: fully exploded, the components move apart.
        if pane.can_explode:
            pane.set_explode(100)
            yield lambda: not getattr(view, "animating", False)
            explosion = getattr(view, "explosion", None)
            moving = explosion.moving if explosion is not None else 0
            rec["explode"] = {"drawn": round(float(view.explode), 4), "moving": moving}
            if abs(view.explode - 1.0) > 1e-6 or not moving:
                self._file_fail(name, "explode", f"exploded to {view.explode}, {moving} moving")
            self._shot(f"{stem}_3d_exploded")
            pane.set_explode(0)
            yield lambda: not getattr(view, "animating", False)
        # A look: hidden, the instance leaves the id pass; Show all brings it back.
        pane.set_hidden(("instance", ident), True)
        self._settle()
        ids = view.ids_drawn() or []
        hidden_ok = 0 not in set(ids)
        pane.show_all()
        self._settle()
        shown_ok = 0 in set(view.ids_drawn() or [])
        rec["hide"] = {"hidden": hidden_ok, "shown_again": shown_ok}
        if not (hidden_ok and shown_ok):
            self._file_fail(name, "hide", "hiding the instance, or Show all, did not change what is drawn")

    def _navigation(self, name: str, rec: dict[str, Any], pane, view) -> None:
        """The view cube's clicks (:data:`CUBE_CHECKS`) and a turn about the point under the
        pointer, from Home, as a person does them; the view is left at Home."""
        nav = rec["navigation"] = {"viewcube": [], "pivot": None}
        check = NavCheck(self, pane, view)
        view.go_home(animate=False)
        self._settle()
        try:
            for what in CUBE_CHECKS:
                for r in check.run_cube(what):
                    nav["viewcube"].append(r)
                    if r.get("failed"):
                        self._file_fail(name, "viewcube", f"{r['viewcube']}: {r['failed']}")
            on = pane.instance_ids[0] if view.can_pick and pane.instance_ids else "part"
            pivot = check.run_pivot(on)
            nav["pivot"] = pivot
            if pivot.get("failed"):
                self._file_fail(name, "pivot", pivot["failed"])
        finally:
            check.close()
            self._settle()

    def _exports(self):
        """Export every sample to STL and 3MF, and through 3D Print's export as 3MF, STL and
        STEP, in a worker thread of the window; then read each file written back in the
        worker pool."""
        w = self.window
        results: dict[str, Any] = {}
        state = {"done": False}
        folder, out_dir, models = self.folder, self.out_dir, w.models

        def work(_emit, cancelled):
            for name in samples.EXPECTED:
                if cancelled():
                    break
                path = os.path.join(folder, name)
                base = {"path": path, "folder": folder, "within": folder, "nested": [], "virtual": []}
                base.update(name=name, configuration=None)
                got: dict[str, Any] = {}
                own = os.path.join(out_dir, _slug(name.replace(".", "_")))  # one folder a sample
                os.makedirs(own, exist_ok=True)
                for fmt in EXPORT_FORMATS:
                    req = {**base, "fmt": fmt, "out_dir": own, "overwrite": False}
                    got[fmt] = _checked(printing.export_in_process(req, cancelled), models, own)
                fmt, doc_type = samples.EXPECTED[name][:2]
                for asked in PRINT_FORMATS:
                    req = {**base, "fmt": asked, "out_base": out_dir, "next_to_model": True}
                    req["confine"] = folder
                    result = printing.export_in_process(req, cancelled)
                    key = "print" if asked == "3mf" else f"print_{asked}"
                    got[key] = _printed(result, models, asked, printing.step_unavailable(fmt, doc_type))
                results[name] = got
            return {"ok": True}

        from .workers import Job

        w._start(w.export_pool, Job(work), on_finished=lambda _r: state.update(done=True))
        yield lambda: state["done"]
        for name, got in results.items():
            rec = self._file(name)
            rec["exports"] = got
            for what, r in got.items():
                if not r.get("ok"):
                    self._file_fail(name, f"export {what}", r.get("why") or "failed")
        missing = [n for n in samples.EXPECTED if n not in results]
        if missing:
            self._fail("exports", f"not exported: {', '.join(missing)}")

    # -- the report -----------------------------------------------------------------------
    def _file(self, name: str) -> dict[str, Any]:
        return self.report["files"].setdefault(name, {"errors": []})

    def _file_fail(self, name: str, where: str, what: str) -> None:
        self._file(name)["errors"].append({"where": where, "error": what})

    def _fail(self, where: str, what: Any) -> None:
        self.report["errors"].append({"where": where, "error": what})

    def _shot(self, label: str) -> None:
        if not self.shots:
            return
        self.shot_no += 1
        name = f"{self.shot_no:02d}_{label}.png"
        try:
            path = _cli.check_output_file(
                os.path.join(self.shots, name),
                [],
                allow_source_dir=False,
                force=self.force,
                source_dirs=[self.folder],
            )
        except _cli.Refused as exc:
            self._fail("screenshot", str(_refused("screenshot", name, exc)))
            return
        self._settle()
        if self.window.grab().save(path, "PNG"):
            self.report["screenshots"].append(path)
        else:
            self._fail("screenshot", f"could not save {name}")

    def _finish(self) -> None:
        self._timer.stop()
        r = self.report
        r["pool"] = {"started": self.window.models.started, "alive": self.window.models.alive()}
        if self.view_3d:
            r["mesh_process"] = {"started": self.window.mesh_reader.started}
        r["total_s"] = round(time.perf_counter() - self.t0, 3)
        failed = bool(r["errors"]) or any(f["errors"] for f in r["files"].values())
        r["ok"] = not failed
        if self.report_path:
            try:
                path = _cli.check_output_file(
                    self.report_path, [], allow_source_dir=False, force=self.force, source_dirs=[self.folder]
                )
                _cli._write(path, json.dumps(r, indent=2, ensure_ascii=False).encode("utf-8"))
            except (OSError, _cli.Refused) as exc:
                failed = True
                if sys.stderr is not None:
                    sys.stderr.write(f"could not write the self-test report: {exc}\n")
        QApplication.exit(1 if failed else 0)


def _checked(result: dict[str, Any], models, out_dir: str | None) -> dict[str, Any]:
    """One export's result for the report: written, closed, and read back in the window's
    worker pool (the library's ``model_summary`` job, within the folder it is in)."""
    if not result.get("ok"):
        err = result.get("error") or {}
        return {"ok": False, "why": f"{err.get('code')}: {err.get('reader_message') or err.get('message')}"}
    data = result["data"]
    out = {
        "ok": True,
        "bytes": data.get("bytes"),
        "triangles": data.get("triangles"),
        "closed": data.get("closed"),
        "place": data.get("place"),
    }
    path = data.get("file") or ""
    if not data.get("closed") or not os.path.isfile(path) or os.path.getsize(path) != data.get("bytes"):
        return {**out, "ok": False, "why": "the file written is not closed or not the size reported"}
    if out_dir is None and data.get("place") != printing.MODEL:
        return {
            **out,
            "ok": False,
            "why": f"3D Print's file went to {data.get('place')}, not next to the model",
        }
    try:
        summary = models.call("model_summary", {"path": path, "within": os.path.dirname(path), "include": []})
        out["read_back"] = (summary.data or {}).get("format")
    except Exception as exc:
        return {**out, "ok": False, "why": f"it could not be read back: {exc}"}
    return out


def _printed(result: dict[str, Any], models, asked: str, why: str | None) -> dict[str, Any]:
    """One 3D Print export for the report (:func:`_checked`), asked for as ``asked``: sent
    in that format, or, for a STEP the export does not write (``why``), as 3MF with that
    reason. A STEP must read back as STEP."""
    out = _checked(result, models, None)
    if not out.get("ok"):
        return out
    data = result["data"]
    want = printing.STEP_FALLBACK if asked == printing.STEP and why else asked
    out.update(format=data.get("format"), requested=data.get("requested_format"))
    out["fallback"] = data.get("format_fallback")
    if data.get("format") != want or os.path.splitext(data.get("file") or "")[1] != printing.EXTENSIONS[want]:
        return {**out, "ok": False, "why": f"asked for {asked}, sent {data.get('format')}, not {want}"}
    if want != asked and data.get("format_fallback") != why:
        said = data.get("format_fallback")
        return {**out, "ok": False, "why": f"sent as {want} saying {said!r}, not {why!r}"}
    if want == printing.STEP and out.get("read_back") != "step":
        return {**out, "ok": False, "why": f"the STEP read back as {out.get('read_back')}"}
    return out


def run(args) -> int:
    """``--self-test-formats``: make the folders, run :class:`FormatsSelfTest` in the
    window and clean up; the exit code."""
    from solidseas.errors import OutputRefusedError

    from .app import EXIT_REFUSED, _fail, use_system_fonts, window_icon
    from .selftest import outputs, settings_output
    from .settings import Settings, SettingsStore

    work = tempfile.mkdtemp(prefix="solidseas-formats-")
    folder = os.path.join(work, "samples")
    out_dir = os.path.join(work, "exports")
    cache = os.path.join(work, "cache")
    try:
        try:
            shots, report = outputs(folder, args.screenshot_dir, args.report, force=args.force)
            assert report is not None
            store = SettingsStore(settings_output(folder, report, force=args.force))
        except OutputRefusedError as exc:
            return _fail(str(exc), EXIT_REFUSED)
        samples.write_samples(folder)
        os.makedirs(out_dir)
        os.environ["SOLIDSEAS_CACHE_DIR"] = cache  # the thumbnail cache and the catalog: the run's own
        own = Settings(
            view_3d=args.view_3d,
            remember_session=False,
            show_all_formats=True,
            show_unreadable=True,
            print_as_is=False,
        )
        if not store.save(own):
            store = SettingsStore(None)
            store.save(own)
        use_system_fonts()
        from .window import MainWindow

        app = QApplication.instance() or QApplication(sys.argv[:1])
        app.setApplicationName("SolidSeas Viewer")
        app.setWindowIcon(window_icon())
        window = MainWindow(store)
        window.resize(1440, 900)
        window.show()
        test = FormatsSelfTest(
            window,
            folder,
            shots=shots,
            report_path=report,
            view_3d=args.view_3d,
            out_dir=out_dir,
            force=args.force,
        )
        QTimer.singleShot(0, test.start)
        code = app.exec()
        window.shutdown()
        window.close()
        return code
    finally:
        shutil.rmtree(work, ignore_errors=True)


__all__ = ["FormatsSelfTest", "run"]
