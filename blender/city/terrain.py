"""Ground plane, streets, river, bridges, park lawn and pond.

Responsible for everything `buildings.html`'s `terrain()`, `streets()`,
`water()`, `bridges()`, and the lawn/pond part of `parkland()` build: the
1600x1600 ground plane, the downtown asphalt sheet + lane markings + kerbed
block platforms (using `city.layout.col_x`/`row_z`/`HALF_X`/`HALF_Z`), the
river mesh (using `city.layout.river_centre`), the two bridges (using
`city.layout.BRIDGE_Z`), and the park lawn ellipse + pond circle (using
`city.layout.PARK`/`POND`).

Consumes from `ctx.materials`: `asphalt`, `water`, `kerb`, `bridge`,
`lane_paint`, `park_grass`, `gravel`. Produces no new `ctx.materials` keys.

COORDINATE NOTE — every vertex this module emits goes through `_pt()` /
`_add_box()`, which apply the three.js -> Blender axis mapping from
`layout.py`'s `COORDINATE_NOTE` (`blender_xyz = (three_x, three_z,
three_y)`) exactly once, at the point of construction. All the geometry
maths below stays in three.js-named terms (x east-west, z north-south, y
height) so it can be checked line-by-line against `buildings.html`.
"""

from __future__ import annotations

import logging
import math

import bmesh
import bpy

from city.layout import (
    BLOCK,
    BRIDGE_Z,
    COLS,
    HALF_X,
    HALF_Z,
    PARK,
    PITCH,
    POND,
    RIVER_W,
    ROWS,
    Y,
    col_x,
    river_centre,
    row_z,
)

logger = logging.getLogger(__name__)

COLLECTION_NAME = "Terrain"

# Dash pattern for lane markings, ported from buildings.html's laneTexture():
# a 64px-wide canvas with a 34px dash, tiled via `mat.map.repeat.set(len /
# 12, 1)` -- i.e. one texture tile every 12 world units, of which 34/64 is
# painted. We replace the canvas trick with real dashed geometry (see
# `_dash_ranges`) -- one of the places Blender's mesh tools do outright what
# three.js needed a texture hack for.
_LANE_PERIOD = 12.0
_LANE_DASH_FRAC = 34.0 / 64.0

# Local corner offsets for a box centred on the origin, ordered so that
# `_CUBE_FACES` below gives outward-pointing normals for an UNROTATED box in
# Blender's own (x, y, z) axes. A proper rotation (see `_add_box`'s
# `rotate_y_rad`) preserves orientation, so the same face list stays correct
# even after tilting -- `_add_box` also runs `_recalc_outward` as a
# belt-and-braces check since every box here is a closed 6-face solid.
_CUBE_FACES: tuple[tuple[int, int, int, int], ...] = (
    (0, 3, 2, 1),  # -Z
    (4, 5, 6, 7),  # +Z
    (0, 1, 5, 4),  # -Y
    (3, 7, 6, 2),  # +Y
    (0, 4, 7, 3),  # -X
    (1, 2, 6, 5),  # +X
)


def build_terrain(ctx) -> None:
    """Build ground, streets, river, bridges, park lawn and pond.

    Args:
        ctx: the `BuildContext` from `build_city.py`.
    """
    collection = _get_or_create_collection(COLLECTION_NAME)
    _ground(ctx, collection)
    _river(ctx, collection)
    _parkland(ctx, collection)
    _streets(ctx, collection)
    _bridges(ctx, collection)
    logger.info("terrain: built ground, river, park/pond, streets, bridges")


# ===== small shared helpers ==================================================


def _get_or_create_collection(name: str) -> bpy.types.Collection:
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
    return collection


def _material(ctx, key: str, note: str = "") -> bpy.types.Material | None:
    """Look up `ctx.materials[key]`. Missing keys are expected while the
    sibling `materials.py` module is still a stub -- log and fall back to
    Blender's default material rather than crash."""
    mat = ctx.materials.get(key)
    if mat is None:
        logger.warning("terrain: ctx.materials[%r] missing%s -- using Blender's default material", key, note)
    return mat


def _pt(x: float, z: float, y: float = 0.0) -> tuple[float, float, float]:
    """Map three.js-named world (x, z, y) to Blender (x, y, z). See
    layout.py's `COORDINATE_NOTE`: `blender_xyz = (three_x, three_z,
    three_y)`."""
    return (x, z, y)


def _new_object(
    name: str,
    verts: list[tuple[float, float, float]],
    faces: list[tuple[int, ...]],
    collection: bpy.types.Collection,
    material: bpy.types.Material | None = None,
    smooth: bool = False,
) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    if smooth:
        for poly in mesh.polygons:
            poly.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    if material is not None:
        obj.data.materials.append(material)
    collection.objects.link(obj)
    return obj


