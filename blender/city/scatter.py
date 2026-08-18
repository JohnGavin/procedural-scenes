"""Park trees + street furniture, scattered with a real Geometry Nodes graph.

`buildings.html` plants its 110 park trees with a `for` loop: pick an angle,
pick a radius, reject anything within `pond.r + 10` of the water, build two
meshes, push them into the scene graph. It works, and it is also the end of
the story — the trees are baked. Want a denser park? Edit the loop bound.
Want the pond bigger? Edit the rejection test. Want a different seed? Rebuild
every mesh.

This module does the same job as a **node graph** instead, and that is the
whole point of the module:

  * The scatter is a *field evaluated at render time*, not a list of objects.
    `Distribute Points on Faces` samples the park ellipse; a distance field
    from the pond centre multiplies the density down to zero over the water.
    Move the pond, change its radius, change the seed, change the density —
    the entire park repopulates on the next depsgraph evaluation with no
    re-authoring and no new mesh data.
  * The trees are *instances*. Two (or a handful of) source meshes live in a
    hidden collection and every tree in the park points at one of them.
    Cycles carries one copy of the geometry no matter how many trees there
    are, so raising the density costs ray-traversal time, not memory.
  * Per-instance variation (rotation, scale, which tree, which leaf colour)
    comes from `Random Value` nodes wired into the instancer, so nothing has
    to be pre-computed on the Python side.

Consumes from `ctx.materials`: `trunk`, `leaf` (and, for the street
furniture, `concrete` / `gravel`). Each of those may hold a single material
or a list of colour variants — `materials.py` is free to choose, so every
lookup here goes through `_material_variants()`, which normalises both
shapes and tolerates a missing key while that sibling module is still a stub.

Produces no new `ctx.materials` keys. Uses `ctx.seed` for the scatter so a
given seed always gives the same park.

COORDINATE_NOTE (see `city.layout`): every constant read from `layout` is in
three.js-named terms. The conversion `blender_xyz = (three_x, three_z,
three_y)` happens exactly once per placement, at the point of use, and is
called out in a comment each time.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Sequence

from city import layout

logger = logging.getLogger(__name__)


# ===== tuning knobs ==========================================================
# Kept here rather than in `layout.py` because they are scatter-implementation
# detail, not part of the shared layout contract.

PARK_RIM_FRACTION: float = 0.96
"""Shrink the distribution ellipse slightly so trees do not overhang the lawn
edge. `parkland()` in buildings.html achieves the same with `sqrt(rand)*0.94`."""

POND_CLEARANCE: float = 10.0
"""Extra buffer beyond `POND.r` that stays tree-free — the same `pond.r + 10`
rejection radius the three.js loop uses."""

TREE_MIN_SPACING: float = 9.0
"""Poisson-disc minimum distance between park trees, in world units."""

TREE_DENSITY_MAX: float = 0.02
"""Upper bound on points per square world unit before the pond mask is applied.
Poisson-disc sampling caps out well below this; `TREE_MIN_SPACING` is what
actually sets the count. Tuned to land near the three.js scene's 110 trees."""

CONIFER_FRACTION: float = 0.3
"""Share of trees that are conifers — matches `rand() < 0.3` in `parkland()`."""

TREE_SCALE_MIN: float = 0.75
TREE_SCALE_MAX: float = 1.35
"""Per-instance uniform scale range. buildings.html scales only the crown
(`0.8 + rand()*0.7`); scaling the whole tree reads better and costs nothing."""

TREE_TILT_RAD: float = 0.06
"""Maximum random lean off vertical, radians. Small — trees, not a gale."""

STREET_FURNITURE_SPACING: float = 24.0
"""Distance between street-furniture instances along a kerb verge."""

STREET_VERGE_INSET: float = 0.6
"""How far inside the kerb edge the furniture line sits, world units."""

# Object / datablock names. Everything this module owns is prefixed `city_`
# so `_purge()` can make the whole stage idempotent.
_SOURCE_COLLECTION = "city_scatter_sources"
_PARK_SURFACE_OBJ = "city_park_scatter_surface"
_PARK_NODE_GROUP = "city_park_scatter"
_STREET_CURVE_OBJ = "city_street_verges"
_STREET_NODE_GROUP = "city_street_scatter"


