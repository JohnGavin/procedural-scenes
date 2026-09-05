"""Tower geometry — one mesh (or mesh group) per `city.layout.Plot`.

Responsible for the podium/shaft/crown/mast construction that
`buildings.html`'s `tower()` does, driven entirely by `ctx.plots` (already
resolved by `city.layout.tower_plots()` — no layout maths happens here, only
geometry + material assignment). Use `plot.seed` (via
`random.Random(plot.seed)`) for any further per-building random choices
(podium height, crown height, mast presence, rooftop plant, material colour
variant, shaft narrowing) so the choices are reproducible without disturbing
`ctx.rng`'s stream.

Consumes from `ctx.materials`: `concrete`, `glass`, `crown`,
`window_emission` (indirectly, via `_window_emission_params` below — read
back out of that material rather than re-deriving preset values here).
Produces no new `ctx.materials` keys of its own, but DOES construct and
cache extra derived materials (`<pool-variant>_Windows`) outside the
registry — see `_windowed_shaft_material`.

Geometry sharing: every box (podium/shaft/crown/low-rise block/rooftop
plant) is a `bpy.types.Object` pointing at ONE shared unit-cube mesh
datablock, scaled per-object — this is Blender's equivalent of three.js's
`UNIT_BOX` shared `BoxGeometry` + per-`Mesh` `.scale`. With ~84 plots x
2-4 objects each, that is a few hundred objects sharing 1-2 mesh
datablocks, built via `bmesh` (never `bpy.ops.mesh.primitive_*_add`, which
is slow and context-fragile in background mode). Differing per-object
materials on a shared mesh use Blender's OBJECT-linked material slots
(`obj.material_slots[0].link = "OBJECT"`), NOT the mesh's own (shared)
material list — that is what lets 84 towers reuse one box mesh while each
still shows its own concrete/glass/window variant.

Window grids: see `_windowed_shaft_material`'s docstring for the approach
and why Object/Generated texture coordinates would break at this scale.
"""

from __future__ import annotations

import logging
import random

from city.layout import Y, Plot

logger = logging.getLogger(__name__)

_UNIT_BOX_MESH_NAME = "City_UnitBox"
_MAST_MESH_NAME = "City_TowerMast"
_COLLECTION_NAME = "Buildings"

# Cache of derived "shaft + window grid" materials, keyed by (pool_name,
# variant_index) so all towers sharing the same concrete/glass colour
# variant also share one combined material — 8 variants total (5 concrete +
# 3 glass) instead of one new material per tower.
_shaft_window_cache: dict[tuple[str, int], object] = {}


# ===== shared geometry ========================================================


def _unit_box_mesh():
    """A 1x1x1 cube centred at the origin (matches three.js
    `BoxGeometry(1,1,1)`, also centred), built once via `bmesh` and reused —
    scaled per-object — for every box in the scene.
    """
    import bmesh
    import bpy

    mesh = bpy.data.meshes.get(_UNIT_BOX_MESH_NAME)
    if mesh is not None:
        return mesh

    mesh = bpy.data.meshes.new(_UNIT_BOX_MESH_NAME)
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(None)  # one object-linkable slot; see obj.material_slots use below
    return mesh


def _mast_mesh():
    """A unit-height hexagonal cone (radius 0.4 base -> 0.28 top), matching
    `buildings.html`'s `CylinderGeometry(0.28, 0.4, 12, 6)` — object scale
    then stretches only the Z axis to reach the real mast height (12), so
    the base/top radii stay exactly as authored rather than scaling
    elliptically.
    """
    import bmesh
    import bpy

    mesh = bpy.data.meshes.get(_MAST_MESH_NAME)
    if mesh is not None:
        return mesh

    mesh = bpy.data.meshes.new(_MAST_MESH_NAME)
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=0.4, radius2=0.28, depth=1.0)
    bm.to_mesh(mesh)
    bm.free()
    mesh.materials.append(None)
    return mesh


def _buildings_collection():
    import bpy

    coll = bpy.data.collections.get(_COLLECTION_NAME)
    if coll is None:
        coll = bpy.data.collections.new(_COLLECTION_NAME)
        bpy.context.scene.collection.children.link(coll)
    return coll


