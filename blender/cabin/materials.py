"""Every material in the cabin scene — all procedural node graphs, no images.

Populates `ctx.materials` with one `bpy.types.Material` per value in
`layout.BLOCK_MATERIALS`. The mesher assigns faces to slots by block id and
looks them up by those exact key strings.

Two things drive almost every decision here:

* **Greedy meshing merges coplanar faces into big quads.** A 20-block wall may
  be a SINGLE quad, so anything driven by UVs stretches grotesquely across it.
  Every graph below therefore takes its coordinates from Geometry > Position —
  true world space — so a plank is the same size on a one-quad wall and a
  twenty-quad one.
* **Blocks are 1.0 world unit.** Noise tuned for a 100-metre city reads as flat
  colour on a 1-metre block, so feature scales here are single digits.
"""

from __future__ import annotations

import logging

from . import layout

logger = logging.getLogger(__name__)


def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _hex(value: int) -> tuple[float, float, float, float]:
    """Hex sRGB -> linear RGBA, because Blender colour sockets are linear."""
    r = _srgb_to_linear(((value >> 16) & 0xFF) / 255.0)
    g = _srgb_to_linear(((value >> 8) & 0xFF) / 255.0)
    b = _srgb_to_linear((value & 0xFF) / 255.0)
    return (r, g, b, 1.0)


def _fresh(name: str):
    """Get-or-create a material with an empty node tree.

    Reusing the datablock rather than making a new one keeps
    `build_materials` idempotent — running the pipeline twice must not leave
    `spruce_log.001` behind.
    """
    import bpy

    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.node_tree.nodes.clear()
    return mat


def _world_coords(nodes, links, scale: float):
    """Geometry > Position through a Mapping node, at a given feature scale.

    NOT Texture Coordinate: that node has no world output in 5.x, and its
    Generated/Object outputs both stretch with object scale and with merged
    quads. Position is the only source that stays honest here.
    """
    geo = nodes.new("ShaderNodeNewGeometry")
    geo.location = (-1000, 0)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-820, 0)
    mapping.inputs["Scale"].default_value = (scale, scale, scale)
    links.new(geo.outputs["Position"], mapping.inputs["Vector"])
    return mapping


def _rough_pbr(name: str, colour: int, roughness: float, *, noise_scale: float = 4.0,
               colour_var: float = 0.06, rough_var: float = 0.12,
               metallic: float = 0.0):
    """Standard opaque block: Principled with noise-driven colour + roughness.

    The variation is what stops a voxel world reading as flat plastic — every
    block face of the same type would otherwise be pixel-identical.
    """
    mat = _fresh(name)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (140, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    mapping = _world_coords(nodes, links, noise_scale)
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-620, 0)
    noise.inputs["Detail"].default_value = 4.0
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])

    base = _hex(colour)
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (-420, 120)
    ramp.color_ramp.elements[0].color = tuple(max(0.0, c * (1 - colour_var)) for c in base[:3]) + (1.0,)
    ramp.color_ramp.elements[1].color = tuple(min(1.0, c * (1 + colour_var)) for c in base[:3]) + (1.0,)
    links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    rmap = nodes.new("ShaderNodeMapRange")
    rmap.location = (-420, -160)
    rmap.inputs["To Min"].default_value = max(0.0, roughness - rough_var)
    rmap.inputs["To Max"].default_value = min(1.0, roughness + rough_var)
    links.new(noise.outputs["Fac"], rmap.inputs["Value"])
    links.new(rmap.outputs["Result"], bsdf.inputs["Roughness"])

    bsdf.inputs["Metallic"].default_value = metallic
    return mat