def _recalc_outward(mesh: bpy.types.Mesh) -> None:
    """Force consistent outward normals on a closed solid via bmesh's data-
    level API (not `bpy.ops`, which is slow/context-dependent in background
    mode)."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()


def _cube_local_corners(ex: float, ey: float, ez: float) -> list[tuple[float, float, float]]:
    """8 corners of a box centred on the origin with Blender-axis full
    extents (ex, ey, ez). Ordering matches `_CUBE_FACES`."""
    hx, hy, hz = ex / 2, ey / 2, ez / 2
    return [
        (-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
        (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz),
    ]


def _add_box(
    collection: bpy.types.Collection,
    name: str,
    x: float,
    y: float,
    z: float,
    w: float,
    h: float,
    d: float,
    material: bpy.types.Material | None = None,
    rotate_y_rad: float = 0.0,
) -> bpy.types.Object:
    """Box specified in three.js-named terms, exactly like buildings.html's
    `box(mat, x, y, z, w, h, d)`: position (x, y=height, z), size (w,
    h=height, d).

    `rotate_y_rad` reproduces `mesh.rotation.z` on one of buildings.html's
    bridge ramps: three.js rotates the box about its *local Z axis* (mixing
    its local x/y, i.e. tilting it in the horizontal-x/height plane). Under
    our coordinate mapping, three.js Z becomes Blender Y, so the same tilt
    is a rotation mixing Blender X/Z while leaving Blender Y (the three.js
    depth axis) untouched -- applied here directly to the local corner
    offsets before translation, so no `bpy` Euler/rotation object is
    needed.
    """
    corners = _cube_local_corners(w, d, h)  # Blender-axis extents: x=w, y=depth(d), z=height(h)
    if rotate_y_rad:
        c, s = math.cos(rotate_y_rad), math.sin(rotate_y_rad)
        corners = [(bx * c - bz * s, by, bx * s + bz * c) for bx, by, bz in corners]
    verts = [(x + bx, z + by, y + bz) for bx, by, bz in corners]
    obj = _new_object(name, verts, list(_CUBE_FACES), collection, material=material)
    _recalc_outward(obj.data)
    return obj


def _ellipse_verts(cx: float, cz: float, rx: float, rz: float, y: float, segments: int) -> list[tuple[float, float, float]]:
    """Rim vertices of an ellipse (circle when rx == rz) in the x/z ground
    plane at height y, walked in increasing-angle order -- paired with
    `_fan_faces` this gives outward (+Blender-Z) normals."""
    verts = []
    for i in range(segments):
        a = 2 * math.pi * i / segments
        verts.append(_pt(cx + rx * math.cos(a), cz + rz * math.sin(a), y))
    return verts


def _fan_faces(center_idx: int, rim_start_idx: int, n: int) -> list[tuple[int, int, int]]:
    faces = []
    for i in range(n):
        v1 = rim_start_idx + i
        v2 = rim_start_idx + (i + 1) % n
        faces.append((center_idx, v1, v2))
    return faces


def _dash_ranges(total_half: float) -> list[tuple[float, float]]:
    """Start/end offsets (from a strip centred at 0, spanning
    [-total_half, +total_half]) for each lane-marking dash. See the
    `_LANE_PERIOD`/`_LANE_DASH_FRAC` comment above."""
    dash_len = _LANE_PERIOD * _LANE_DASH_FRAC
    ranges = []
    pos = -total_half
    while pos < total_half:
        end = min(pos + dash_len, total_half)
        ranges.append((pos, end))
        pos += _LANE_PERIOD
    return ranges


# ===== stage 1: ground ========================================================


def _ground(ctx, collection: bpy.types.Collection) -> None:
    """Large base plane beneath everything, ported from `terrain()`."""
    size = 1600.0
    half = size / 2
    verts = [_pt(-half, -half), _pt(half, -half), _pt(half, half), _pt(-half, half)]
    faces = [(0, 1, 2, 3)]
    # No dedicated "ground" key in the materials contract (see materials.py's
    # docstring) -- park_grass is the closest available tone to buildings.html's
    # olive-green 0x6f7758 base, so we reuse it rather than invent a new key.
    mat = _material(ctx, "ground")
    _new_object("ground", verts, faces, collection, material=mat)


# ===== stage 2: river ==========================================================


def _river(ctx, collection: bpy.types.Collection) -> None:
    """Meandering river strip, sampled along z via `layout.river_centre`.

    The mesh carries width-wise subdivision (7 verts across, not just a
    left/right rail) so a bump/wave material -- materials.py's job, not
    ours -- has geometry to displace; a flat two-vertex-wide strip would
    give Cycles nothing to perturb for specular reflection/refraction. Smooth
    shading is enabled so any such displacement reads as a continuous wave
    rather than faceted panels.
    """
    z0, z1, step = -700.0, 700.0, 10.0
    n_len = int(round((z1 - z0) / step)) + 1
    n_width = 6  # -> 7 verts per cross-section
    mat = _material(ctx, "water")

    verts: list[tuple[float, float, float]] = []
    for i in range(n_len):
        z = z0 + i * step
        cx = river_centre(z)
        for j in range(n_width + 1):
            frac = j / n_width  # 0 (west bank) .. 1 (east bank)
            x = (cx - RIVER_W / 2) + frac * RIVER_W
            verts.append(_pt(x, z, Y.river))

    row_stride = n_width + 1
    faces: list[tuple[int, int, int, int]] = []
    for i in range(n_len - 1):
        for j in range(n_width):
            a = i * row_stride + j
            b = a + 1
            c = a + row_stride + 1
            d = a + row_stride
            faces.append((a, b, c, d))

    _new_object("river", verts, faces, collection, material=mat, smooth=True)


# ===== stage 3: park lawn, pond, gravel loop ==================================


def _parkland(ctx, collection: bpy.types.Collection) -> None:
    _park_lawn(ctx, collection)
    _pond(ctx, collection)
    _gravel_ring(ctx, collection)


def _park_lawn(ctx, collection: bpy.types.Collection) -> None:
    """Elliptical lawn, ported from `parkland()`'s `shape.absellipse(...)`
    (48 curve segments there, matched here)."""
    segments = 48
    mat = _material(ctx, "park_grass")
    center = _pt(PARK.x, PARK.z, Y.park)
    rim = _ellipse_verts(PARK.x, PARK.z, PARK.rx, PARK.rz, Y.park, segments)
    verts = [center] + rim
    faces = _fan_faces(0, 1, segments)
    _new_object("park_lawn", verts, faces, collection, material=mat, smooth=True)


def _pond(ctx, collection: bpy.types.Collection) -> None:
    """Circular pond, ported from `parkland()`'s `CircleGeometry(pond.r, 40)`."""
    segments = 40
    mat = _material(ctx, "water")
    center = _pt(POND.x, POND.z, Y.pond)
    rim = _ellipse_verts(POND.x, POND.z, POND.r, POND.r, Y.pond, segments)
    verts = [center] + rim
    faces = _fan_faces(0, 1, segments)
    _new_object("pond", verts, faces, collection, material=mat, smooth=True)


