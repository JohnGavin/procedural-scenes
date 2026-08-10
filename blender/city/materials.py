"""Material construction — populates `ctx.materials`.

Responsible for building every Blender material/shader node-graph used by
the other stages and registering it in `ctx.materials` under a fixed set of
keys. Every other module reads materials by name from that dict; it never
constructs its own (`buildings.py` is the one exception — it builds a
*derived* per-tower material that mixes a pool member with `window_emission`;
see that module's docstring).

Zero image textures are used anywhere in this module — every material is a
pure node graph (Noise/Wave/Brick/ColorRamp/MapRange driving Base
Color/Roughness/Emission/Normal). That is a deliberate headline point of this
rebuild: `buildings.html`'s three.js version needed a canvas-drawn PNG for
its dashed lane markings and otherwise used flat solid `MeshStandardMaterial`
colours everywhere; Blender gets grain, wear, and pattern from shader math
alone, and — for `glass` and `water` — genuine Cycles transmission, which a
`MeshStandardMaterial` can only ever fake with a tinted, non-refractive
reflection.

Keys this module populates (see `build_city.py`'s `ctx.materials` docstring
for the authoritative list) and their **types**:

    concrete        — list[bpy.types.Material], 5 colour variants
    glass           — list[bpy.types.Material], 3 colour variants
    leaf            — list[bpy.types.Material], 3 colour variants
    asphalt         — bpy.types.Material (single)
    water           — bpy.types.Material (single)
    kerb            — bpy.types.Material (single)
    bridge          — bpy.types.Material (single)
    trunk           — bpy.types.Material (single)
    crown           — bpy.types.Material (single)
    lane_paint      — bpy.types.Material (single)
    park_grass      — bpy.types.Material (single)
    gravel          — bpy.types.Material (single)
    window_emission — bpy.types.Material (single)

**Pooling convention (binding on every consumer):** only `concrete`, `glass`
and `leaf` are lists — every other key is always a single `Material`. This
mirrors the colour pools in `buildings.html` (5 concrete / 3 glass / 3 leaf
`MeshStandardMaterial`s, one picked per instance via
`pool[(rand()*pool.length)|0]`). Consumers pick a variant the same way, e.g.
`ctx.materials["concrete"][some_rand.randrange(len(pool))]`.

`build_materials()` is idempotent: re-running it in the same Blender session
looks up existing `bpy.data.materials` by name and reuses them rather than
rebuilding (and therefore never duplicating) their node graphs.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ===== small shared helpers =================================================


def _hex_to_linear(hex_int: int, gamma: float = 2.2) -> tuple[float, float, float]:
    """Convert a `0xRRGGBB` literal (as used for the three.js
    `MeshStandardMaterial` colours in `buildings.html`) to an approximate
    linear-space RGB triple for Blender's Principled BSDF, which expects
    linear input while the three.js scene works directly in sRGB display
    space. This is a coarse gamma approximation, not a true sRGB EOTF — more
    than accurate enough for "roughly the same colour family"; exact colour
    management fidelity is out of scope for this rebuild.
    """
    r = ((hex_int >> 16) & 0xFF) / 255.0
    g = ((hex_int >> 8) & 0xFF) / 255.0
    b = (hex_int & 0xFF) / 255.0
    return (r**gamma, g**gamma, b**gamma)


def _get_or_create(name: str):
    """Return `(material, is_new)`. `is_new=False` means a material with
    this name already exists (e.g. a previous call to `build_materials()` in
    the same Blender session) and its node graph should NOT be rebuilt —
    this is what makes `build_materials()` idempotent.
    """
    import bpy

    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing, False
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    return mat, True


def _set_input(node, names: tuple[str, ...], value) -> None:
    """Set the first matching input socket by name. Several Principled BSDF
    sockets were renamed across Blender versions (e.g. `"Transmission"` ->
    `"Transmission Weight"` in 4.0); passing multiple candidate names keeps
    this module working across that rename without version-sniffing.
    """
    for name in names:
        socket = node.inputs.get(name)
        if socket is not None:
            socket.default_value = value
            return
    raise KeyError(f"none of {names} found on {node.bl_idname} inputs")


# ===== per-material builders =================================================


def _simple_principled_material(
    name: str,
    base_color: tuple[float, float, float],
    roughness: float,
    roughness_var: float = 0.08,
    metallic: float = 0.0,
    noise_scale: float = 10.0,
) -> "bpy.types.Material":  # noqa: F821 (bpy only available under Blender)
    """A flat-coloured Principled BSDF with noise-driven roughness variation
    — the workhorse builder for every material that does not need a bespoke
    graph (kerb, bridge, trunk, crown, park_grass, gravel, leaf, asphalt).
    """
    mat, is_new = _get_or_create(name)
    if not is_new:
        return mat

    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (300, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
    _set_input(bsdf, ("Metallic",), metallic)

    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-400, -220)
    noise.inputs["Scale"].default_value = noise_scale
    map_range = nodes.new("ShaderNodeMapRange")
    map_range.location = (-180, -220)
    map_range.inputs["To Min"].default_value = max(0.0, roughness - roughness_var)
    map_range.inputs["To Max"].default_value = min(1.0, roughness + roughness_var)
    links.new(noise.outputs["Fac"], map_range.inputs["Value"])
    links.new(map_range.outputs["Result"], bsdf.inputs["Roughness"])

    return mat


def _concrete_material(name: str, base_color: tuple[float, float, float]):
    """Concrete: noise-driven roughness/colour variation plus a cheap
    vertical grime-streak — a height gradient (object-space Z, since these
    boxes are never rotated) broken up with noise so it reads as uneven
    weathering rather than a clean band, multiplied into the base colour.
    """
    mat, is_new = _get_or_create(name)
    if not is_new:
        return mat

    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (600, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (300, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    _set_input(bsdf, ("Metallic",), 0.04)

    base_rgb = nodes.new("ShaderNodeRGB")
    base_rgb.location = (-700, 250)
    base_rgb.outputs[0].default_value = (*base_color, 1.0)

    coord = nodes.new("ShaderNodeTexCoord")
    coord.location = (-900, -50)
    sep = nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-700, -50)
    links.new(coord.outputs["Object"], sep.inputs["Vector"])

    height_ramp = nodes.new("ShaderNodeValToRGB")
    height_ramp.location = (-500, -50)
    height_ramp.color_ramp.elements[0].position = 0.0
    height_ramp.color_ramp.elements[0].color = (0.55, 0.55, 0.55, 1.0)
    height_ramp.color_ramp.elements[1].position = 0.5
    height_ramp.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1.0)
    links.new(sep.outputs["Z"], height_ramp.inputs["Fac"])

    streak_noise = nodes.new("ShaderNodeTexNoise")
    streak_noise.location = (-500, -250)
    streak_noise.inputs["Scale"].default_value = 6.0

    streak_mix = nodes.new("ShaderNodeMixRGB")
    streak_mix.location = (-300, -100)
    streak_mix.blend_type = "MULTIPLY"
    streak_mix.inputs["Fac"].default_value = 0.6
    links.new(height_ramp.outputs["Color"], streak_mix.inputs["Color1"])
    links.new(streak_noise.outputs["Fac"], streak_mix.inputs["Color2"])

    tint = nodes.new("ShaderNodeMixRGB")
    tint.location = (-100, 150)
    tint.blend_type = "MULTIPLY"
    tint.inputs["Fac"].default_value = 1.0
    links.new(base_rgb.outputs[0], tint.inputs["Color1"])
    links.new(streak_mix.outputs["Color"], tint.inputs["Color2"])
    links.new(tint.outputs["Color"], bsdf.inputs["Base Color"])

    rough_noise = nodes.new("ShaderNodeTexNoise")
    rough_noise.location = (-100, -250)
    rough_noise.inputs["Scale"].default_value = 14.0
    map_range = nodes.new("ShaderNodeMapRange")
    map_range.location = (100, -250)
    map_range.inputs["To Min"].default_value = 0.55
    map_range.inputs["To Max"].default_value = 0.85
    links.new(rough_noise.outputs["Fac"], map_range.inputs["Value"])
    links.new(map_range.outputs["Result"], bsdf.inputs["Roughness"])

    return mat


def _glass_material(name: str, base_color: tuple[float, float, float]):
    """The headline material of this whole rebuild: a real Principled BSDF
    with Transmission so Cycles genuinely refracts/reflects the sky and
    neighbouring towers. `buildings.html`'s glass towers use
    `MeshStandardMaterial({ metalness: 0.85, roughness: 0.12 })` — a tinted
    mirror-ish reflection with *zero* refraction, because three.js's
    real-time PBR has no transmission model. Roughness is noise-varied so
    panels are not perfectly mirror-smooth (uniform mirror roughness reads
    as fake; real curtain-wall glass has panel-to-panel variation).
    """
    mat, is_new = _get_or_create(name)
    if not is_new:
        return mat

    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (300, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

    bsdf.inputs["Base Color"].default_value = (*base_color, 1.0)
    _set_input(bsdf, ("Metallic",), 0.0)
    _set_input(bsdf, ("IOR",), 1.47)
    _set_input(bsdf, ("Transmission Weight", "Transmission"), 1.0)

    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-400, -220)
    noise.inputs["Scale"].default_value = 24.0
    noise.inputs["Detail"].default_value = 2.0
    map_range = nodes.new("ShaderNodeMapRange")
    map_range.location = (-180, -220)
    map_range.inputs["To Min"].default_value = 0.02
    map_range.inputs["To Max"].default_value = 0.14
    links.new(noise.outputs["Fac"], map_range.inputs["Value"])
    links.new(map_range.outputs["Result"], bsdf.inputs["Roughness"])

    return mat


def _water_material(name: str):
    """River + pond: transmission + low roughness for real refraction, plus
    a Wave/Noise-driven bump normal so the surface reads as moving water
    (specular breakup) instead of `buildings.html`'s flat, static
    `waterMat` plane. `terrain.py` is responsible for giving the water mesh
    enough subdivision for the bump to read well at grazing angles.
    """
    mat, is_new = _get_or_create(name)
    if not is_new:
        return mat

    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (400, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (100, 0)
    links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])
    bsdf.inputs["Base Color"].default_value = (0.05, 0.12, 0.16, 1.0)
    _set_input(bsdf, ("Metallic",), 0.0)
    _set_input(bsdf, ("Roughness",), 0.05)
    _set_input(bsdf, ("IOR",), 1.33)
    _set_input(bsdf, ("Transmission Weight", "Transmission"), 1.0)

    wave = nodes.new("ShaderNodeTexWave")
    wave.location = (-400, -100)
    wave.wave_type = "BANDS"
    wave.inputs["Scale"].default_value = 5.0
    wave.inputs["Distortion"].default_value = 3.5

    ripple_noise = nodes.new("ShaderNodeTexNoise")
    ripple_noise.location = (-400, -300)
    ripple_noise.inputs["Scale"].default_value = 20.0

    combine = nodes.new("ShaderNodeMixRGB")
    combine.location = (-180, -200)
    combine.blend_type = "ADD"
    combine.inputs["Fac"].default_value = 0.4
    links.new(wave.outputs["Fac"], combine.inputs["Color1"])
    links.new(ripple_noise.outputs["Fac"], combine.inputs["Color2"])

    bump = nodes.new("ShaderNodeBump")
    bump.location = (40, -200)
    bump.inputs["Strength"].default_value = 0.15
    links.new(combine.outputs["Color"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])

    return mat


def _lane_paint_material(name: str):
    """Dashed lane markings, generated entirely from a Wave texture — no
    asset to ship. Replaces `buildings.html`'s `laneTexture()`, a
    64x8px `CanvasTexture` drawn once at load time with a hand-picked
    dash/gap ratio baked into pixels; this version tiles infinitely at any
    scale instead of being stretched over a fixed UV repeat.

    Built as a Transparent/Diffuse mix (not simple alpha) so it composites
    correctly in Cycles: `Fac` from a `CONSTANT`-interpolated ColorRamp on
    the wave gives a hard-edged ~53%/47% dash/gap split, matching the
    three.js texture's 34px-dash-of-64px-tile ratio.
    """
    mat, is_new = _get_or_create(name)
    if not is_new:
        return mat

    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (400, 0)
    diffuse = nodes.new("ShaderNodeBsdfDiffuse")
    diffuse.location = (0, 100)
    diffuse.inputs["Color"].default_value = (0.94, 0.93, 0.89, 1.0)
    transparent = nodes.new("ShaderNodeBsdfTransparent")
    transparent.location = (0, -50)
    mix_shader = nodes.new("ShaderNodeMixShader")
    mix_shader.location = (200, 0)
    links.new(mix_shader.outputs["Shader"], output.inputs["Surface"])
    links.new(transparent.outputs["BSDF"], mix_shader.inputs[1])
    links.new(diffuse.outputs["BSDF"], mix_shader.inputs[2])

    wave = nodes.new("ShaderNodeTexWave")
    wave.location = (-400, 0)
    wave.wave_type = "BANDS"
    wave.bands_direction = "X"
    wave.inputs["Scale"].default_value = 0.08
    wave.inputs["Distortion"].default_value = 0.0

    dash_ramp = nodes.new("ShaderNodeValToRGB")
    dash_ramp.location = (-180, 0)
    dash_ramp.color_ramp.interpolation = "CONSTANT"
    dash_ramp.color_ramp.elements[0].position = 0.0
    dash_ramp.color_ramp.elements[0].color = (1.0, 1.0, 1.0, 1.0)  # dash
    dash_ramp.color_ramp.elements[1].position = 0.53  # ~34/64, matches buildings.html
    dash_ramp.color_ramp.elements[1].color = (0.0, 0.0, 0.0, 1.0)  # gap
    links.new(wave.outputs["Fac"], dash_ramp.inputs["Fac"])
    links.new(dash_ramp.outputs["Color"], mix_shader.inputs["Fac"])

    return mat


def _window_emission_material(name: str, color: tuple[float, float, float], strength: float):
    """Standalone emissive window material. `strength` is resolved ONCE at
    build time from `ctx.preset["window_emission_strength"]` (0.0 when
    `ctx.preset["window_emission"]` is False) — materials are rebuilt fresh
    per `build_city.py` invocation/preset, so there is no need for this to
    react to preset changes after the fact.

    `buildings.py` reads this material's Emission node back out (colour +
    strength) to drive its own per-shaft window-grid mix, so this material
    is the single source of truth for "what do lit windows look like".
    """
    mat, is_new = _get_or_create(name)
    if not is_new:
        return mat

    nt = mat.node_tree
    nodes, links = nt.nodes, nt.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputMaterial")
    output.location = (200, 0)
    emission = nodes.new("ShaderNodeEmission")
    emission.location = (0, 0)
    emission.inputs["Color"].default_value = (*color, 1.0)
    emission.inputs["Strength"].default_value = strength
    links.new(emission.outputs["Emission"], output.inputs["Surface"])

    return mat


# ===== colour pools, ported from buildings.html =============================

_CONCRETE_HEX: tuple[int, ...] = (0xB9BCC0, 0xA4A8AE, 0xCBC7BD, 0x8F959D, 0xD2CFC7)
_GLASS_HEX: tuple[int, ...] = (0x8FB4D6, 0x6F93B6, 0xA9C6DE)
_LEAF_HEX: tuple[int, ...] = (0x3F7A3A, 0x4F8C42, 0x35682F)


def build_materials(ctx) -> None:
    """Populate `ctx.materials` with every key listed in the module
    docstring.

    Args:
        ctx: the `BuildContext` from `build_city.py`.
    """
    ctx.materials["concrete"] = [
        _concrete_material(f"City_Concrete_{i}", _hex_to_linear(h)) for i, h in enumerate(_CONCRETE_HEX)
    ]
    ctx.materials["glass"] = [
        _glass_material(f"City_Glass_{i}", _hex_to_linear(h)) for i, h in enumerate(_GLASS_HEX)
    ]
    ctx.materials["leaf"] = [
        _simple_principled_material(
            f"City_Leaf_{i}", _hex_to_linear(h), roughness=0.85, roughness_var=0.1, noise_scale=6.0
        )
        for i, h in enumerate(_LEAF_HEX)
    ]

    ctx.materials["asphalt"] = _simple_principled_material(
        "City_Asphalt", _hex_to_linear(0x3B3D42), roughness=0.92, roughness_var=0.06, noise_scale=30.0
    )
    ctx.materials["water"] = _water_material("City_Water")
    ctx.materials["kerb"] = _simple_principled_material(
        "City_Kerb", _hex_to_linear(0x9A9A94), roughness=0.9, roughness_var=0.05, noise_scale=16.0
    )
    ctx.materials["bridge"] = _simple_principled_material(
        "City_Bridge",
        _hex_to_linear(0x8B8D92),
        roughness=0.75,
        roughness_var=0.08,
        metallic=0.2,
        noise_scale=10.0,
    )
    ctx.materials["trunk"] = _simple_principled_material(
        "City_Trunk", _hex_to_linear(0x5B4632), roughness=0.92, roughness_var=0.05, noise_scale=8.0
    )
    ctx.materials["crown"] = _simple_principled_material(
        "City_Crown",
        _hex_to_linear(0x6D737C),
        roughness=0.55,
        roughness_var=0.08,
        metallic=0.3,
        noise_scale=8.0,
    )
    ctx.materials["lane_paint"] = _lane_paint_material("City_LanePaint")
    ctx.materials["park_grass"] = _simple_principled_material(
        "City_ParkGrass", _hex_to_linear(0x4A7A3C), roughness=0.95, roughness_var=0.05, noise_scale=40.0
    )
    ctx.materials["gravel"] = _simple_principled_material(
        "City_Gravel", _hex_to_linear(0xA89A80), roughness=0.9, roughness_var=0.08, noise_scale=50.0
    )
    # The 1600-unit base plane, distinct from `park_grass`. buildings.html uses
    # a muted olive (0x6F7758) here and the far brighter 0x4A7A3C only inside
    # the park. Reusing park_grass for both turned the whole horizon into a
    # saturated green field and flattened the park's contrast against it.
    ctx.materials["ground"] = _simple_principled_material(
        "City_Ground", _hex_to_linear(0x6F7758), roughness=1.0, roughness_var=0.04, noise_scale=25.0
    )

    strength = ctx.preset["window_emission_strength"] if ctx.preset["window_emission"] else 0.0
    ctx.materials["window_emission"] = _window_emission_material(
        "City_WindowEmission", (1.0, 0.85, 0.55), strength
    )

    logger.info("materials: %d keys populated", len(ctx.materials))
