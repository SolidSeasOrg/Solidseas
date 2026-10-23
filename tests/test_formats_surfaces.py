"""Model files on every surface (``docs/API.md`` 3.20, 3.21, 7.1 and 8.6): folder listings
with ``formats``, the worker jobs, the command line and the REST service, and the
same ``model_summary`` from Python, the CLI and REST."""

import json
import os
import shutil

import pytest

import mesh_writers as mw
from jsonschema_subset import validate
from model_writers import box, scene_document, stl_ascii, stl_binary, two_object_assembly
from serve_support import Running
from solidseas import Root, Roots, cli, jobs, model, scan
from solidseas.errors import FormatNotSupportedError, InvalidArgumentError, PathRefusedError, SldLimitError
from solidseas.formats import Limits, open_model
from solidseas.workers import WorkerPool
from support import fixture_path

pytestmark = pytest.mark.usefixtures("outbound_guard")
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# The first line of an IGES file's start section: a format SolidSeas lists but cannot read.
IGES = b"a synthetic IGES file".ljust(72) + b"S      1\n"


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    """A folder of mixed files: SOLIDWORKS documents, STLs, an IGES file (a format with no
    reader), an assembler source and a Solid Edge-looking ``.asm``, and a text file."""
    base = tmp_path_factory.mktemp("formats") / "mixed"
    base.mkdir()
    for name in ("o02_boxA.SLDPRT", "o02_boxA.STL"):
        shutil.copy2(fixture_path(name), base / name)
    (base / "part.igs").write_bytes(IGES)
    (base / "assembly.stl").write_bytes(stl_binary(two_object_assembly()))
    (base / "solids.stl").write_bytes(stl_ascii(two_object_assembly()))
    (base / "boot.asm").write_bytes(b"; an assembler source\nmov ax, 1\n")
    (base / "edge.asm").write_bytes(OLE + b"\0" * 504)
    (base / "notes.txt").write_text("nothing")
    return base


def _by_path(entries):
    return {e["path"]: e for e in entries}


# --------------------------------------------------------------------------- listings
def test_a_default_listing_is_solidworks_only(folder):
    data = scan(folder).listing()
    assert [e["path"] for e in data["entries"]] == ["o02_boxA.SLDPRT"]
    assert data["counts"]["unsupported"] == 0 and data["entries"][0]["model"] is None


def test_a_listing_of_every_format(folder):
    data = scan(folder, formats="all", include=("properties", "preview")).listing()
    assert validate(model.envelope("listing", data), model.envelope_schema("listing"), strict=True) == []
    got = _by_path(data["entries"])
    assert sorted(got) == sorted(
        ["assembly.stl", "edge.asm", "o02_boxA.SLDPRT", "o02_boxA.STL", "part.igs", "solids.stl"]
    )
    stl = got["o02_boxA.STL"]
    assert stl["status"] == "ok" and stl["model"]["format"] == "stl" and stl["model"]["readable"]
    assert stl["model"]["counts"]["triangles"] == 12 and stl["format"] is None and stl["doc_type"] == "part"
    assert stl["preview"]["available"] is False and stl["model"]["preview_renderable"]
    assert [p["name"] for p in stl["properties"]] == ["header"]
    iges = got["part.igs"]
    assert (iges["status"], iges["detected"], iges["model"]["readable"]) == ("unsupported", "iges", False)
    assert got["edge.asm"]["status"] == "unsupported" and got["edge.asm"]["detected"] == "solid_edge"
    assert got["o02_boxA.SLDPRT"]["model"] is None and got["o02_boxA.SLDPRT"]["format"] == "modern"
    assert data["counts"]["unsupported"] == 2 and data["counts"]["ok"] == 4


def test_a_listing_of_chosen_formats_and_a_bad_choice(folder):
    entries = list(scan(folder, formats="stl"))
    assert sorted(e["path"] for e in entries) == ["assembly.stl", "o02_boxA.STL", "solids.stl"]
    with pytest.raises(InvalidArgumentError):
        scan(folder, formats="nope")


def test_a_listing_in_workers_matches_one_in_process(folder):
    with WorkerPool(2, roots=[str(folder)]) as pool:
        pooled = scan(folder, formats="all", pool=pool, include=("properties", "preview_data")).listing()
    alone = scan(folder, formats="all", include=("properties", "preview_data")).listing()
    assert pooled == alone