def _gravel_ring(ctx, collection: bpy.types.Collection) -> None:
    """Gravel loop path around the pond, ported from `parkland()`'s
    `RingGeometry(pond.r + 4, pond.r + 8, 48)`."""
    segments = 48
    mat = _material(ctx, "gravel")
    y = Y.park + 0.15
    inner = _ellipse_verts(POND.x, POND.z, POND.r + 4, POND.r + 4, y, segments)
    outer = _ellipse_verts(POND.x, POND.z, POND.r + 8, POND.r + 8, y, segments)
    verts = inner + outer

    faces: list[tuple[int, int, int, int]] = []
    for i in range(segments):
        i2 = (i + 1) % segments
        in_i, in_i2 = i, i2
        out_i, out_i2 = segments + i, segments + i2
        faces.append((in_i, out_i, out_i2, in_i2))

    _new_object("gravel_ring", verts, faces, collection, material=mat)


# ===== stage 4: streets (asphalt, arterials, lane paint, kerb platforms) =====


def _streets(ctx, collection: bpy.types.Collection) -> None:
    _asphalt_sheet(ctx, collection)
    _arterial_roads(ctx, collection)
    _lane_markings(ctx, collection)
    _kerb_platforms(ctx, collection)


def _asphalt_sheet(ctx, collection: bpy.types.Collection) -> None:
    """Downtown asphalt sheet, `HALF_X*2 x HALF_Z*2`, matching `streets()`."""
    mat = _material(ctx, "asphalt")
    verts = [
        _pt(-HALF_X, -HALF_Z, Y.asphalt), _pt(HALF_X, -HALF_Z, Y.asphalt),
        _pt(HALF_X, HALF_Z, Y.asphalt), _pt(-HALF_X, HALF_Z, Y.asphalt),
    ]
    _new_object("downtown_asphalt", verts, [(0, 1, 2, 3)], collection, material=mat)