# ===== material helpers ======================================================


def _material_variants(ctx, key: str) -> list[Any]:
    """Return `ctx.materials[key]` as a list, whatever shape it arrived in.

    `materials.py` documents per-key whether a slot holds one material or a
    pool of colour variants (`concrete` and `leaf` are the likely pools). We
    do not want to care, and we do not want to crash while that module is
    still a stub, so: missing key -> warn and return `[]`; single material ->
    `[mat]`; list/tuple -> `list(...)` with any `None` entries dropped.
    """
    raw = getattr(ctx, "materials", None)
    if not isinstance(raw, dict) or key not in raw or raw[key] is None:
        logger.warning("scatter: ctx.materials[%r] missing — meshes will be untextured", key)
        return []
    value = raw[key]
    if isinstance(value, (list, tuple)):
        return [m for m in value if m is not None]
    return [value]


def _assign_materials(mesh, slots: Sequence[Any]) -> None:
    """Append `slots` to `mesh` in order; slot index i == material_index i."""
    for mat in slots:
        mesh.materials.append(mat)


# ===== Geometry Nodes plumbing ==============================================
#
# Socket wiring is the one place a Geometry Nodes graph fails *silently*: link
# to the wrong socket and you get an empty result and no error. Two defences
# are used throughout:
#
#   1. `_sock()` looks sockets up by name and raises with the full list of
#      available names when the name is wrong, so a Blender-version rename
#      turns into a loud failure instead of an empty park.
#   2. `_enabled()` filters to the sockets Blender currently has switched on.
#      `Random Value` in particular carries three overlapping "Min"/"Max"
#      pairs (vector / float / int) and only the ones matching `data_type`
#      are enabled — name lookup on that node returns the wrong socket.


def _sock(node, name: str, out: bool = False):
    """Look a socket up by name, raising a useful error when it is missing."""
    coll = node.outputs if out else node.inputs
    for s in coll:
        if s.name == name:
            return s
    kind = "output" if out else "input"
    available = [s.name for s in coll]
    raise KeyError(f"{node.bl_idname}: no {kind} socket {name!r}; available: {available}")


def _enabled(sockets: Iterable) -> list:
    """Only the sockets Blender currently exposes for this node's data_type."""
    return [s for s in sockets if s.enabled]


def _new_tree(name: str):
    """Create (or reset) a geometry node tree with a Geometry in/out interface."""
    import bpy

    existing = bpy.data.node_groups.get(name)
    if existing is not None:
        bpy.data.node_groups.remove(existing)

    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    # Blender 4.0 replaced `ng.inputs.new(...)` with the interface API; 5.x
    # keeps the interface API. There is no fallback here on purpose — if this
    # call ever fails we want the traceback, not a half-built graph.
    ng.interface.new_socket(name="Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket(name="Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    return ng


def _random_value(ng, data_type: str, seed: int, location=(0, 0)):
    """A `Random Value` node with `data_type` set and its Seed pinned.

    Returns `(node, min_socket, max_socket, value_socket)` — the min/max/value
    sockets resolved through `_enabled()`, because on this node name lookup
    is actively wrong (see the module comment above).
    """
    node = ng.nodes.new("FunctionNodeRandomValue")
    node.data_type = data_type
    node.location = location
    ins = _enabled(node.inputs)
    outs = _enabled(node.outputs)
    _sock(node, "Seed").default_value = seed
    # Enabled inputs are ordered [Min, Max, ID, Seed] for FLOAT / INT /
    # FLOAT_VECTOR; BOOLEAN has [Probability, ID, Seed] and is not used here.
    return node, ins[0], ins[1], outs[0]


# ===== source geometry ======================================================
#
# Ported from the three shared geometries at the top of buildings.html:
#   TRUNK_GEO = CylinderGeometry(0.45, 0.7, 4.5, 6)
#   BLOB_GEO  = IcosahedronGeometry(3.2, 0)
#   CONE_GEO  = ConeGeometry(3, 9, 7)
# Each source object here is a whole tree (trunk + crown) with its origin at
# the trunk base, so the instancer can drop it straight onto the lawn.


def _bm_cone(bm, segments: int, radius_bottom: float, radius_top: float, depth: float, z: float):
    """Cylinder/cone primitive centred at local z, built into `bm`."""
    import bmesh
    from mathutils import Matrix

    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=segments,
        radius1=radius_bottom,
        radius2=radius_top,
        depth=depth,
        matrix=Matrix.Translation((0.0, 0.0, z)),
        calc_uvs=False,
    )


