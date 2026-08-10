"""Dusk sky, sun, emissive-block lights, and bounded evening fog.

Runs after the world mesh exists. Everything is driven by `ctx.preset`, so the
same geometry reads as dusk, night, snow or a lit interior.

Two pieces of hard-won knowledge from the city build are reused here rather
than rediscovered — see the comments on `_fog` and `_sky` respectively:
a World volume renders black, and `sky_type = "NISHITA"` no longer exists.
"""

from __future__ import annotations

import logging
import math

import numpy as np

from . import layout
from .layout import Block

logger = logging.getLogger(__name__)

#: Fog box extents, in world units, around the generated region.
_FOG_MARGIN = 6.0

#: Scale from the preset's `fog_density` to a real per-unit extinction.
#: The city needed 0.25 because its camera sat ~340 units out; here the camera
#: is ~30 units from the cabin, so the same optical depth needs a much larger
#: coefficient. Calibrated for roughly 0.4-0.6 optical depth across the view.
_FOG_SCALE = 1.0


def _sun_direction(elevation: float, rotation: float):
    """Unit vector pointing FROM the sun toward the scene."""
    import mathutils

    return mathutils.Vector((
        math.cos(elevation) * math.sin(rotation),
        math.cos(elevation) * -math.cos(rotation),
        -math.sin(elevation),
    )).normalized()