def _arterial_roads(ctx, collection: bpy.types.Collection) -> None:
    """The two arterial roads (one per `BRIDGE_Z` value) running the full
    760-unit width, sitting fractionally below the downtown sheet -- matches
    `streets()`'s `PlaneGeometry(760, 9)` at `Y.asphalt - 0.05`."""
    mat = _material(ctx, "asphalt")
    half_len = 380.0
    half_w = 4.5
    y = Y.asphalt - 0.05
    for z in BRIDGE_Z:
        verts = [
            _pt(-half_len, z - half_w, y), _pt(half_len, z - half_w, y),
            _pt(half_len, z + half_w, y), _pt(-half_len, z + half_w, y),
        ]
        _new_object(f"arterial_road_{z:g}", verts, [(0, 1, 2, 3)], collection, material=mat)


def _lane_markings(ctx, collection: bpy.types.Collection) -> None:
    """Dashed lane markings down every downtown-grid road corridor -- real
    geometry (see `_dash_ranges`) standing in for buildings.html's
    canvas-texture dashes. One mesh per corridor line, each mesh containing
    every dash as a disconnected quad, keeps the object count sane (10
    objects instead of one per dash)."""
    mat = _material(ctx, "lane_paint")
    half_w = 0.275  # ported from paint()'s PlaneGeometry(len, 0.55)

    for j in range(ROWS - 1):
        z_at = row_z(j) + PITCH / 2
        verts: list[tuple[float, float, float]] = []
        faces: list[tuple[int, int, int, int]] = []
        for start, end in _dash_ranges(HALF_X):
            base = len(verts)
            verts.extend([
                _pt(start, z_at - half_w, Y.paint), _pt(end, z_at - half_w, Y.paint),
                _pt(end, z_at + half_w, Y.paint), _pt(start, z_at + half_w, Y.paint),
            ])
            faces.append((base, base + 1, base + 2, base + 3))
        _new_object(f"lane_row_{j}", verts, faces, collection, material=mat)

    for i in range(COLS - 1):
        x_at = col_x(i) + PITCH / 2
        verts = []
        faces = []
        for start, end in _dash_ranges(HALF_Z):
            base = len(verts)
            verts.extend([
                _pt(x_at - half_w, start, Y.paint), _pt(x_at + half_w, start, Y.paint),
                _pt(x_at + half_w, end, Y.paint), _pt(x_at - half_w, end, Y.paint),
            ])
            faces.append((base, base + 1, base + 2, base + 3))
        _new_object(f"lane_col_{i}", verts, faces, collection, material=mat)


def _kerb_platforms(ctx, collection: bpy.types.Collection) -> None:
    """One kerbed slab per block, top at `Y.kerb_top`, matching `streets()`'s
    `box(kerbMat, colX(i), Y.kerbTop - 0.4, rowZ(j), BLOCK, 0.8, BLOCK)`."""
    mat = _material(ctx, "kerb")
    for i in range(COLS):
        for j in range(ROWS):
            _add_box(
                collection, f"kerb_{i}_{j}",
                x=col_x(i), y=Y.kerb_top - 0.4, z=row_z(j),
                w=BLOCK, h=0.8, d=BLOCK,
                material=mat,
            )


# ===== stage 5: bridges ========================================================


def _bridges(ctx, collection: bpy.types.Collection) -> None:
    """Deck, ramps, piers and railings per `BRIDGE_Z` crossing, ported from
    `bridges()`."""
    mat = _material(ctx, "bridge")
    for z in BRIDGE_Z:
        cx = river_centre(z)
        deck_y = 3.4
        span = 74.0
        tag = f"{z:g}"

        _add_box(collection, f"bridge_deck_{tag}", x=cx, y=deck_y, z=z, w=span, h=1.1, d=9.5, material=mat)

        for direction in (-1, 1):
            ramp_x = cx + direction * (span / 2 + 9)
            theta = direction * math.atan2(deck_y, 20.0)
            _add_box(
                collection, f"bridge_ramp_{tag}_{'east' if direction > 0 else 'west'}",
                x=ramp_x, y=deck_y / 2 + 0.2, z=z, w=20.0, h=1.1, d=9.5,
                material=mat, rotate_y_rad=theta,
            )

        for dx in (-13, 13):
            _add_box(
                collection, f"bridge_pier_{tag}_{dx}",
                x=cx + dx, y=deck_y / 2, z=z, w=3.4, h=deck_y, d=9.5,
                material=mat,
            )

        for dz in (-5, 5):
            _add_box(
                collection, f"bridge_railing_{tag}_{dz}",
                x=cx, y=deck_y + 1.2, z=z + dz, w=span, h=1.2, d=0.4,
                material=mat,
            )
