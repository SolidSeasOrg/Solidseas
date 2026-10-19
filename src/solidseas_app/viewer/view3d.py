"""The 3D view: a part's or an assembly's saved display meshes drawn with OpenGL.

Only used when Settings > Interactive 3D View is on: the first 3D view in a
window switches Qt to OpenGL compositing for that window, and reading a large
display mesh takes time, so the viewer never does either unless asked.

:class:`Renderer` holds the GPU side (one shader program and, for each mesh, a
position, a normal and an index buffer and two buffers of its instances'
matrices and colours, through Qt's ``QOpenGLShaderProgram``, ``QOpenGLBuffer``
and ``QOpenGLVertexArrayObject``) and draws with simple lighting from the
stored normals; a face stored without normals is lit from its own plane. A
:class:`Scene` is what it draws: a part is one mesh with one instance, an
assembly one mesh per component file with every instance of it. Each mesh is
uploaded once; where the context has instanced drawing (OpenGL 3.3, OpenGL ES
3.0) all of a mesh's instances are one draw call, each taking its matrix and
colour from the instance buffers, and elsewhere each instance is drawn in turn
with them set as constant attributes. The exploded view (:mod:`.explode`) adds
a third instance buffer, each instance's offset when fully exploded, which the
vertex shader scales by the explode amount, a uniform: exploding and collapsing
upload nothing per frame, and the placements themselves never change.

An instance the assembly has no mesh for, but stores a box for, is drawn as that
box (:data:`BOX_MESH`, a unit cube each such instance's matrix takes to its box,
:class:`.mesh3d.BoxBuffers`): one more mesh of the scene, the last, whose
instances explode, pick and take the picked and faded states like any other.
Only its look differs, so it cannot pass for real geometry: after the meshes
its faces are drawn light grey and translucent, blended over what is behind
them without hiding it, with its edges as dark lines (light ones on the dark
background), on both drawing paths; a box the user made transparent fades its
edges as well.

Each instance also has a look, the user's choice (:mod:`.appearance`): its
opacity and whether it is hidden, a fourth instance buffer. A hidden instance is
left out of every pass: the vertex shader puts it outside the view on the
instanced path, and the one-by-one path skips it (the instances it draws are
kept as the looks change, so a frame does not test each one). A frame draws the
opaque instances first, writing depth; then what is blended over them without
writing depth, pulled a little toward the eye so a face lying on an opaque one
never speckles against it. With no transparent instance that is the boxes
alone, which need no sort among themselves: every box's far side, then every
near side, then their edges over them (on the instanced path a call each).
With a transparent instance it is that and every box, in halves sorted along
the line of sight (:meth:`Renderer.back_to_front`, sorted again only when the
camera turns, the explode moves or the looks change): each one's far side
placed at the far end of its box (as exploded now) and its near side at the
near end, farthest first, so a closed mesh is blended in the order its faces
lie, one inside another's box between that one's far and near sides, and a
box's edges, drawn right after its near side, under whatever nearer is blended
after them. Sorting goes across meshes, so this pass draws one half at a time
with the instance's values set as the attributes' constants on both paths, and
sorts only what it draws, a list kept as the looks change.

Picking an assembly's instance is a second pass of the same shaders: each
instance is drawn flat in a colour that is its number (:func:`.viewmath.pick_color`),
into an offscreen framebuffer that holds only the few pixels round the pointer
(:func:`.viewmath.pick_projection`), so it costs one small draw per click,
follows the explode, and finds what is in front. Of each box that pass draws
the far side only (the faces turned away from the eye, :data:`BOX_MESH` being
wound outward) and its edges: a box in front of a mesh is picked where it
covers it, while a mesh inside a box, or reaching into it, lies in front of the
box's far side and is picked through it. A transparent instance ranks the same
way: its own program's fragment shader moves the depth of each of its fragments
to where the line of sight leaves the mesh's own box, carried by the instance's
matrix, so it is picked where it is drawn over what lies behind its box, and a
part inside it (or in front) is picked through it; a hidden one is never
picked. The colour buffer's fourth
value is an instance's state: shown as usual, picked (drawn in a selection
blue), or faded toward the background while another is picked. The id pass's
depth variant (``u_depth``) writes each fragment's own window depth, 24 bits in
the colour as the number is (:func:`.viewmath.depth_bytes`), instead of the
number: the same fragments win, so
it gives the surface a click there would pick (:meth:`ModelView.surface_at`),
the point a turn drag turns about, without reading a depth buffer back, which
OpenGL ES cannot do and the view's own multisampled one would not allow.

:class:`ModelView` is the widget: an orthographic orbit camera
(:class:`.viewmath.OrbitCamera`) driven by the mouse as the mouse style setting
says, turning freely or as a turntable as the rotation setting says, wheel
zoom toward the cursor, double-click (on empty space, in an
assembly) or F to fit and R for the isometric view. A turn drag turns the model
about the surface under the pointer where it starts (a setting), which keeps
its pixel; a sideways scroll turns the model, Page Up and Page Down roll it,
and in the SOLIDWORKS style Ctrl or Shift pressed during a middle-drag switch
it to panning or zooming. In an assembly a click
picks the instance under the pointer (``picked``), a double-click on one asks
for its file (``activated``) and a right-click without a drag asks for its
menu (``menuRequested``, -1 on empty space, and anywhere on a part, whose menu
offers 3D Print); hovering names it.
:meth:`ModelView.set_looks` sets what is hidden or transparent: the camera fits
what is shown (all of it when nothing is) and the exploded view spreads what is
shown, and :meth:`ModelView.set_explode_choices` the sub-assemblies that explode
or stay together whatever the level says (:func:`.explode.group_of`). The keys work as in SOLIDWORKS,
so the view can be turned
without a middle button: the arrow keys turn the model 15 degrees (90 with
Shift), Ctrl+arrow pans and Ctrl+1 to Ctrl+7 give the standard views. The
model stays fitted until the user moves it, refitting when the view changes
shape and while an assembly explodes or collapses; :meth:`ModelView.camera_state`
and :meth:`ModelView.set_camera_state` give and put back how it is turned and
zoomed, for Back. The view cube over its top-right corner (:mod:`.cubewidget`,
a child widget painted with QPainter, not drawn in this view's frame) turns
with the camera: its regions look from their direction, its house goes Home
(the view a scene opens at: the isometric, unless the user set another, which
the Preview pane keeps for each document), and its arrows step and roll.
Those, R and Ctrl+1 to Ctrl+7 ease the camera there
(:class:`.viewmath.CameraMove`, stepped by the explode's timer); any other way
of moving it takes over where the move got to, and code that sets a view, and
Back, still set it at once. Another configuration of the same document keeps
the camera (``keep_camera``): a fitted one fits the new scene from the same
direction, a moved one stays unless none of the new model would be in view.
Whatever lies over the view and says so with its ``reservesArea`` property (the
legend) is kept clear: a fit centres the model in the area left of it or below
it, through the camera's lens shift (:meth:`ModelView.overlays_changed`), and
keeps it off the view cube's corner where that costs little of its size. The
explode amount eases to a value set at once, and follows a dragged or stepped
slider closely (``explode_to(..., follow=True)``). :func:`gl_status` checks
once whether OpenGL works here at all, so the Preview tab can say so instead
of showing an empty widget.

The mesh is read and its buffers made in a separate process (:mod:`.meshproc`);
this module only uploads and draws, on the UI thread, where OpenGL must run.
"""

