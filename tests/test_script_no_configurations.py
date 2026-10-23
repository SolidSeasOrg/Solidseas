"""scripts/corpus-no-configurations.py, run on a manifest of fixtures: it counts the
documents in which SolidSeas finds no configuration and what they hold, and prints no
name or path."""

import importlib.util
import json
from pathlib import Path

from builders import rebuild
from support import fixture_path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "corpus-no-configurations.py"


def _script():
    spec = importlib.util.spec_from_file_location("corpus_no_configurations", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_it_counts_the_documents_with_no_configuration_and_names_none(tmp_path, monkeypatch, capsys):
    bare = tmp_path / "secret-name.SLDPRT"
    carriers = ("swXmlContents/Features", "swXmlContents/KeyWords", "swXmlContents/MATERIALTREE")
    bare.write_bytes(rebuild(fixture_path("o02_boxA.SLDPRT"), drop=carriers))
    manifest = tmp_path / "manifest.csv"
    rows = [
        str(fixture_path(n))
        for n in ("o02_boxA.SLDPRT", "o06_boxA_props_mat_cfg.SLDPRT", "o15_sub_asm.SLDASM")
    ]
    rows += [str(bare), str(fixture_path("o18_drw_boxA.SLDDRW"))]  # a drawing is not counted
    manifest.write_text("path,format\n" + "".join(f"{r},modern\n" for r in rows), encoding="utf-8")
    monkeypatch.setenv("SOLIDSEAS_CORPUS_MANIFEST", str(manifest))
    assert _script().main(["--json"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["totals"]["documents"] == 4 and data["totals"]["with configurations"] == 3
    assert data["totals"]["without configurations"] == 1
    assert sum(data["patterns"].values()) == 1
    assert "secret-name" not in out and str(tmp_path) not in out


def test_without_a_manifest_it_says_what_to_set(monkeypatch, capsys):
    monkeypatch.delenv("SOLIDSEAS_CORPUS_MANIFEST", raising=False)
    assert _script().main([]) == 2
    assert "SOLIDSEAS_CORPUS_MANIFEST" in capsys.readouterr().err
