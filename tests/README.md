# Tests

```bash
python -m pytest -q
python -m ruff check .
```

The default suite needs nothing but the `dev` extra and runs on Linux and Windows
(`.github/workflows/ci.yml`). Some tests are opt-in: they skip unless an
environment variable points them at something outside the repository.

| Variable | Tests | What it names |
|---|---|---|
| `SOLIDSEAS_CORPUS_MANIFEST` | `test_corpus*.py`, `test_*_corpus.py`, `test_fixture_paths.py` (corpus names) | the private corpus manifest (`AGENTS.md`, scrub rules) |
| `SOLIDSEAS_OCCT_PYTHON` | `test_occt_oracle.py`, and with the manifest `test_occt_corpus.py`; `test_occt_backend.py`'s run of the OCCT backend's helper | an interpreter where `import OCP` works: the OCCT oracle, below |
| `SOLIDSEAS_SW_TRUTH` | `test_occt_corpus.py` | SOLIDWORKS' own measurements of corpus parts, keyed by manifest row |

`tests/fixtures/README.md` describes the fixtures and their ground truth.

## The OCCT oracle

Open CASCADE (OCCT) is an independent B-rep kernel. The oracle tests use it to
read the STEP files SolidSeas writes and the ones SolidSeas reads, and to measure
them exactly: a second opinion on the STEP export (what goes to suppliers and to
the 3D printer) and on the STEP reader (what the viewer shows and prints).
SolidSeas itself never imports OCCT; `tests/test_occt_support.py` checks that on
every run.

### Setting it up

OCCT comes from the `cadquery-ocp` wheel, which provides the `OCP` bindings. Any
interpreter of Python 3.11 or newer where `import OCP` works will do; a
CadQuery environment has one. In a separate virtual environment:

```powershell
python -m venv occt-venv
occt-venv\Scripts\python -m pip install cadquery-ocp==7.9.3.1.1
```

The wheel also installs VTK (about 330 MB with OCCT itself). The tests were
measured with `cadquery-ocp` 7.9.3.1.1 (OCCT 7.9.3), and
`test_the_ocp_version_is_the_pinned_one` fails on any other version until
`PINNED` in `occt_support.py` is moved, after the tiers pass with the new one.

### Running it

```powershell
$env:SOLIDSEAS_OCCT_PYTHON = "C:\path\to\occt-venv\Scripts\python.exe"
python -m pytest -q -m occt
```

(On Linux, `export SOLIDSEAS_OCCT_PYTHON=/path/to/occt-venv/bin/python`.)

`-m occt` selects the oracle tests (marker `occt`). With the variable set they
also run as part of the whole suite. Without it, or when `import OCP` fails in that
interpreter, they skip and say why. The fixture and reader tiers take about three
minutes.

The corpus tiers also need the manifest, and print their numbers with `-s`:

```powershell
$env:SOLIDSEAS_CORPUS_MANIFEST = "C:\path\to\manifest.csv"
$env:SOLIDSEAS_SW_TRUTH = "C:\path\to\corpus.json"
python -m pytest -q -s tests/test_occt_corpus.py
```

| Variable | Default | Meaning |
|---|---|---|
| `SOLIDSEAS_SW_TRUTH` | unset | SOLIDWORKS' measurements (the `sw_oracle` job's `corpus.json`); its rows are the parts exported, and volume and area are compared |
| `SOLIDSEAS_OCCT_CORPUS_SAMPLE` | 175 | without the truth, how many parts to export (`random.Random(20261004)`) |
| `SOLIDSEAS_OCCT_STEP_SAMPLE` | 40 | how many corpus STEP files the reader tier reads |
| `SOLIDSEAS_OCCT_STEP_MAX_MB` | 5 | the largest STEP file sampled |
| `SOLIDSEAS_OCCT_STEP_KEYS` | none | `step#N` keys to read as well, such as `38,1389` |
| `SOLIDSEAS_CORPUS_WORKERS` | 3 | files in parallel |

### The tiers

- **The pin.** The OCP and OCCT versions are the pinned ones, and every reply
  records them.
