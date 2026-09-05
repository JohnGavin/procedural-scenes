"""Camera placement, focal length, and depth-of-field.

Responsible for building a Blender camera at `ctx.preset["camera_position"]`
looking at `ctx.preset["camera_target"]` (both three.js-named `(x, y, z)` —
apply the `(x, z, y)` axis remap documented in `city.layout`'s
`COORDINATE_NOTE` before setting `obj.location`), with focal length
`ctx.preset["camera_focal_length_mm"]`. When `ctx.preset["dof_enabled"]` is
True, enable depth-of-field with `ctx.preset["dof_fstop"]` and either an
explicit `ctx.preset["dof_focus_distance"]` or, when that key is `None`,
autofocus by computing the distance from `camera_position` to
`camera_target`. This is one of the things this rebuild should show off that
three.js's `OrbitControls` pinhole camera cannot — real physically-based
depth-of-field (see the `tiltshift` preset).

Also provides `build_turntable()`, a separate helper (not called from
`build_camera`) that orbits the built camera around `camera_target` for a
render.py-driven animation.
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

CAMERA_OBJECT_NAME = "CityCamera"
CAMERA_DATA_NAME = "CityCameraData"
TURNTABLE_PIVOT_NAME = "CityTurntablePivot"

# lighting.py's sun-lamp/world object names, duplicated here as plain string
# constants rather than imported. camera.py must stay usable (and, for
# build_camera, useful) even if build_lighting(ctx) hasn't run yet or
# failed, so build_turntable() only *looks up* these names at call time and
# skips the sun-animation extra (with a warning) if they aren't found.
_SUN_OBJECT_NAME = "CitySun"


def _three_to_blender(xyz: tuple[float, float, float]):
    """Apply the axis remap documented in `city.layout`'s `COORDINATE_NOTE`:
    three.js `(x, y, z)` -> Blender `(x, z, y)`."""
    import mathutils

    x, y, z = xyz
    return mathutils.Vector((x, z, y))


def _get_or_create_camera(ctx):
    import bpy

    cam_data = bpy.data.cameras.get(CAMERA_DATA_NAME)
    if cam_data is None:
        cam_data = bpy.data.cameras.new(CAMERA_DATA_NAME)

    cam_obj = bpy.data.objects.get(CAMERA_OBJECT_NAME)
    if cam_obj is None:
        cam_obj = bpy.data.objects.new(CAMERA_OBJECT_NAME, cam_data)
        bpy.context.scene.collection.objects.link(cam_obj)
    else:
        cam_obj.data = cam_data  # reuse the existing object across reruns — never a second camera
        # A previous build_turntable() call may have parented the camera to
        # the orbit pivot; rebuilding the camera from a preset should start
        # from a plain, unparented placement.
        if cam_obj.parent is not None:
            cam_obj.parent = None
            cam_obj.matrix_parent_inverse.identity()

    bpy.context.scene.camera = cam_obj
    return cam_obj


def build_camera(ctx) -> None:
    """Build the scene camera from `ctx.preset`.

    Args:
        ctx: the `BuildContext` from `build_city.py`.
    """
    preset = ctx.preset
    cam_obj = _get_or_create_camera(ctx)
    cam_data = cam_obj.data

    position = _three_to_blender(preset["camera_position"])
    target = _three_to_blender(preset["camera_target"])

    cam_obj.location = position

    # Aim the camera by computing its rotation directly from the
    # position -> target vector rather than eyeballing euler angles. A
    # Blender camera's forward direction is its local -Z axis with +Y as
    # up, so `to_track_quat('-Z', 'Y')` gives the exact quaternion that
    # points the lens at `target`.
    direction = target - position
    if direction.length == 0:
        logger.warning("camera position equals target — leaving default orientation")
    else:
        cam_obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

    cam_data.lens = preset["camera_focal_length_mm"]

    cam_data.dof.use_dof = preset["dof_enabled"]
    if preset["dof_enabled"]:
        cam_data.dof.aperture_fstop = preset["dof_fstop"]
        focus_distance = preset["dof_focus_distance"]
        if focus_distance is None:
            # "Autofocus on target" — three.js's pinhole camera has no
            # notion of a focus plane at all; this distance is what racks
            # the `dusk` preset's shallow depth of field onto the city
            # instead of blurring it uniformly regardless of depth.
            focus_distance = direction.length
        cam_data.dof.focus_object = None
        cam_data.dof.focus_distance = focus_distance

    logger.info(
        "camera: pos=%s target=%s lens=%.1fmm dof=%s",
        tuple(round(v, 1) for v in position),
        tuple(round(v, 1) for v in target),
        cam_data.lens,
        preset["dof_enabled"],
    )


def build_turntable(
    ctx,
    frames: int = 240,
    animate_sun: bool = False,
    sun_elevation_arc_rad: float = math.radians(20.0),
) -> None:
    """Orbit the camera 360 degrees around `ctx.preset["camera_target"]`.

    Keyframes a pivot Empty's Z rotation from 0 at frame 1 to a full turn
    (2*pi) at frame `frames`, linear interpolation for constant angular
    velocity, then parents the already-built camera to that pivot
    (preserving its current world position/orientation) so it swings around
    the target while continuing to look at it. Does NOT set
    `scene.frame_start`/`scene.frame_end` and does not render anything — the
    caller (`render.py`) owns the frame range and the render/animation loop;
    this only prepares the animation data.

    Must be called AFTER `build_camera(ctx)` — it reparents the camera
    `build_camera` already created and aimed. Idempotent: reruns reuse the
    same pivot object and replace its keyframes rather than stacking more.

    Args:
        ctx: the `BuildContext` from `build_city.py`.
        frames: length of the turntable in frames (default 240, i.e. 10
            seconds at 24fps for one full revolution).
        animate_sun: when True, also sweeps the Nishita sky's sun elevation
            (and the matching sun-lamp rotation, so shadows stay consistent
            with the sky) through `sun_elevation_arc_rad` over the same
            frame range, for a simple day-progression look alongside the
            orbit. Requires `build_lighting(ctx)` to have already run;
            silently skipped, with a log warning, if the sun/sky can't be
            found — camera.py must keep working even when lighting.py
            hasn't run yet.
        sun_elevation_arc_rad: total elevation sweep in radians when
            `animate_sun` is True (default 20 degrees).
    """
    import bpy
    import mathutils

    cam_obj = bpy.data.objects.get(CAMERA_OBJECT_NAME)
    if cam_obj is None:
        raise RuntimeError("build_turntable() called before build_camera() — no camera to orbit")

    target = _three_to_blender(ctx.preset["camera_target"])

    pivot = bpy.data.objects.get(TURNTABLE_PIVOT_NAME)
    if pivot is None:
        pivot = bpy.data.objects.new(TURNTABLE_PIVOT_NAME, None)
        bpy.context.scene.collection.objects.link(pivot)
    if pivot.animation_data:
        pivot.animation_data_clear()
    pivot.rotation_euler = (0.0, 0.0, 0.0)
    pivot.location = target
    bpy.context.view_layer.update()  # force matrix_world to reflect the location set above

    # Re-parent while preserving the camera's current world transform, so
    # the orbit starts exactly where build_camera() aimed it.
    cam_obj.parent = pivot
    cam_obj.matrix_parent_inverse = pivot.matrix_world.inverted()

    pivot.rotation_euler.z = 0.0
    pivot.keyframe_insert(data_path="rotation_euler", index=2, frame=1)
    pivot.rotation_euler.z = 2.0 * math.pi
    pivot.keyframe_insert(data_path="rotation_euler", index=2, frame=frames)
    for fcurve in pivot.animation_data.action.fcurves:
        for kp in fcurve.keyframe_points:
            kp.interpolation = "LINEAR"

    if not animate_sun:
        return

    sun_obj = bpy.data.objects.get(_SUN_OBJECT_NAME)
    world = bpy.context.scene.world
    sky_node = None
    if world is not None and world.use_nodes:
        sky_node = next(
            (n for n in world.node_tree.nodes if n.bl_idname == "ShaderNodeTexSky"), None
        )
    if sun_obj is None or sky_node is None:
        logger.warning(
            "build_turntable: animate_sun=True but no sun lamp / Nishita sky node found "
            "(has build_lighting(ctx) run yet?) — skipping sun animation"
        )
        return

    if sun_obj.animation_data:
        sun_obj.animation_data_clear()

    elevation_start = sky_node.sun_elevation
    elevation_end = elevation_start + sun_elevation_arc_rad
    rotation = sky_node.sun_rotation

    for frame, elevation in ((1, elevation_start), (frames, elevation_end)):
        sky_node.sun_elevation = elevation
        sky_node.keyframe_insert(data_path="sun_elevation", frame=frame)

        direction_to_sun = mathutils.Vector(
            (
                math.cos(rotation) * math.cos(elevation),
                math.sin(rotation) * math.cos(elevation),
                math.sin(elevation),
            )
        )
        sun_obj.rotation_euler = direction_to_sun.to_track_quat("Z", "Y").to_euler()
        sun_obj.keyframe_insert(data_path="rotation_euler", frame=frame)

    node_tree_anim = world.node_tree.animation_data
    if node_tree_anim and node_tree_anim.action:
        for fcurve in node_tree_anim.action.fcurves:
            if fcurve.data_path.endswith("sun_elevation"):
                for kp in fcurve.keyframe_points:
                    kp.interpolation = "LINEAR"
    if sun_obj.animation_data and sun_obj.animation_data.action:
        for fcurve in sun_obj.animation_data.action.fcurves:
            if fcurve.data_path == "rotation_euler":
                for kp in fcurve.keyframe_points:
                    kp.interpolation = "LINEAR"