def _three_to_blender(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Axis remap from `city.layout`'s `COORDINATE_NOTE`: three.js
    `(x, y, z)` -> Blender `(x, z, y)`.
    """
    return (x, z, y)


def _add_box(collection, mesh, name, three_x, three_y, three_z, w, h, d, material):
    """Link a new object at (three.js-named) centre `(three_x, three_y,
    three_z)` with three.js footprint `w`x`d` and height `h`, using the
    shared `mesh`. `w`/`d`/`h` are three.js-named (x/z footprint, y height);
    they map to Blender object scale `(w, d, h)` under the same axis remap
    as position, since these boxes are never rotated.
    """
    import bpy

    obj = bpy.data.objects.new(name, mesh)
    obj.location = _three_to_blender(three_x, three_y, three_z)
    obj.scale = (w, d, h)
    collection.objects.link(obj)
    if material is not None:
        obj.material_slots[0].link = "OBJECT"
        obj.material_slots[0].material = material
    return obj


def _add_mast(collection, mesh, name, plot: Plot, y_center: float, material):
    import bpy

    obj = bpy.data.objects.new(name, mesh)
    obj.location = _three_to_blender(plot.x, y_center, plot.z)
    obj.scale = (1.0, 1.0, 12.0)  # radii baked into the mesh; only height is scaled
    collection.objects.link(obj)
    if material is not None:
        obj.material_slots[0].link = "OBJECT"
        obj.material_slots[0].material = material
    return obj


# ===== window grid =============================================================


def _window_emission_params(ctx) -> tuple[tuple[float, float, float, float], float]:
    """Read `(color, strength)` back out of `ctx.materials["window_emission"]`'s
    Emission node, so the per-shaft window mix below always matches whatever
    `materials.py` configured for the active preset (strength 0 under
    `noon`, >0 under `dusk`/`night`) without re-deriving preset values here —
    `materials.py` is the single source of truth for what a lit window looks
    like.
    """
    mat = ctx.materials["window_emission"]
    for node in mat.node_tree.nodes:
        if node.type == "EMISSION":
            color = tuple(node.inputs["Color"].default_value)
            strength = node.inputs["Strength"].default_value
            return color, strength
    return (1.0, 0.85, 0.55, 1.0), 0.0


def _windowed_shaft_material(ctx, pool_name: str, variant_index: int, base_mat):
    """Build (once per pool/variant, cached in `_shaft_window_cache`) a
    derived copy of `base_mat` with an emissive window grid mixed in via the
    Principled BSDF's native Emission Color/Strength inputs — a Cycles-only
    trick three.js cannot do: these emissive panes actually cast light onto
    the street (see `lighting.py`/`render.py`), not just fake a bright
    texture the way an emissive map would in three.js.

    **Grid approach chosen (procedural node graph, not inset geometry):** a
    Brick-texture mortar mask (window pane vs. frame) combined with a
    per-cell random "lit/dark" value from a White Noise texture fed a
    FLOORed (quantised-to-cell) coordinate. Feeding White Noise a quantised
    input is the standard trick for "one random value per grid cell" without
    needing per-window geometry or a Voronoi cell lookup — 84 towers x a
    Brick+VectorMath(Floor)+WhiteNoise graph is far cheaper than real inset
    geometry, and it is exactly the kind of node-driven shading trick this
    rebuild exists to demonstrate.

    **Why World texture coordinates, not Object or Generated:** every shaft
    reuses the ONE shared unit-cube mesh from `_unit_box_mesh()`, scaled
    per-object to each tower's actual footprint/height. Object and Generated
    coordinates are normalised to a mesh's local bounding box — on a shared,
    non-uniformly-scaled mesh that means the window grid would stretch to
    match each tower's own dimensions instead of staying a fixed real-world
    size, exactly the failure mode this module's brief warned about. World
    coordinates are absolute world-space positions, unaffected by
    per-object scale, so a window reads the same physical size on a
    20-storey tower and an 80-storey one alike.
    """
    cache_key = (pool_name, variant_index)
    cached = _shaft_window_cache.get(cache_key)
    if cached is not None:
        return cached

    import bpy

    name = f"{base_mat.name}_Windows"
    mat = bpy.data.materials.get(name)
    if mat is not None:
        _shaft_window_cache[cache_key] = mat
        return mat

    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (900, 0)
    facade = nodes.new("ShaderNodeBsdfPrincipled")
    facade.location = (600, 0)
    links.new(facade.outputs["BSDF"], output.inputs["Surface"])

    # Copy the base pool material's own facade look (colour/metal/rough/
    # transmission) so window-less areas still read as that concrete/glass
    # variant.
    base_bsdf = next(n for n in base_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    for socket_names in (
        ("Base Color",),
        ("Metallic",),
        ("Roughness",),
        ("Transmission Weight", "Transmission"),
        ("IOR",),
    ):
        src = next((base_bsdf.inputs.get(n) for n in socket_names if base_bsdf.inputs.get(n)), None)
        dst = next((facade.inputs.get(n) for n in socket_names if facade.inputs.get(n)), None)
        if src is not None and dst is not None:
            dst.default_value = src.default_value

    window_color, window_strength = _window_emission_params(ctx)
    facade.inputs["Emission Color"].default_value = window_color

    # True world-space position, NOT Texture Coordinate. ShaderNodeTexCoord has
    # no "World" output (its outputs are Generated/Normal/UV/Object/Camera/
    # Window/Reflection), and both Generated and Object stretch with the object's
    # scale — which would make window cells taller on tall towers, since the
    # shafts share one unit mesh and differ only by scale. Geometry > Position is
    # in world units, so a 2.6 m cell is 2.6 m on every tower.
    coord = nodes.new("ShaderNodeNewGeometry")
    coord.location = (-800, -200)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-600, -200)
    window_pitch = 2.6  # metres per window cell, roughly office-floor scale
    mapping.inputs["Scale"].default_value = (1.0 / window_pitch,) * 3
    links.new(coord.outputs["Position"], mapping.inputs["Vector"])

    brick = nodes.new("ShaderNodeTexBrick")
    brick.location = (-400, -100)
    brick.inputs["Mortar Size"].default_value = 0.06
    links.new(mapping.outputs["Vector"], brick.inputs["Vector"])
    # brick.outputs["Fac"] is ~1 on the mortar lines (window frames), ~0
    # inside each pane; invert to get a 0..1 "is glass pane" mask.
    invert_pane = nodes.new("ShaderNodeMath")
    invert_pane.location = (-180, -50)
    invert_pane.operation = "SUBTRACT"
    invert_pane.inputs[0].default_value = 1.0
    links.new(brick.outputs["Fac"], invert_pane.inputs[1])

    cell_floor = nodes.new("ShaderNodeVectorMath")
    cell_floor.location = (-400, -300)
    cell_floor.operation = "FLOOR"
    links.new(mapping.outputs["Vector"], cell_floor.inputs[0])

    cell_random = nodes.new("ShaderNodeTexWhiteNoise")
    cell_random.location = (-180, -300)
    cell_random.noise_dimensions = "3D"
    links.new(cell_floor.outputs["Vector"], cell_random.inputs["Vector"])

    lit_threshold = nodes.new("ShaderNodeMath")
    lit_threshold.location = (40, -300)
    lit_threshold.operation = "GREATER_THAN"
    lit_threshold.inputs[1].default_value = 0.3  # ~70% of windows lit
    links.new(cell_random.outputs["Value"], lit_threshold.inputs[0])

    pane_and_lit = nodes.new("ShaderNodeMath")
    pane_and_lit.location = (260, -150)
    pane_and_lit.operation = "MULTIPLY"
    links.new(invert_pane.outputs["Value"], pane_and_lit.inputs[0])
    links.new(lit_threshold.outputs["Value"], pane_and_lit.inputs[1])

    strength_scale = nodes.new("ShaderNodeMath")
    strength_scale.location = (440, -150)
    strength_scale.operation = "MULTIPLY"
    strength_scale.inputs[1].default_value = window_strength
    links.new(pane_and_lit.outputs["Value"], strength_scale.inputs[0])
    links.new(strength_scale.outputs["Value"], facade.inputs["Emission Strength"])

    _shaft_window_cache[cache_key] = mat
    return mat


# ===== tower construction ======================================================


def _build_tower(ctx, collection, unit_mesh, mast_mesh, plot: Plot) -> int:
    """Build one plot's geometry (podium/shaft/crown/mast, or a plain low
    box). Returns the number of objects created. All random choices here use
    `random.Random(plot.seed)`, independent of `ctx.rng`, so this plot's
    geometry is reproducible without disturbing any other stage's draws.
    """
    r = random.Random(plot.seed)
    pool_name = "glass" if plot.is_glass else "concrete"
    pool = ctx.materials[pool_name]
    variant_index = r.randrange(len(pool))
    shaft_mat = pool[variant_index]
    concrete_pool = ctx.materials["concrete"]

    name_base = f"Tower_b{plot.block_i}{plot.block_j}_{plot.x:.1f}_{plot.z:.1f}"
    count = 0

    if plot.h > 30:
        # Podium, shaft, crown — reads as a real tower rather than a plain slab.
        pod_h = 6 + r.random() * 5
        pod_mat = concrete_pool[r.randrange(len(concrete_pool))]
        _add_box(
            collection,
            unit_mesh,
            f"{name_base}_podium",
            plot.x,
            Y.kerb_top + pod_h / 2,
            plot.z,
            plot.w,
            pod_h,
            plot.d,
            pod_mat,
        )
        count += 1

        sw = plot.w * (0.62 + r.random() * 0.16)
        sd = plot.d * (0.62 + r.random() * 0.16)
        windowed_mat = _windowed_shaft_material(ctx, pool_name, variant_index, shaft_mat)
        shaft_y = Y.kerb_top + pod_h + plot.h / 2
        _add_box(
            collection, unit_mesh, f"{name_base}_shaft", plot.x, shaft_y, plot.z, sw, plot.h, sd, windowed_mat
        )
        count += 1

        crown_h = 3 + r.random() * 7
        crown_y = Y.kerb_top + pod_h + plot.h + crown_h / 2
        _add_box(
            collection,
            unit_mesh,
            f"{name_base}_crown",
            plot.x,
            crown_y,
            plot.z,
            sw * 0.5,
            crown_h,
            sd * 0.5,
            ctx.materials["crown"],
        )
        count += 1

        if r.random() < 0.4:
            mast_y = Y.kerb_top + pod_h + plot.h + crown_h + 6
            _add_mast(collection, mast_mesh, f"{name_base}_mast", plot, mast_y, ctx.materials["crown"])
            count += 1
    else:
        _add_box(
            collection,
            unit_mesh,
            f"{name_base}_block",
            plot.x,
            Y.kerb_top + plot.h / 2,
            plot.z,
            plot.w,
            plot.h,
            plot.d,
            shaft_mat,
        )
        count += 1

        if r.random() < 0.35:
            _add_box(
                collection,
                unit_mesh,
                f"{name_base}_plant",
                plot.x,
                Y.kerb_top + plot.h + 1,
                plot.z,
                plot.w * 0.4,
                2,
                plot.d * 0.4,
                ctx.materials["crown"],
            )
            count += 1

    return count


def build_buildings(ctx) -> None:
    """Build every tower in `ctx.plots`.

    Args:
        ctx: the `BuildContext` from `build_city.py`.
    """
    unit_mesh = _unit_box_mesh()
    mast_mesh = _mast_mesh()
    collection = _buildings_collection()
    # Rebuild the window-grid material cache every invocation so a changed
    # preset's window_emission strength/colour is picked up fresh rather
    # than reusing a stale combined material from a previous preset's build.
    _shaft_window_cache.clear()

    created = 0
    for plot in ctx.plots:
        created += _build_tower(ctx, collection, unit_mesh, mast_mesh, plot)

    logger.info("buildings: %d plots -> %d objects", len(ctx.plots), created)