def _bm_icosphere(bm, radius: float, z: float):
    import bmesh
    from mathutils import Matrix

    bmesh.ops.create_icosphere(
        bm,
        subdivisions=1,  # bmesh counts from 1; three.js IcosahedronGeometry detail 0
        radius=radius,
        matrix=Matrix.Translation((0.0, 0.0, z)),
        calc_uvs=False,
    )


def _shade_flat(mesh) -> None:
    """`Mesh.shade_flat()` is a 4.1+ convenience; fall back on older builds."""
    fn = getattr(mesh, "shade_flat", None)
    if callable(fn):
        fn()
    else:  # pragma: no cover — pre-4.1 only
        for poly in mesh.polygons:
            poly.use_smooth = False


def _build_tree_object(name: str, conifer: bool, trunk_mat, leaf_mat, scale: float = 1.0):
    """One source tree: trunk (material slot 0) + crown (material slot 1).

    Heights follow `parkland()`: the trunk is 4.5 tall sitting on the lawn,
    a broadleaf blob centres at 6.5 and a conifer cone at 8.0.

    `scale` is baked into the mesh rather than left on the object transform,
    because `Collection Info` runs with Reset Children on — which is what puts
    every instance at its point rather than at the source object's location,
    and which therefore discards object-level transforms.
    """
    import bmesh
    import bpy
    from mathutils import Matrix

    bm = bmesh.new()
    try:
        _bm_cone(bm, segments=6, radius_bottom=0.7, radius_top=0.45, depth=4.5, z=2.25)
        trunk_faces = len(bm.faces)
        if conifer:
            _bm_cone(bm, segments=7, radius_bottom=3.0, radius_top=0.0, depth=9.0, z=8.0)
        else:
            _bm_icosphere(bm, radius=3.2, z=6.5)

        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
    finally:
        bm.free()

    mesh.polygons.foreach_set(
        "material_index",
        [0] * trunk_faces + [1] * (len(mesh.polygons) - trunk_faces),
    )
    if scale != 1.0:
        mesh.transform(Matrix.Scale(scale, 4))
    # Flat shading on the crown, matching `flatShading: true` on leafMats.
    _shade_flat(mesh)
    _assign_materials(mesh, [trunk_mat, leaf_mat])

    return bpy.data.objects.new(name, mesh)


def _build_lamp_object(name: str, post_mat, head_mat):
    """A minimal street lamp: thin post + a small head. Deliberately cheap —
    there are dozens of these and they are set dressing, not the subject."""
    import bmesh
    import bpy

    bm = bmesh.new()
    try:
        _bm_cone(bm, segments=6, radius_bottom=0.22, radius_top=0.14, depth=6.0, z=3.0)
        post_faces = len(bm.faces)
        _bm_cone(bm, segments=6, radius_bottom=0.55, radius_top=0.35, depth=0.5, z=6.1)
        mesh = bpy.data.meshes.new(name)
        bm.to_mesh(mesh)
    finally:
        bm.free()

    mesh.polygons.foreach_set(
        "material_index",
        [0] * post_faces + [1] * (len(mesh.polygons) - post_faces),
    )
    mesh.shade_flat()
    _assign_materials(mesh, [post_mat, head_mat])
    return bpy.data.objects.new(name, mesh)


def _source_collection(objects: Sequence) -> Any:
    """Put `objects` in a collection that is *not* linked to the scene.

    An unlinked collection is still resolved by `Collection Info`, so the node
    graph can instance from it while the source meshes themselves never appear
    in a render. That is cheaper and less error-prone than linking them and
    then fighting per-object visibility flags.
    """
    import bpy

    existing = bpy.data.collections.get(_SOURCE_COLLECTION)
    if existing is not None:
        bpy.data.collections.remove(existing)

    coll = bpy.data.collections.new(_SOURCE_COLLECTION)
    for obj in objects:
        coll.objects.link(obj)
    return coll


