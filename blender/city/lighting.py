"""Sun, sky (Nishita), volumetrics — everything driven by `ctx.preset`.

Responsible for building a Blender sun lamp positioned from
`ctx.preset["sun_elevation_rad"]`/`["sun_rotation_rad"]`/`["sun_strength"]`;
a Nishita sky world shader driven by `ctx.preset["sky_air_density"]`/
`["sky_dust_density"]`/`["sky_ozone_density"]` (must use the SAME
elevation/rotation as the sun lamp so sky and shadows agree, mirroring how
`buildings.html` derives both the `Sky` object and the `DirectionalLight`
from one shared `sunDir`); and a volume scatter world/object driven by
`ctx.preset["volumetric_density"]`. This is one of the things this rebuild
should show off that three.js's `Sky.js` approximation cannot — real
physically-based Nishita atmospheric scattering plus volumetric god-rays.

Produces no `ctx.materials` keys (works on world/lamp data, not
`ctx.materials`), but MUST read `ctx.preset["window_emission"]` /
`["window_emission_strength"]` only indirectly — the actual window emission
material lives in `ctx.materials["window_emission"]`, built by materials.py;
lighting.py just decides overall exposure/scene brightness to match.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

SUN_OBJECT_NAME = "CitySun"
SUN_DATA_NAME = "CitySunData"
WORLD_NAME = "CityWorld"

SUN_ANGULAR_DIAMETER_RAD = math.radians(1.5)
"""Angular diameter of the sun disc as seen from the ground. The real sun
subtends about 0.53 deg; we widen it a little (three.js's DirectionalLight
in buildings.html has zero size, so its shadows are razor-sharp everywhere)
so Cycles renders a soft, physically-motivated penumbra at shadow edges
instead — a look three.js's shadow-map approach can only fake."""

NIGHT_FILL_STRENGTH = 0.35
NIGHT_FILL_COLOR = (0.05, 0.07, 0.11)
"""Faint, cool ambient mixed into the world background only when the sun is
below the horizon (see `_build_world_shader`). Deliberately far dimmer than
the window-emission strength used by the `night` preset — the point of that
preset is that the buildings' lit windows carry the scene, this just keeps
roads/terrain/the volume itself from disappearing into pure black."""


def _sun_direction(elevation_rad: float, rotation_rad: float):
    """Unit vector (Blender world space, Z-up) pointing FROM the origin
    TOWARD the sun, using the same elevation/rotation convention as Cycles'
    Nishita sky texture (`ShaderNodeTexSky.sun_elevation` / `.sun_rotation`):
    elevation is the angle above the horizon, rotation is azimuth measured
    from +X toward +Y."""
    import mathutils

    return mathutils.Vector(
        (
            math.cos(rotation_rad) * math.cos(elevation_rad),
            math.sin(rotation_rad) * math.cos(elevation_rad),
            math.sin(elevation_rad),
        )
    )


def _build_sun_lamp(ctx) -> None:
    """Create/update the sun lamp so its direction matches the Nishita sky's
    sun exactly — same elevation/rotation, read from the same preset keys —
    so cast shadows always agree with the sky's bright spot, the same
    invariant buildings.html keeps by deriving both from one `sunDir`."""
    import bpy

    preset = ctx.preset
    elevation = preset["sun_elevation_rad"]
    rotation = preset["sun_rotation_rad"]

    light_data = bpy.data.lights.get(SUN_DATA_NAME)
    if light_data is None or light_data.type != "SUN":
        light_data = bpy.data.lights.new(SUN_DATA_NAME, type="SUN")
    light_data.energy = preset["sun_strength"]
    light_data.angle = SUN_ANGULAR_DIAMETER_RAD

    sun_obj = bpy.data.objects.get(SUN_OBJECT_NAME)
    if sun_obj is None:
        sun_obj = bpy.data.objects.new(SUN_OBJECT_NAME, light_data)
        bpy.context.scene.collection.objects.link(sun_obj)
    else:
        sun_obj.data = light_data  # reuse existing object across reruns — never a second sun

    # A Sun object's rays travel along its local -Z axis (Blender's default
    # lamp/camera forward convention), so we want the local +Z axis to point
    # AT the sun — then -Z automatically points from the sun toward the
    # ground, which is the direction shadows are cast.
    direction_to_sun = _sun_direction(elevation, rotation)
    sun_obj.rotation_euler = direction_to_sun.to_track_quat("Z", "Y").to_euler()
    sun_obj.location = (0.0, 0.0, 0.0)  # a Sun's location never affects its lighting; keep it at the origin


