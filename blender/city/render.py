"""Cycles configuration, colour management, compositing, and the render call.

Two stage entry points, plus one opt-in extra:

- `configure(ctx)` — engine, compute device, sampling, denoising, colour
  management, and a small compositor graph. Idempotent.
- `render(ctx)`    — render a still into `ctx.out_dir`.
- `render_animation(ctx, frames=...)` — the turntable path, deliberately
  **not** wired into the default flow (see "Why animation is opt-in" below).

The three.js scene rasterises with one sample per pixel and fakes everything
else; this module's job is the opposite trade. What it buys, concretely:
path-traced global illumination and soft shadows instead of a shadow map, a
real film response curve (AgX) instead of raw sRGB clipping, and an optical
glare model so the `dusk` / `night` window emission blooms the way a lens
actually blooms rather than the way a screen-space post filter guesses.

Everything version-sensitive here (compute-device backends, view transforms,
the Blender 5.x compositor datablock move, glare node modes) is probed
against the live runtime and logged, never assumed. Blender's Python API
changes shape across 4.x/5.x and a wrong assumption in this module fails
silently as a black frame.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any, Sequence

logger = logging.getLogger(__name__)


# ===== tuning knobs ==========================================================

ADAPTIVE_THRESHOLD: float = 0.01
"""Cycles stops refining a pixel once its noise estimate drops below this.
Together with OpenImageDenoise it is what makes a 128-sample render of this
scene usable — without both, the same frame needs several hundred samples."""

GLARE_THRESHOLD: float = 1.0
GLARE_MIX: float = -0.55
"""Glare `Mix` runs -1 (image only) .. +1 (glare only). Just off -1 gives a
lens bloom you notice on the emissive windows and nowhere else."""

TURNTABLE_DEFAULT_FRAMES: int = 240

_ENV_ANIMATE = "CITY_ANIMATE"
_ENV_TURNTABLE_FRAMES = "CITY_TURNTABLE_FRAMES"


# ===== small runtime-probing helpers ========================================


def _enum_values(owner: Any, prop: str) -> list[str]:
    """The enum identifiers a property actually accepts on this build.

    Used instead of hardcoding e.g. `'AgX'` — the identifier exists in 4.x,
    but this module should not be the thing that breaks when it is renamed.
    """
    try:
        return [item.identifier for item in owner.bl_rna.properties[prop].enum_items]
    except (KeyError, AttributeError):
        return []


def _set_enum(owner: Any, prop: str, preferred: Sequence[str], what: str) -> str | None:
    """Set `prop` to the first value in `preferred` this build accepts.

    Deliberately does NOT gate on `_enum_values()`. Several of the enums we care
    about — `view_transform`, `look`, `compute_device_type` — are populated
    dynamically at runtime (from the OCIO config, from the compiled GPU
    backends), so static RNA introspection reports `['NONE']` even when 'AgX'
    assigns perfectly well. Gating on that list silently left this scene on the
    default view transform. Just attempt the assignment: a rejected value raises
    TypeError, which is the only trustworthy signal here.
    """
    for value in preferred:
        try:
            setattr(owner, prop, value)
        except (TypeError, AttributeError):
            # TypeError  = value rejected by the enum.
            # AttributeError = the property does not exist on this build at all
            #                  (e.g. Glare's `glare_type`, which became an input
            #                  socket in 5.x). Both mean "try the next one".
            continue
        logger.info("render: %s = %s", what, value)
        return value
    logger.warning("render: none of %s accepted for %s; leaving default (introspection saw: %s)",
                   list(preferred), what, _enum_values(owner, prop))
    return None


def _truthy(value: str | None) -> bool:
    return bool(value) and value.strip().lower() not in {"0", "false", "no", ""}


# ===== compute device =======================================================


def _cycles_preferences():
    import bpy

    addons = bpy.context.preferences.addons
    for key in ("cycles", "bl_ext.blender_org.cycles", "bl_ext.system.cycles"):
        addon = addons.get(key)
        if addon is not None and getattr(addon, "preferences", None) is not None:
            return addon.preferences
    logger.warning("render: cycles addon preferences not found; keys=%s", sorted(addons.keys()))
    return None


def configure_device(scene) -> str:
    """Pick and enable the best available Cycles compute device.

    This is the one thing about the machine we genuinely cannot know until we
    ask it: whether this Blender build ships a working Cycles GPU backend
    (METAL on Apple silicon) or is CPU-only. Everything is logged at INFO —
    the backend list, the device list, and the choice — because getting this
    wrong silently is the difference between a render that takes seconds and
    one that takes hours.

    Returns the `scene.cycles.device` value that was set: `'GPU'` or `'CPU'`.
    """
    import bpy

    logger.info("render: blender %s", ".".join(str(v) for v in bpy.app.version))

    prefs = _cycles_preferences()
    if prefs is None:
        scene.cycles.device = "CPU"
        logger.info("render: device=CPU (no cycles preferences)")
        return "CPU"

    # `compute_device_type` is a DYNAMIC enum — it is populated at runtime from
    # the backends this build actually supports, so static RNA introspection
    # (`_enum_values`) returns [] and would silently strand us on CPU even on a
    # machine with a working GPU. `get_device_types(context)` is the API that
    # reports the real list; keep the static read only as a last-ditch fallback.
    backends: list[str] = []
    get_types = getattr(prefs, "get_device_types", None)
    if callable(get_types):
        try:
            backends = [entry[0] for entry in get_types(bpy.context)]
        except Exception as exc:  # noqa: BLE001 — advisory only
            logger.warning("render: get_device_types failed (%s)", exc)
    if not backends:
        backends = _enum_values(prefs, "compute_device_type")
    logger.info("render: cycles compute backends available = %s", backends)

    # 'NONE' is the CPU-only sentinel; anything else is a GPU backend. METAL
    # first because this is Apple silicon, then the portable fallbacks.
    for backend in ("METAL", "OPTIX", "CUDA", "HIP", "ONEAPI"):
        if backend not in backends:
            continue
        try:
            prefs.compute_device_type = backend
        except TypeError:
            continue

        # `get_devices()` is the older spelling, `refresh_devices()` the newer;
        # both exist on some versions, neither is guaranteed.
        for refresh in ("refresh_devices", "get_devices"):
            fn = getattr(prefs, refresh, None)
            if callable(fn):
                try:
                    fn()
                    break
                except Exception as exc:  # noqa: BLE001 — advisory only
                    logger.debug("render: %s() failed: %s", refresh, exc)

        devices = list(getattr(prefs, "devices", []))
        for dev in devices:
            logger.info("render:   device %-8s %s", dev.type, dev.name)

        usable = [d for d in devices if d.type == backend]
        if not usable:
            logger.info("render: backend %s exposes no devices; trying next", backend)
            continue

        for dev in devices:
            # Enable the GPU devices; leave the CPU device off so Cycles does
            # not split tiles across a much slower worker.
            dev.use = dev.type == backend

        scene.cycles.device = "GPU"
        logger.info(
            "render: device=GPU backend=%s enabled=%s",
            backend,
            [d.name for d in usable],
        )
        return "GPU"

    scene.cycles.device = "CPU"
    logger.info("render: device=CPU (no usable GPU backend; backends seen = %s)", backends)
    return "CPU"


# ===== compositor ===========================================================


def _compositor_tree(scene):
    """Return the scene's compositor node tree, creating it if needed.

    Blender 5.x moved the scene compositor onto a `compositing_node_group`
    datablock; 4.x used `scene.use_nodes` + `scene.node_tree`. Try the new
    shape first, fall back to the old, and log which one this build used.
    """
    import bpy

    if hasattr(scene, "compositing_node_group"):
        tree = scene.compositing_node_group
        if tree is None:
            tree = bpy.data.node_groups.new("city_compositor", "CompositorNodeTree")
            scene.compositing_node_group = tree
        logger.info("render: compositor via scene.compositing_node_group (5.x API)")
        return tree, "new"

    if hasattr(scene, "use_nodes"):
        scene.use_nodes = True
        logger.info("render: compositor via scene.node_tree (4.x API)")
        return scene.node_tree, "old"

    logger.warning("render: no compositor API found; skipping glare")
    return None, None


def configure_compositor(scene) -> bool:
    """Render layers -> Glare -> Composite. Returns True if it was built.

    The glare is the point: the `dusk` and `night` presets light the city
    almost entirely with emissive windows, and an emissive surface that does
    not bloom reads as a flat decal. Kept subtle — a lens artefact, not a
    filter.
    """
    tree, api = _compositor_tree(scene)
    if tree is None:
        return False

    tree.nodes.clear()

    if api == "new":
        # The source MUST be a Render Layers node, not NodeGroupInput.
        #
        # A scene compositing node group looks like it should take the rendered
        # frame on its group input — it does not. Blender never feeds that input,
        # so a NodeGroupInput -> NodeGroupOutput graph outputs an empty image and
        # the render comes out black with zero alpha, silently, whatever else the
        # scene is doing. Measured on this build: group-input passthrough gives
        # mean 0.00033 / alpha 0.000, Render Layers gives 0.76122 / alpha 1.000.
        #
        # Note this bites even with `scene.render.use_compositing = False` —
        # in 5.x an assigned `compositing_node_group` is honoured regardless.
        src = tree.nodes.new("CompositorNodeRLayers")
        dst = tree.nodes.new("NodeGroupOutput")
        # Only the OUTPUT socket is needed; the group has no meaningful input.
        if not any(i.in_out == "OUTPUT" for i in tree.interface.items_tree):
            tree.interface.new_socket(name="Image", in_out="OUTPUT", socket_type="NodeSocketColor")
        src_out, dst_in = src.outputs["Image"], dst.inputs[0]
    else:
        src = tree.nodes.new("CompositorNodeRLayers")
        dst = tree.nodes.new("CompositorNodeComposite")
        src_out, dst_in = src.outputs["Image"], dst.inputs["Image"]

    src.location = (-400, 0)
    dst.location = (400, 0)

    glare = tree.nodes.new("CompositorNodeGlare")
    glare.location = (0, 0)
    # 'BLOOM' landed in 4.4 and is the physically-motivated one; FOG_GLOW is
    # the long-standing fallback. Streaks would be too stylised here.
    _set_enum(glare, "glare_type", ("BLOOM", "FOG_GLOW", "GHOSTS"), "glare type")
    _set_enum(glare, "quality", ("HIGH", "MEDIUM", "LOW"), "glare quality")
    for prop, value in (("threshold", GLARE_THRESHOLD), ("mix", GLARE_MIX), ("size", 7)):
        if hasattr(glare, prop):
            setattr(glare, prop, value)
    # 5.x moved essentially every Glare setting from RNA property to input
    # socket, including the glare mode itself ("Type", a menu socket taking the
    # UI label). Setting these is what actually makes the emissive windows bloom
    # in the dusk/night presets; without it the compositor is a no-op passthrough.
    for name, value in (
        ("Type", "Bloom"),
        ("Quality", "High"),
        ("Threshold", GLARE_THRESHOLD),
        ("Strength", 0.25),
        ("Size", 7),
    ):
        sock = glare.inputs.get(name)
        if sock is None:
            continue
        try:
            sock.default_value = value
        except (TypeError, AttributeError) as exc:
            logger.debug("render: glare socket %s not set (%s)", name, exc)

    tree.links.new(src_out, glare.inputs[0])
    tree.links.new(glare.outputs[0], dst_in)

    if hasattr(scene.render, "use_compositing"):
        scene.render.use_compositing = True
    return True


# ===== stage entry points ===================================================


def configure(ctx) -> None:
    """Configure Cycles, colour management and compositing from `ctx.preset`.

    Args:
        ctx: the `BuildContext` from `build_city.py`. Reads
            `ctx.preset["samples"]` and `ctx.preset["resolution"]`, both of
            which `build_city._resolve_preset()` has already merged with any
            `--samples` / `--resolution` CLI override, so this function never
            needs to look at argv.
    """
    import bpy

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"

    device = configure_device(scene)

    samples = int(ctx.preset["samples"])
    width, height = ctx.preset["resolution"]
    scene.cycles.samples = samples
    scene.render.resolution_x = int(width)
    scene.render.resolution_y = int(height)
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"

    # Adaptive sampling + OpenImageDenoise are what make the sample counts in
    # layout.PRESETS (128-320) enough. Adaptive stops spending rays on pixels
    # that have already converged; OIDN cleans up what is left. Drop either
    # and the same frames need roughly an order of magnitude more samples.
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = ADAPTIVE_THRESHOLD
    scene.cycles.adaptive_min_samples = max(16, samples // 16)
    scene.cycles.use_denoising = True
    _set_enum(scene.cycles, "denoiser", ("OPENIMAGEDENOISE", "OPTIX"), "denoiser")
    _set_enum(scene.cycles, "denoising_input_passes", ("RGB_ALBEDO_NORMAL", "RGB_ALBEDO", "RGB"),
              "denoising passes")
    if hasattr(scene.cycles, "denoising_use_gpu"):
        scene.cycles.denoising_use_gpu = device == "GPU"

    # Light-path limits: this scene is architectural, not a caustics test.
    scene.cycles.max_bounces = 8
    scene.cycles.diffuse_bounces = 4
    scene.cycles.glossy_bounces = 4
    scene.cycles.transmission_bounces = 8
    scene.cycles.transparent_max_bounces = 8
    scene.cycles.volume_bounces = 2
    if hasattr(scene.cycles, "use_fast_gi"):
        scene.cycles.use_fast_gi = False

    # Background renders get one shot at the scene, so caching the BVH across
    # frames buys nothing and costs memory. The turntable path turns it on.
    scene.render.use_persistent_data = False
    for prop, value in (("tile_size", 2048), ("use_auto_tile", True)):
        if hasattr(scene.cycles, prop):
            setattr(scene.cycles, prop, value)
    if hasattr(scene.render, "threads_mode"):
        scene.render.threads_mode = "AUTO"

    # AgX rolls highlights off instead of clipping them, which matters when
    # the brightest thing in frame is an emissive window.
    _set_enum(scene.view_settings, "view_transform", ("AgX", "Filmic", "Standard"), "view transform")
    _set_enum(scene.view_settings, "look", ("AgX - Base Contrast", "Base Contrast", "None"),
              "look")

    # The glare is a nicety; an unexpected compositor API should degrade to
    # "no bloom", never to "no render".
    try:
        configure_compositor(scene)
    except Exception as exc:  # noqa: BLE001
        logger.warning("render: compositor setup failed (%s: %s); continuing without glare",
                       type(exc).__name__, exc)

    logger.info(
        "render: configured cycles device=%s samples=%d adaptive<=%.3f res=%dx%d",
        device, samples, ADAPTIVE_THRESHOLD, width, height,
    )


def _output_path(ctx, suffix: str = "") -> Path:
    """Output filename for this render.

    The prefix is read off the context rather than hardcoded to "city_". This
    module is shared: `build_cabin.py` reuses it wholesale, and with a fixed
    prefix the cabin renders silently overwrote the city's `city_dusk.png` and
    `city_night.png` — same directory, same names, no warning. Defaults to
    "city" so the original pipeline is unchanged.
    """
    out_dir = Path(ctx.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = getattr(ctx, "output_prefix", "city")
    return out_dir / f"{prefix}_{ctx.preset_name}{suffix}.png"


def render(ctx) -> Path:
    """Render a still (or, when opted in, the turntable) and report timing.

    Why animation is opt-in: `layout.PRESETS` asks for 128-320 samples at
    1920x1080. One frame is a coffee; 240 of them is an afternoon. So the
    default is always the still, and the turntable is behind the
    `CITY_ANIMATE` environment variable — an env var rather than a CLI flag
    because `build_city.py`'s argument parser is owned by another module and
    this stage should not need to change it.

    Set `CITY_ANIMATE=1` to render the turntable, and optionally
    `CITY_TURNTABLE_FRAMES=<n>` to shorten it.

    Returns the path of the still that was written (or the output directory
    when an animation was rendered).
    """
    if _truthy(os.environ.get(_ENV_ANIMATE)):
        frames = int(os.environ.get(_ENV_TURNTABLE_FRAMES, TURNTABLE_DEFAULT_FRAMES))
        return render_animation(ctx, frames=frames)

    import bpy

    scene = bpy.context.scene
    path = _output_path(ctx)
    scene.render.filepath = str(path)

    started = time.perf_counter()
    bpy.ops.render.render(write_still=True)
    elapsed = time.perf_counter() - started

    size = path.stat().st_size if path.exists() else 0
    logger.info(
        "render: wrote %s (%d bytes) in %.1fs — %s, %d samples, %dx%d",
        path, size, elapsed, scene.cycles.device, scene.cycles.samples,
        scene.render.resolution_x, scene.render.resolution_y,
    )
    return path


def render_animation(ctx, frames: int = TURNTABLE_DEFAULT_FRAMES) -> Path:
    """Render a turntable orbit as a PNG sequence into `ctx.out_dir`.

    The orbit itself belongs to `camera.py`; this function only asks for it,
    sets the frame range, and renders. The helper's exact signature is not
    visible from here (that module is being written in parallel), so it is
    resolved with `getattr` and the assumed shape is
    `camera.build_turntable(ctx, frames=<int>)`. A missing helper raises with
    a message naming what was expected rather than failing somewhere deep in
    the render loop.
    """
    import bpy

    from city import camera as camera_mod

    build_turntable = getattr(camera_mod, "build_turntable", None)
    if not callable(build_turntable):
        raise RuntimeError(
            "render_animation() needs city.camera.build_turntable(ctx, frames=int); "
            f"city.camera exposes {sorted(n for n in dir(camera_mod) if not n.startswith('_'))}"
        )
    build_turntable(ctx, frames=frames)

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = int(frames)
    scene.frame_set(1)

    out_dir = Path(ctx.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Trailing separator makes Blender treat this as a directory + frame
    # numbering rather than one literal filename.
    scene.render.filepath = str(out_dir / f"turntable_{ctx.preset_name}_")
    # Across a sequence the BVH is worth keeping — the scene never changes,
    # only the camera does.
    scene.render.use_persistent_data = True

    started = time.perf_counter()
    bpy.ops.render.render(animation=True)
    elapsed = time.perf_counter() - started

    logger.info(
        "render: wrote %d turntable frames to %s in %.1fs (%.1fs/frame)",
        frames, out_dir, elapsed, elapsed / max(1, frames),
    )
    return out_dir