def _build_tree_sources(ctx) -> tuple[Any, int]:
    """Build the tree source collection.

    Returns `(collection, n_variants)`. Children are named with a zero-padded
    index so that `Collection Info`'s alphabetical child ordering matches the
    index arithmetic in the node graph: the first `n_variants` children are
    broadleaf, the next `n_variants` are conifer.
    """
    trunk_pool = _material_variants(ctx, "trunk")
    leaf_pool = _material_variants(ctx, "leaf")

    trunk_mat = trunk_pool[0] if trunk_pool else None
    # `leaf` may be a pool of green variants (buildings.html has three). One
    # source object per variant per tree type is what lets the node graph pick
    # a colour per instance without touching the materials themselves.
    leaves = leaf_pool if leaf_pool else [None]
    n_variants = len(leaves)

    objects = []
    index = 0
    for conifer in (False, True):
        kind = "conifer" if conifer else "broadleaf"
        for v, leaf_mat in enumerate(leaves):
            objects.append(
                _build_tree_object(f"city_tree_{index:02d}_{kind}_v{v}", conifer, trunk_mat, leaf_mat)
            )
            index += 1

    return _source_collection(objects), n_variants


# ===== park scatter surface =================================================


def _build_park_surface():
    """A hidden triangle-fan ellipse over the park lawn — the sampling domain.

    This module builds its own distribution surface rather than reaching for
    whatever `terrain.py` calls its lawn object: the scatter then depends only
    on `layout.PARK`, which is frozen, instead of on a sibling module's
    naming. It is replaced by the node graph's output, so it never renders.
    """
    import bpy

    existing = bpy.data.objects.get(_PARK_SURFACE_OBJ)
    if existing is not None:
        bpy.data.objects.remove(existing, do_unlink=True)

    import math

    segments = 64
    rx = layout.PARK.rx * PARK_RIM_FRACTION
    rz = layout.PARK.rz * PARK_RIM_FRACTION

    verts = [(0.0, 0.0, 0.0)]
    for i in range(segments):
        a = 2.0 * math.pi * i / segments
        verts.append((math.cos(a) * rx, math.sin(a) * rz, 0.0))
    faces = [(0, 1 + i, 1 + (i + 1) % segments) for i in range(segments)]

    mesh = bpy.data.meshes.new(_PARK_SURFACE_OBJ)
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    obj = bpy.data.objects.new(_PARK_SURFACE_OBJ, mesh)
    # COORDINATE_NOTE: layout is three.js-named, Blender is Z-up.
    # blender_xyz = (three_x, three_z, three_y)
    obj.location = (layout.PARK.x, layout.PARK.z, layout.Y.park)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _build_park_node_group(collection, n_variants: int, seed: int):
    """The park scatter graph.

    Shape:

        Group Input ─┐
                     ├─ Distribute Points on Faces (Poisson) ─ Instance on Points ─ Group Output
        Position ─ Vector Math(Distance to pond) ─ Math(> pond.r + clearance) ─┘ (Density Factor)
        Collection Info ──────────────────────────────────────┘ (Instance, Pick Instance)
        Random Value(int)  ─┐
        Random Value(float) ─ Math(< 0.3) ─ Math(*n) ─ Math(+) ─┘ (Instance Index)
        Random Value(vector) ─────────────────────────────────┘ (Rotation)
        Random Value(float) ──────────────────────────────────┘ (Scale)
    """
    import math

    ng = _new_tree(_PARK_NODE_GROUP)
    nodes, links = ng.nodes, ng.links

    n_in = nodes.new("NodeGroupInput")
    n_in.location = (-900, 0)
    n_out = nodes.new("NodeGroupOutput")
    n_out.location = (700, 0)

    # --- pond mask ----------------------------------------------------------
    # A distance field, not a rejection loop. Move POND and the hole moves.
    pos = nodes.new("GeometryNodeInputPosition")
    pos.location = (-900, -320)

    dist = nodes.new("ShaderNodeVectorMath")
    dist.operation = "DISTANCE"
    dist.location = (-700, -320)
    # COORDINATE_NOTE: blender_xyz = (three_x, three_z, three_y). The park
    # surface sits at blender z == Y.park, so putting the pond centre at the
    # same height makes this distance planar.
    dist.inputs[1].default_value = (layout.POND.x, layout.POND.z, layout.Y.park)
    links.new(_sock(pos, "Position", out=True), dist.inputs[0])

    mask = nodes.new("ShaderNodeMath")
    mask.operation = "GREATER_THAN"
    mask.location = (-520, -320)
    mask.inputs[1].default_value = layout.POND.r + POND_CLEARANCE
    links.new(_sock(dist, "Value", out=True), mask.inputs[0])

    # --- distribution -------------------------------------------------------
    dist_pts = nodes.new("GeometryNodeDistributePointsOnFaces")
    dist_pts.distribute_method = "POISSON"
    dist_pts.location = (-300, 0)
    _sock(dist_pts, "Distance Min").default_value = TREE_MIN_SPACING
    _sock(dist_pts, "Density Max").default_value = TREE_DENSITY_MAX
    _sock(dist_pts, "Seed").default_value = seed
    links.new(n_in.outputs[0], _sock(dist_pts, "Mesh"))
    links.new(_sock(mask, "Value", out=True), _sock(dist_pts, "Density Factor"))

    # --- what to instance ---------------------------------------------------
    coll_info = nodes.new("GeometryNodeCollectionInfo")
    coll_info.location = (-300, -560)
    coll_info.transform_space = "RELATIVE"
    _sock(coll_info, "Collection").default_value = collection
    _sock(coll_info, "Separate Children").default_value = True
    _sock(coll_info, "Reset Children").default_value = True

    # Leaf-colour variant: uniform over the source objects of one tree type.
    _, v_min, v_max, v_val = _random_value(ng, "INT", seed + 11, (-300, -760))
    v_min.default_value = 0
    v_max.default_value = max(0, n_variants - 1)

    # Conifer roll: `rand() < 0.3` in parkland(), as a field.
    _, c_min, c_max, c_val = _random_value(ng, "FLOAT", seed + 23, (-300, -960))
    c_min.default_value = 0.0
    c_max.default_value = 1.0

    is_conifer = nodes.new("ShaderNodeMath")
    is_conifer.operation = "LESS_THAN"
    is_conifer.location = (-110, -960)
    is_conifer.inputs[1].default_value = CONIFER_FRACTION
    links.new(c_val, is_conifer.inputs[0])

    conifer_offset = nodes.new("ShaderNodeMath")
    conifer_offset.operation = "MULTIPLY"
    conifer_offset.location = (70, -960)
    conifer_offset.inputs[1].default_value = float(n_variants)
    links.new(_sock(is_conifer, "Value", out=True), conifer_offset.inputs[0])

    inst_index = nodes.new("ShaderNodeMath")
    inst_index.operation = "ADD"
    inst_index.location = (250, -860)
    links.new(v_val, inst_index.inputs[0])
    links.new(_sock(conifer_offset, "Value", out=True), inst_index.inputs[1])

    # --- per-instance variation --------------------------------------------
    _, r_min, r_max, r_val = _random_value(ng, "FLOAT_VECTOR", seed + 37, (-300, -1160))
    r_min.default_value = (-TREE_TILT_RAD, -TREE_TILT_RAD, 0.0)
    r_max.default_value = (TREE_TILT_RAD, TREE_TILT_RAD, 2.0 * math.pi)

    _, s_min, s_max, s_val = _random_value(ng, "FLOAT", seed + 53, (-300, -1360))
    s_min.default_value = TREE_SCALE_MIN
    s_max.default_value = TREE_SCALE_MAX

    # --- instancer ----------------------------------------------------------
    iop = nodes.new("GeometryNodeInstanceOnPoints")
    iop.location = (420, 0)
    links.new(_sock(dist_pts, "Points", out=True), _sock(iop, "Points"))
    links.new(coll_info.outputs[0], _sock(iop, "Instance"))
    _sock(iop, "Pick Instance").default_value = True
    links.new(_sock(inst_index, "Value", out=True), _sock(iop, "Instance Index"))
    links.new(r_val, _sock(iop, "Rotation"))
    links.new(s_val, _sock(iop, "Scale"))

    links.new(_sock(iop, "Instances", out=True), n_out.inputs[0])
    return ng


