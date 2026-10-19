"""The pictures of the part the assistant shows the AI when the person ticks "Show the AI a
picture of the part", and, in Automatic mode, "Show it the part after each step"
(``docs/ASSISTANT.md``).

Off until ticked, and off for good where an administrator set ``DisableImages``
(:func:`allowed`, read again before every picture). Every picture is made by SolidSeas,
never a file the person or the model names, and is drawn the same way (:func:`drawn`:
:func:`solidseas.render.render_preview` of the meshes 3D Print makes, white background,
the home view). Making one reads a file read-only, as every SolidSeas read does, and takes
a second or two, so it is made on a worker thread.

* :func:`saved_picture`: the part's file as it was last saved, sent beside a draft or a
  plan. Its caption says so, since changes not yet saved in SOLIDWORKS are not in it.
* :class:`CopyPictures`: the part after a step of an Automatic run. The bridge writes a
  copy of the part as it is now, unsaved changes included, into the run's folder (the
  same silent copy as the safety copy), and that copy is drawn.
* :class:`ModelLook` and :class:`PictureLook` look at the part after each step of a run
  (:data:`.run.LookAfterStep`): the first asks the person's own AI whether the part looks
  as the step should leave it, the second only makes the picture, for a chat through the
  MCP server whose model looks at it itself.

SOLIDWORKS' own view of the part, through the bridge, is not built yet: it needs a
``live_capture`` operation in the bridge, measured in SOLIDWORKS. When it is, it becomes a
second :class:`PictureSource`, tried first, with the pictures drawn here kept as the
fallback.
"""

from __future__ import annotations

import os
import time
from typing import Any, Protocol

from solidseas import policy
from solidseas.ai.base import CallOptions
from solidseas.ai.http import Cancel
from solidseas.ai.prompts import MAX_IMAGE_SIDE, PartImage, part_image

from .run import StepLook, StepRecord, step_text

PICTURE_TEXT = "Show the AI a picture of the part"
PICTURE_TIP = (
    "Send a picture of the part, as it was last saved, beside the request, so the model sees its "
    "shape as well as its features. Off until you tick it."
)
STEP_TEXT = "Show it the part after each step"
STEP_TIP = (
    "Automatic mode: after each step passes SolidSeas' own checks, SolidSeas saves a copy of the part "
    "in the run's folder, draws it, and asks the model whether the part looks as the step should leave "
    "it. If the model says it does not, the run stops after that step, for you to Keep or Revert. "
    "Each look is one more request to the AI, with the picture. Off until you tick it."
)
STEP_NEEDS_PICTURE = "Tick Show the AI a picture of the part first."
ADMIN_OFF = "Set by your administrator: pictures are not sent."
CAPTION = "the part as it was last saved (changes not yet saved in SOLIDWORKS are not shown)"
NO_LOOKS = "This AI provider does not look at pictures."
SIDE = min(800, MAX_IMAGE_SIDE)  # pixels: enough to see the shape, a small share of the request


def allowed() -> bool:
    """Whether a picture may be sent at all (no ``DisableImages`` policy)."""
    return not policy.current().images_disabled


def step_caption(index: int | str) -> str:
    return (
        f"the part after step {index}, drawn from a copy SolidSeas saved after the step "
        "(changes not yet saved in SOLIDWORKS are included)"
    )


def saved_picture(path: str, *, side: int = SIDE) -> PartImage:
    """The part at ``path`` as last saved (see :func:`drawn`)."""
    return drawn(path, CAPTION, side=side)


def drawn(path: str, caption: str, *, side: int = SIDE) -> PartImage:
    """The part or model file at ``path`` rendered as a PNG at most ``side`` pixels a side
    (a SOLIDWORKS part through the meshes 3D Print makes, a model file from its own scene),
    with ``caption``. Raises the library's errors (an unreadable file, a part with nothing
    to draw)."""
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
    return part_image(rendered.data, caption)


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


# --------------------------------------------------------------------------- after each step
class PictureSource(Protocol):
    """Where the picture of the part after a step of a run comes from."""

    def after_step(self, index: int) -> PartImage:
        """The part as step ``index`` left it. Raises when no picture can be made."""
        ...


class CopyPictures:
    """The part after each step, drawn from a copy the bridge writes then
    (``live_checkpoint``: ``SaveAs3`` with the copy and silent options, which leaves the
    open part, its path, its unsaved state and its undo list alone). The copy goes into the
    run's folder as ``checkpoint-<run id>-step-<k>.sldprt``, the only names the bridge
    writes, and stays there with the safety copy and the journal. ``live`` is the session
    object (:class:`.live_sessions.BridgeSessions`)."""

    def __init__(self, live: Any, session: Any, document: Any, folder: str, run_id: str) -> None:
        self.live = live
        self.session = session
        self.document = document
        self.folder = folder
        self.run_id = run_id

    def copy_path(self, index: int) -> str:
        return os.path.join(self.folder, f"checkpoint-{self.run_id}-step-{int(index)}.sldprt")

    def after_step(self, index: int) -> PartImage:
        path = self.copy_path(index)
        self.live.write_checkpoint(self.session, self.document, path)
        return drawn(path, step_caption(index))


def _pictures_allowed() -> None:
    if not allowed():
        raise RuntimeError(ADMIN_OFF)


class ModelLook:
    """The window's look after each step (:data:`.run.LookAfterStep`): the picture, then the
    person's own AI asked whether the part looks as the step should leave it
    (``check_step``), with the run's ``goal``, the step as the Plan panel shows it and
    nothing else from the part. The calls share the run's token ``budget``. The machine
    policy is read again before every picture."""

    def __init__(self, provider: Any, pictures: PictureSource, goal: Any, count: int, *, budget: Any = None):
        self.provider = provider
        self.pictures = pictures
        self.goal = goal
        self.count = count
        self.budget = budget

    def __call__(self, record: StepRecord, cancel: Cancel, seconds_left: float) -> StepLook:
        _pictures_allowed()
        step = record.step
        image = self.pictures.after_step(step.index)
        call = CallOptions(cancel=cancel, deadline=time.monotonic() + seconds_left, run_budget=self.budget)
        shown = step_text(step)
        result = self.provider.check_step(self.goal, shown, step.index, self.count, image, call=call)
        if result is None:
            raise RuntimeError(NO_LOOKS)
        look = result.value
        return StepLook(
            look.as_expected,
            look.reason,
            image,
            {
                "prompt": result.prompt.text(),
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        )


class PictureLook:
    """The picture after each step and no judgment (:data:`.run.LookAfterStep`): for a chat
    through the MCP server, whose own model looks at the pictures ``run_plan`` returns."""

    def __init__(self, pictures: PictureSource) -> None:
        self.pictures = pictures

    def __call__(self, record: StepRecord, cancel: Cancel, seconds_left: float) -> StepLook:
        _pictures_allowed()
        image = self.pictures.after_step(record.step.index)
        return StepLook(None, "A picture was made for the chat.", image)


__all__ = [
    "ADMIN_OFF",
    "CAPTION",
    "NO_LOOKS",
    "PICTURE_TEXT",
    "PICTURE_TIP",
    "STEP_NEEDS_PICTURE",
    "STEP_TEXT",
    "STEP_TIP",
    "CopyPictures",
    "ModelLook",
    "PictureLook",
    "PictureSource",
    "allowed",
    "drawn",
    "saved_picture",
    "step_caption",
]