- **STEP export, fixtures** (`test_occt_oracle.py`). Every configuration of every
  fixture part with bodies is exported by SolidSeas and read by OCCT's basic
  `STEPControl_Reader`. The checks:
  - the read is done and every root is transferred;
  - no load or transfer check fails;
  - the only healing message allowed is "Missing seam-edge added", for a closed
    periodic face SolidSeas still writes whole (it cuts the others at their
    seams, and no fixture now gets it);
  - the solids are the ones SOLIDWORKS counts, and the faces the ones SolidSeas
    wrote;
  - every shell is closed, no edge is free and `BRepCheck_Analyzer` finds the
    shape valid;
  - the Gauss-Kronrod volume and the adaptive area are within 1e-12 of
    `ground_truth.json`, the centre of mass within 1e-12 of the box's diagonal,
    and the box within 1e-8 of it;
  - OCCT's own fine mesh agrees with its integrators within 1e-4.

  SOLIDWORKS' STEP of o02 passes the same checks, as a control.
- **STEP export, synthetic bodies.** Two Parasolid bodies the fixtures lack, built
  by code (`xt_bodies.py`) and exported through the same mapper:
  - a cube with a cavity, written as a `BREP_WITH_VOIDS`: OCCT reads the cavity's
    shell at -1,000 cubic millimetres and the solid exactly, and SolidSeas' reader
    of the file pairs its own void piece with it, of the same sign;
  - a part of one sheet, which File > Export STEP sends as its sheet: one free
    shell, valid, its area exact.

  OCCT orients a void by its geometry whatever the file says, so it alone cannot
  see a cavity written inside out. The pairing above can, and so can
  `test_step.py`, which reads the void's orientation in the file itself as
  ISO 10303-42 does, on every run.
- **The reader.** SolidSeas' STEP reader against OCCT, tessellated at a
  2 micrometre chord, on every synthetic file of `occt_shapes.SHAPES`, on
  SolidSeas' STEP of every fixture and of the synthetic bodies, and on
  SOLIDWORKS' STEP of o02:
  - each face pairs with an OCCT face and is within 3e-3 of its area;
  - each closed piece of the mesh pairs with the OCCT shell at its place and has
    its sign and volume;
  - the totals agree within 3e-3;
  - no edge of a solid is open or used twice the same way;
  - no face is skipped.

  A face is never larger than the whole surface it lies on.
- **As the viewer and 3D Print draw them.** The viewer draws a STEP at 1e-3 of
  its box diagonal, and 3D Print tessellates it at 2.5e-4 of the diagonal, at most
  10 micrometres. Both are far coarser than the reader tier's chord, and whether a
  solid comes out open or a face folded depends on the chord. So the same files
  are read as each draws them (`occt_support.DRAWN`, from the library's own
  constants), and checked for what no chord excuses: no face larger than
  its surface, no shell inside out, no edge of a solid open or used twice the same
  way, no face skipped.
- **The defects.** `occt_shapes.DEFECTS` reproduces, in files written by code,
  the reader defects the oracle found in real files: a void whose shell already
  faces into it (bead 1) and faces whose loops run against them (bead 3). OCCT
  reads each to its true volume, and the reader agrees. That test was marked as an
  expected failure (`xfail`, strict) until the reader's fixes landed; the mark came
  off with them. A defect found later gets the same mark until its fix lands.
- **Corpus, STEP export** (`test_occt_corpus.py`). The same structure checks on
  SolidSeas' STEP of private parts, made as File > Export STEP makes it: the solid
  bodies, or, for a part with no solid, its sheets, which are then what goes to a
  supplier. Then:
  - SolidSeas' own reader reads each file back, and every shell it finds must have
    the sign of OCCT's shell at its place;
  - against SOLIDWORKS, the volume and the area are compared within 1e-3; for a
    part of sheets, the sheet area and the box of all bodies. A part with hidden
    bodies is compared by volume and area like the others now that the export
    leaves them out; one whose STEP still holds more solids than SOLIDWORKS
    shows is compared by the box of all bodies.

  The rows OCCT finds invalid for a cause outside SolidSeas' mapping are listed in
  `KNOWN_INVALID`, and two parts of one degenerate sheet in
  `KNOWN_DEGENERATE_SHEETS`.