def test_the_fingerprint_covers_model_files(folder, tmp_path):
    copy = tmp_path / "copy"
    shutil.copytree(folder, copy)
    before = scan(copy, formats="all").fingerprint()
    assert scan(copy, formats="all").fingerprint() == before
    assert scan(copy).fingerprint() != before
    (copy / "assembly.stl").write_bytes(stl_binary(box(1, 1, 1)))
    assert scan(copy, formats="all").fingerprint() != before


def test_a_solidworks_name_with_stl_content(tmp_path):
    (tmp_path / "inside.SLDPRT").write_bytes(stl_binary(box(1, 1, 1)))
    (tmp_path / "step.SLDPRT").write_bytes(fixture_path("o02_boxA.step").read_bytes())
    plain = _by_path(scan(tmp_path).listing()["entries"])
    assert (
        plain["inside.SLDPRT"]["status"] == "error"
        and plain["inside.SLDPRT"]["error"]["code"] == "unknown_format"
    )
    assert (plain["step.SLDPRT"]["status"], plain["step.SLDPRT"]["detected"]) == ("not_solidworks", "step")
    every = _by_path(scan(tmp_path, formats="all").listing()["entries"])
    assert every["inside.SLDPRT"]["status"] == "ok" and every["inside.SLDPRT"]["model"]["format"] == "stl"
    assert "extension_mismatch" in {w["code"] for w in every["inside.SLDPRT"]["warnings"]}
    # STEP content SolidSeas reads now: read as STEP, as the STL content is
    assert every["step.SLDPRT"]["status"] == "ok" and every["step.SLDPRT"]["model"]["format"] == "step"
    assert "extension_mismatch" in {w["code"] for w in every["step.SLDPRT"]["warnings"]}


# --------------------------------------------------------------------------- the jobs
def test_the_model_jobs(folder):
    jobs.configure({"roots": [str(folder)]})
    try:
        base = {"path": str(folder / "o02_boxA.STL"), "within": str(folder), "name": "o02_boxA.STL"}
        summary = jobs.model_summary(base)
        with open_model(folder / "o02_boxA.STL") as doc:
            assert summary == model.build_model_summary(doc, include=model.MODEL_SUMMARY_PARTS)
        assert jobs.model_properties({**base, "view": "file"})["properties"][0]["name"] == "header"
        meta, png = jobs.model_preview(base)
        assert meta["source"] == "rendered" and meta["mime"] == "image/png" and png.startswith(b"\x89PNG")
        assert (meta["width"], meta["height"]) == (256, 192)
        meta, _png = jobs.model_preview({**base, "width": 64, "height": 48})
        assert (meta["width"], meta["height"]) == (64, 48)
        from solidseas.errors import NoPreviewError

        with pytest.raises(NoPreviewError):
            jobs.model_preview({**base, "render": "never"})
        with pytest.raises(InvalidArgumentError):
            jobs.model_preview({**base, "render": "sometimes"})
        entry, image = jobs.model_entry(
            {**base, "rel": "o02_boxA.STL", "file": None, "include": ["preview_data"]}
        )
        assert entry["model"]["format"] == "stl" and image is None
        from solidseas.errors import PathRefusedError

        with pytest.raises(PathRefusedError):
            jobs.model_summary({**base, "within": str(folder.parent)})
    finally:
        jobs.configure({})


def test_the_worker_pool_runs_model_summary(folder):
    with WorkerPool(1, roots=[str(folder)]) as pool:
        env = pool.run("model_summary", folder / "o02_boxA.STL", within=str(folder))
        assert env["ok"] and env["kind"] == "model_summary" and env["data"]["format"] == "stl"
        env = pool.run("model_summary", folder / "part.igs", within=str(folder))
        assert not env["ok"] and env["error"]["code"] == "format_not_supported"


@pytest.fixture
def disguised(tmp_path):
    """A folder with ``x.stl``, which holds a 3MF, and ``box.stl``, an STL of twelve triangles."""
    (tmp_path / "x.stl").write_bytes(mw.threemf(box(1, 1, 1)))
    (tmp_path / "box.stl").write_bytes(stl_binary(box(1, 1, 1)))
    return tmp_path