# ===== street furniture =====================================================


def _build_street_verges():
    """Edge-only mesh tracing the kerb verges of the north-south corridors.

    Kept to the downtown grid (`HALF_X` x `HALF_Z`) so nothing marches off
    across the river or into the park. Sits at kerb height, so the furniture
    stands on the block platform rather than in the roadway.
    """
    import bpy

    existing = bpy.data.objects.get(_STREET_CURVE_OBJ)
    if existing is not None:
        bpy.data.objects.remove(existing, do_unlink=True)

    verts: list[tuple[float, float, float]] = []
    edges: list[tuple[int, int]] = []
    # Corridor centres sit half a pitch past each column except the last;
    # the block edge is BLOCK/2 either side of the column centre.
    verge_offset = (layout.PITCH - layout.BLOCK) / 2.0 - STREET_VERGE_INSET
    for i in range(layout.COLS - 1):
        corridor_x = layout.col_x(i) + layout.PITCH / 2.0
        for side in (-1.0, 1.0):
            x = corridor_x + side * verge_offset
            base = len(verts)
            # COORDINATE_NOTE: blender_xyz = (three_x, three_z, three_y).
            verts.append((x, -layout.HALF_Z, layout.Y.kerb_top))
            verts.append((x, layout.HALF_Z, layout.Y.kerb_top))
            edges.append((base, base + 1))

    mesh = bpy.data.meshes.new(_STREET_CURVE_OBJ)
    mesh.from_pydata(verts, edges, [])
    mesh.update()

    obj = bpy.data.objects.new(_STREET_CURVE_OBJ, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def _build_street_sources(ctx):
    """Two cheap props — a lamp post and a half-size street tree."""
    trunk_pool = _material_variants(ctx, "trunk")
    leaf_pool = _material_variants(ctx, "leaf")
    concrete_pool = _material_variants(ctx, "concrete")
    gravel_pool = _material_variants(ctx, "gravel")

    post_mat = (concrete_pool or gravel_pool or [None])[0]
    head_mat = (gravel_pool or concrete_pool or [None])[0]
    trunk_mat = (trunk_pool or [None])[0]
    leaf_mat = (leaf_pool or [None])[0]

    lamp = _build_lamp_object("city_street_00_lamp", post_mat, head_mat)
    tree = _build_tree_object(
        "city_street_01_tree", conifer=False, trunk_mat=trunk_mat, leaf_mat=leaf_mat, scale=0.55
    )
    return _street_source_collection([lamp, tree])


def _street_source_collection(objects: Sequence):
    import bpy

    name = "city_street_sources"
    existing = bpy.data.collections.get(name)
    if existing is not None:
        bpy.data.collections.remove(existing)
    coll = bpy.data.collections.new(name)
    for obj in objects:
        coll.objects.link(obj)
    return coll


def _build_street_node_group(collection, seed: int):
    """Resample the verge edges into evenly spaced points and instance onto
    them. A second, much cheaper graph — the density is fixed by
    `STREET_FURNITURE_SPACING`, so it never surprises the render budget."""
    import math

    ng = _new_tree(_STREET_NODE_GROUP)
    nodes, links = ng.nodes, ng.links

    n_in = nodes.new("NodeGroupInput")
    n_in.location = (-700, 0)
    n_out = nodes.new("NodeGroupOutput")
    n_out.location = (600, 0)

    to_curve = nodes.new("GeometryNodeMeshToCurve")
    to_curve.location = (-500, 0)
    links.new(n_in.outputs[0], _sock(to_curve, "Mesh"))

    resample = nodes.new("GeometryNodeResampleCurve")
    # In Blender 5.x the resample mode is a menu *socket*, not a node property —
    # `resample.mode = "LENGTH"` raises AttributeError. The socket takes the
    # menu label ("Count" / "Length" / "Evaluated"), not the old enum token.
    resample.location = (-300, 0)
    resample.inputs["Mode"].default_value = "Length"
    _sock(resample, "Length").default_value = STREET_FURNITURE_SPACING
    links.new(_sock(to_curve, "Curve", out=True), _sock(resample, "Curve"))

    coll_info = nodes.new("GeometryNodeCollectionInfo")
    coll_info.location = (-300, -320)
    coll_info.transform_space = "RELATIVE"
    _sock(coll_info, "Collection").default_value = collection
    _sock(coll_info, "Separate Children").default_value = True
    _sock(coll_info, "Reset Children").default_value = True

    _, i_min, i_max, i_val = _random_value(ng, "INT", seed + 71, (-300, -520))
    i_min.default_value = 0
    i_max.default_value = 1  # lamp (0) / street tree (1)

    _, r_min, r_max, r_val = _random_value(ng, "FLOAT_VECTOR", seed + 89, (-300, -720))
    r_min.default_value = (0.0, 0.0, 0.0)
    r_max.default_value = (0.0, 0.0, 2.0 * math.pi)

    _, s_min, s_max, s_val = _random_value(ng, "FLOAT", seed + 97, (-300, -920))
    s_min.default_value = 0.85
    s_max.default_value = 1.15

    iop = nodes.new("GeometryNodeInstanceOnPoints")
    iop.location = (320, 0)
    links.new(_sock(resample, "Curve", out=True), _sock(iop, "Points"))
    links.new(coll_info.outputs[0], _sock(iop, "Instance"))
    _sock(iop, "Pick Instance").default_value = True
    links.new(i_val, _sock(iop, "Instance Index"))
    links.new(r_val, _sock(iop, "Rotation"))
    links.new(s_val, _sock(iop, "Scale"))

    links.new(_sock(iop, "Instances", out=True), n_out.inputs[0])
    return ng


# ===== stage entry point ====================================================


def _attach(obj, node_group, mod_name: str) -> None:
    """Attach `node_group` to `obj` via a NODES modifier, replacing any prior."""
    for mod in list(obj.modifiers):
        obj.modifiers.remove(mod)
    mod = obj.modifiers.new(name=mod_name, type="NODES")
    mod.node_group = node_group


def _purge() -> None:
    """Drop everything a previous `build_scatter()` left behind, so the stage
    is idempotent within one Blender session."""
    import bpy

    for name in (_PARK_SURFACE_OBJ, _STREET_CURVE_OBJ):
        obj = bpy.data.objects.get(name)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)
    for name in (_PARK_NODE_GROUP, _STREET_NODE_GROUP):
        ng = bpy.data.node_groups.get(name)
        if ng is not None:
            bpy.data.node_groups.remove(ng)
    for name in (_SOURCE_COLLECTION, "city_street_sources"):
        coll = bpy.data.collections.get(name)
        if coll is not None:
            bpy.data.collections.remove(coll)
    for obj in list(bpy.data.objects):
        if obj.name.startswith(("city_tree_", "city_street_0")):
            bpy.data.objects.remove(obj, do_unlink=True)