- **Corpus, STEP reader.** The reader against OCCT within 1 % on a sample of the
  corpus STEP files, plus every file of `KNOWN_KEYS`, where the oracle has found
  the reader wrong, grouped by the bead that fixes them, and the files with voids
  the reader reads right (`VOIDS_READ_RIGHT`), which bead 1 must keep right. The
  kinds no chord excuses are also looked for as the viewer and 3D Print draw
  each file. It
  reports what disagrees by kind and key, which known files agree now and which
  sampled ones are new, and asserts only that SolidSeas never failed and no file
  changed.

### How OCCT is measured

The defaults are not good enough. OCCT's default `BRepGProp.VolumeProperties` and
`SurfaceProperties` were wrong by up to 8.6 % on volume and 4.5 % on area on
B-spline-heavy corpus parts. So the child measures:

- volume with `VolumePropertiesGK` (eps 1e-9, spans split, centre of mass), once
  per shell, a void's volume coming out negative;
- area with `SurfaceProperties` at eps 1e-9;
- a fine mesh of its own, as a check on both.

Even so, the adaptive area of the side of an elliptic prism (a surface of linear
extrusion) is 1.2 % high. And a mesh whose deflection is set by the part's size
(the corpus tier's) is coarse beside a small fillet. So the reader tier counts a
SolidSeas face as agreeing with OCCT when it agrees with either OCCT measure, the
adaptive area or the mesh area, and counts the faces where the two disagree
(`occt_unsure`). The reader's defects put a face far from both.

On a cylinder, sphere or torus a face may also fall short by its own
tessellation's error. A polygon whose sagitta is the chord falls short of its
arc by about a third of the chord over the radius, so the allowance is one and a
half times that for each direction in which the surface curves (one for a
cylinder, two for a sphere or a torus, over its smallest radius). A torus fillet
of 0.05 mm drawn at a 1.6 micrometre chord is 1.1 % short, and right. The
allowance is one-sided: a polygon is never larger than its surface, so a face
larger than OCCT's by more than the tolerance is wrong whatever the chord.

Shells pair by place as faces do: by their centroids, within 5 % of the box
diagonal, then by size. A piece OCCT has no shell for, or the other way round, is
counted, and does not pair the rest with unrelated shells.

Some synthetic files are left out because OCCT cannot referee them, though
SolidSeas reads them (`occt_shapes.py` names them):

- edges stored only as pcurves;
- composite-curve edges;
- a seam curve without pcurves;
- an assembly placed by mapped items.

### The process model

OCCT is not safe on every file. On damaged files it crashed on about one STEP in
seven, and under memory pressure it dies with an access violation. So it runs
only in `occt_child.py`, a child process that imports the standard library and
OCP alone, started by `occt_support.run_child`:

- **Windows.** The child is created with a quiet error mode: no error box, and no
  Windows Error Reporting, so a crash writes no dump even where LocalDumps is on.
  It starts suspended inside a Job Object with:
  - `KILL_ON_JOB_CLOSE`;
  - `DIE_ON_UNHANDLED_EXCEPTION`;
  - a memory cap per process;
  - at most two processes (a venv's launcher and its interpreter);
  - below-normal priority.

  Only then is it resumed.
- **Elsewhere.** The child runs in a session of its own with `RLIMIT_AS`, no core
  file and `nice` 10.
- **Every call** has a timeout, after which the whole job is killed.
- **The request** goes in on standard input.
- **The answer** comes back as one line, read strictly. The child's other output,
  and OCCT's own messages, which can quote the file, never reach the tests; of
  standard error only an exception's class name is kept.

The corpus tiers run SolidSeas' side in a child of the same kind
(`occt_solidseas_child.py`), so that a slow or huge private file never stalls
the test process.

### Private files

The corpus tiers follow `AGENTS.md`:

- **Read-only.** Private files are opened read-only, at below-normal priority, and
  each one's size and modification time are checked after.
- **Keys.** Parts are keyed by manifest row. STEP files are keyed `step#N`, the
  N-th (from 0) in sorted-path order among the STEP files in the folders that
  hold manifest rows and below them, SolidSeas' own checkouts left out. This
  numbering is the one the OCCT evaluation used; `test_formats_step_corpus.py`
  reads the manifest folders without going below them.
- **Nothing kept.** No name, path or text is printed or kept. A STEP file
  exported from a private part is written to a temporary folder and deleted as
  soon as OCCT and SolidSeas' reader have read it, and the PRODUCT inside it is
  named after the row.