def test_the_jobs_read_only_the_formats_and_within_the_limits_the_worker_has(disguised):
    """A worker set to read STL, as ``serve --formats stl`` sets it, refuses a ``.stl`` that
    holds a 3MF in every model-file job, and reads within the limits it was given."""
    base = {"path": str(disguised / "x.stl"), "within": str(disguised), "name": "x.stl"}
    jobs.configure({"roots": [str(disguised)], "formats": ["stl"], "limits": {"triangles": 10}})
    try:
        for job in (jobs.model_summary, jobs.model_properties, jobs.model_preview):
            with pytest.raises(FormatNotSupportedError) as exc:
                job(base)
            assert exc.value.detail == {"rule": "format_not_enabled", "value": "3mf"}
        entry, _image = jobs.model_entry({**base, "rel": "x.stl", "file": None, "include": []})
        assert entry["status"] == "error" and entry["error"]["code"] == "format_not_supported"
        assert entry["error"]["detail"] == {"rule": "format_not_enabled", "value": "3mf"}
        with pytest.raises(FormatNotSupportedError):
            jobs.catalog_document({**base, "previews": False})
        with pytest.raises(FormatNotSupportedError):  # a listing asking for 3MF gets no more
            jobs.model_entry({**base, "rel": "x.stl", "file": None, "include": [], "formats": ["3mf"]})
        stl = {"path": str(disguised / "box.stl"), "within": str(disguised), "name": "box.stl"}
        assert jobs.model_summary(stl)["format"] == "stl"
        with pytest.raises(SldLimitError) as exc:  # twelve triangles, ten allowed
            jobs.model_preview(stl)
        assert exc.value.detail["limit"] == "triangles"
    finally:
        jobs.configure({})
    jobs.configure({"roots": [str(disguised)]})  # a worker with no formats reads what the file holds
    try:
        assert jobs.model_summary(base)["format"] == "3mf"
    finally:
        jobs.configure({})


def test_a_pool_carries_its_formats_and_limits_to_its_workers(disguised):
    with WorkerPool(1, roots=[str(disguised)], formats="stl", limits=Limits(triangles=10)) as pool:
        settings = pool._settings["job_settings"]
        assert settings["formats"] == ["stl"] and settings["limits"] == {"triangles": 10}
        env = pool.run("model_summary", disguised / "x.stl", within=str(disguised))
        assert not env["ok"] and env["error"]["code"] == "format_not_supported"
        assert env["error"]["detail"] == {"rule": "format_not_enabled", "value": "3mf"}
        env = pool.run("model_summary", disguised / "box.stl", within=str(disguised))
        assert env["ok"] and env["data"]["format"] == "stl"
    with WorkerPool(1, roots=[str(disguised)]) as pool:  # none given: every format, the defaults
        assert pool._settings["job_settings"]["formats"] is None
        assert pool._settings["job_settings"]["limits"] is None



def test_a_root_served_without_subfolders_keeps_named_files_beside_the_document(tmp_path):
    data, sib = mw.gltf(box(1, 1, 1), buffer="file")
    doc = json.loads(data)
    doc["buffers"][0]["uri"] = "sub/scene.bin"
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "scene.bin").write_bytes(sib["scene.bin"])
    (tmp_path / "s.gltf").write_text(json.dumps(doc))
    base = {"path": str(tmp_path / "s.gltf"), "within": str(tmp_path), "name": "s.gltf"}
    jobs.configure({"roots": [str(tmp_path)], "flat_roots": [str(tmp_path)]})
    try:
        assert jobs.model_summary(base)["references"][0]["resolution"]["status"] == "refused"
        with pytest.raises(PathRefusedError) as exc:
            jobs.model_preview({**base, "render": "always"})
        assert exc.value.detail == {"rule": "subfolder"}
    finally:
        jobs.configure({})
    jobs.configure({"roots": [str(tmp_path)]})  # a root served with its subfolders
    try:
        assert jobs.model_summary(base)["references"][0]["resolution"]["status"] == "found"
    finally:
        jobs.configure({})
    flat = Roots([Root("r", str(tmp_path), recursive=False)])
    with WorkerPool(1, roots=flat) as pool:  # a pool takes the rule from a root that is not recursive
        assert pool._settings["job_settings"]["flat_roots"] == [os.path.abspath(tmp_path)]