def _grain(name: str, colour: int, roughness: float, axis: str, freq: float):
    """Timber: banding along one axis plus noise, for logs and planks.

    A Wave texture on world coordinates gives the banding a fixed real-world
    pitch, so the grain does not change size between a corner post and a long
    merged wall quad.
    """
    mat = _fresh(name)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links

    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (140, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    mapping = _world_coords(nodes, links, 1.0)
    sep = nodes.new("ShaderNodeSeparateXYZ")
    sep.location = (-640, -60)
    links.new(mapping.outputs["Vector"], sep.inputs["Vector"])

    wave = nodes.new("ShaderNodeTexWave")
    wave.location = (-620, 160)
    wave.inputs["Scale"].default_value = freq
    wave.inputs["Distortion"].default_value = 3.0
    wave.inputs["Detail"].default_value = 2.0
    links.new(mapping.outputs["Vector"], wave.inputs["Vector"])

    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-620, -220)
    noise.inputs["Scale"].default_value = 9.0
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])

    mix = nodes.new("ShaderNodeMixRGB")
    mix.location = (-400, 60)
    mix.blend_type = "MULTIPLY"
    mix.inputs["Fac"].default_value = 0.35
    links.new(wave.outputs["Fac"], mix.inputs["Color1"])
    links.new(noise.outputs["Fac"], mix.inputs["Color2"])

    base = _hex(colour)
    ramp = nodes.new("ShaderNodeValToRGB")
    ramp.location = (-200, 60)
    ramp.color_ramp.elements[0].color = tuple(c * 0.72 for c in base[:3]) + (1.0,)
    ramp.color_ramp.elements[1].color = tuple(min(1.0, c * 1.14) for c in base[:3]) + (1.0,)
    links.new(mix.outputs["Color"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])

    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def _glass(name: str):
    """Window glass — real transmission.

    The single most important material in the scene: the whole concept is warm
    interior light arriving outside through this. It must actually transmit,
    not merely look pale.
    """
    mat = _fresh(name)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (60, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    bsdf.inputs["Base Color"].default_value = (0.86, 0.92, 0.95, 1.0)
    for key in ("Transmission Weight", "Transmission"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 1.0
            break
    bsdf.inputs["Roughness"].default_value = 0.04
    bsdf.inputs["IOR"].default_value = 1.45
    mat.use_backface_culling = False
    return mat


def _water(name: str):
    """River water: low roughness, transmission, gentle wave normal.

    Roughness stays low and the bump stays subtle on purpose — the brief asks
    for gentle reflections, and a strong bump shreds a reflection into noise.
    """
    mat = _fresh(name)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (160, 0)
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

    bsdf.inputs["Base Color"].default_value = (0.06, 0.17, 0.22, 1.0)
    for key in ("Transmission Weight", "Transmission"):
        if key in bsdf.inputs:
            bsdf.inputs[key].default_value = 0.85
            break
    bsdf.inputs["Roughness"].default_value = 0.02
    bsdf.inputs["IOR"].default_value = 1.33

    mapping = _world_coords(nodes, links, 1.0)
    wave = nodes.new("ShaderNodeTexNoise")
    wave.location = (-600, -200)
    wave.inputs["Scale"].default_value = 2.4
    wave.inputs["Detail"].default_value = 3.0
    links.new(mapping.outputs["Vector"], wave.inputs["Vector"])
    bump = nodes.new("ShaderNodeBump")
    bump.location = (-320, -220)
    bump.inputs["Strength"].default_value = 0.06
    links.new(wave.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def _leaves(name: str, colour: int):
    """Spruce needles — noise-cutout alpha so the canopy is not a solid cube.

    `BLOCK_FLAGS` marks leaves transparent, so the mesher does not cull the
    faces behind them; the cutout is what turns those extra faces into foliage
    rather than a green block.
    """
    mat = _rough_pbr(name, colour, 0.85, noise_scale=7.0, colour_var=0.16)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    out = next(n for n in nodes if n.type == "OUTPUT_MATERIAL")

    mapping = _world_coords(nodes, links, 9.0)
    noise = nodes.new("ShaderNodeTexNoise")
    noise.location = (-560, -420)
    noise.inputs["Scale"].default_value = 5.0
    noise.inputs["Detail"].default_value = 2.0
    links.new(mapping.outputs["Vector"], noise.inputs["Vector"])

    thresh = nodes.new("ShaderNodeMath")
    thresh.location = (-340, -420)
    thresh.operation = "GREATER_THAN"
    thresh.inputs[1].default_value = 0.34
    links.new(noise.outputs["Fac"], thresh.inputs[0])

    transp = nodes.new("ShaderNodeBsdfTransparent")
    transp.location = (140, -200)
    mix = nodes.new("ShaderNodeMixShader")
    mix.location = (300, 0)
    links.new(thresh.outputs["Value"], mix.inputs["Fac"])
    links.new(transp.outputs["BSDF"], mix.inputs[1])
    links.new(bsdf.outputs["BSDF"], mix.inputs[2])
    links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def _emissive(name: str, colour: int, strength: float, *, variation: float = 0.0):
    """Lamp / campfire. Real emitters — in Cycles these light the scene.

    Emission strength comes from the preset so the same geometry can be a
    gentle evening glow or the only light in the valley.
    """
    mat = _fresh(name)
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    out = nodes.new("ShaderNodeOutputMaterial")
    out.location = (320, 0)
    emit = nodes.new("ShaderNodeEmission")
    emit.location = (100, 0)
    emit.inputs["Color"].default_value = _hex(colour)
    emit.inputs["Strength"].default_value = strength
    links.new(emit.outputs["Emission"], out.inputs["Surface"])

    if variation > 0.0:
        mapping = _world_coords(nodes, links, 6.0)
        noise = nodes.new("ShaderNodeTexNoise")
        noise.location = (-560, 0)
        noise.inputs["Scale"].default_value = 6.0
        links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
        rmap = nodes.new("ShaderNodeMapRange")
        rmap.location = (-320, 0)
        rmap.inputs["To Min"].default_value = strength * (1.0 - variation)
        rmap.inputs["To Max"].default_value = strength * (1.0 + variation)
        links.new(noise.outputs["Fac"], rmap.inputs["Value"])
        links.new(rmap.outputs["Result"], emit.inputs["Strength"])
    return mat


def build_materials(ctx) -> None:
    """Populate `ctx.materials` with every key in `layout.BLOCK_MATERIALS`."""
    preset = ctx.preset
    lamp_strength = float(preset.get("window_light_strength", 12.0))
    fire_strength = float(preset.get("campfire_strength", 22.0))

    m = ctx.materials
    m["spruce_log"] = _grain("Cabin_SpruceLog", 0x5A3F28, 0.82, "z", 5.5)
    m["spruce_plank"] = _grain("Cabin_SprucePlank", 0x8A6440, 0.72, "x", 3.0)
    m["spruce_leaves"] = _leaves("Cabin_SpruceLeaves", 0x2B4A32)
    m["glass"] = _glass("Cabin_Glass")
    m["water"] = _water("Cabin_Water")
    m["lamp"] = _emissive("Cabin_Lamp", 0xFFB765, lamp_strength)
    m["campfire"] = _emissive("Cabin_Campfire", 0xFF6A22, fire_strength, variation=0.35)

    m["grass"] = _rough_pbr("Cabin_Grass", 0x4E7A38, 0.95, noise_scale=5.0, colour_var=0.14)
    m["dirt"] = _rough_pbr("Cabin_Dirt", 0x5C4530, 0.96, noise_scale=6.0, colour_var=0.10)
    m["stone"] = _rough_pbr("Cabin_Stone", 0x76797C, 0.88, noise_scale=4.5, colour_var=0.08)
    m["cobble"] = _rough_pbr("Cabin_Cobble", 0x6B6E70, 0.92, noise_scale=11.0, colour_var=0.18)
    m["sand"] = _rough_pbr("Cabin_Sand", 0xC2AE84, 0.94, noise_scale=8.0, colour_var=0.07)
    m["snow"] = _rough_pbr("Cabin_Snow", 0xE9EEF4, 0.35, noise_scale=6.0,
                           colour_var=0.03, rough_var=0.18)
    m["path"] = _rough_pbr("Cabin_Path", 0x8B7A5E, 0.95, noise_scale=7.0, colour_var=0.12)

    missing = sorted(set(layout.BLOCK_MATERIALS.values()) - set(m))
    if missing:
        logger.warning("materials: MISSING keys %s", missing)
    logger.info("materials: %d keys populated (lamp=%.1f fire=%.1f)",
                len(m), lamp_strength, fire_strength)
