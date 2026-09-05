"""The voxel volume and its mesher — hidden-face culling + greedy meshing.

Everything in this module except `build_mesh()` itself is `bpy`-free (only
`numpy` and the stdlib), so the meshing algorithm can be exercised and
benchmarked with plain `python3` — no Blender runtime needed until the very
last step, converting the merged quads into an actual `bpy.types.Object`.

Why this module exists (the point of Phase 1)
-----------------------------------------------
A naive "one cube per block" approach on a `layout.SIZE_X x SIZE_Y x
SIZE_Z` volume is hundreds of thousands of cubes and millions of faces, most
of them buried inside solid ground where Cycles can never see them. Two
standard voxel-engine techniques fix that, both implemented here from
scratch:

1. **Hidden-face culling** — emit a face only where it could possibly be
   seen: a solid (opaque or transparent) block touching air, or touching a
   *different* transparent block, or an opaque block touching a transparent
   one. Two opaque blocks touching, or two touching voxels of the *same*
   transparent block type, emit nothing (see `_face_masks` for the exact
   rule and why the same-type case is excluded).
2. **Greedy meshing** — after culling, adjacent same-block-id faces that
   share a plane are merged into the largest quad that covers them, so a
   flat 40x40 patch of grass becomes 1 quad instead of 1600.

Volume representation
-----------------------
A block world is a 3-D `numpy.uint8` array, shape `(layout.SIZE_X,
layout.SIZE_Y, layout.SIZE_Z)`, values are `layout.Block` members (`AIR` is
0 everywhere by default). `new_volume()`/`fill_box()`/`set_block()`/
`get_block()` are the only things sibling modules should use to touch it —
never index the array as raw numpy from outside this module's helpers,
so the block-id convention stays in one place.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

import numpy as np

from cabin import layout
from cabin.layout import AIR

if TYPE_CHECKING:
    import bpy

logger = logging.getLogger(__name__)

# A quad is (corners, block_id) where corners is a list of 4 (x, y, z)
# world-space float tuples, wound so `cross(corners[1]-corners[0],
# corners[2]-corners[0])` points along the outward face normal.
_Quad = tuple[list[tuple[float, float, float]], int]


# ===== volume construction ====================================================


def new_volume() -> np.ndarray:
    """A fresh, all-AIR world volume, shape `(SIZE_X, SIZE_Y, SIZE_Z)`."""
    return np.zeros((layout.SIZE_X, layout.SIZE_Y, layout.SIZE_Z), dtype=np.uint8)


def set_block(volume: np.ndarray, bx: int, by: int, bz: int, block_id: int) -> None:
    """Set one voxel. Out-of-range indices raise (numpy's own IndexError) —
    deliberately not clipped, unlike `fill_box`, since a single wildly
    out-of-range coordinate is far more likely a bug than a deliberate
    partial write."""
    volume[bx, by, bz] = block_id


def get_block(volume: np.ndarray, bx: int, by: int, bz: int) -> int:
    """Read one voxel; out-of-range coordinates read as `AIR` rather than
    raising, since callers (e.g. neighbour checks during procedural
    generation) routinely probe just past the world edge."""
    if 0 <= bx < volume.shape[0] and 0 <= by < volume.shape[1] and 0 <= bz < volume.shape[2]:
        return int(volume[bx, by, bz])
    return AIR


def fill_box(
    volume: np.ndarray, x0: int, y0: int, z0: int, x1: int, y1: int, z1: int, block_id: int
) -> None:
    """Fill the half-open box `[x0, x1) x [y0, y1) x [z0, z1)` with
    `block_id`. Clipped to the volume bounds — a box that partly overhangs
    the world edge fills only its in-bounds portion rather than raising, so
    callers can express shapes without hand-clamping every coordinate."""
    x0c, x1c = max(0, x0), min(volume.shape[0], x1)
    y0c, y1c = max(0, y0), min(volume.shape[1], y1)
    z0c, z1c = max(0, z0), min(volume.shape[2], z1)
    if x0c < x1c and y0c < y1c and z0c < z1c:
        volume[x0c:x1c, y0c:y1c, z0c:z1c] = block_id


# ===== hidden-face culling ====================================================


def _lookup_tables() -> tuple[np.ndarray, np.ndarray]:
    """`(opaque, transparent)` — two 256-length bool arrays indexed directly
    by block id, built once per meshing pass from `layout.BLOCK_FLAGS`.
    `opaque[id]` is `True` for every non-AIR block NOT flagged transparent;
    `AIR` is `False` in both (air is neither opaque nor "a transparent
    block" — it just isn't there)."""
    transparent = np.zeros(256, dtype=bool)
    for block_id, flags in layout.BLOCK_FLAGS.items():
        transparent[int(block_id)] = bool(flags.get("transparent", False))
    opaque = ~transparent
    opaque[AIR] = False
    return opaque, transparent


def _axis_layers(volume: np.ndarray, axis: int, opaque: np.ndarray, transparent: np.ndarray):
    """Yield `(grid_pos, grid_neg, world_coord)` for every boundary plane
    perpendicular to `axis` (0=x, 1=y, 2=z).

    At each of the `volume.shape[axis] + 1` boundaries, `a` is the voxel
    behind the plane (lower coordinate) and `b` is the voxel in front
    (higher coordinate) — both read from a volume padded with one AIR layer
    on each end of `axis`, so the world's own outer surface is included
    without a special-cased first/last iteration.

    `grid_pos` holds `a`'s block id wherever `a` needs to emit a face
    pointing in the `+axis` direction (i.e. `a` is present and not fully
    hidden by `b`); `grid_neg` holds `b`'s block id wherever `b` needs a
    `-axis`-facing face. 0 (`AIR`) means "no face here" in both grids,
    which doubles as the "empty" sentinel for `_greedy_rects` since `AIR`
    itself never has a face.

    The culling rule (`face_needed`, applied identically to both
    directions): a block's face toward a neighbour is skipped only when the
    neighbour is present AND opaque; if the neighbour is transparent and
    the *same* block id as this one, the face is also skipped (no interior
    wall inside one contiguous body of water / leaf canopy — see
    `layout.BLOCK_FLAGS`'s docstring for why).
    """
    pad_width = [(0, 0), (0, 0), (0, 0)]
    pad_width[axis] = (1, 1)
    padded = np.pad(volume, pad_width, mode="constant", constant_values=AIR)

    size_axis = volume.shape[axis]
    for d in range(size_axis + 1):
        a_ids = np.take(padded, d, axis=axis)
        b_ids = np.take(padded, d + 1, axis=axis)

        same = a_ids == b_ids
        a_is_air = a_ids == AIR
        b_is_air = b_ids == AIR
        a_opaque = opaque[a_ids]
        b_opaque = opaque[b_ids]
        a_transparent = transparent[a_ids]
        b_transparent = transparent[b_ids]

        mask_pos = (~a_is_air) & (~b_opaque) & ~(a_transparent & same)
        mask_neg = (~b_is_air) & (~a_opaque) & ~(b_transparent & same)

        grid_pos = np.where(mask_pos, a_ids, AIR).astype(np.uint8)
        grid_neg = np.where(mask_neg, b_ids, AIR).astype(np.uint8)

        yield grid_pos, grid_neg, float(d) * layout.BLOCK_SIZE


# ===== greedy meshing (2-D, per boundary plane) ==============================


def _quad_corners(
    axis: int, coord: float, i0: int, i1: int, j0: int, j1: int, positive: bool
) -> list[tuple[float, float, float]]:
    """World-space corners of one merged rectangle, wound for an outward
    normal along `+axis` (`positive=True`) or `-axis` (`positive=False`).

    `axis` selects which two world axes the 2-D grid's `(i, j)` indices map
    to (`_axis_layers` always builds the grid in that same order — see the
    three branches below, one per axis):

    - axis 0 (X boundary planes): grid is (Y, Z) -> i=Y, j=Z.
    - axis 1 (Y boundary planes): grid is (X, Z) -> i=X, j=Z.
    - axis 2 (Z boundary planes): grid is (X, Y) -> i=X, j=Y.

    Each branch's 4-corner order is the one that makes
    `cross(corners[1]-corners[0], corners[2]-corners[0])` point along
    `+axis` (verified by hand for each: e.g. for axis 2 the corners run
    `(X0,Y0)->(X1,Y0)->(X1,Y1)->(X0,Y1)`, whose cross product is
    `(0, 0, (X1-X0)*(Y1-Y0))`, i.e. `+Z` for a real rectangle). Reversing
    the whole list — `positive=False` — flips the normal to `-axis` without
    needing a second hand-derived ordering.
    """
    bs = layout.BLOCK_SIZE
    if axis == 0:
        x = coord
        pts = [
            (x, i0 * bs, j0 * bs),
            (x, i1 * bs, j0 * bs),
            (x, i1 * bs, j1 * bs),
            (x, i0 * bs, j1 * bs),
        ]
    elif axis == 1:
        y = coord
        pts = [
            (i0 * bs, y, j0 * bs),
            (i0 * bs, y, j1 * bs),
            (i1 * bs, y, j1 * bs),
            (i1 * bs, y, j0 * bs),
        ]
    else:
        z = coord
        pts = [
            (i0 * bs, j0 * bs, z),
            (i1 * bs, j0 * bs, z),
            (i1 * bs, j1 * bs, z),
            (i0 * bs, j1 * bs, z),
        ]
    return pts if positive else list(reversed(pts))


def _greedy_rects(grid: np.ndarray, axis: int, coord: float, positive: bool) -> list[_Quad]:
    """Greedy-merge one boundary-plane's face grid into maximal same-id
    rectangles.

    Classic two-phase scan: for each unvisited non-zero cell, grow a run
    along `j` while the id matches (the rectangle's width), then grow along
    `i` one full row at a time while every cell in that row (across the
    already-found width) still matches and is unvisited (the rectangle's
    height). Mark the whole rectangle visited and move on — every cell is
    visited at most once as a rectangle *interior*, so this is linear in
    the number of non-empty cells, not quadratic in the grid size.
    """
    dim_i, dim_j = grid.shape
    visited = np.zeros_like(grid, dtype=bool)
    quads: list[_Quad] = []

    for i in range(dim_i):
        j = 0
        while j < dim_j:
            val = grid[i, j]
            if val == AIR or visited[i, j]:
                j += 1
                continue

            w = 1
            while j + w < dim_j and grid[i, j + w] == val and not visited[i, j + w]:
                w += 1

            h = 1
            while i + h < dim_i:
                row = grid[i + h, j : j + w]
                if np.any(row != val) or np.any(visited[i + h, j : j + w]):
                    break
                h += 1

            visited[i : i + h, j : j + w] = True
            corners = _quad_corners(axis, coord, i, i + h, j, j + w, positive)
            quads.append((corners, int(val)))
            j += w

    return quads


def _mesh_all(volume: np.ndarray) -> tuple[list[_Quad], int]:
    """Run culling + greedy meshing over all 3 axes. Returns `(quads,
    culled_face_count)` — `culled_face_count` is the number of individual
    1x1 faces that survived culling, BEFORE greedy merging; `len(quads)` is
    the count AFTER merging. Both are what `mesh_stats()` reports."""
    opaque, transparent = _lookup_tables()
    quads: list[_Quad] = []
    culled = 0

    for axis in range(3):
        for grid_pos, grid_neg, coord in _axis_layers(volume, axis, opaque, transparent):
            culled += int(np.count_nonzero(grid_pos)) + int(np.count_nonzero(grid_neg))
            quads.extend(_greedy_rects(grid_pos, axis, coord, positive=True))
            quads.extend(_greedy_rects(grid_neg, axis, coord, positive=False))

    return quads, culled


def mesh_stats(volume: np.ndarray) -> dict:
    """Meshing statistics for `volume`, without touching Blender at all —
    safe to call from plain `python3` for fast benchmarking/testing.

    Returns a dict with `solid_blocks`, `naive_faces` (`solid_blocks * 6`),
    `culled_faces` (post hidden-face-culling, pre greedy-merge), `quads`
    (post greedy-merge), `reduction_factor` (`naive_faces / quads`), and
    `elapsed_seconds` (wall-clock time for the culling + merge pass, NOT
    including building the actual `bpy` mesh — that step is comparatively
    fast and only runs inside Blender).
    """
    solid = int(np.count_nonzero(volume))
    started = time.perf_counter()
    quads, culled = _mesh_all(volume)
    elapsed = time.perf_counter() - started
    naive = solid * 6
    return {
        "solid_blocks": solid,
        "naive_faces": naive,
        "culled_faces": culled,
        "quads": len(quads),
        "reduction_factor": (naive / len(quads)) if quads else float("nan"),
        "elapsed_seconds": elapsed,
    }


# ===== Blender mesh construction (the only bpy-dependent part) ===============


def build_mesh(volume: np.ndarray, name: str, materials: dict) -> "bpy.types.Object":
    """Convert `volume` into ONE Blender mesh object with per-face material
    slots, via hidden-face culling + greedy meshing.

    Args:
        volume: a `(SIZE_X, SIZE_Y, SIZE_Z)` uint8 block-id array, from
            `new_volume()` plus whatever `terrain`/`cabin`/`scatter` wrote
            into it.
        name: object (and mesh datablock) name, e.g. `"CabinWorld"`.
        materials: `ctx.materials` — maps `layout.BLOCK_MATERIALS` values
            (e.g. `"spruce_log"`) to `bpy.types.Material`. A key with no
            entry yet (or an entirely empty dict, as in Phase 1 before
            `materials.py` is implemented) still gets a mesh material slot —
            just filled with `None` — so this function never fails before
            `materials.py` exists; the object just renders with Blender's
            default grey material on those faces until it does.

    Returns the linked `bpy.types.Object`. One mesh, N material slots (one
    per DISTINCT block id actually present in `volume`'s faces — never one
    per block type in the enum, and never one object per block type).
    """
    import bpy

    quads, _culled = _mesh_all(volume)

    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int, int]] = []
    material_keys: list[str] = []
    key_to_index: dict[str, int] = {}
    face_material_index: list[int] = []

    for corners, block_id in quads:
        key = layout.BLOCK_MATERIALS.get(block_id, f"block_{block_id}")
        idx = key_to_index.get(key)
        if idx is None:
            idx = len(material_keys)
            key_to_index[key] = idx
            material_keys.append(key)
        base = len(verts)
        verts.extend(corners)
        faces.append((base, base + 1, base + 2, base + 3))
        face_material_index.append(idx)

    mesh = bpy.data.meshes.new(f"{name}Mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update(calc_edges=False)

    for key in material_keys:
        mesh.materials.append(materials.get(key) if materials else None)
    for poly, idx in zip(mesh.polygons, face_material_index):
        poly.material_index = idx

    existing = bpy.data.objects.get(name)
    if existing is not None:
        old_mesh = existing.data
        existing.data = mesh
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
        obj = existing
    else:
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)

    logger.info(
        "blocks: built %s — %d verts, %d quads, %d material slots (%d solid blocks)",
        name,
        len(verts),
        len(faces),
        len(material_keys),
        int(np.count_nonzero(volume)),
    )
    return obj