def test_a_listing_reads_a_model_file_only_as_a_listed_format(disguised):
    got = _by_path(scan(disguised, formats="stl").listing()["entries"])
    assert got["box.stl"]["status"] == "ok"
    assert got["x.stl"]["status"] == "error" and got["x.stl"]["error"]["detail"] == {
        "rule": "format_not_enabled",
        "value": "3mf",
    }
    with WorkerPool(1, roots=[str(disguised)]) as pool:
        pooled = _by_path(scan(disguised, formats="stl", pool=pool).listing()["entries"])
    assert pooled["x.stl"]["error"]["detail"]["rule"] == "format_not_enabled"
    every = _by_path(scan(disguised, formats="all").listing()["entries"])
    assert every["x.stl"]["status"] == "ok" and every["x.stl"]["model"]["format"] == "3mf"


# --------------------------------------------------------------------------- the command line
def _run(capsys, *argv):
    code = cli.main([*argv, "--json"])
    out, err = capsys.readouterr()
    assert err == ""
    return code, json.loads(out)


def test_cli_reads_model_files(folder, capsys, tmp_path):
    stl = str(folder / "o02_boxA.STL")
    code, env = _run(capsys, "info", stl)
    assert code == 0 and env["kind"] == "model_summary" and env["data"]["counts"]["triangles"] == 12
    assert validate(env, model.envelope_schema("model_summary"), strict=True) == []
    code, env = _run(capsys, "props", stl)
    assert code == 0 and env["kind"] == "properties"
    code, env = _run(capsys, "configurations", stl)
    assert code == 0 and env["data"]["configurations"] == []
    code, env = _run(capsys, "preview", stl, "-o", str(tmp_path))
    assert code == 0 and env["data"]["source"] == "rendered" and env["data"]["mime"] == "image/png"
    assert (tmp_path / "o02_boxA.png").read_bytes().startswith(b"\x89PNG")
    code, env = _run(capsys, "preview", stl, "-o", str(tmp_path / "s.png"), "--stored")
    assert code == 1 and env["error"]["code"] == "no_preview"
    code, env = _run(capsys, "export", stl, "--format", "3mf", "-o", str(tmp_path / "a.3mf"))
    assert code == 0 and env["data"]["source_format"] == "stl" and env["data"]["closed"]
    code, env = _run(capsys, "export", str(folder / "assembly.stl"), "--format", "stl", "-o", str(tmp_path))
    assert code == 0 and env["data"]["output"].endswith("assembly.stl")
    assert validate(env, model.envelope_schema("export_result"), strict=True) == []


@pytest.mark.parametrize(
    "argv",
    [
        ("components",),
        ("references",),
        ("bom",),
        ("paths",),
        ("streams",),
        ("dump", "Contents", "-o", "x.bin"),
        ("parasolid", "-o", "."),
    ],
)
def test_cli_solidworks_only_commands_say_not_implemented(folder, capsys, argv):
    code, env = _run(capsys, argv[0], str(folder / "o02_boxA.STL"), *argv[1:])
    assert code == 1 and env["error"]["code"] == "not_implemented"
    assert env["error"]["detail"] == {"rule": "model_file", "value": "stl"}


def test_cli_refusals_for_model_files(folder, capsys, tmp_path):
    code, env = _run(capsys, "info", str(folder / "part.igs"))
    assert code == 1 and env["error"]["code"] == "format_not_supported"
    assert env["error"]["detail"] == {"rule": "needs_extension", "value": "iges"}
    assert "OCCT backend extension" in env["error"]["reader_message"]
    code, env = _run(capsys, "preview", str(fixture_path("o02_boxA.SLDPRT")), "-o", str(tmp_path), "--render")
    assert code == 1 and env["error"]["code"] == "not_implemented"
    code, env = _run(capsys, "info", str(folder / "o02_boxA.STL"), "--nested", "x")
    assert code == 2 and env["error"]["code"] == "invalid_argument"
    code, env = _run(capsys, "list", str(folder), "--formats", "nope")
    assert code == 2 and env["error"]["code"] == "invalid_argument"


