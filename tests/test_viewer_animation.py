"""Save Animation's plan (``solidseas_app.viewer.animation``): what each frame shows."""

import pytest

from solidseas_app.viewer.animation import AnimationOptions, OptionsError, ease, frames, with_format

CAMERA = {"yaw": 45.0, "pitch": 35.26, "half_height": 0.1, "target": [0.0, 0.0, 0.0], "fitted": True}


def test_the_camera_circles_the_model_and_the_assembly_explodes_and_collapses():
    o = AnimationOptions(seconds=2, fps=10)
    fs = frames(o, CAMERA)
    assert len(fs) == 20 and fs[0].yaw == 45.0
    assert fs[-1].yaw == pytest.approx((45.0 - 360.0) % 360.0), "clockwise, the whole way round"
    assert {f.pitch for f in fs} == {35.26} and all(f.half_height == pytest.approx(0.1) for f in fs)
    amounts = [f.explode for f in fs]
    assert amounts[0] == 0.0 and amounts[-1] == 0.0 and max(amounts) == pytest.approx(1.0)
    peak = amounts.index(max(amounts))
    assert all(a <= b for a, b in zip(amounts[:peak], amounts[1 : peak + 1], strict=True)), "it eases out"
    assert all(a >= b for a, b in zip(amounts[peak:-1], amounts[peak + 1 :], strict=True)), "and back"


def test_zoom_pan_direction_and_no_explode():
    o = AnimationOptions(
        seconds=1, fps=5, orbit_degrees=90, clockwise=False, zoom=2.0, pan=(0.5, 0.0), explode=0
    )
    fs = frames(o, CAMERA)
    assert fs[-1].yaw == pytest.approx(135.0) and fs[-1].half_height == pytest.approx(0.05)
    assert all(f.explode == 0.0 for f in fs)
    assert fs[0].target == (0.0, 0.0, 0.0) and fs[-1].target != fs[0].target


@pytest.mark.parametrize(
    "bad",
    [
        {"seconds": 0},
        {"seconds": 61},
        {"fps": 4},
        {"fps": 30.0},
        {"size": "4k"},
        {"zoom": 0},
        {"explode_from": 0.8, "collapse_from": 0.2},
        {"background": "white"},
        {"format": "avi"},
        {"pan": (3.0, 0.0)},
    ],
)
def test_options_out_of_range_are_refused(bad):
    with pytest.raises(OptionsError):
        AnimationOptions(**bad)


def test_the_format_follows_the_file_name():
    assert with_format(AnimationOptions(), "turntable.GIF").format == "gif"
    assert with_format(AnimationOptions(format="gif"), "clip.mp4").format == "mp4"
    assert ease(-1) == 0.0 and ease(2) == 1.0 and ease(0.5) == 0.5


def test_an_exploding_clip_zooms_out_once_to_keep_the_exploded_assembly_in_the_picture():
    from solidseas_app.viewer.animation import steady_framing

    plan = frames(AnimationOptions(seconds=1, fps=10), CAMERA)
    # exploded all the way the assembly needs twice the height from every side, and its box
    # centre moves down by 0.05 as it explodes
    framed = steady_framing(plan, lambda yaw, pitch, a: 0.1 * (1 + a), lambda a: (0.0, 0.0, -0.05 * a))
    peak = max(f.explode for f in plan)
    assert {round(f.half_height, 9) for f in framed} == {round(0.1 * (1 + peak), 9)}, "one zoom, no pumping"
    for f, g in zip(plan, framed, strict=True):
        assert g.target[2] == pytest.approx(f.target[2] - 0.05 * f.explode)
        assert (g.yaw, g.explode) == (f.yaw, f.explode)
    still = frames(AnimationOptions(seconds=1, fps=10, explode=0), CAMERA)
    assert steady_framing(still, lambda *a: pytest.fail("no fit is needed"), lambda a: (0, 0, 0)) == still