def _build_world_shader(ctx) -> None:
    """Nishita sky (physically-based atmospheric scattering — drives the
    world background AND doubles as the environment light for GI/glass
    reflections, unlike buildings.html's `Sky.js`, which is only baked once
    into a static PMREM map) plus a world volume for haze/god-rays, plus a
    faint fill for the `night` preset.

    Sole owner of the `World` datablock's node tree: rebuilds it from
    scratch on every call, which makes this idempotent without needing to
    track which nodes came from a previous run.
    """
    import bpy

    preset = ctx.preset
    world = bpy.data.worlds.get(WORLD_NAME)
    if world is None:
        world = bpy.data.worlds.new(WORLD_NAME)
    bpy.context.scene.world = world
    world.use_nodes = True

    tree = world.node_tree
    tree.nodes.clear()

    nodes = tree.nodes
    links = tree.links

    output = nodes.new("ShaderNodeOutputWorld")
    output.location = (600, 0)

    sky_tex = nodes.new("ShaderNodeTexSky")
    sky_tex.location = (-200, 200)
    # Blender 5.x retired the "NISHITA" sky_type enum and split that model into
    # SINGLE_SCATTERING / MULTIPLE_SCATTERING. MULTIPLE_SCATTERING is the direct
    # successor — the same physically-based atmospheric scattering, now also
    # accounting for light scattered more than once, which is what gives a
    # believable horizon glow at low sun. Fall back through the older names so
    # this module still runs on a 4.x Blender.
    for sky_type in ("MULTIPLE_SCATTERING", "NISHITA", "HOSEK_WILKIE"):
        try:
            sky_tex.sky_type = sky_type
            break
        except TypeError:
            continue
    sky_tex.sun_elevation = preset["sun_elevation_rad"]
    sky_tex.sun_rotation = preset["sun_rotation_rad"]
    sky_tex.air_density = preset["sky_air_density"]
    # `dust_density` was renamed `aerosol_density` in 5.x (Mie scattering).
    if hasattr(sky_tex, "aerosol_density"):
        sky_tex.aerosol_density = preset["sky_dust_density"]
    else:
        sky_tex.dust_density = preset["sky_dust_density"]
    sky_tex.ozone_density = preset["sky_ozone_density"]

    sky_background = nodes.new("ShaderNodeBackground")
    sky_background.location = (200, 200)
    links.new(sky_tex.outputs["Color"], sky_background.inputs["Color"])

    surface_shader = sky_background
    if preset["sun_elevation_rad"] < 0:
        # Sun below the horizon: Nishita alone renders near-black here, and
        # the `night` preset is meant to read almost entirely by the
        # buildings' emissive windows (materials.py owns that material; we
        # only decide ambient exposure). Add Shader sums this fill on top of
        # the (already near-zero) sky background without needing a mix
        # factor — it stays far dimmer than window emission by construction
        # (see NIGHT_FILL_STRENGTH), so it can't wash the scene out.
        fill_background = nodes.new("ShaderNodeBackground")
        fill_background.location = (200, -50)
        fill_background.inputs["Color"].default_value = (*NIGHT_FILL_COLOR, 1.0)
        fill_background.inputs["Strength"].default_value = NIGHT_FILL_STRENGTH

        add_shader = nodes.new("ShaderNodeAddShader")
        add_shader.location = (400, 100)
        links.new(sky_background.outputs["Background"], add_shader.inputs[0])
        links.new(fill_background.outputs["Background"], add_shader.inputs[1])
        surface_shader = add_shader

    links.new(surface_shader.outputs[0], output.inputs["Surface"])

    # NOTE: deliberately NO volume on the World's Volume socket.
    #
    # The obvious-looking move is to hang a Volume Scatter off the World and let
    # the medium "fill the scene" with no box to size. That renders pure black,
    # and not subtly — measured mean pixel 0.00033 against 0.968 for the same
    # scene without it. A World volume is UNBOUNDED: every camera ray that does
    # not hit geometry travels to infinity through the medium, so its optical
    # depth is unbounded too and it extinguishes completely. No density is small
    # enough to escape that, because the path length is infinite either way.
    #
    # The atmosphere therefore lives in a bounded domain object instead —
    # see `_build_atmosphere_domain`.


#: Half-extent of the atmosphere box in x/y, and its top in z (Blender units).
#: Covers the 1600-unit ground plane with margin, and reaches above the highest
#: preset camera (tiltshift sits at z=220) so the camera is always INSIDE the
#: medium — god-rays need the camera in the haze, not looking at it from outside.
ATMOSPHERE_HALF_XY = 900.0
ATMOSPHERE_TOP_Z = 320.0
ATMOSPHERE_BASE_Z = -5.0

