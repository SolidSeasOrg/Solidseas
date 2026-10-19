"""The scene and head contract the mesh readers share (``docs/API.md`` 3.20.4,
``docs/formats/mesh.md``): a scene cut by ``max_triangles`` keeps and places the
objects finished before the cut, placements that fan out are counted and timed and a
tree stops at ``limits.tree_nodes``, and the 3MF and AMF heads read the first 64 KiB
alone, a full read settling what they leave unknown."""

import io
import time
import zipfile

import pytest

import mesh_writers as mw
from model_writers import Item, Mesh, Scene, box, two_object_assembly
from solidseas.errors import SldLimitError
from solidseas.formats import Limits, open_model
from support import within


def _five_boxes() -> Scene:
    """Five boxes of 12 triangles, each its own mesh placed once, 20 mm apart."""
    return Scene(
        [box(10, 10, 10, origin=(20.0 * k, 0.0, 0.0), name=f"box{k}") for k in range(5)],
        [Item(k) for k in range(5)],
    )


def _files() -> dict[str, bytes]:
    scene = _five_boxes()
    obj, _ = mw.obj(scene, mtl=None)
    gltf, _ = mw.gltf(scene)
    return {
        "a.3mf": mw.threemf(scene, colors=None),
        "p.3mf": mw.threemf(scene, colors=None, production=True),
        "a.obj": obj,
        "a.gltf": gltf,
        "a.amf": mw.amf(scene, constellation=False),
        "c.amf": mw.amf(scene),
        "z.amf": mw.amf(scene, zipped=True),
    }


FILES = _files()


# --------------------------------------------------------------------------- max_triangles
@pytest.mark.parametrize("name", sorted(FILES))
def test_max_triangles_keeps_and_places_the_objects_finished_before_the_cut(name):
    with open_model(FILES[name], name=name) as doc:
        whole = doc.scene()
        s = doc.scene(max_triangles=30)
    assert whole.truncated == () and whole.counts["items"] == 5
    assert s.truncated == ("max_triangles",)
    # two boxes fit in 30 triangles; the third, read when the cap was passed, is dropped
    assert s.counts["objects"] == 2 and s.counts["items"] == 2 and s.counts["triangles"] == 24
    assert all(o.n_triangles == 12 for o in s.objects)
    placed = sorted(
        s.objects[it.object].measures()["box"][0][0] + it.placement.translation_m[0] for it in s.items
    )
    assert placed == pytest.approx([0.0, 0.02])
    assert not s.skipped and "component_not_found" not in mw.codes(s.warnings)


@pytest.mark.parametrize("name", ["s.ply", "s.off", "s.stl"])
def test_a_file_of_one_object_keeps_nothing_when_cut(name):
    scene = _five_boxes()
    from model_writers import stl_binary

    data = {"s.ply": mw.ply(scene), "s.off": mw.off(scene), "s.stl": stl_binary(scene)}[name]
    with open_model(data, name=name) as doc:
        s = doc.scene(max_triangles=30)
    assert s.truncated == ("max_triangles",) and s.counts["objects"] == 0 and s.counts["items"] == 0


def _grid(n: int, name: str, x0: float = 0.0) -> Mesh:
    """A flat n x n grid of 2 n^2 triangles at x0."""
    v = [(x0 + i, float(j), 0.0) for i in range(n + 1) for j in range(n + 1)]
    t = []
    for i in range(n):
        for j in range(n):
            a = i * (n + 1) + j
            t += [(a, a + n + 1, a + 1), (a + 1, a + n + 1, a + n + 2)]
    return Mesh(name, v, t)


def test_a_cut_inside_a_large_3mf_object_keeps_the_ones_before_it():
    scene = Scene(
        [_grid(46, f"g{k}", 100.0 * k) for k in range(3)], [Item(k) for k in range(3)]
    )  # 4,232 each
    with open_model(mw.threemf(scene, colors=None), name="g.3mf") as doc:
        s = doc.scene(max_triangles=6000)
    assert s.truncated == ("max_triangles",)
    assert (s.counts["objects"], s.counts["items"], s.counts["triangles"]) == (1, 1, 4232)


def test_a_cut_keeps_every_placement_of_a_finished_object():
    # the box (12 triangles) is placed twice; the holed block (32) passes the cap
    with open_model(mw.threemf(two_object_assembly()), name="t.3mf") as doc:
        s = doc.scene(max_triangles=20)
    assert s.truncated == ("max_triangles",)
    assert s.counts["objects"] == 1 and s.counts["items"] == 2 and s.counts["triangles"] == 24


# --------------------------------------------------------------------------- fan-out
def _threemf_fan(depth: int, fan: int) -> bytes:
    cube = mw.threemf_mesh_xml(box(1, 1, 1), 1)
    objs = [cube]
    for k in range(2, depth + 2):
        comps = "".join(
            f'<component objectid="{k - 1}" transform="1 0 0 0 1 0 0 0 1 {2 * j} 0 0"/>' for j in range(fan)
        )
        objs.append(f'<object id="{k}" type="model"><components>{comps}</components></object>')
    build = f'<build><item objectid="{depth + 1}"/></build>'
    return mw.threemf(
        Scene([box(1, 1, 1)], []), colors=None, resources_extra="".join(objs[1:]), build_xml=build
    )