import math
import os
import time
from array import array
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import shiboken6
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QContextMenuEvent,
    QCursor,
    QGuiApplication,
    QImage,
    QMatrix4x4,
    QOffscreenSurface,
    QOpenGLContext,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QSurfaceFormat,
)
from PySide6.QtOpenGL import (
    QOpenGLBuffer,
    QOpenGLFramebufferObject,
    QOpenGLFramebufferObjectFormat,
    QOpenGLShader,
    QOpenGLShaderProgram,
    QOpenGLVertexArrayObject,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QToolTip, QWidget

from . import viewcube
from .cubewidget import PivotMark, ViewCube
from .explode import TOP, Animation, Explosion, Follow, explode, instance_bounds
from .mesh3d import MeshBuffers, SceneBuffers, component_color
from .viewmath import (
    ARROW_STEP,
    CLICK_SLOP,
    FREE,
    ISO_PITCH,
    ISO_YAW,
    PAN,
    PICK_RADIUS,
    ROTATE,
    SOLIDWORKS,
    STANDARD,
    VIEW_KEYS,
    VIEWS,
    ZOOM,
    CameraMove,
    OrbitCamera,
    avoid_area,
    depth_of,
    drag_action,
    free_areas,
    ndc,
    nearest_hit,
    nearest_index,
    pick_index,
    pick_projection,
    pick_window,
    region_angles,
    unproject,
    upright_angles,
    wheel_factor,
)
from .wording import tip

GL_DEPTH_BUFFER_BIT, GL_COLOR_BUFFER_BIT = 0x0100, 0x4000
GL_LINES, GL_TRIANGLES, GL_UNSIGNED_INT, GL_FLOAT = 0x0001, 0x0004, 0x1405, 0x1406
GL_DEPTH_TEST, GL_LEQUAL, GL_MULTISAMPLE = 0x0B71, 0x0203, 0x809D
GL_RENDERER, GL_VERSION = 0x1F01, 0x1F02
GL_DITHER, GL_BLEND = 0x0BD0, 0x0BE2
GL_ZERO, GL_ONE, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA = 0, 1, 0x0302, 0x0303
# glDrawElements reads the indices from the bound index buffer, from its first byte.
# PySide6 takes that offset as a pointer, and refuses a plain 0.
_NO_OFFSET = shiboken6.VoidPtr(0)

_LIGHT_BACKGROUND, _DARK_BACKGROUND = QColor("#e9edf2"), QColor("#2b2f36")
_MODEL = QColor("#a9b9cc")
# The boxes drawn for instances without a mesh: a neutral grey no component colour uses
# (:func:`.mesh3d.component_color`), faces this opaque, and edges that stand out from
# each background.
BOX_COLOR = QColor("#b8bfc8")
BOX_ALPHA = 0.3
BOX_EDGE = {False: QColor("#4b535d"), True: QColor("#c9d0d8")}  # on a dark background or not
_IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
# The matrix takes 2 to 5. The colour is red, green, blue and the instance's state (0 shown,
# 1 picked, 2 dimmed); the offset is x, y, z and the instance's number from 1, for picking;
# the look is the instance's opacity (1 opaque) and 1 when it is hidden, else 0.
A_POSITION, A_NORMAL, A_MATRIX, A_COLOR, A_OFFSET, A_LOOK = 0, 1, 2, 6, 7, 8
SHOWN, PICKED, DIMMED = 0.0, 1.0, 2.0
OPAQUE = 0.999  # an opacity from here up is opaque: drawn in the first pass, writing depth
BOTH_SIDES, FAR_SIDE, NEAR_SIDE = 0.0, 1.0, 2.0  # u_side: the faces turned away from the eye, or toward it
_EXPLODE_TICK_MS = 15
Vec3 = tuple[float, float, float]
GL_POLYGON_OFFSET_FILL = 0x8037

_VERTEX = """
VIN vec3 a_position;
VIN vec3 a_normal;
VIN vec4 a_m0;
VIN vec4 a_m1;
VIN vec4 a_m2;
VIN vec4 a_m3;
VIN vec4 a_color;
VIN vec4 a_offset;
VIN vec2 a_look;
uniform mat4 u_viewproj;
uniform mat4 u_view;
uniform float u_explode;
uniform float u_opaque;  /* 1 in the first pass: the opaque instances only */
VOUT vec3 v_normal;
VOUT vec3 v_pos;
VOUT vec3 v_color;
VOUT float v_state;
VOUT vec3 v_id;
VOUT float v_mirror;  /* below 0 when the instance's matrix mirrors, which turns its faces round */
VOUT float v_alpha;
#ifdef FAR_DEPTH
uniform vec3 u_dir;
VOUT vec3 v_local;
VOUT vec3 v_ray;
VOUT vec3 v_world;
#endif
void main() {
    v_alpha = a_look.x;
    if (a_look.y > 0.5 || (u_opaque > 0.5 && a_look.x < 0.999)) {
        /* hidden, or transparent in the opaque pass: outside the view, so nothing is drawn */
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        v_normal = vec3(0.0); v_pos = vec3(0.0); v_color = vec3(0.0); v_state = 0.0;
        v_id = vec3(0.0); v_mirror = 1.0;
#ifdef FAR_DEPTH
        v_local = vec3(0.0); v_ray = vec3(0.0); v_world = vec3(0.0);
#endif
        return;
    }
    mat4 model = mat4(a_m0, a_m1, a_m2, a_m3);
    v_mirror = dot(cross(a_m0.xyz, a_m1.xyz), a_m2.xyz);
    vec4 world = model * vec4(a_position, 1.0);
    world.xyz += u_explode * a_offset.xyz;
    v_pos = (u_view * world).xyz;
    v_normal = (u_view * (model * vec4(a_normal, 0.0))).xyz;
    v_color = a_color.rgb;
    v_state = a_color.a;
    /* the instance's number as three bytes, low byte in red: exact in 32-bit floats */
    float id = a_offset.w;
    v_id = vec3(mod(id, 256.0), mod(floor(id / 256.0), 256.0), floor(id / 65536.0)) / 255.0;
#ifdef FAR_DEPTH
    /* The line of sight in the mesh's own frame, through the inverse of the matrix's
       3 x 3 part (its rows are these cross products over the determinant), so the
       fragment shader can find where it leaves the mesh's own box. */
    vec3 c0 = a_m0.xyz;
    vec3 c1 = a_m1.xyz;
    vec3 c2 = a_m2.xyz;
    float det = dot(c0, cross(c1, c2));
    if (abs(det) < 1e-30) det = 1e-30;
    v_ray = vec3(dot(cross(c1, c2), u_dir), dot(cross(c2, c0), u_dir), dot(cross(c0, c1), u_dir)) / det;
    v_local = a_position;
    v_world = world.xyz;
#endif
    gl_Position = u_viewproj * world;
}
"""
_FRAGMENT = """
FIN vec3 v_normal;
FIN vec3 v_pos;
FIN vec3 v_color;
FIN float v_state;
FIN vec3 v_id;
FIN float v_mirror;
FIN float v_alpha;
uniform float u_pick;
uniform float u_depth;  /* 1 in the id pass's depth variant: each fragment's depth, not its number */
uniform float u_side;  /* 1: only the faces turned away from the eye (the far side), 2: only the others */
uniform vec3 u_fade;
uniform float u_alpha;  /* 1 for the meshes, less for the faces of the boxes */
uniform float u_edge;  /* 1 while the boxes' edges are drawn: flat lines in u_edge_color */
uniform vec3 u_edge_color;
#ifdef FAR_DEPTH
FIN vec3 v_local;
FIN vec3 v_ray;
FIN vec3 v_world;
uniform mat4 u_viewproj;
uniform vec3 u_dir;
uniform vec3 u_box_lo;  /* the mesh's own box, in its own frame */
uniform vec3 u_box_hi;
uniform float u_rank_box;  /* 1 for a mesh's transparent instances: ranked at the far side of the box */

float leave(float p, float d, float lo, float hi) {
    if (abs(d) < 1e-20) return 1e30;
    return ((d > 0.0 ? hi : lo) - p) / d;
}
#endif
void main() {
#ifdef FAR_DEPTH
    FRAG_DEPTH = gl_FragCoord.z;
#endif
    if (u_edge > 0.5) {  /* a line has no far side: drawn whatever u_side says */
        vec3 e = u_edge_color;
        if (v_state > 0.5 && v_state < 1.5) e = vec3(0.10, 0.42, 0.95);
        if (v_state > 1.5) e = mix(e, u_fade, 0.65);
        FRAG = vec4(e, v_alpha);  /* as opaque as the box was made: solid unless made transparent */
        return;
    }
    bool toward = gl_FrontFacing == (v_mirror >= 0.0);  /* the face turns toward the eye */
    if (u_side > 0.5 && u_side < 1.5 && toward) discard;
    if (u_side > 1.5 && !toward) discard;
    if (u_pick > 0.5) {
#ifdef FAR_DEPTH
        if (u_rank_box > 0.5 && v_alpha < 0.999) {
            /* A transparent instance ranks where the line of sight leaves its own box, as a
               box's far side does: what lies inside the box, or in front, is picked through
               it, and it is picked over what lies behind the box. */
            float t = min(leave(v_local.x, v_ray.x, u_box_lo.x, u_box_hi.x),
                          min(leave(v_local.y, v_ray.y, u_box_lo.y, u_box_hi.y),
                              leave(v_local.z, v_ray.z, u_box_lo.z, u_box_hi.z)));
            if (t < 1e29) {
                vec4 c = u_viewproj * vec4(v_world + max(t, 0.0) * u_dir, 1.0);
                FRAG_DEPTH = clamp(0.5 * c.z / c.w + 0.5, 0.0, 1.0);
            }
        }
#endif
        if (u_depth > 0.5) {
            /* Where the surface is: its window depth z as 24 bits, low byte in red as the
               instance's number is: floor(255 z) in blue, the next 16 bits of 255 z's
               fraction in green and red (viewmath.depth_bytes). Nothing on the way exceeds
               256, so OpenGL ES's mediump, which may be half precision (at most 65504),
               cannot overflow. The fragment that wins is still the one the id pass picks (a
               transparent instance ranks at the far side of its box). */
            float t = clamp(gl_FragCoord.z, 0.0, 1.0) * 255.0;
            float m = fract(t) * 256.0;
            FRAG = vec4(floor(fract(m) * 256.0), floor(m), floor(t), 255.0) / 255.0;
            return;
        }
        FRAG = vec4(v_id, 1.0);
        return;
    }
    vec3 n = v_normal;
    if (dot(n, n) < 0.25) {
#ifdef DERIVATIVES
        n = cross(dFdx(v_pos), dFdy(v_pos));
#else
        n = vec3(0.0, 0.0, 1.0);
#endif
    }
    n = normalize(n);
    if (n.z < 0.0) n = -n;  /* the mesh is not closed: light both sides */
    vec3 key = normalize(vec3(0.25, 0.35, 1.0));
    vec3 fill = normalize(vec3(-0.6, -0.2, 0.8));
    float diffuse = 0.6 * max(dot(n, key), 0.0) + 0.1 * max(dot(n, fill), 0.0);
    float spec = pow(max(dot(n, normalize(key + vec3(0.0, 0.0, 1.0))), 0.0), 48.0);
    vec3 base = v_color;
    float ambient = 0.32;
    if (v_state > 0.5 && v_state < 1.5) {  /* picked: the selection blue, brighter */
        base = mix(base, vec3(0.20, 0.55, 1.0), 0.75);
        ambient = 0.45;
    }
    vec3 c = base * (ambient + diffuse) + vec3(0.14) * spec;
    if (v_state > 1.5) c = mix(c, u_fade, 0.65);  /* another instance is picked: fade it */
    FRAG = vec4(c, u_alpha * v_alpha);
}
"""


class GLError(RuntimeError):
    pass


def _headers(ctx: QOpenGLContext, *, far_depth: bool = False) -> tuple[str, str] | None:
    """GLSL headers for the context: 1.20 (a compatibility context, the Windows
    default), 1.50 (a core profile) or ES 1.00. With ``far_depth`` the id pass's: its
    fragment shader sets the depth of a transparent instance's fragments to where the
    line of sight leaves its box (``FAR_DEPTH``); None where it cannot (OpenGL ES
    without ``GL_EXT_frag_depth``)."""
    fmt = ctx.format()
    if ctx.isOpenGLES():
        extensions = ""
        if ctx.hasExtension(b"GL_OES_standard_derivatives"):
            extensions += "#extension GL_OES_standard_derivatives : enable\n"
        if far_depth:
            if not ctx.hasExtension(b"GL_EXT_frag_depth"):
                return None
            extensions += "#extension GL_EXT_frag_depth : enable\n"
        precision = "precision mediump float;\n"
        if far_depth:  # a depth worked out in the shader wants every bit there is
            precision = (
                "#ifdef GL_FRAGMENT_PRECISION_HIGH\nprecision highp float;\n"
                "#else\nprecision mediump float;\n#endif\n"
            )
        frag = f"#version 100\n{extensions}{precision}#define FIN varying\n#define FRAG gl_FragColor\n"
        if "derivatives" in extensions:
            frag += "#define DERIVATIVES 1\n"
        vert = "#version 100\n#define VIN attribute\n#define VOUT varying\n"
        if far_depth:
            frag += "#define FAR_DEPTH 1\n#define FRAG_DEPTH gl_FragDepthEXT\n"
            vert += "#define FAR_DEPTH 1\n"
        return vert, frag
    far = "#define FAR_DEPTH 1\n#define FRAG_DEPTH gl_FragDepth\n" if far_depth else ""
    if fmt.profile() == QSurfaceFormat.OpenGLContextProfile.CoreProfile:
        return (
            "#version 150\n#define VIN in\n#define VOUT out\n" + far,
            "#version 150\n#define FIN in\nout vec4 fragColor;\n#define FRAG fragColor\n"
            "#define DERIVATIVES 1\n" + far,
        )
    return (
        "#version 120\n#define VIN attribute\n#define VOUT varying\n" + far,
        "#version 120\n#define FIN varying\n#define FRAG gl_FragColor\n#define DERIVATIVES 1\n" + far,
    )


def _matrix(rows: list[float]) -> QMatrix4x4:
    return QMatrix4x4(*rows)


def _corners(lo: list[float], hi: list[float]) -> list[tuple[float, float, float]]:
    """The eight corners of the box from ``lo`` to ``hi``."""
    return [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]


def _box_mesh() -> MeshBuffers:
    """A unit cube, 0 to 1 along each axis, as :data:`BOX_MESH`: four corners for each
    face, with zero normals, so the fragment shader lights each face flat from its own
    plane; the indices of its twelve triangles (:data:`BOX_FACES`), each wound
    counter-clockwise seen from outside, so the id pass can tell a face's far side,
    then of its twelve edges as pairs (:data:`BOX_EDGES`, from byte
    :data:`BOX_EDGE_OFFSET`)."""
    positions = array("f")
    faces = array("I")
    for axis in range(3):
        u, v = (axis + 1) % 3, (axis + 2) % 3
        for side in (0.0, 1.0):
            first = len(positions) // 3
            for a, b in ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)):
                p = [0.0, 0.0, 0.0]
                p[axis], p[u], p[v] = side, a, b
                positions.extend(p)
            # u then v turns counter-clockwise seen from the side the axis points to: the
            # outside of the face at 1, the inside of the face at 0, which goes the other way.
            quad = (0, 1, 2, 0, 2, 3) if side else (0, 2, 1, 0, 3, 2)
            faces.extend(first + q for q in quad)
    corner: dict[tuple[float, ...], int] = {}
    for k in range(len(positions) // 3):
        corner.setdefault(tuple(positions[3 * k : 3 * k + 3]), k)
    edges = array("I")
    for a, i in corner.items():
        for b, j in corner.items():
            if a < b and sum(x != y for x, y in zip(a, b, strict=True)) == 1:
                edges.extend((i, j))
    indices = faces + edges
    return MeshBuffers(
        positions=positions.tobytes(),
        normals=bytes(4 * len(positions)),
        indices=indices.tobytes(),
        n_vertices=len(positions) // 3,
        n_triangles=len(faces) // 3,
        bbox=((0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
    )


BOX_MESH = _box_mesh()
BOX_FACES, BOX_EDGES = 36, 24  # indices
BOX_EDGE_OFFSET = shiboken6.VoidPtr(4 * BOX_FACES)  # bytes into the index buffer


@dataclass
class Scene:
    """What the 3D view draws: meshes, each with its instances' matrices (float32,
    column-major, 16 each) and colours (float32 red, green, blue). ``bbox`` holds
    every instance, in the frame the camera fits. An assembly's scene also has each
    instance's component tree id (``ids``) and box (``bounds``), which the exploded
    view groups and moves; a part's has neither. ``box_mesh`` is the index of the
    mesh, the last, that is :data:`BOX_MESH`: the instances drawn as boxes, for want
    of a mesh of their own; None when there are none."""

    meshes: list[MeshBuffers]
    matrices: list[bytes]
    colors: list[bytes]
    bbox: tuple[tuple[float, float, float], tuple[float, float, float]]
    ids: list[list[str]] | None = None
    bounds: list[bytes] | None = None
    box_mesh: int | None = None

    @property
    def n_instances(self) -> int:
        """Every instance drawn, as a mesh or as a box."""
        return sum(len(m) // 64 for m in self.matrices)

    @property
    def n_boxes(self) -> int:
        """The instances drawn as boxes."""
        return 0 if self.box_mesh is None else len(self.matrices[self.box_mesh]) // 64

    @property
    def n_triangles(self) -> int:
        """Triangles drawn: each mesh's, once per instance; the boxes' are not counted."""
        return sum(
            m.n_triangles * (len(x) // 64)
            for k, (m, x) in enumerate(zip(self.meshes, self.matrices, strict=True))
            if k != self.box_mesh
        )

    @classmethod
    def of_part(cls, mesh: MeshBuffers) -> "Scene":
        color = array("f", (_MODEL.redF(), _MODEL.greenF(), _MODEL.blueF()))
        return cls([mesh], [array("f", _IDENTITY).tobytes()], [color.tobytes()], mesh.bbox)

    @classmethod
    def of_assembly(cls, scene: SceneBuffers, *, boxes: bool = True) -> "Scene":
        """Each instance in the colour of its component file (:func:`.mesh3d.component_color`),
        and with ``boxes`` each instance without a mesh that has a stored box as that box,
        in :data:`BOX_COLOR`, after them all."""
        palette = [component_color(i) for i in range(len(scene.files))]
        colors = []
        for files_of in scene.files_of:
            index = array("I")
            index.frombytes(files_of)
            out = array("f")
            for i in index:
                out.extend(
                    palette[i] if i < len(palette) else (_MODEL.redF(), _MODEL.greenF(), _MODEL.blueF())
                )
            colors.append(out.tobytes())
        bounds = list(scene.bounds) or [
            instance_bounds(m.bbox, x) for m, x in zip(scene.meshes, scene.matrices, strict=True)
        ]
        meshes, matrices = list(scene.meshes), list(scene.matrices)
        ids = [list(i) for i in scene.instance_ids]
        bbox = scene.bbox
        box_mesh = None
        b = scene.boxes
        if boxes and b is not None and len(b):
            box_mesh = len(meshes)
            meshes.append(BOX_MESH)
            matrices.append(b.matrices)
            grey = (BOX_COLOR.redF(), BOX_COLOR.greenF(), BOX_COLOR.blueF())
            colors.append(array("f", grey * len(b)).tobytes())
            ids.append(list(b.ids))
            bounds.append(b.bounds)
            if scene.meshes:
                (a0, a1), (b0, b1) = scene.bbox, b.bbox
                bbox = (
                    (min(a0[0], b0[0]), min(a0[1], b0[1]), min(a0[2], b0[2])),
                    (max(a1[0], b1[0]), max(a1[1], b1[1]), max(a1[2], b1[2])),
                )
            else:
                bbox = b.bbox
        return cls(meshes, matrices, colors, bbox, ids=ids, bounds=bounds, box_mesh=box_mesh)

    def explosion(
        self,
        level: str,
        choices: "Mapping[str, bool] | None" = None,
        hidden: "Sequence[bool] | None" = None,
    ) -> Explosion | None:
        """The offsets of an exploded view at ``level``, with the sub-assemblies of
        ``choices`` exploding or kept together, leaving out the instances ``hidden``
        says are hidden (numbered over the scene); None for a part."""
        if self.ids is None or self.bounds is None:
            return None
        per_mesh = None
        if hidden is not None and any(hidden):
            per_mesh, k = [], 0
            for ids in self.ids:
                per_mesh.append(list(hidden[k : k + len(ids)]))
                k += len(ids)
        return explode(self.ids, self.bounds, level, choices=choices, hidden=per_mesh)

    def bbox_of(self, shown: "Sequence[bool] | None") -> tuple[Vec3, Vec3]:
        """The box of the instances ``shown`` says are shown (numbered over the scene), at
        rest; the whole scene's when every one is, when none is, or for a part."""
        if shown is None or all(shown) or not any(shown) or self.bounds is None:
            return self.bbox
        lo, hi = [math.inf] * 3, [-math.inf] * 3
        g = 0
        for raw in self.bounds:
            b = array("f")
            b.frombytes(raw)
            for k in range(len(b) // 6):
                if g < len(shown) and shown[g]:
                    for i in range(3):
                        lo[i] = min(lo[i], b[6 * k + i])
                        hi[i] = max(hi[i], b[6 * k + 3 + i])
                g += 1
        if lo[0] > hi[0]:
            return self.bbox
        return (lo[0], lo[1], lo[2]), (hi[0], hi[1], hi[2])


def instance_buffers(colors: bytes, base: int) -> tuple[array, array]:
    """The colour and offset buffers of a mesh's instances, from their colours (float32
    red, green, blue): each colour with the state :data:`SHOWN`, and each offset zero
    with the instance's number, ``base + 1`` for its first."""
    rgb = array("f")
    rgb.frombytes(colors)
    n = len(rgb) // 3
    col = array("f", bytes(16 * n))
    for c in range(3):
        col[c::4] = rgb[c::3]
    off = array("f", bytes(16 * n))
    off[3::4] = array("f", range(base + 1, base + n + 1))
    return col, off


def image_ids(img: QImage) -> list[int | None]:
    """The instance each pixel of an id pass shows, row by row from the top."""
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    row = img.bytesPerLine()
    data = bytes(img.constBits())
    out: list[int | None] = []
    for y in range(h):
        line = data[y * row : y * row + 4 * w]
        out.extend(pick_index(line[i], line[i + 1], line[i + 2]) for i in range(0, 4 * w, 4))
    return out


def image_depths(img: QImage) -> list[float | None]:
    """The window depth (0 near to 1 far) each pixel of the id pass's depth variant shows,
    row by row from the top; None where nothing is drawn."""
    img = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = img.width(), img.height()
    row = img.bytesPerLine()
    data = bytes(img.constBits())
    out: list[float | None] = []
    for y in range(h):
        line = data[y * row : y * row + 4 * w]
        out.extend(
            depth_of(line[i], line[i + 1], line[i + 2]) if line[i + 3] else None for i in range(0, 4 * w, 4)
        )
    return out


class _GpuMesh:
    """One mesh on the GPU: its buffers, its vertex arrays and its instances, the first
    of which is instance ``base`` of the scene. ``vao`` draws every instance at once
    (instanced drawing), ``solo`` one at a time with the instance's values set as the
    attributes' constants; without instanced drawing they are the same."""

    def __init__(
        self,
        buffers: list[QOpenGLBuffer],
        count: int,
        matrices: bytes,
        colors: array,
        offsets: array,
        looks: array,
        bounds: bytes,
        bbox: tuple[tuple[float, float, float], tuple[float, float, float]],
        base: int,
        box: bool = False,
    ) -> None:
        self.buffers = buffers  # position, normal, index, matrices, colours, offsets, looks
        self.count = count  # indices of its triangles
        self.box = box  # the boxes drawn for instances without a mesh (:data:`BOX_MESH`)
        self.instances = len(matrices) // 64
        self.base = base
        self.matrices = array("f")
        self.matrices.frombytes(matrices)
        self.colors = colors  # red, green, blue, state
        self.offsets = offsets  # x, y, z, number
        self.looks = looks  # opacity, hidden
        # Each instance's box, collapsed, as its centre and half its size along x, y and z:
        # what the sort of the blended pass goes by.
        self.centres, self.halves = _centres(bounds)
        self.bbox = bbox  # the mesh's own box, in its own frame
        self.vao: QOpenGLVertexArrayObject | None = None
        self.solo: QOpenGLVertexArrayObject | None = None
        # What the one-by-one path draws, kept as the looks change: the instances shown, the
        # opaque ones among them, and the opacity the shown ones share (None if they differ).
        self.shown: Sequence[int] = range(self.instances)
        self.opaque: Sequence[int] = self.shown
        self.shown_opacity: float | None = 1.0

    def set_looks(self, looks: array) -> None:
        """Each instance's opacity and hidden flag (``looks``, two floats each), and what
        follows from them for the one-by-one path."""
        self.looks = looks
        n = self.instances
        shown = [k for k in range(n) if looks[2 * k + 1] <= 0.5]
        self.shown = range(n) if len(shown) == n else shown
        opaque = [k for k in shown if looks[2 * k] >= OPAQUE]
        self.opaque = self.shown if len(opaque) == len(shown) else opaque
        shared = {looks[2 * k] for k in shown}
        self.shown_opacity = shared.pop() if len(shared) == 1 else (None if shared else 1.0)

    def write(self, slot: int, data: array) -> None:
        buf = self.buffers[slot]
        buf.bind()
        raw = data.tobytes()
        buf.write(0, raw, len(raw))
        buf.release()


def _centres(bounds: bytes) -> tuple[array, array]:
    """The centre of each box of ``bounds`` (float32 low then high x, y, z per box), and
    half its size along each axis."""
    b = array("f")
    b.frombytes(bounds)
    n = len(b) // 6
    centres, halves = array("d", bytes(24 * n)), array("d", bytes(24 * n))
    for c in range(3):
        lows, highs = b[c::6], b[c + 3 :: 6]
        centres[c::3] = array("d", ((lo + hi) / 2 for lo, hi in zip(lows, highs, strict=True)))
        halves[c::3] = array("d", (abs(hi - lo) / 2 for lo, hi in zip(lows, highs, strict=True)))
    return centres, halves


class Renderer:
    """The GPU side of the 3D view. Create, use and release it with its OpenGL
    context current."""

    allow_instancing = True  # tests turn it off to draw instance by instance

    def __init__(self) -> None:
        ctx = QOpenGLContext.currentContext()
        if ctx is None:
            raise GLError("no OpenGL context is current")
        if ctx.isOpenGLES() and not ctx.hasExtension(b"GL_OES_element_index_uint"):
            raise GLError("this OpenGL ES driver cannot draw meshes over 65,536 vertices")
        self.gl = ctx.functions()
        fmt = ctx.format()
        version = (fmt.majorVersion(), fmt.minorVersion())
        self.instanced = self.allow_instancing and (
            version >= (3, 0) if ctx.isOpenGLES() else version >= (3, 3)
        )
        self.extra = ctx.extraFunctions() if self.instanced else None
        heads = _headers(ctx)
        assert heads is not None
        self.program = self._program(*heads)
        # Where the uniforms the blended pass sets for each instance live: set by name, each
        # call would look the name up again.
        self._at = {name: self.program.uniformLocation(name) for name in ("u_side", "u_edge", "u_alpha")}
        # The id pass's own program, which ranks a transparent instance at the far side of
        # its box (FAR_DEPTH). Its fragment shader sets the depth, which costs the drawing
        # pass its early depth test, so that pass keeps the plain one. Where it cannot be
        # made, a transparent instance ranks as an opaque one does.
        self.pick_program = self.program
        self.rank_far = False
        far = _headers(ctx, far_depth=True)
        if far is not None:
            try:
                self.pick_program = self._program(*far)
                self.rank_far = True
            except GLError:
                pass
        probe = QOpenGLVertexArrayObject()
        self.has_vao = probe.create()
        probe.destroy()
        self.meshes: list[_GpuMesh] = []
        self.count = 0  # triangles' indices drawn in a frame, over every instance
        self.upload_seconds = 0.0
        self.explode = 0.0  # how much of the offsets is applied: 0 collapsed, 1 fully exploded
        self.instances = 0  # over every mesh
        self.boxes = 0  # the instances drawn as boxes
        self.transparent = 0  # the meshes' instances drawn transparent
        self.hidden = 0  # instances not drawn at all
        self.sort_seconds = 0.0  # the last sort of the blended pass, back to front
        # What the last frame sorted: the transparent instances and every box shown, or 0
        # when nothing was transparent and the boxes were drawn without a sort.
        self.sorted_items = 0
        self._looks_version = 0
        self._items: list[tuple[int, int]] = []  # what the sorted pass draws (:meth:`_collect`)
        self._order: list[tuple[int, int, float]] = []
        self._order_key: tuple | None = None
        self._fbo: QOpenGLFramebufferObject | None = None  # the id pass's, kept while its size holds
        self._frame_fbo: QOpenGLFramebufferObject | None = None  # Save Animation's frames

    @staticmethod
    def _program(vertex_head: str, fragment_head: str) -> QOpenGLShaderProgram:
        program = QOpenGLShaderProgram()
        bits = QOpenGLShader.ShaderTypeBit
        if not program.addShaderFromSourceCode(bits.Vertex, vertex_head + _VERTEX):
            raise GLError("the vertex shader did not compile: " + program.log().strip())
        if not program.addShaderFromSourceCode(bits.Fragment, fragment_head + _FRAGMENT):
            raise GLError("the fragment shader did not compile: " + program.log().strip())
        for name, location in (
            ("a_position", A_POSITION),
            ("a_normal", A_NORMAL),
            ("a_m0", A_MATRIX),
            ("a_m1", A_MATRIX + 1),
            ("a_m2", A_MATRIX + 2),
            ("a_m3", A_MATRIX + 3),
            ("a_color", A_COLOR),
            ("a_offset", A_OFFSET),
            ("a_look", A_LOOK),
        ):
            program.bindAttributeLocation(name, location)
        if not program.link():
            raise GLError("the shaders did not link: " + program.log().strip())
        return program

    def _attributes(self, m: _GpuMesh, instanced: bool) -> None:
        """Point the attributes at ``m``'s buffers: the vertices per vertex and, for
        ``instanced`` drawing, the matrix, colour, offset and look per instance; else
        those four are constants set for each instance drawn."""
        p, n, i, mat, col, off, look = m.buffers
        prog = self.program
        p.bind()
        prog.enableAttributeArray(A_POSITION)
        prog.setAttributeBuffer(A_POSITION, GL_FLOAT, 0, 3, 12)
        n.bind()
        prog.enableAttributeArray(A_NORMAL)
        prog.setAttributeBuffer(A_NORMAL, GL_FLOAT, 0, 3, 12)
        if instanced:
            extra = self.extra
            assert extra is not None
            mat.bind()
            for k in range(4):
                prog.enableAttributeArray(A_MATRIX + k)
                prog.setAttributeBuffer(A_MATRIX + k, GL_FLOAT, 16 * k, 4, 64)
                extra.glVertexAttribDivisor(A_MATRIX + k, 1)
            for buf, location, size in ((col, A_COLOR, 4), (off, A_OFFSET, 4), (look, A_LOOK, 2)):
                buf.bind()
                prog.enableAttributeArray(location)
                prog.setAttributeBuffer(location, GL_FLOAT, 0, size, 4 * size)
                extra.glVertexAttribDivisor(location, 1)
        else:
            for location in (A_MATRIX, A_MATRIX + 1, A_MATRIX + 2, A_MATRIX + 3, A_COLOR, A_OFFSET, A_LOOK):
                prog.disableAttributeArray(location)
        i.bind()

    def upload(self, scene: "Scene | MeshBuffers | None") -> None:
        """Replace what is drawn; None draws nothing. A part's mesh alone is a scene of
        one instance. Every instance starts opaque and shown."""
        self.clear()
        if scene is None:
            return
        if isinstance(scene, MeshBuffers):
            scene = Scene.of_part(scene)
        t = time.perf_counter()
        base = 0
        for k, (mesh, matrices, colors) in enumerate(
            zip(scene.meshes, scene.matrices, scene.colors, strict=True)
        ):
            made = []
            col, off = instance_buffers(colors, base)
            n = len(matrices) // 64
            looks = array("f", (1.0, 0.0) * n)
            bounds = scene.bounds[k] if scene.bounds is not None else instance_bounds(mesh.bbox, matrices)
            for data, kind in (
                (mesh.positions, QOpenGLBuffer.Type.VertexBuffer),
                (mesh.normals, QOpenGLBuffer.Type.VertexBuffer),
                (mesh.indices, QOpenGLBuffer.Type.IndexBuffer),
                (matrices, QOpenGLBuffer.Type.VertexBuffer),
                (col.tobytes(), QOpenGLBuffer.Type.VertexBuffer),
                (off.tobytes(), QOpenGLBuffer.Type.VertexBuffer),
                (looks.tobytes(), QOpenGLBuffer.Type.VertexBuffer),
            ):
                buf = QOpenGLBuffer(kind)
                buf.setUsagePattern(QOpenGLBuffer.UsagePattern.StaticDraw)
                if not buf.create() or not buf.bind():
                    for b in made:
                        b.destroy()
                    self.clear()
                    raise GLError("the graphics driver refused a buffer")
                buf.allocate(data, len(data))
                made.append(buf)
            box = k == scene.box_mesh
            m = _GpuMesh(
                made,
                BOX_FACES if box else mesh.n_triangles * 3,
                matrices,
                col,
                off,
                looks,
                bounds,
                mesh.bbox,
                base,
                box,
            )
            base += m.instances
            if box:
                self.boxes = m.instances
            if self.has_vao:
                m.vao = QOpenGLVertexArrayObject()
                m.vao.create()
                m.vao.bind()
                self._attributes(m, self.instanced)
                m.vao.release()
                m.solo = m.vao
                if self.instanced:
                    m.solo = QOpenGLVertexArrayObject()
                    m.solo.create()
                    m.solo.bind()
                    self._attributes(m, False)
                    m.solo.release()
            self.meshes.append(m)
            self.count += m.count * m.instances
        self.instances = base
        self._collect()
        self.gl.glFinish()
        self.upload_seconds = time.perf_counter() - t

    def set_offsets(self, offsets: "list[array] | None") -> None:
        """Each instance's offset when fully exploded (``offsets[m]``: float32 x, y, z
        per instance of mesh ``m``), or None for none; written over the offset buffers."""
        for k, m in enumerate(self.meshes):
            data = offsets[k] if offsets is not None and k < len(offsets) else None
            if data is None or len(data) != 3 * m.instances:
                data = array("f", bytes(12 * m.instances))
            for c in range(3):
                m.offsets[c::4] = array("f", data[c::3])
            m.write(5, m.offsets)
        self._order_key = None

    def set_states(self, picked: "Iterable[int] | None") -> None:
        """Draw the instances ``picked`` (numbered over the scene from 0) in the selection
        blue and fade the others; with none picked, every instance is drawn as usual."""
        chosen = set(picked or ())
        for m in self.meshes:
            if chosen:
                states = array("f", (PICKED if m.base + k in chosen else DIMMED for k in range(m.instances)))
            else:
                states = array("f", bytes(4 * m.instances))
            m.colors[3::4] = states
            m.write(4, m.colors)

    def set_looks(self, opacity: "Sequence[float] | None", hidden: "Sequence[bool] | None") -> None:
        """Each instance's opacity (1 opaque) and whether it is hidden, numbered over the
        scene from 0; None for every instance opaque, or shown."""
        transparent = hidden_count = 0
        for m in self.meshes:
            looks = array("f", bytes(8 * m.instances))
            for k in range(m.instances):
                g = m.base + k
                a = min(max(float(opacity[g]), 0.0), 1.0) if opacity is not None and g < len(opacity) else 1.0
                h = bool(hidden[g]) if hidden is not None and g < len(hidden) else False
                looks[2 * k] = a
                looks[2 * k + 1] = 1.0 if h else 0.0
                hidden_count += h
                transparent += not h and not m.box and a < OPAQUE
            m.set_looks(looks)
            m.write(6, looks)
        self.transparent, self.hidden = transparent, hidden_count
        self._looks_version += 1
        self._order_key = None
        self._collect()

    def _collect(self) -> None:
        """What the sorted blended pass draws, ``(mesh, instance)``, kept as the looks
        change so a turn of the camera sorts only these: each mesh's transparent instances
        and every box, all shown."""
        self._items = [
            (mi, k)
            for mi, m in enumerate(self.meshes)
            for k in (m.shown if m.box else [k for k in m.shown if m.looks[2 * k] < OPAQUE])
        ]

    def draw(self, camera: OrbitCamera, background: QColor, *, finish: bool = False) -> None:
        self._draw(
            camera.view_matrix(),
            camera.projection_matrix(),
            (background.redF(), background.greenF(), background.blueF(), 1.0),
            edges=BOX_EDGE[background.lightness() < 128],
        )
        if finish:
            self.gl.glFinish()

    def pick_image(
        self,
        camera: OrbitCamera,
        window: tuple[float, float, float, float],
        size: tuple[int, int],
        *,
        only_boxes: bool = False,
        depth: bool = False,
    ) -> QImage:
        """The id pass of the NDC ``window`` (centre x, y and half width, height) of the
        camera's view, drawn into an offscreen framebuffer of ``size`` pixels: each
        pixel's colour is the number of the instance in front there, black where none
        is (:func:`image_ids` reads it). With ``only_boxes``, of the boxes alone. With
        ``depth``, each pixel holds the window depth of the surface drawn there instead
        (:func:`image_depths` reads it): the same pass, the same fragments win, so OpenGL
        ES, which cannot read a depth buffer back, gets it too."""
        w, h = size
        if self._fbo is None or (self._fbo.width(), self._fbo.height()) != (w, h):
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.Attachment.Depth)
            self._fbo = QOpenGLFramebufferObject(w, h, fmt)
        fbo = self._fbo
        if not fbo.isValid() or not fbo.bind():
            self._fbo = None
            raise GLError("the graphics driver refused an offscreen framebuffer for picking")
        gl = self.gl
        try:
            gl.glViewport(0, 0, w, h)
            gl.glDisable(GL_DITHER)
            projection = pick_projection(camera.projection_matrix(), *window)
            self._draw(
                camera.view_matrix(),
                projection,
                (0.0, 0.0, 0.0, 0.0),
                pick=True,
                only_boxes=only_boxes,
                depth=depth,
            )
            gl.glEnable(GL_DITHER)
            return fbo.toImage()
        finally:
            fbo.release()

    def render_image(self, camera: OrbitCamera, background: QColor, size: tuple[int, int]) -> QImage:
        """The view as ``camera`` sees it, drawn into an offscreen framebuffer of ``size``
        pixels with four samples a pixel: a frame of Save Animation. The camera's aspect
        should be the size's."""
        w, h = size
        if self._frame_fbo is None or (self._frame_fbo.width(), self._frame_fbo.height()) != (w, h):
            fmt = QOpenGLFramebufferObjectFormat()
            fmt.setAttachment(QOpenGLFramebufferObject.Attachment.Depth)
            fmt.setSamples(4)
            self._frame_fbo = QOpenGLFramebufferObject(w, h, fmt)
        fbo = self._frame_fbo
        if not fbo.isValid() or not fbo.bind():
            self._frame_fbo = None
            raise GLError("the graphics driver refused an offscreen framebuffer for the frame")
        try:
            self.gl.glViewport(0, 0, w, h)
            self.draw(camera, background, finish=True)
            return fbo.toImage()
        finally:
            fbo.release()

    def back_to_front(self, view_rows: list[float]) -> list[tuple[int, int, float]]:
        """What the sorted blended pass draws, as halves ``(mesh, instance, side)``: of each
        mesh's transparent instances and every box, all shown (:meth:`_collect`), the far
        side (:data:`FAR_SIDE`) placed at the far end of its box (as exploded now) along
        the line of sight and the near side (:data:`NEAR_SIDE`) at the near end, farthest
        first. One inside another's box is so drawn between that one's far and near
        sides, and of two apart each is drawn far side then near side. At one depth a near
        side comes before a far side (a part resting on another, the lower one's top
        first), of two far sides the larger first and of two near sides the smaller, then
        the one numbered first. Sorted again only when the camera turns, the explode
        moves or the looks change: a pan or a zoom keeps the order."""
        back = (view_rows[8], view_rows[9], view_rows[10])
        key = (back, self.explode, self._looks_version)
        if key == self._order_key:
            return self._order
        t = time.perf_counter()
        bx, by, bz = back
        ax, ay, az = abs(bx), abs(by), abs(bz)
        e = self.explode
        meshes = self.meshes
        halves: list[tuple[float, int, float, int, int, int, float]] = []
        for mi, k in self._items:
            m = meshes[mi]
            c, h, off = m.centres, m.halves, m.offsets
            q, o = 3 * k, 4 * k
            x, y, z = c[q] + e * off[o], c[q + 1] + e * off[o + 1], c[q + 2] + e * off[o + 2]
            depth = bx * x + by * y + bz * z
            r = ax * h[q] + ay * h[q + 1] + az * h[q + 2]  # half the box's depth along the line of sight
            g = m.base + k
            halves.append((depth - r, 1, -r, g, mi, k, FAR_SIDE))
            halves.append((depth + r, 0, r, g, mi, k, NEAR_SIDE))
        halves.sort()  # least along ``back`` (toward the eye) first: the farthest
        self._order = [(mi, k, side) for *_rank, mi, k, side in halves]
        self._order_key = key
        self.sort_seconds = time.perf_counter() - t
        self.sorted_items = len(self._items)
        return self._order

    def _draw(
        self,
        view_rows: list[float],
        projection_rows: list[float],
        background: tuple[float, float, float, float],
        *,
        pick: bool = False,
        only_boxes: bool = False,
        depth: bool = False,
        edges: QColor = BOX_EDGE[False],
    ) -> None:
        gl = self.gl
        # Every state the passes rely on is set here: Qt may leave blending on in this
        # context between frames, and blended into, the id pass would keep the cleared
        # alpha of 0, which reads back as no instance anywhere.
        gl.glDisable(GL_BLEND)
        gl.glBlendFunc(GL_ONE, GL_ZERO)
        gl.glDisable(GL_POLYGON_OFFSET_FILL)
        gl.glDepthMask(True)
        gl.glClearColor(*background)
        gl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        if not self.meshes:
            return
        gl.glEnable(GL_DEPTH_TEST)
        gl.glDepthFunc(GL_LEQUAL)
        view = _matrix(view_rows)
        projection = _matrix(projection_rows)
        prog = self.pick_program if pick else self.program
        prog.bind()
        prog.setUniformValue("u_viewproj", projection * view)
        prog.setUniformValue("u_view", view)
        prog.setUniformValue1f("u_explode", float(self.explode))
        prog.setUniformValue1f("u_pick", 1.0 if pick else 0.0)
        prog.setUniformValue1f("u_depth", 1.0 if depth else 0.0)
        prog.setUniformValue(prog.uniformLocation("u_fade"), *background[:3])
        prog.setUniformValue1f("u_alpha", 1.0)
        prog.setUniformValue1f("u_edge", 0.0)
        prog.setUniformValue1f("u_side", BOTH_SIDES)
        prog.setUniformValue1f("u_opaque", 0.0)
        edge = (edges.redF(), edges.greenF(), edges.blueF())
        prog.setUniformValue(prog.uniformLocation("u_edge_color"), *edge)
        meshes = [m for m in self.meshes if not m.box]
        boxes = [m for m in self.meshes if m.box]
        if pick:
            # One depth-tested pass. Of a box, its far side and its edges: in front of a mesh,
            # the box is picked where it covers it, and a mesh inside it, or reaching into it,
            # is in front of that far side, so it is picked through the box. A mesh's
            # transparent instance ranks the same way, at the far side of its own box (the
            # fragment shader moves its depth there). The boxes alone (the self-test's
            # check) are drawn whole. A hidden instance is not drawn at all.
            back = (view_rows[8], view_rows[9], view_rows[10])
            prog.setUniformValue(prog.uniformLocation("u_dir"), -back[0], -back[1], -back[2])
            if not only_boxes:
                prog.setUniformValue1f("u_rank_box", 1.0)
                for m in meshes:
                    (x0, y0, z0), (x1, y1, z1) = m.bbox
                    prog.setUniformValue(prog.uniformLocation("u_box_lo"), x0, y0, z0)
                    prog.setUniformValue(prog.uniformLocation("u_box_hi"), x1, y1, z1)
                    self._instances(m, GL_TRIANGLES, m.count, _NO_OFFSET)
                prog.setUniformValue1f("u_rank_box", 0.0)
            for m in boxes:
                prog.setUniformValue1f("u_side", BOTH_SIDES if only_boxes else FAR_SIDE)
                self._instances(m, GL_TRIANGLES, BOX_FACES, _NO_OFFSET)
                prog.setUniformValue1f("u_side", BOTH_SIDES)  # lines face the eye: never their far side
                self._instances(m, GL_LINES, BOX_EDGES, BOX_EDGE_OFFSET)
        else:
            # The opaque instances first, writing depth; then what is blended over them, writing
            # no depth, so whatever is behind or inside it still shows (:meth:`_blended`).
            prog.setUniformValue1f("u_opaque", 1.0)
            for m in meshes:
                self._instances(m, GL_TRIANGLES, m.count, _NO_OFFSET, opaque=True)
            prog.setUniformValue1f("u_opaque", 0.0)
            if self.transparent:
                self._blended(prog, self.back_to_front(view_rows))
            else:
                self.sorted_items = 0
                if boxes:
                    self._boxes(prog, boxes)
        if not self.has_vao:
            prog.disableAttributeArray(A_POSITION)
            prog.disableAttributeArray(A_NORMAL)
        prog.release()

    def _blend(self, on: bool) -> None:
        """Blend over what is drawn without writing depth, keeping the window's alpha, with a
        small depth offset toward the eye that keeps a face lying on an opaque one from
        speckling against it; or not."""
        gl = self.gl
        if on:
            gl.glEnable(GL_BLEND)
            gl.glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ZERO, GL_ONE)
            gl.glDepthMask(False)
            gl.glEnable(GL_POLYGON_OFFSET_FILL)
            gl.glPolygonOffset(-1.0, -1.0)
        else:
            gl.glDisable(GL_POLYGON_OFFSET_FILL)
            gl.glDepthMask(True)
            gl.glBlendFunc(GL_ONE, GL_ZERO)
            gl.glDisable(GL_BLEND)

    def _boxes(self, prog: QOpenGLShaderProgram, boxes: list[_GpuMesh]) -> None:
        """The boxes when no mesh's instance is transparent, which need no sort: their faces
        blended, far side then near side (with instanced drawing a call for every box's far
        side, then one for every near side; one by one, each box's two in turn), then their
        edges over them, as opaque as each box's look says."""
        side_at, edge_at, alpha_at = self._at["u_side"], self._at["u_edge"], self._at["u_alpha"]
        self._blend(True)
        prog.setUniformValue1f(alpha_at, BOX_ALPHA)
        if self.instanced:
            for side in (FAR_SIDE, NEAR_SIDE):
                prog.setUniformValue1f(side_at, side)
                for m in boxes:
                    self._instances(m, GL_TRIANGLES, BOX_FACES, _NO_OFFSET)
        else:
            for m in boxes:
                if m.vao is not None:
                    m.vao.bind()
                else:
                    self._attributes(m, False)
                faces = (GL_TRIANGLES, BOX_FACES, _NO_OFFSET)
                self._each(m, m.shown, *faces, m.shown_opacity, sides=(prog, side_at))
                if m.vao is not None:
                    m.vao.release()
        prog.setUniformValue1f(side_at, BOTH_SIDES)
        prog.setUniformValue1f(alpha_at, 1.0)
        prog.setUniformValue1f(edge_at, 1.0)  # still blended: a box made transparent fades its edges too
        for m in boxes:
            self._instances(m, GL_LINES, BOX_EDGES, BOX_EDGE_OFFSET)
        prog.setUniformValue1f(edge_at, 0.0)
        self._blend(False)

    def _blended(self, prog: QOpenGLShaderProgram, order: list[tuple[int, int, float]]) -> None:
        """Draw ``order``'s halves (:meth:`back_to_front`) one at a time, farthest first,
        blended (:meth:`_blend`): a mesh's far side or near side, so a closed mesh is
        blended in the order its faces lie and one inside another between that one's two
        sides; a box's faces the same way, and after its near side its edges, so what is
        nearer and blended later lies over them too."""
        side_at, edge_at, alpha_at = self._at["u_side"], self._at["u_edge"], self._at["u_alpha"]
        uniform = prog.setUniformValue1f
        self._blend(True)
        gl = self.gl
        draw, attrib, attrib2 = gl.glDrawElements, gl.glVertexAttrib4f, gl.glVertexAttrib2f
        m0, m1, m2, m3 = A_MATRIX, A_MATRIX + 1, A_MATRIX + 2, A_MATRIX + 3
        current: _GpuMesh | None = None
        item: tuple[int, int] | None = None
        alpha = side_now = None
        mat = col = off = look = array("f")
        for mi, k, side in order:
            m = self.meshes[mi]
            if m is not current:
                if current is not None and current.solo is not None:
                    current.solo.release()
                current = m
                if m.solo is not None:
                    m.solo.bind()
                else:
                    self._attributes(m, False)
                want = BOX_ALPHA if m.box else 1.0
                if want != alpha:
                    uniform(alpha_at, want)
                    alpha = want
                mat, col, off, look = m.matrices, m.colors, m.offsets, m.looks
            if item != (mi, k):  # its values, as the attributes' constants (as :meth:`_each` sets them)
                o = 16 * k
                attrib(m0, mat[o], mat[o + 1], mat[o + 2], mat[o + 3])
                attrib(m1, mat[o + 4], mat[o + 5], mat[o + 6], mat[o + 7])
                attrib(m2, mat[o + 8], mat[o + 9], mat[o + 10], mat[o + 11])
                attrib(m3, mat[o + 12], mat[o + 13], mat[o + 14], mat[o + 15])
                q = 4 * k
                attrib(A_COLOR, col[q], col[q + 1], col[q + 2], col[q + 3])
                attrib(A_OFFSET, off[q], off[q + 1], off[q + 2], off[q + 3])
                attrib2(A_LOOK, look[2 * k], look[2 * k + 1])
                item = (mi, k)
            if side != side_now:
                uniform(side_at, side)
                side_now = side
            draw(GL_TRIANGLES, BOX_FACES if m.box else m.count, GL_UNSIGNED_INT, _NO_OFFSET)
            if m.box and side == NEAR_SIDE:
                uniform(edge_at, 1.0)
                draw(GL_LINES, BOX_EDGES, GL_UNSIGNED_INT, BOX_EDGE_OFFSET)
                uniform(edge_at, 0.0)
        if current is not None and current.solo is not None:
            current.solo.release()
        uniform(side_at, BOTH_SIDES)
        uniform(alpha_at, 1.0)
        self._blend(False)

    def _instances(self, m: _GpuMesh, mode: int, count: int, offset, *, opaque: bool = False) -> None:
        """Draw ``count`` indices of ``m`` from byte ``offset`` of its index buffer as
        ``mode`` (triangles or lines), for every instance shown (with ``opaque``, every
        opaque one): in one call with instanced drawing, where the vertex shader drops the
        others, else one instance at a time (:meth:`_each`)."""
        if m.vao is not None:
            m.vao.bind()
        else:
            self._attributes(m, self.instanced)
        if self.instanced:
            self.extra.glDrawElementsInstanced(  # type: ignore[union-attr]
                mode, count, GL_UNSIGNED_INT, offset, m.instances
            )
        elif opaque:
            self._each(m, m.opaque, mode, count, offset, 1.0)
        else:
            self._each(m, m.shown, mode, count, offset, m.shown_opacity)
        if m.vao is not None:
            m.vao.release()

    def _each(
        self,
        m: _GpuMesh,
        ks: "Iterable[int]",
        mode: int | None,
        count: int,
        offset,
        opacity: float | None,
        *,
        sides: tuple[QOpenGLShaderProgram, int] | None = None,
    ) -> None:
        """For each instance ``ks`` of ``m``, set its values as the constants of the
        attributes whose arrays are off (its matrix, colour, offset and, unless every one
        has the ``opacity`` given, its look) and, with a ``mode``, draw it: with ``sides``
        (the program and where its ``u_side`` is) its far side, then its near side."""
        gl = self.gl
        attrib, draw = gl.glVertexAttrib4f, gl.glDrawElements
        mat, col, off, look = m.matrices, m.colors, m.offsets, m.looks
        m0, m1, m2, m3 = A_MATRIX, A_MATRIX + 1, A_MATRIX + 2, A_MATRIX + 3
        if opacity is not None:
            gl.glVertexAttrib2f(A_LOOK, opacity, 0.0)
        for k in ks:
            o = 16 * k
            attrib(m0, mat[o], mat[o + 1], mat[o + 2], mat[o + 3])
            attrib(m1, mat[o + 4], mat[o + 5], mat[o + 6], mat[o + 7])
            attrib(m2, mat[o + 8], mat[o + 9], mat[o + 10], mat[o + 11])
            attrib(m3, mat[o + 12], mat[o + 13], mat[o + 14], mat[o + 15])
            q = 4 * k
            attrib(A_COLOR, col[q], col[q + 1], col[q + 2], col[q + 3])
            attrib(A_OFFSET, off[q], off[q + 1], off[q + 2], off[q + 3])
            if opacity is None:
                gl.glVertexAttrib2f(A_LOOK, look[2 * k], look[2 * k + 1])
            if mode is None:
                continue
            if sides is None:
                draw(mode, count, GL_UNSIGNED_INT, offset)
            else:
                prog, side_at = sides
                prog.setUniformValue1f(side_at, FAR_SIDE)
                draw(mode, count, GL_UNSIGNED_INT, offset)
                prog.setUniformValue1f(side_at, NEAR_SIDE)
                draw(mode, count, GL_UNSIGNED_INT, offset)

    def clear(self) -> None:
        for m in self.meshes:
            for vao in {id(v): v for v in (m.vao, m.solo) if v is not None}.values():
                vao.destroy()
            for b in m.buffers:
                b.destroy()
        self.meshes = []
        self.count = 0
        self.instances = 0
        self.boxes = 0
        self.transparent = 0
        self.hidden = 0
        self._items = []
        self._order, self._order_key = [], None

    def release(self) -> None:
        self.clear()
        self._fbo = None  # deleted while its context is current
        self.program.removeAllShaders()
        if self.pick_program is not self.program:
            self.pick_program.removeAllShaders()


_STATUS: tuple[bool, str] | None = None
_ROTATE_CURSOR: QCursor | None = None


def rotate_cursor() -> QCursor:
    """Two curved arrows round a circle, as SOLIDWORKS shows while rotating; Qt has
    no rotate cursor of its own, and its four-way arrow means move (pan)."""
    global _ROTATE_CURSOR
    if _ROTATE_CURSOR is None:
        size, c, r = 32, 16.0, 9.0
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        arcs = QPainterPath()
        heads = QPainterPath()
        for start in (20.0, 200.0):  # two arcs of 140 degrees, each ending in an arrowhead
            arcs.arcMoveTo(c - r, c - r, 2 * r, 2 * r, start)
            arcs.arcTo(c - r, c - r, 2 * r, 2 * r, start, 140.0)
            end = math.radians(start + 140.0)
            tip = QPointF(c + r * math.cos(end), c - r * math.sin(end))
            along = QPointF(-math.sin(end), -math.cos(end))  # the arc's direction at its end, on screen
            out = QPointF(math.cos(end), -math.sin(end))
            heads.moveTo(tip + along * 4.5)
            heads.lineTo(tip - along * 1.5 + out * 4.0)
            heads.lineTo(tip - along * 1.5 - out * 4.0)
            heads.closeSubpath()
        for color, width in ((Qt.GlobalColor.white, 4.5), (Qt.GlobalColor.black, 2.0)):
            p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(arcs)
            p.setBrush(color)
            p.setPen(QPen(color, width - 1.5 if width > 3 else 0.8))
            p.drawPath(heads)
        p.end()
        _ROTATE_CURSOR = QCursor(pix, int(c), int(c))
    return _ROTATE_CURSOR


def gl_status() -> tuple[bool, str]:
    """``(True, renderer)`` when an OpenGL 2.0 or later context can be made here,
    else ``(False, why)``. Checked once per process, without a window."""
    global _STATUS
    if _STATUS is not None:
        return _STATUS
    ctx = QOpenGLContext()
    ctx.setFormat(QSurfaceFormat.defaultFormat())
    surface = QOffscreenSurface()
    try:
        if not ctx.create():
            _STATUS = (
                False,
                f"no OpenGL context can be made on the {QGuiApplication.platformName()} platform",
            )
            return _STATUS
        surface.setFormat(ctx.format())
        surface.create()
        if not surface.isValid() or not ctx.makeCurrent(surface):
            _STATUS = (False, "an OpenGL context was made but could not be used")
            return _STATUS
        fmt = ctx.format()
        renderer = ctx.functions().glGetString(GL_RENDERER) or "unknown renderer"
        version = ctx.functions().glGetString(GL_VERSION) or ""
        ctx.doneCurrent()
        if fmt.majorVersion() < 2:
            _STATUS = (False, f"OpenGL {fmt.majorVersion()}.{fmt.minorVersion()} is too old (2.0 is needed)")
        else:
            _STATUS = (True, f"{renderer}, OpenGL {version}".strip())
    finally:
        surface.destroy()
    return _STATUS


class ModelView(QOpenGLWidget):
    """The interactive 3D view. ``failed`` carries the reason when OpenGL cannot
    draw here after all, so the Preview tab can show it as a message."""

    failed = Signal(str)
    uploaded = Signal(float)  # seconds the upload took
    explodeChanged = Signal(float)  # the explode amount drawn, while it animates and when it stops
    # An assembly's instances are numbered from 0 over its meshes, in the scene's order.
    picked = Signal(int)  # a click: the instance under the pointer, or -1 for none
    activated = Signal(int)  # a double-click on an instance
    menuRequested = Signal(int, QPoint)  # a right-click without a drag: the instance (or -1), where
    hideRequested = Signal(int)  # Tab: the instance under the pointer, to hide
    showAllRequested = Signal()  # Shift+Tab: every hidden instance back
    homeChanged = Signal(object)  # the user set Home (a camera state) or put it back to the isometric (None)
    layoutChanged = Signal()  # the view cube was shown, hidden or resized: what lies under it moves

    def __init__(
        self,
        parent=None,
        *,
        mouse_style: str = STANDARD,
        invert_wheel: bool = False,
        rotation_mode: str = FREE,
        show_cube: bool = True,
        about_pointer: bool = True,
    ) -> None:
        super().__init__(parent)
        fmt = QSurfaceFormat.defaultFormat()
        fmt.setDepthBufferSize(24)
        fmt.setSamples(4)
        self.setFormat(fmt)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(60, 60)
        self.mouse_style = mouse_style
        self.invert_wheel = invert_wheel
        self.rotation_mode = rotation_mode
        self.camera = OrbitCamera(mode=rotation_mode)
        self.renderer: Renderer | None = None
        self.error: str | None = None
        self.mesh: MeshBuffers | None = None  # a part's
        self.scene: Scene | None = None  # what is drawn: the part, or an assembly
        self.measure_frames = False  # time each frame to the end of its drawing (the self-test does)
        self._pending = False
        self._drag: str | None = None
        self._last = QPointF()
        self._press = QPointF()
        self.frame_seconds = 0.0
        # The exploded view: the level its groups are made at, the amount drawn (0 to 1),
        # the amount it is heading for, and the offsets, made when first needed.
        self.explode_level = TOP
        self.explode = 0.0
        self.explode_target = 0.0
        self.explosion: Explosion | None = None
        self._offsets_pending = False
        self._animation: Animation | Follow | None = None
        self._clock = time.perf_counter  # tests step the animation on a clock of their own
        self._ticker = QTimer(self)
        self._ticker.setInterval(_EXPLODE_TICK_MS)
        self._ticker.timeout.connect(self._tick)
        # Picking: the instances drawn picked, the button pressed, and whether a menu waits
        # for the right button's release (where Qt asks for it on the press).
        self.selected: set[int] = set()
        self._states_pending = False
        # The looks the user chose: each instance's opacity and whether it is hidden, and
        # the sub-assemblies chosen to explode or stay together, by id.
        self.opacity: list[float] = []
        self.hidden: list[bool] = []
        self._looks_pending = False
        self.explode_choices: dict[str, bool] = {}
        self._press_button: str | None = None
        self._right_moved = 0.0
        self._menu_on_release = False
        # Whether the right press the menu belongs to was this view's own: one another widget
        # took (the view cube) is that widget's gesture, wherever its release lands.
        self._right_own = False
        self.describe: Callable[[int], str] | None = None  # the hover text of an instance
        self.any_hidden: Callable[[], bool] | None = None  # whether Shift+Tab has something to show
        self.setMouseTracking(False)
        # A camera move under way (the view cube, Home, R, the standard views), and Home: the
        # camera state a new scene opens at and the Home key goes to, None for the isometric.
        self._move: CameraMove | None = None
        self.home: dict[str, Any] | None = None
        # The view cube over the top-right corner, a widget of its own (:mod:`.cubewidget`).
        self.show_cube = show_cube
        self.cube = ViewCube(self)
        self.cube.regionClicked.connect(lambda region: self.look_at_region(region))
        self.cube.homeClicked.connect(lambda: self.go_home())
        self.cube.stepClicked.connect(lambda side: self.step(side))
        self.cube.rollClicked.connect(lambda sign: self.cube_roll(sign))
        self.cube.dragged.connect(self._cube_dragged)
        self.cube.dragEnded.connect(self._cube_drag_ended)
        self.cube.homeSet.connect(self.set_home)
        self.cube.fitClicked.connect(self.fit)
        self._place_cube()
        # Turning about the surface under the pointer (Settings): the point a rotate drag
        # turns about, read at its first move (False until then, None for none there), and
        # its mark; ``_anchor`` is where a zoom drag zooms toward.
        self.about_pointer = about_pointer
        self._about: Vec3 | None | bool = False
        self.pivot_mark = PivotMark(self)
        self._anchor = QPointF()

    # -- content -------------------------------------------------------------------------
    def set_mesh(self, mesh: MeshBuffers | None, *, keep_camera: bool = False) -> None:
        """Show a part's ``mesh``, at Home (isometric and fitted unless another was set),
        or with ``keep_camera`` as the camera is (:meth:`_show`). The view may not have its
        real size yet (a new view is 640 x 480 until it is laid out): the camera stays
        fitted and refits when the size arrives."""
        self.mesh = mesh
        self._show(Scene.of_part(mesh) if mesh is not None else None, keep_camera=keep_camera)

    def set_assembly(
        self, scene: SceneBuffers | None, *, boxes: bool = True, keep_camera: bool = False
    ) -> None:
        """Show an assembly as the mesh process read it, each component file in its colour,
        and with ``boxes`` a box in place of each instance without a mesh that has one; with
        ``keep_camera`` (another configuration of the same document) the camera stays."""
        self.set_scene(
            Scene.of_assembly(scene, boxes=boxes) if scene is not None else None, keep_camera=keep_camera
        )

    def set_scene(self, scene: "Scene | None", *, keep_camera: bool = False) -> None:
        """Show an assembly's ``scene``, at Home, fitted to all of it, or as the camera is."""
        self.mesh = None
        self._show(scene, keep_camera=keep_camera)

    def _show(self, scene: "Scene | None", *, keep_camera: bool = False) -> None:
        """Show ``scene``. A new one opens at Home. With ``keep_camera``, and a scene shown
        already, the camera stays as it is: a fitted one fits the new scene from the same
        direction, and one the user moved keeps its direction, target, zoom and shift
        unless none of the new model would be in view, or the zoom is far too far out for
        it (:meth:`.viewmath.OrbitCamera.keep_in_view`), when it fits from the same
        direction."""
        kept = self.camera_state() if keep_camera and self.scene is not None else None
        self.scene = scene
        self._pending = True
        self._ticker.stop()
        self._animation = None
        self._move = None
        self.explode = self.explode_target = 0.0
        self.explosion = None
        self._offsets_pending = False
        self.selected = set()
        self._states_pending = False
        self.opacity, self.hidden = [], []  # each instance as the file draws it, until told
        self._looks_pending = False
        if scene is not None:
            free, avoid = self.camera.free, self.camera.avoid
            self.camera = OrbitCamera(scene.bbox, mode=self.rotation_mode)
            self.camera.aspect = self.width() / max(self.height(), 1)
            self.camera.free, self.camera.avoid = free, avoid
            if kept is None:
                self.camera.set_state(self._home_state())  # Home: the isometric, unless one was set
            else:
                self.camera.set_state(kept)
                if not self.camera.fitted:
                    self.camera.keep_in_view()
        self.update()

    # -- picking -------------------------------------------------------------------------
    @property
    def can_pick(self) -> bool:
        """Whether the view shows an assembly, whose instances a click picks."""
        return self.scene is not None and self.scene.ids is not None and not self.error

    @property
    def can_menu(self) -> bool:
        """Whether a right-click asks for a menu: the view shows a part or an assembly."""
        return self.scene is not None and not self.error

    def set_highlight(self, indices: "Iterable[int]") -> None:
        """Draw the instances ``indices`` picked, and the others dimmed; none: all as usual."""
        chosen = set(indices)
        if chosen != self.selected:
            self.selected = chosen
            self._states_pending = True
            self.update()

    # -- what the user chose to see --------------------------------------------------------
    def set_looks(self, opacity: "Sequence[float] | None", hidden: "Sequence[bool] | None") -> None:
        """Each instance's opacity (1 opaque, less to see through it) and whether it is
        hidden, numbered as picking numbers them; None for every one opaque, or shown. A
        hidden instance is not drawn or picked, the camera fits what is shown (all of it
        when nothing is), and the exploded view spreads what is shown."""
        n = self.scene.n_instances if self.scene is not None else 0
        alpha = [min(max(float(a), 0.0), 1.0) for a in (opacity or ())][:n]
        alpha += [1.0] * (n - len(alpha))
        gone = [bool(h) for h in (hidden or ())][:n]
        gone += [False] * (n - len(gone))
        if alpha == (self.opacity or [1.0] * n) and gone == (self.hidden or [False] * n):
            return
        hid_before = self.hidden or [False] * n
        self.opacity, self.hidden = alpha, gone
        self._looks_pending = True
        if gone != hid_before:
            self.explosion = None
            if self.explode or self.explode_target:
                self._prepare_explosion()
            self._follow_explode()
        self.update()

    def set_explode_choices(self, choices: "Mapping[str, bool] | None") -> None:
        """The sub-assemblies to explode (True) or keep together (False) whatever the
        level says, by id (:func:`.explode.group_of`); an exploded view moves to the new
        groups' places at once."""
        chosen = dict(choices or {})
        if chosen == self.explode_choices:
            return
        self.explode_choices = chosen
        self.explosion = None
        if self.explode or self.explode_target:
            self._prepare_explosion()
            self._follow_explode()

    @property
    def all_hidden(self) -> bool:
        """Whether every instance of the scene is hidden, so nothing is drawn."""
        return bool(self.hidden) and all(self.hidden)

    def instance_at(self, x: float, y: float, radius: int = PICK_RADIUS) -> int | None:
        """The instance in front at the view position ``(x, y)`` (pixels from the top
        left), or the nearest within ``radius`` pixels; None for none, and for a part."""
        if not self.can_pick:
            return None
        cx, cy, hw, hh, side = pick_window(x, y, self.width(), self.height(), radius)
        ids = self._id_pass((cx, cy, hw, hh), (side, side))
        return None if ids is None else nearest_hit(ids, side)

    def ids_drawn(self) -> list[int | None] | None:
        """The id pass of the whole view: the instance in front at each pixel, row by row
        from the top (None where there is none); None when it cannot draw."""
        if not self.can_pick:
            return None
        return self._id_pass((0.0, 0.0, 1.0, 1.0), (max(self.width(), 1), max(self.height(), 1)))

    def surface_at(self, x: float, y: float, radius: int = PICK_RADIUS) -> Vec3 | None:
        """The model point drawn at the view position ``(x, y)`` (pixels from the top left),
        where the model is exploded and turned now: of the drawn pixels within ``radius``,
        the depth of the one nearest ``(x, y)``, at ``(x, y)`` itself, so the point lies
        under the pointer. None where nothing is drawn, or without OpenGL. One small draw
        of the id pass's depth variant (:meth:`Renderer.pick_image`), as a click's pick
        costs; for a part as well. The depth holds 24 bits where the GPU works in single
        precision (desktop OpenGL), about 11 where OpenGL ES works in half precision."""
        if self.renderer is None or self.scene is None or self.error:
            return None
        w, h = self.width(), self.height()
        cx, cy, hw, hh, side = pick_window(x, y, w, h, radius)
        self.makeCurrent()
        try:
            if not self._sync():
                return None
            self._follow_size(w, h)
            img = self.renderer.pick_image(self.camera, (cx, cy, hw, hh), (side, side), depth=True)
        except GLError as exc:
            self._fail(str(exc))
            return None
        finally:
            self.doneCurrent()
        depths = image_depths(img)
        k = nearest_index(depths, side)
        if k is None:
            return None
        nx, ny = ndc(x, y, w, h)
        return unproject(self.camera, nx, ny, depths[k])  # type: ignore[arg-type]

    def pixel_of(self, index: int, *, clear: bool = False) -> tuple[float, float] | None:
        """A view position where instance ``index`` is in front: of its pixels, the one
        nearest their middle; None when it is hidden or off the view. With ``clear``, only
        pixels a click reaches the view at (:meth:`overlay_at`): not under the legend or
        the view cube."""
        if not self.can_pick:
            return None
        w, h = max(self.width(), 1), max(self.height(), 1)
        ids = self._id_pass((0.0, 0.0, 1.0, 1.0), (w, h))
        if ids is None:
            return None
        pts = [(k % w, k // w) for k, i in enumerate(ids) if i == index]
        if clear:
            pts = [p for p in pts if self.overlay_at(p[0] + 0.5, p[1] + 0.5) is None]
        if not pts:
            return None
        mx = sum(p[0] for p in pts) / len(pts)
        my = sum(p[1] for p in pts) / len(pts)
        px, py = min(pts, key=lambda p: (p[0] - mx) ** 2 + (p[1] - my) ** 2)
        return (px + 0.5, py + 0.5)

    def box_report(self) -> dict[str, Any] | None:
        """Whether every box is drawn where it belongs, for the self-test; None for a part.

        One id pass of the boxes alone, at the view's size: ``boxes`` counts them,
        ``visible`` those that pass shows, ``outside`` lists the numbers of those whose
        centre (as exploded now) is off the view, ``subpixel`` those whose eight corners
        project within a pixel (too small to cover one, so they may draw nothing), and
        ``missing`` the others with no box at all within :data:`.viewmath.PICK_RADIUS`
        pixels of where their centre is drawn. A box drawn where it belongs covers the
        point its centre projects to, unless another box covers it in front, so only a
        box not drawn there is missing. A box the user hid is none of these: ``hidden``
        lists them, when there are any."""
        scene = self.scene
        if scene is None or scene.ids is None:
            return None
        report: dict[str, Any] = {
            "boxes": scene.n_boxes,
            "visible": 0,
            "outside": [],
            "subpixel": [],
            "missing": [],
        }
        if scene.box_mesh is None or scene.bounds is None:
            return report
        k0 = sum(len(i) for i in scene.ids[: scene.box_mesh])
        hidden = [k0 + k for k in range(scene.n_boxes) if self._is_hidden(k0 + k)]
        if hidden:  # hidden by the user, so drawn nowhere, as they should be
            report["hidden"] = hidden
        w, h = max(self.width(), 1), max(self.height(), 1)
        ids = self._id_pass((0.0, 0.0, 1.0, 1.0), (w, h), only_boxes=True)
        if ids is None:
            report["missing"] = list(range(k0, k0 + scene.n_boxes))
            return report
        report["visible"] = len({i for i in ids if i is not None and i >= k0})
        b = array("f")
        b.frombytes(scene.bounds[scene.box_mesh])
        r = PICK_RADIUS

        def pixel(p: list[float]) -> tuple[float, float]:
            nx, ny, _ = self.camera.project((p[0], p[1], p[2]))
            return (nx + 1) * w / 2, (1 - ny) * h / 2

        for k in range(scene.n_boxes):
            if self._is_hidden(k0 + k):
                continue  # hidden by the user: drawn nowhere, as it should be
            lo, hi = list(b[6 * k : 6 * k + 3]), list(b[6 * k + 3 : 6 * k + 6])
            if self.explosion is not None and self.explode:
                d = self.explosion.offset(scene.box_mesh, k)
                lo = [lo[i] + self.explode * d[i] for i in range(3)]
                hi = [hi[i] + self.explode * d[i] for i in range(3)]
            fx, fy = pixel([(lo[i] + hi[i]) / 2 for i in range(3)])
            if not (math.isfinite(fx) and math.isfinite(fy)) or not (0 <= fx < w and 0 <= fy < h):
                report["outside"].append(k0 + k)
                continue
            x, y = int(fx), int(fy)
            corners = [pixel([c[0], c[1], c[2]]) for c in _corners(lo, hi)]
            xs, ys = [p[0] for p in corners], [p[1] for p in corners]
            if max(xs) - min(xs) < 1.0 and max(ys) - min(ys) < 1.0:
                report["subpixel"].append(k0 + k)
                continue
            near = (
                ids[yy * w + xx]
                for yy in range(max(0, y - r), min(h, y + r + 1))
                for xx in range(max(0, x - r), min(w, x + r + 1))
            )
            if not any(i is not None and i >= k0 for i in near):
                report["missing"].append(k0 + k)
        return report

    def _is_hidden(self, index: int) -> bool:
        return index < len(self.hidden) and self.hidden[index]

    def _id_pass(self, window, size, *, only_boxes: bool = False) -> list[int | None] | None:
        if self.renderer is None:
            return None
        self.makeCurrent()
        try:
            if not self._sync():
                return None
            self._follow_size(self.width(), self.height())
            img = self.renderer.pick_image(self.camera, window, size, only_boxes=only_boxes)
        except GLError as exc:
            self._fail(str(exc))
            return None
        finally:
            self.doneCurrent()
        return image_ids(img)

    def render_frames(
        self, frames, size: tuple[int, int], background: str, folder: str, progress=None
    ) -> int:
        """Draw each of ``frames`` (:class:`.animation.Frame`) offscreen at ``size`` on
        ``background`` and save it as ``frame00000.png`` on in ``folder``; how many were
        saved. ``progress(index)`` is called after each and stops the run when it returns
        False. The view's own camera and explode are as they were afterwards."""
        if self.renderer is None or self.scene is None or self.error:
            raise GLError("the 3D view is not drawing")
        w, h = size
        self.finish_animation()
        self.finish_camera()
        if self.can_explode and self.explosion is None and any(f.explode for f in frames):
            self._prepare_explosion()
        if self.explosion is not None and self.explosion.groups:
            from .animation import steady_framing

            frames = steady_framing(frames, self._fitted_half(w / h), self._box_centre)
        saved = self.explode
        colour = QColor(background)
        done = 0
        self.makeCurrent()
        try:
            for f in frames:
                self.explode = f.explode if self.can_explode else 0.0
                if not self._sync():
                    raise GLError("the 3D view could not take the model again")
                camera = self.camera.copy()
                if self.explosion is not None and self.explosion.groups:
                    camera.bbox = self.explosion.bbox_at(self.explode)
                camera.set_state(
                    {
                        "yaw": f.yaw,
                        "pitch": f.pitch,
                        "target": list(f.target),
                        "half_height": f.half_height,
                        "shift": [0.0, 0.0],
                        "fitted": False,
                    }
                )
                camera.set_aspect(w / h)
                image = self.renderer.render_image(camera, colour, (w, h))
                if not image.save(os.path.join(folder, f"frame{f.index:05d}.png"), "PNG"):
                    raise GLError("a frame could not be saved")
                done += 1
                if progress is not None and progress(f.index) is False:
                    break
        finally:
            self.explode = saved
            self.doneCurrent()
            self.update()
        return done

    def _fitted_half(self, aspect: float):
        """``(yaw, pitch, amount) -> half height`` that fits the assembly exploded by
        ``amount`` from that direction in a whole view of ``aspect``: Save Animation's framing."""

        def half(yaw: float, pitch: float, amount: float) -> float:
            c = self.camera.copy()
            c.bbox = self.explosion.bbox_at(amount)
            c.free, c.avoid = ((-1.0, -1.0, 1.0, 1.0),), None
            c.set_state({"yaw": yaw, "pitch": pitch, "target": list(c.center), "half_height": 1.0})
            c.aspect = aspect
            c.fit()
            return c.half_height

        return half

    def _box_centre(self, amount: float) -> tuple[float, float, float]:
        (x0, y0, z0), (x1, y1, z1) = self.explosion.bbox_at(amount)
        return ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)

    # -- the exploded view ---------------------------------------------------------------
    @property
    def can_explode(self) -> bool:
        """Whether this is an assembly, whose instances the exploded view can move."""
        return self.scene is not None and self.scene.ids is not None

    @property
    def animating(self) -> bool:
        return self._animation is not None

    def set_explode_level(self, level: str) -> None:
        """Group the instances at ``level`` (:data:`.explode.TOP` or ``PARTS``); an
        exploded view moves to the new groups' places at once."""
        if level == self.explode_level and (self.explosion is not None or not self.explode_target):
            return
        self.explode_level = level
        self.explosion = None
        if self.explode or self.explode_target:
            self._prepare_explosion()
            self._follow_explode()

    def explode_to(self, amount: float, *, animate: bool = True, follow: bool = False) -> None:
        """Explode the assembly to ``amount`` (0 collapsed to 1 fully exploded), easing
        there from where it is, or at once without ``animate``. With ``follow`` (the
        slider dragged, or stepped by a key) the view closes on the amount at once and
        keeps closing on it as it changes (:class:`.explode.Follow`), instead of easing
        from rest again at each change. A part never explodes."""
        amount = min(max(float(amount), 0.0), 1.0)
        if not self.can_explode:
            return
        self.explode_target = amount
        if amount and self.explosion is None:
            self._prepare_explosion()
        now = self._clock()
        if follow and amount != self.explode:
            if isinstance(self._animation, Follow):
                self._animation.retarget(amount, now)
            else:
                self._animation = Follow(self.explode, amount, now)
            if not self._ticker.isActive():
                self._ticker.start()
            return
        if animate and amount != self.explode:
            self._animation = Animation(self.explode, amount, now)
            if not self._ticker.isActive():
                self._ticker.start()
            return
        if self._move is None:
            self._ticker.stop()
        self._animation = None
        self._set_explode(amount)

    def finish_animation(self) -> None:
        """Jump to where the animation is heading."""
        if self._animation is not None:
            if self._move is None:
                self._ticker.stop()
            target, self._animation = self._animation.target, None
            self._set_explode(target)

    def _prepare_explosion(self) -> None:
        if self.scene is not None:
            self.explosion = self.scene.explosion(
                self.explode_level, self.explode_choices, self.hidden if any(self.hidden) else None
            )
            self._offsets_pending = True

    def _tick(self) -> None:
        """A step of the explode's easing and of the camera's move, whichever run."""
        now = self._clock()
        anim = self._animation
        if anim is not None:
            if anim.done(now):
                self._animation = None
                self._set_explode(anim.target)
            else:
                self._set_explode(anim.value(now))
        move = self._move
        if move is not None:
            if move.apply(self.camera, now):
                self._move = None
            self.update()
        if self._animation is None and self._move is None:
            self._ticker.stop()

    def _set_explode(self, amount: float) -> None:
        self.explode = amount
        self._follow_explode()
        self.explodeChanged.emit(amount)

    def _follow_explode(self) -> None:
        """The camera's box follows the exploded assembly, of what is shown (all of it when
        nothing is), and a fitted camera refits."""
        if self.scene is None:
            return
        if self.explosion is not None and self.explosion.groups:
            box = self.explosion.bbox_at(self.explode)
        else:
            box = self.scene.bbox_of([not h for h in self.hidden] if self.hidden else None)
        self.camera.bbox = box
        if self.camera.fitted:
            self.camera.fit()
        self.update()

    def fit(self) -> None:
        self._stop_move()
        self.camera.fit()
        self.update()

    def update(self, *args) -> None:  # type: ignore[override]
        """Draw again; the view cube turns with the camera at once."""
        cube = getattr(self, "cube", None)
        if cube is not None:
            cube.follow(self.camera.axes, self.camera.mode)
        super().update(*args)

    def camera_state(self) -> dict[str, Any]:
        """The direction the camera looks from, what it looks at and how far it is zoomed,
        and whether it is fitted: what Back puts back (:meth:`set_camera_state`). While the
        camera moves (:attr:`moving`), where the move ends: Back taken then returns where
        the user was going."""
        if self._move is not None:
            return self._move.state(self.camera)
        return self.camera.state()

    def set_camera_state(self, state: dict[str, Any], *, animate: bool = False) -> None:
        """Turn and zoom the camera as :meth:`camera_state` gave it, at once (Back) or with
        ``animate`` easing there. A fitted one fits what is shown now, from that direction."""
        self._move_to(state, animate)

    def set_rotation_mode(self, mode: str) -> None:
        """Turn freely or as a turntable (:data:`.viewmath.ROTATION_MODES`); a view turned
        freely becomes the upright one from the same direction as a turntable. A move under
        way ends first."""
        self.finish_camera()
        self.rotation_mode = mode
        self.camera.set_mode(mode)
        self.update()

    def reset_view(self, *, animate: bool = False) -> None:
        """The isometric view, fitted (R, and the Isometric button, which ease there)."""
        self.set_view("isometric", animate=animate)

    def set_view(self, name: str, *, animate: bool = False) -> None:
        """A standard view (:data:`.viewmath.VIEWS`), fitted: at once, or with ``animate``
        easing there (Ctrl+1 to Ctrl+7)."""
        if animate:
            yaw, pitch = VIEWS[name]
            self._move_to({"yaw": yaw, "pitch": pitch, "fitted": True}, True)
            return
        self._stop_move()
        self.camera.set_view(name)
        self.update()

    # -- the view cube and Home ----------------------------------------------------------
    @property
    def moving(self) -> bool:
        """Whether a camera move is under way."""
        return self._move is not None

    def finish_camera(self) -> None:
        """Jump to the end of the camera move under way, if any."""
        move, self._move = self._move, None
        if move is not None:
            move.finish(self.camera)
            self.update()

    def _stop_move(self) -> None:
        """Another way of moving the camera takes over: the move stops where it is."""
        self._move = None

    @property
    def dragging(self) -> bool:
        """Whether a drag holds the camera: a button pressed on the view, or on the view cube."""
        return self._drag is not None or self.cube.pressed

    def _move_to(self, end: dict[str, Any], animate: bool) -> None:
        """Ease the camera to the state ``end`` from where it is now, or put it there at once:
        at once too where nothing could be seen easing (a view not shown) and where a drag
        holds the camera (:attr:`dragging`), whose next move would stop the move a step in;
        the drag goes on from there, a turn reading its point under the pointer again."""
        if animate and self.isVisible() and not self.dragging:
            self._move = CameraMove(self.camera, end, self._clock())
            self.camera.fitted = False  # nothing refits it under the move
            if not self._ticker.isActive():
                self._ticker.start()
        else:
            self._move = None
            self.camera.set_state(end)
            if self._drag is not None:
                self._about = False
                self.pivot_mark.hide()
                self._anchor = QPointF(self._last)
        self.update()

    def _home_state(self) -> dict[str, Any]:
        return dict(self.home) if self.home else {"yaw": ISO_YAW, "pitch": ISO_PITCH, "fitted": True}

    def use_home(self, state: dict[str, Any] | None) -> None:
        """The document's Home, before its scene is shown: None for the isometric, fitted."""
        self.home = dict(state) if state else None
        self.cube.has_home = self.home is not None

    def go_home(self, *, animate: bool = True) -> None:
        """Home: the view this document opened with, the isometric fitted unless the user set
        another (:meth:`set_home`)."""
        self._move_to(self._home_state(), animate)

    def set_home(self, current: bool) -> None:
        """Make the camera as it is now Home (``current``), or the isometric again; a fitted
        view kept as Home fits whatever is shown when it is used."""
        self.use_home(self.camera_state() if current else None)
        self.homeChanged.emit(self.home)

    def look_at_region(self, region: Sequence[int], *, animate: bool = True) -> None:
        """Look from a view cube region's direction, upright and fitted."""
        yaw, pitch = region_angles(region)
        self._move_to({"yaw": yaw, "pitch": pitch, "fitted": True}, animate)

    def step(self, side: str, *, animate: bool = True) -> None:
        """A view cube step arrow, while the view looks at a face square on: a quarter turn
        about the screen's vertical or horizontal axis that brings the face on that side to
        the front (:func:`.viewcube.stepped`). Free, it stays turned as the step turned it;
        a turntable looks at that face upright. Fitted. Nothing from a view rolled part of
        the way, where the arrows are not shown."""
        axes = viewcube.stepped(self.camera.axes, side)
        if axes is not None:
            self._move_to(self._square_state(axes), animate)

    def cube_roll(self, sign: int, *, animate: bool = True) -> None:
        """A view cube roll arrow, while the view looks straight at a face: counter-clockwise on
        the screen (``sign`` 1) or clockwise (-1) to the next quarter turn
        (:func:`.viewcube.rolled`), 90 degrees from a view square on, less from one rolled
        part of the way; fitted. A turntable rolls only looking straight down or up."""
        axes = viewcube.rolled(self.camera.axes, sign)
        if axes is None or (self.camera.mode != FREE and not axes[2][1]):
            return
        self._move_to(self._square_state(axes), animate)

    def _square_state(self, axes: tuple) -> dict[str, Any]:
        """The fitted camera state looking along whole axes (right, up, back): for a turntable
        upright, from the same direction."""
        right, up, back = (tuple(float(v) for v in a) for a in axes)
        yaw, pitch = upright_angles(right, back)
        if self.camera.mode == FREE:
            return {"yaw": yaw, "pitch": pitch, "axes": [list(right), list(up)], "fitted": True}
        return {"yaw": round(yaw, 9) % 360.0, "pitch": round(pitch, 9), "fitted": True}

    def _cube_dragged(self, dx: float, dy: float) -> None:
        """A drag on the view cube turns the model as a drag on the view does, about its
        target: the pointer is over the cube, not the model."""
        self._stop_move()
        self.camera.rotate(dx, dy)
        self.update()

    def _cube_drag_ended(self) -> None:
        self.camera.to_model_depth()
        self.update()

    def overlays_changed(self) -> None:
        """Something laid over the view (the legend, which says so with its ``reservesArea``
        property) came, went or moved: the areas a fit may centre the model in are worked
        out again, the view less the column over its right that the legend and the view
        cube take (:func:`.viewmath.free_areas`), and a fitted camera fits again. Without
        the legend the cube's corner is kept clear where that costs little
        (:func:`.viewmath.avoid_area`): a fit that would reach under the cube puts the
        model left of it or below it instead, unless that draws it under
        :data:`.viewmath.OrbitCamera.AVOID_SHARE` as large."""
        reserved, beside = [], []
        for child in self.children():
            if isinstance(child, QWidget) and child.isVisibleTo(self):
                rect = child.geometry().getRect()
                if child.property("reservesArea"):
                    reserved.append(rect)
                elif child is self.cube:
                    beside.append(rect)
        w, h = self.width(), self.height()
        avoid = avoid_area(w, h, beside[0]) if beside else None
        self.camera.set_free(free_areas(w, h, reserved, beside), avoid)
        self.update()

    def overlay_at(self, x: float, y: float) -> QWidget | None:
        """The widget laid over the view that a click at the view position ``(x, y)`` would
        reach instead of the view: the cube where it has a region or a button, anything
        else that takes clicks (the legend). None where the click is the view's."""
        point = QPoint(int(x), int(y))
        for child in self.children():
            if not isinstance(child, QWidget) or not child.isVisibleTo(self):
                continue
            if child.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents):
                continue
            if not child.geometry().contains(point):
                continue
            if child is self.cube and self.cube.at(x - child.x(), y - child.y()) is None:
                continue  # beside the cube: the cube passes the click on to the view
            return child
        return None

    def legend_top(self) -> int:
        """Where something laid over the view's top-right corner (the legend) starts: under
        the view cube when it is shown."""
        rect = viewcube.placement(self.width(), self.height()) if self.show_cube else None
        return viewcube.MARGIN if rect is None else rect[1] + rect[3] + 6

    def set_about_pointer(self, on: bool) -> None:
        """Settings: turn about the surface under the pointer, or about the middle of the view."""
        self.about_pointer = on

    def roll(self, degrees: float) -> None:
        """Roll the model ``degrees`` counter-clockwise on the screen (clockwise when negative)
        about the line of sight, at once; a turntable only looking straight down or up."""
        self._stop_move()
        if self.camera.roll(degrees):
            self.update()

    def set_cube_shown(self, on: bool) -> None:
        """Settings: show the view cube or not; a fit keeps clear of it only while shown."""
        if on != self.show_cube:
            self.show_cube = on
            self._place_cube()
            self.overlays_changed()

    def _place_cube(self) -> None:
        rect = viewcube.placement(self.width(), self.height()) if self.show_cube else None
        before = (self.cube.isVisibleTo(self), self.cube.geometry())
        if rect is None:
            self.cube.hide()
        else:
            self.cube.setGeometry(*rect)
            self.cube.show()
            self.cube.raise_()
        if (self.cube.isVisibleTo(self), self.cube.geometry()) != before:
            self.layoutChanged.emit()

    def _follow_size(self, width: int, height: int) -> None:
        self.camera.set_aspect(width / max(height, 1))

    def resizeEvent(self, event) -> None:
        # Before OpenGL is ready, and wherever it is not, the camera still follows.
        self._follow_size(event.size().width(), event.size().height())
        self._place_cube()
        self.overlays_changed()
        super().resizeEvent(event)

    # -- OpenGL --------------------------------------------------------------------------
    def initializeGL(self) -> None:
        try:
            self.renderer = Renderer()
        except GLError as exc:
            self._fail(str(exc))
            return
        ctx = self.context()
        if ctx is not None:
            ctx.aboutToBeDestroyed.connect(self._cleanup)

    def _fail(self, why: str) -> None:
        self.error = why
        QTimer.singleShot(0, lambda: self.failed.emit(why))

    def _cleanup(self) -> None:
        if self.renderer is not None:
            self.makeCurrent()
            self.renderer.release()
            self.renderer = None
            self.doneCurrent()

    def resizeGL(self, w: int, h: int) -> None:
        self._follow_size(w, h)

    def _sync(self) -> bool:
        """Bring the GPU up to what the view shows, with the context current: the scene,
        the explode offsets and amount, and the instances picked. False when it cannot
        draw."""
        if self.renderer is None:
            return False
        if self._pending:
            self._pending = False
            try:
                self.renderer.upload(self.scene)
            except GLError as exc:
                self._fail(str(exc))
                return False
            QTimer.singleShot(0, lambda s=self.renderer.upload_seconds: self.uploaded.emit(s))
            self._offsets_pending = self.explosion is not None
            self._states_pending = bool(self.selected)
            self._looks_pending = bool(self.opacity)
        if self._offsets_pending:
            self._offsets_pending = False
            self.renderer.set_offsets(self.explosion.offsets if self.explosion is not None else None)
        if self._states_pending:
            self._states_pending = False
            self.renderer.set_states(self.selected)
        if self._looks_pending:
            self._looks_pending = False
            self.renderer.set_looks(self.opacity or None, self.hidden or None)
        self.renderer.explode = self.explode
        return True

    def paintGL(self) -> None:
        if self.renderer is None:
            return
        t = time.perf_counter()
        if not self._sync():
            return
        self._follow_size(self.width(), self.height())
        dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
        self.renderer.draw(
            self.camera, _DARK_BACKGROUND if dark else _LIGHT_BACKGROUND, finish=self.measure_frames
        )
        self.frame_seconds = time.perf_counter() - t
        self.cube.follow(self.camera.axes, self.camera.mode)  # whatever moved the camera

    # -- the mouse and keys -------------------------------------------------------------
    def mousePressEvent(self, event) -> None:
        button = {
            Qt.MouseButton.LeftButton: "left",
            Qt.MouseButton.RightButton: "right",
            Qt.MouseButton.MiddleButton: "middle",
        }.get(event.button())
        mods = event.modifiers()
        self._drag = (
            drag_action(
                self.mouse_style,
                button or "",
                ctrl=bool(mods & Qt.KeyboardModifier.ControlModifier),
                shift=bool(mods & Qt.KeyboardModifier.ShiftModifier),
            )
            if button
            else None
        )
        self._press_button = button
        self._right_own = button == "right"
        self._last = self._press = self._anchor = event.position()
        self._about = False  # read at the first move of a turn: a click costs nothing more
        self._stop_move()  # the user takes the camera from wherever the move got to
        self._drag_cursor()
        event.accept()

    def _drag_cursor(self) -> None:
        if self._drag == ROTATE:
            self.setCursor(rotate_cursor())
        elif self._drag == PAN:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)  # as the preview image pans
        elif self._drag == ZOOM:
            self.setCursor(Qt.CursorShape.SizeVerCursor)

    def _pivot(self) -> Vec3 | None:
        """The point a turn drag turns about: the surface under the pointer where the turn
        began, read once (the picture has not changed since); None for the target, where
        nothing is under it or the setting is off."""
        if self._about is False:
            self._about = None
            if self.about_pointer:
                self._about = self.surface_at(self._anchor.x(), self._anchor.y())
            if self._about is not None:
                self.pivot_mark.show_at(self._anchor.x(), self._anchor.y())
        return self._about  # type: ignore[return-value]

    @property
    def turning_about(self) -> Vec3 | None:
        """The model point the turn under way turns about, read under the pointer; None for
        none (no turn, nothing there, or turning about the middle of the view)."""
        return self._about if self._about else None  # type: ignore[return-value]

    def _end_turn(self) -> None:
        """A turn about a point under the pointer is over: the target goes back to the depth
        of the model's centre (which changes nothing on screen), and the mark goes."""
        if self._about:
            self.camera.to_model_depth()
        self._about = False
        self.pivot_mark.hide()

    def _redrag(self, mods) -> None:
        """SOLIDWORKS style: Ctrl or Shift pressed or let go during a middle-drag switches it
        between rotating, panning (Ctrl) and zooming (Shift), from where the pointer is."""
        if self.mouse_style != SOLIDWORKS or self._press_button != "middle" or self._drag is None:
            return
        new = drag_action(
            SOLIDWORKS,
            "middle",
            ctrl=bool(mods & Qt.KeyboardModifier.ControlModifier),
            shift=bool(mods & Qt.KeyboardModifier.ShiftModifier),
        )
        if new == self._drag or new is None:
            return
        if self._drag == ROTATE:
            self._end_turn()
        self._drag = new
        self._anchor = QPointF(self._last)  # a zoom zooms toward here, a turn reads its point here
        self._about = False
        self._drag_cursor()

    def mouseMoveEvent(self, event) -> None:
        if self._drag is None:
            return
        self._stop_move()  # the drag holds the camera, as its press took it
        self._redrag(event.modifiers())
        pos = event.position()
        dx, dy = pos.x() - self._last.x(), pos.y() - self._last.y()
        self._last = pos
        if self._drag == ROTATE:
            self.camera.rotate(dx, dy, self._pivot())
        elif self._drag == PAN:
            self.camera.pan(dx, dy, self.height())
        elif self._drag == ZOOM:  # drag up to zoom in, toward where the drag began
            self.camera.zoom(
                1.01 ** (-dy), ndc(self._anchor.x(), self._anchor.y(), self.width(), self.height())
            )
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        """A press and release that hardly moved is a click: the left button picks the
        instance there, the right one may ask for its menu."""
        if self._drag == ROTATE:
            self._end_turn()
        self._drag = None
        self.unsetCursor()
        button, self._press_button = self._press_button, None
        pos = event.position()
        moved = abs(pos.x() - self._press.x()) + abs(pos.y() - self._press.y())
        if button == "right":
            self._right_moved = moved
            if self._menu_on_release:
                self._menu_on_release = False
                if moved <= CLICK_SLOP:
                    self._request_menu(pos, event.globalPosition().toPoint())
        elif button == "left" and moved <= CLICK_SLOP and self.can_pick:
            index = self.instance_at(pos.x(), pos.y())
            self.picked.emit(-1 if index is None else index)

    def mouseDoubleClickEvent(self, event) -> None:
        """On an assembly's instance, ask for its file; anywhere else, fit."""
        if event.button() == Qt.MouseButton.LeftButton and self.can_pick:
            pos = event.position()
            index = self.instance_at(pos.x(), pos.y())
            if index is not None:
                self.activated.emit(index)
                return
        self.fit()

    def contextMenuEvent(self, event) -> None:
        """The right button pans, so only a right-click without a drag asks for a menu: of
        the instance there in an assembly, else (-1) of the empty space, or of a part. Only
        for a right press of the view's own: one the view cube took and that was dragged
        here is the cube's gesture (Windows asks for the menu where the button is let go)."""
        event.accept()
        if not self.can_menu:
            return
        if event.reason() == QContextMenuEvent.Reason.Mouse:
            if not self._right_own:
                return
            if QGuiApplication.mouseButtons() & Qt.MouseButton.RightButton:
                self._menu_on_release = True  # asked on the press here: see whether it drags
                return
            self._right_own = False
            if self._right_moved > CLICK_SLOP:
                return
        self._request_menu(QPointF(event.pos()), event.globalPos())

    def _request_menu(self, pos: QPointF, global_pos: QPoint) -> None:
        index = self.instance_at(pos.x(), pos.y())
        self.menuRequested.emit(-1 if index is None else index, global_pos)

    def event(self, e) -> bool:
        """Hovering over an instance names it. As in SOLIDWORKS, Tab hides the instance
        under the pointer and Shift+Tab shows every hidden one again; with nothing to
        hide or show they move the keyboard focus, as they do elsewhere (Qt takes them
        for that before :meth:`keyPressEvent`)."""
        if e.type() == QEvent.Type.KeyPress and self._hide_key(e):
            e.accept()
            return True
        if e.type() == QEvent.Type.ToolTip and self.can_pick and self.describe is not None:
            index = self.instance_at(e.pos().x(), e.pos().y())
            text = self.describe(index) if index is not None else ""
            if text:
                QToolTip.showText(e.globalPos(), tip(text), self)
            else:
                QToolTip.hideText()
                e.ignore()
            return True
        return super().event(e)

    def _hide_key(self, e) -> bool:
        """Tab or Shift+Tab acted on (see :meth:`event`)."""
        mods = e.modifiers()
        # each modifier named, never ~Shift: PySide6 on Windows inverts a flag within its
        # own bits only (0x1FFFFFF), which loses Ctrl (0x04000000) and Alt
        others = (
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.AltModifier
            | Qt.KeyboardModifier.MetaModifier
        )
        if not self.can_pick or mods & others:
            return False
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if e.key() == Qt.Key.Key_Backtab or (e.key() == Qt.Key.Key_Tab and shift):
            if self.any_hidden is None or not self.any_hidden():
                return False
            self.showAllRequested.emit()
            return True
        if e.key() != Qt.Key.Key_Tab:
            return False
        pos = self.mapFromGlobal(QCursor.pos())
        if not self.rect().contains(pos):
            return False
        index = self.instance_at(pos.x(), pos.y())
        if index is None:
            return False
        self.hideRequested.emit(index)
        return True

    def wheelEvent(self, event) -> None:
        """The wheel zooms toward the pointer; a horizontal scroll (a two-finger touchpad
        swipe, a tilted wheel) turns the model about the screen's vertical axis instead,
        :data:`.viewmath.ARROW_STEP` degrees a notch, its front following the fingers as
        the content of a scroll area does."""
        across, down = event.angleDelta().x(), event.angleDelta().y()
        if abs(across) > abs(down):
            self._stop_move()
            self.camera.turn_model(ARROW_STEP * across / 120.0, 0.0)
            self.update()
            event.accept()
            return
        steps = down / 120.0
        if not steps:
            return
        self._stop_move()
        pos = event.position()
        self.camera.zoom(
            wheel_factor(steps, style=self.mouse_style, invert=self.invert_wheel),
            ndc(pos.x(), pos.y(), self.width(), self.height()),
        )
        self.update()
        event.accept()

    _ARROWS = {
        Qt.Key.Key_Left: (-1, 0),
        Qt.Key.Key_Right: (1, 0),
        Qt.Key.Key_Up: (0, -1),
        Qt.Key.Key_Down: (0, 1),
    }
    _DIGITS = {getattr(Qt.Key, f"Key_{n}"): n for n in VIEW_KEYS}
    _MODIFIER = {
        Qt.Key.Key_Control: Qt.KeyboardModifier.ControlModifier,
        Qt.Key.Key_Shift: Qt.KeyboardModifier.ShiftModifier,
    }

    def keyReleaseEvent(self, event) -> None:
        """Ctrl or Shift let go during a SOLIDWORKS middle-drag: back to what the rest gives."""
        key = event.key()
        if key in self._MODIFIER:
            self._redrag(event.modifiers() & ~self._MODIFIER[key])
        super().keyReleaseEvent(event)

    def keyPressEvent(self, event) -> None:
        """F fits, R is isometric, Home goes Home, Esc drops the instance picked; as in
        SOLIDWORKS, an arrow key turns the model as a drag that way would, 15 degrees (90
        with Shift), about the screen's axes when rotation is free, Ctrl+arrow pans a
        tenth of the view and Ctrl+1 to Ctrl+7 are Front, Back, Left, Right, Top, Bottom
        and Isometric. R, Home and Ctrl+1 to Ctrl+7 ease there (at once during a drag, which
        goes on from there); the others act at once. Page Up and Page Down roll the model 15
        degrees about the line of sight (90 with Shift; a turntable only looking straight
        down or up), Alt+Left being Back. Ctrl or Shift pressed during a SOLIDWORKS
        middle-drag switches it."""
        key, mods = event.key(), event.modifiers()
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift):
            self._redrag(mods | self._MODIFIER[key])
            super().keyPressEvent(event)
            return
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        if key in self._ARROWS:
            self._stop_move()
            dx, dy = self._ARROWS[key]
            if ctrl:
                self.camera.pan(dx * self.width() / 10, dy * self.height() / 10, self.height())
            else:
                step = 90.0 if shift else ARROW_STEP
                self.camera.turn_model(dx * step, dy * step)
            self.update()
        elif ctrl and key in self._DIGITS:
            self.set_view(VIEW_KEYS[self._DIGITS[key]], animate=True)
        elif key == Qt.Key.Key_F and not ctrl:
            self.fit()
        elif key == Qt.Key.Key_R and not ctrl:
            self.reset_view(animate=True)
        elif key == Qt.Key.Key_Home and not ctrl:
            self.go_home()
        elif key in (Qt.Key.Key_PageUp, Qt.Key.Key_PageDown) and not ctrl:
            step = 90.0 if shift else ARROW_STEP
            self.roll(step if key == Qt.Key.Key_PageUp else -step)
        elif key == Qt.Key.Key_Escape and self.selected:
            self.picked.emit(-1)  # as a click on nothing
        else:
            super().keyPressEvent(event)
            return
        event.accept()