#: Scale applied to `preset["volumetric_density"]` before it reaches the domain.
#:
#: The preset numbers (0.006 noon .. 0.02 night) were written against a World
#: volume, where density is a free knob because the medium is infinite anyway.
#: In a bounded domain the number becomes a real per-unit extinction coefficient,
#: and 0.006 across the 1800-unit box is an optical depth near 11 — everything
#: fades to flat milk. Calibrated instead against the distance that matters: the
#: cameras sit ~340 units from the city centre, and optical depth ~0.5 over that
#: span gives visible aerial perspective while keeping the towers readable.
#:   0.006 * 0.25 * 340 ~= 0.51
#: Kept as a scale rather than edited into the presets so `layout.py` stays the
#: single shared contract across all seven modules.
ATMOSPHERE_DENSITY_SCALE = 0.25


def _build_atmosphere_domain(ctx) -> None:
    """Bounded volume-scatter box — haze and god-rays, with no three.js analogue.

    Bounded rather than a World volume for the reason documented in
    `_build_world_shader`: an unbounded medium gives every sky-bound ray infinite
    optical depth and renders black. A box gives each ray a finite path through
    the medium, so `volumetric_density` behaves like a real per-unit density and
    the horizon fades to aerial perspective instead of to nothing.

    The surface shader is left unconnected on purpose. A material with only its
    Volume socket linked has no surface at all in Cycles, so the box never
    appears as geometry — it only bounds the medium.
    """
    import bpy

    density = ctx.preset["volumetric_density"] * ATMOSPHERE_DENSITY_SCALE

    for stale in ("CityAtmosphere",):
        obj = bpy.data.objects.get(stale)
        if obj is not None:
            bpy.data.objects.remove(obj, do_unlink=True)

    mesh = bpy.data.meshes.new("CityAtmosphere")
    half = ATMOSPHERE_HALF_XY
    z0, z1 = ATMOSPHERE_BASE_Z, ATMOSPHERE_TOP_Z
    verts = [
        (-half, -half, z0), (half, -half, z0), (half, half, z0), (-half, half, z0),
        (-half, -half, z1), (half, -half, z1), (half, half, z1), (-half, half, z1),
    ]
    faces = [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
    mesh.from_pydata(verts, [], faces)
    mesh.update()

    obj = bpy.data.objects.new("CityAtmosphere", mesh)
    bpy.context.scene.collection.objects.link(obj)
    # Wireframe in the viewport. The box has no surface shader so it is already
    # invisible to Cycles, but in the GUI's Solid shading it would draw as an
    # opaque 1800-unit cube wrapped around the city, hiding everything. Wire
    # keeps it selectable and honest about being there without blocking the view;
    # Rendered shading still shows the volumetrics normally.
    obj.display_type = "WIRE"
    obj.hide_select = True

    mat = bpy.data.materials.get("city_atmosphere") or bpy.data.materials.new("city_atmosphere")
    mat.use_nodes = True
    tree = mat.node_tree
    tree.nodes.clear()
    output = tree.nodes.new("ShaderNodeOutputMaterial")
    output.location = (300, 0)
    scatter = tree.nodes.new("ShaderNodeVolumeScatter")
    scatter.location = (0, 0)
    scatter.inputs["Density"].default_value = density
    # Forward-scattering, so the medium brightens sharply looking toward the sun
    # — that anisotropy is what actually reads as god-rays between the towers.
    scatter.inputs["Anisotropy"].default_value = 0.3
    tree.links.new(scatter.outputs["Volume"], output.inputs["Volume"])
    obj.data.materials.append(mat)

    logger.info(
        "lighting: atmosphere domain %.0f x %.0f x %.0f, density=%.4f",
        half * 2, half * 2, z1 - z0, density,
    )


def build_lighting(ctx) -> None:
    """Build sun, sky, and volumetrics from `ctx.preset`.

    Args:
        ctx: the `BuildContext` from `build_city.py`.
    """
    _build_world_shader(ctx)
    _build_sun_lamp(ctx)
    _build_atmosphere_domain(ctx)
    logger.info(
        "lighting: sun_elevation=%.4f sun_rotation=%.4f sun_strength=%.2f volumetric_density=%.4f",
        ctx.preset["sun_elevation_rad"],
        ctx.preset["sun_rotation_rad"],
        ctx.preset["sun_strength"],
        ctx.preset["volumetric_density"],
    )