def _sky(ctx) -> None:
    """World shader: physically-based sky whose sun drives the scene light."""
    import bpy

    preset = ctx.preset
    world = bpy.data.worlds.get("CabinWorld") or bpy.data.worlds.new("CabinWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    tree = world.node_tree
    tree.nodes.clear()

    out = tree.nodes.new("ShaderNodeOutputWorld")
    out.location = (400, 0)
    bg = tree.nodes.new("ShaderNodeBackground")
    bg.location = (180, 0)
    sky = tree.nodes.new("ShaderNodeTexSky")
    sky.location = (-120, 0)

    # 5.x retired the NISHITA enum and split that model into SINGLE_ and
    # MULTIPLE_SCATTERING. Fall back through the old names so this still runs
    # on a 4.x Blender.
    for kind in ("MULTIPLE_SCATTERING", "NISHITA", "HOSEK_WILKIE"):
        try:
            sky.sky_type = kind
            break
        except TypeError:
            continue

    sky.sun_elevation = preset["sun_elevation_rad"]
    sky.sun_rotation = preset["sun_rotation_rad"]
    sky.air_density = preset["sky_air_density"]
    # `dust_density` was renamed `aerosol_density` in 5.x.
    if hasattr(sky, "aerosol_density"):
        sky.aerosol_density = preset["sky_dust_density"]
    else:
        sky.dust_density = preset["sky_dust_density"]
    sky.ozone_density = preset["sky_ozone_density"]

    tree.links.new(sky.outputs["Color"], bg.inputs["Color"])
    bg.inputs["Strength"].default_value = 1.0

    if preset["sun_elevation_rad"] < 0:
        # Below the horizon the sky itself contributes almost nothing, so add an
        # explicit cool moonlight fill. Without it the frame is black with a few
        # lit rectangles in it: the emitters read but the cabin has no silhouette
        # and the forest disappears entirely. Kept cold and dim so it separates
        # from the warm emitters rather than competing with them.
        moon = tree.nodes.new("ShaderNodeRGB")
        moon.location = (-120, -220)
        moon.outputs[0].default_value = (0.10, 0.16, 0.30, 1.0)
        tree.links.new(moon.outputs[0], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = 1.4

    tree.links.new(bg.outputs["Background"], out.inputs["Surface"])
    # Deliberately NOT wiring anything into out.inputs["Volume"] — see _fog.


def _sun(ctx) -> None:
    """Sun lamp aimed to agree with the sky's own sun."""
    import bpy

    preset = ctx.preset
    data = bpy.data.lights.get("CabinSunData") or bpy.data.lights.new("CabinSunData", "SUN")
    data.type = "SUN"
    data.energy = preset["sun_strength"]
    data.angle = math.radians(1.5)          # soft-edged shadows
    data.color = (1.0, 0.86, 0.68) if preset["sun_elevation_rad"] < 0.35 else (1.0, 0.96, 0.9)

    obj = bpy.data.objects.get("CabinSun")
    if obj is None:
        obj = bpy.data.objects.new("CabinSun", data)
        bpy.context.scene.collection.objects.link(obj)
    obj.data = data

    direction = _sun_direction(preset["sun_elevation_rad"], preset["sun_rotation_rad"])
    obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    obj.location = (layout.SIZE_X / 2, layout.SIZE_Y / 2, layout.SIZE_Z + 20)


def _block_lights(ctx) -> tuple[int, int]:
    """Real point lights at every LAMP and CAMPFIRE block.

    The emissive materials already light the scene physically — that is the
    demo. But small emissive faces, especially ones seen through a window, are
    slow for Cycles to find by chance and come back noisy. Adding an explicit
    light Cycles can sample directly at the same position buys a dramatically
    cleaner image at the same sample count. The emitters stay: they provide the
    visible glow and the bounce; these provide the sampling.
    """
    import bpy

    volume = ctx.volume
    preset = ctx.preset

    for obj in [o for o in bpy.data.objects if o.name.startswith("CabinBlockLight")]:
        bpy.data.objects.remove(obj, do_unlink=True)

    specs = (
        (int(Block.LAMP), preset["window_light_strength"], (1.0, 0.72, 0.40), 1.6),
        (int(Block.CAMPFIRE), preset["campfire_strength"], (1.0, 0.45, 0.15), 2.2),
    )

    made = 0
    emissive_blocks = 0
    for block_id, strength, colour, radius in specs:
        coords = np.argwhere(volume == block_id)
        emissive_blocks += len(coords)
        for i, (bx, by, bz) in enumerate(coords):
            data = bpy.data.lights.new(f"CabinBlockLightData_{block_id}_{i}", "POINT")
            data.energy = float(strength) * 12.0     # W, tuned against block emission
            data.color = colour
            data.shadow_soft_size = radius
            obj = bpy.data.objects.new(f"CabinBlockLight_{block_id}_{i}", data)
            obj.location = (
                (bx + 0.5) * layout.BLOCK_SIZE,
                (by + 0.5) * layout.BLOCK_SIZE,
                (bz + 0.5) * layout.BLOCK_SIZE,
            )
            bpy.context.scene.collection.objects.link(obj)
            made += 1
    return made, emissive_blocks


def _fog(ctx) -> float:
    """Evening fog as a BOUNDED volume domain.

    Not a World volume. That was measured in the city build: an unbounded medium
    gives every sky-bound ray infinite optical depth and the frame renders pure
    black (mean pixel 0.00033 against 0.968 without). No density is small enough
    to escape it, because the path length is infinite either way. A box gives
    each ray a finite path, so density behaves like real extinction and the
    distance haze the brief asks for actually appears.
    """
    import bpy

    density = float(ctx.preset["fog_density"]) * _FOG_SCALE

    old = bpy.data.objects.get("CabinFog")
    if old is not None:
        bpy.data.objects.remove(old, do_unlink=True)

    x1 = layout.SIZE_X * layout.BLOCK_SIZE + _FOG_MARGIN
    y1 = layout.SIZE_Y * layout.BLOCK_SIZE + _FOG_MARGIN
    z1 = layout.SIZE_Z * layout.BLOCK_SIZE
    verts = [
        (-_FOG_MARGIN, -_FOG_MARGIN, -2.0), (x1, -_FOG_MARGIN, -2.0),
        (x1, y1, -2.0), (-_FOG_MARGIN, y1, -2.0),
        (-_FOG_MARGIN, -_FOG_MARGIN, z1), (x1, -_FOG_MARGIN, z1),
        (x1, y1, z1), (-_FOG_MARGIN, y1, z1),
    ]
    faces = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    mesh = bpy.data.meshes.new("CabinFogMesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    obj = bpy.data.objects.new("CabinFog", mesh)
    bpy.context.scene.collection.objects.link(obj)
    # Wire + unselectable so it never blocks the GUI viewport, same as the city
    # atmosphere. It has no surface shader, so Cycles never sees it as geometry.
    obj.display_type = "WIRE"
    obj.hide_select = True

    mat = bpy.data.materials.get("Cabin_Fog") or bpy.data.materials.new("Cabin_Fog")
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    out = tree.nodes.new("ShaderNodeOutputMaterial")
    out.location = (300, 0)
    scatter = tree.nodes.new("ShaderNodeVolumeScatter")
    scatter.location = (60, 0)
    scatter.inputs["Density"].default_value = density
    scatter.inputs["Anisotropy"].default_value = 0.35   # forward scatter -> glow around the fire
    tree.links.new(scatter.outputs["Volume"], out.inputs["Volume"])
    obj.data.materials.append(mat)
    return density


def build_lighting(ctx) -> None:
    """Sky, sun, emissive-block lights and fog, all from `ctx.preset`."""
    _sky(ctx)
    _sun(ctx)
    lights, emissive = _block_lights(ctx)
    density = _fog(ctx)

    logger.info(
        "lighting: sun_elev=%.3f strength=%.1f | %d point lights for %d emissive blocks | fog=%.4f",
        ctx.preset["sun_elevation_rad"], ctx.preset["sun_strength"], lights, emissive, density,
    )