def _amf_fan(depth: int, fan: int, leaf: str = "c0") -> bytes:
    cs = ['<constellation id="c0"></constellation>']
    for k in range(1, depth + 1):
        inner = "".join(
            f'<instance objectid="{leaf if k == 1 else f"c{k - 1}"}"><deltax>{j}</deltax></instance>'
            for j in range(fan)
        )
        cs.append(f'<constellation id="c{k}">{inner}</constellation>')
    cube = mw.amf(Scene([box(1, 1, 1)], [Item(0)]), constellation=False).decode()
    return cube.replace("</amf>", "".join(cs) + "</amf>").encode()


def test_a_3mf_tree_stops_at_tree_nodes_however_far_components_fan_out():
    data = _threemf_fan(6, 10)  # a million placements from a package of about a kilobyte
    with open_model(data, name="f.3mf", limits=Limits(tree_nodes=50)) as doc:
        t0 = time.perf_counter()
        tree = doc.tree()
        assert time.perf_counter() - t0 < within(2.0)
        assert tree.truncated and len(tree.nodes) == 50
    with open_model(data, name="f.3mf", limits=Limits(items=5_000)) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "items"


def test_amf_constellations_that_fan_out_are_counted_and_timed():
    data = _amf_fan(7, 10)  # ten million placements of empty constellations, from 5 KB
    assert len(data) < 8_000
    with open_model(data, name="f.amf", limits=Limits(items=5_000)) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
        assert exc.value.detail["limit"] == "items"
    with open_model(data, name="f.amf") as doc:
        t0 = time.perf_counter()
        with pytest.raises(SldLimitError) as exc:
            doc.scene(max_seconds=0.3)
        assert exc.value.detail["limit"] == "seconds" and time.perf_counter() - t0 < within(2.0)
    with open_model(data, name="f.amf", limits=Limits(tree_nodes=50)) as doc:
        t0 = time.perf_counter()
        tree = doc.tree()
        assert tree.truncated and len(tree.nodes) == 50 and time.perf_counter() - t0 < within(2.0)
    with open_model(_amf_fan(3, 10, leaf="0"), name="o.amf") as doc:
        s = doc.scene()
        assert s.counts["items"] == 1_000 and s.counts["triangles"] == 12_000


# --------------------------------------------------------------------------- heads
def _long_3mf(items: int) -> bytes:
    """A 3MF whose root model is far longer than 64 KiB (a 60 x 60 grid), placed ``items`` times."""
    scene = Scene([_grid(60, "grid")], [Item(0, translation_mm=(100.0 * k, 0.0, 0.0)) for k in range(items)])
    return mw.threemf(scene, colors=None)


@pytest.mark.parametrize(("items", "doc_type"), [(1, "part"), (2, "assembly")])
def test_a_long_3mf_head_leaves_the_type_to_a_full_read(items, doc_type):
    data = _long_3mf(items)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert z.getinfo("3D/3dmodel.model").file_size > 4 * 64 * 1024
    with open_model(data, name="l.3mf") as doc:
        assert doc.doc_type is None
        assert doc.counts()["objects"] is None and doc.counts()["items"] is None
        doc.tree()
        assert doc.doc_type == doc_type
        assert doc.counts()["objects"] == 1 and doc.counts()["items"] == items
    with open_model(data, name="l.3mf") as doc:
        doc.scene()
        assert doc.doc_type == doc_type
    # the head reads 64 KiB of the model, so a bound the whole model passes does not stop it
    limits = Limits(zip_member_bytes=256 * 1024)
    with open_model(data, name="l.3mf", limits=limits) as doc:
        with pytest.raises(SldLimitError) as exc:
            doc.scene()
    assert exc.value.detail["limit"] == "zip_member_bytes"


def test_a_short_3mf_head_settles_type_and_counts():
    with open_model(mw.threemf(two_object_assembly()), name="s.3mf") as doc:
        assert doc.doc_type == "assembly" and doc.counts()["items"] == 3 and doc.counts()["objects"] == 2


@pytest.mark.parametrize("zipped", [False, True])
def test_a_long_amf_head_leaves_the_type_to_a_full_read(zipped):
    scene = Scene([_grid(60, "grid")], [Item(0), Item(0, translation_mm=(100.0, 0.0, 0.0))])
    data = mw.amf(scene, zipped=zipped)
    with open_model(data, name="l.amf") as doc:
        assert doc.doc_type is None
        assert len(doc.tree().nodes) == 4
        assert doc.doc_type == "assembly"
    with open_model(mw.amf(scene, zipped=zipped, constellation=False), name="p.amf") as doc:
        assert doc.doc_type is None
        assert doc.scene().counts["items"] == 1
        assert doc.doc_type == "part"
    if zipped:
        with open_model(data, name="l.amf", limits=Limits(zip_member_bytes=512 * 1024)) as doc:
            with pytest.raises(SldLimitError):
                doc.scene()