def test_cli_list_with_formats(folder, capsys):
    code, env = _run(capsys, "list", str(folder), "--formats", "all", "--in-process")
    assert code == 0 and env["data"]["counts"]["unsupported"] == 2
    assert cli.main(["list", str(folder), "--formats", "stl,iges", "--in-process"]) == 0
    out = capsys.readouterr().out
    assert "STL binary part" in out and "IGES: IGES and BREP files open with the OCCT backend" in out
    assert "unsupported 1" in out


def test_cli_info_text(folder, capsys):
    assert cli.main(["info", str(folder / "solids.stl")]) == 0
    out = capsys.readouterr().out
    assert "STL (ascii)" in out and "mm (assumed)" in out and "units_assumed" in out


# --------------------------------------------------------------------------- the service
@pytest.fixture(scope="module")
def served(folder):
    running = Running({"mixed": folder}, workers=2, formats=("solidworks", "stl"))
    yield running
    running.close()


def test_rest_answers_for_model_files(served, folder):
    r = served.get("document", root="mixed", path="o02_boxA.STL")
    assert r.status == 200
    env = r.json()
    assert env["kind"] == "model_summary" and env["source"] == {"root": "mixed", "path": "o02_boxA.STL"}
    assert validate(env, model.envelope_schema("model_summary"), strict=True) == []
    r = served.get("properties", root="mixed", path="o02_boxA.STL")
    assert r.status == 200 and r.json()["data"]["properties"][0]["name"] == "header"
    r = served.get("preview", root="mixed", path="o02_boxA.STL")
    assert r.status == 200 and r.body.startswith(b"\x89PNG") and r.headers["content-type"] == "image/png"
    assert served.get("preview", root="mixed", path="o02_boxA.STL", render="never").status == 404
    for route in ("components", "references", "configurations", "path-report", "bom"):
        r = served.get(route, root="mixed", path="o02_boxA.STL")
        assert r.status == 501 and r.json()["error"]["detail"]["rule"] == "model_file", route
    r = served.get("preview", root="mixed", path="o02_boxA.SLDPRT", render="always")
    assert r.status == 501
    r = served.get("document", root="mixed", path="part.igs")  # not enabled: not a document here
    assert r.status == 403 and r.json()["error"]["detail"]["rule"] == "not_a_document"


def test_rest_listing_with_formats(served):
    data = served.get("list", root="mixed").json()["data"]
    assert [e["path"] for e in data["entries"]] == ["o02_boxA.SLDPRT"]
    data = served.get("list", root="mixed", formats="all").json()["data"]
    assert sorted(e["path"] for e in data["entries"]) == [
        "assembly.stl",
        "o02_boxA.SLDPRT",
        "o02_boxA.STL",
        "solids.stl",
    ]
    r = served.get("list", root="mixed", formats="step")
    assert r.status == 400 and r.json()["error"]["detail"]["parameter"] == "formats"


def test_a_default_service_refuses_model_files(folder):
    running = Running({"mixed": folder}, workers=1)
    try:
        r = running.get("document", root="mixed", path="o02_boxA.STL")
        assert r.status == 403 and r.json()["error"]["detail"]["rule"] == "not_a_document"
        assert running.get("list", root="mixed", formats="stl").status == 400
    finally:
        running.close()


def test_python_cli_and_rest_give_the_same_model_summary(served, folder, capsys):
    for name in ("o02_boxA.STL", "assembly.stl", "solids.stl"):
        with open_model(folder / name) as doc:
            python = doc.summary(include=model.MODEL_SUMMARY_PARTS)
        _code, cli_env = _run(capsys, "info", str(folder / name))
        rest_env = served.get("document", root="mixed", path=name).json()
        assert cli_env["data"] == python == rest_env["data"], name
        assert {k: v for k, v in cli_env.items() if k != "source"} == {
            k: v for k, v in rest_env.items() if k != "source"
        }


def test_a_scene_document_summary_is_consistent():
    doc = scene_document(two_object_assembly())
    assert doc.summary(include=("tree",))["tree"]["nodes"][0]["kind"] == "assembly"
