"""The picture of the part the assistant shows the AI when the person ticks "Show the AI a
picture of the part" (``docs/ASSISTANT.md``).

Off until ticked, and off for good where an administrator set ``DisableImages``
(:func:`allowed`). The picture is made by SolidSeas, never a file the person or the model
names: :func:`saved_picture` renders the part's file as it was last saved
(:func:`solidseas.render.render_preview` of the meshes 3D Print makes, white background,
the home view), and its caption says so, since changes not yet saved in SOLIDWORKS are not
in it. Making it reads the file read-only, as every SolidSeas read does, and takes a second
or two, so the window makes it on its worker thread.
"""

from __future__ import annotations

from solidseas import policy
from solidseas.ai.prompts import MAX_IMAGE_SIDE, PartImage, part_image

PICTURE_TEXT = "Show the AI a picture of the part"
PICTURE_TIP = (
    "Send a picture of the part, as it was last saved, beside the request, so the model sees its "
    "shape as well as its features. Off until you tick it."
)
ADMIN_OFF = "Set by your administrator: pictures are not sent."
CAPTION = "the part as it was last saved (changes not yet saved in SOLIDWORKS are not shown)"
SIDE = min(800, MAX_IMAGE_SIDE)  # pixels: enough to see the shape, a small share of the request


def allowed() -> bool:
    """Whether a picture may be sent at all (no ``DisableImages`` policy)."""
    return not policy.current().images_disabled


def saved_picture(path: str, *, side: int = SIDE) -> PartImage:
    """The part at ``path`` as last saved, rendered as a PNG at most ``side`` pixels a side
    (a SOLIDWORKS part through the meshes 3D Print makes, a model file from its own scene).
    Raises the library's errors (an unreadable file, a part with nothing to draw)."""
    from solidseas.formats import open_any
    from solidseas.render import render_preview

    doc = open_any(path)
    try:
        scene = doc if callable(getattr(doc, "scene", None)) else _scene_of(doc)
        rendered = render_preview(scene, width=side, height=side, background=(255, 255, 255))
    finally:
        close = getattr(doc, "close", None)
        if callable(close):
            close()
    return part_image(rendered.data, CAPTION)


def _scene_of(doc):
    """A SOLIDWORKS part's or assembly's meshes as a scene the renderer draws."""
    from solidseas.export import print_model
    from solidseas.formats.base import SCENE_COUNTS, MeshObject, Scene, SceneItem

    model = print_model(doc)
    objects = tuple(
        MeshObject(name=o.name, positions=o.positions, triangles=o.triangles) for o in model.objects
    )
    items = tuple(SceneItem(object=i.object, instance=i.instance, placement=i.placement) for i in model.items)
    return Scene(objects, items, {k: None for k in SCENE_COUNTS})


__all__ = ["ADMIN_OFF", "CAPTION", "PICTURE_TEXT", "PICTURE_TIP", "allowed", "saved_picture"]