def build_scatter(ctx) -> None:
    """Scatter park trees and street furniture with Geometry Nodes.

    Args:
        ctx: the `BuildContext` from `build_city.py`. Reads `ctx.seed` and
            `ctx.materials`; adds two objects to the scene and two node
            groups to the blend data.
    """
    _purge()
    seed = int(getattr(ctx, "seed", 0))

    tree_sources, n_variants = _build_tree_sources(ctx)
    park_surface = _build_park_surface()
    park_ng = _build_park_node_group(tree_sources, n_variants, seed)
    _attach(park_surface, park_ng, "city_park_scatter")
    logger.info(
        "scatter: park graph attached (%d source trees, %d leaf variants, seed=%d)",
        len(tree_sources.objects),
        n_variants,
        seed,
    )

    street_sources = _build_street_sources(ctx)
    verges = _build_street_verges()
    street_ng = _build_street_node_group(street_sources, seed)
    _attach(verges, street_ng, "city_street_scatter")
    logger.info(
        "scatter: street graph attached (%d verge lines, spacing %.1f)",
        len(verges.data.edges),
        STREET_FURNITURE_SPACING,
    )


def count_instances(depsgraph=None) -> dict[str, int]:
    """Count evaluated instances per source object — the anti-silent-failure check.

    A Geometry Nodes graph with one bad link evaluates cleanly and produces
    nothing, so "the script ran" proves nothing. This walks the evaluated
    depsgraph and returns `{source_object_name: count}`; an empty dict means
    the graph is mis-wired.
    """
    import bpy

    if depsgraph is None:
        depsgraph = bpy.context.evaluated_depsgraph_get()
    counts: dict[str, int] = {}
    for inst in depsgraph.object_instances:
        if not inst.is_instance:
            continue
        name = inst.object.name if inst.object is not None else "<none>"
        counts[name] = counts.get(name, 0) + 1
    return counts
