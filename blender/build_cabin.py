"""Entry point for the Blender procedural voxel-cabin scene.

Run inside Blender's own Python, e.g.:

    blender --background --python blender/build_cabin.py -- \\
        --preset dusk --seed 7 --out renders/

Everything after the bare `--` is this script's own argv; everything before
it is Blender's. Mirrors `blender/build_city.py`'s shape closely (argument
parsing, scene clearing, a `BuildContext` dataclass, per-stage error
attribution, the GUI-viewport convenience hook) so the two entrypoints stay
easy to compare; see that file for the sibling scene.

Stage pipeline — five stages are this package's own (`cabin.*`, currently
all stubs — see `blender/cabin/*.py`), two are REUSED, unmodified, from the
`city` package (`camera.build_camera`, `render.configure` /
`render.render` — both are scene-agnostic: camera placement/DOF and Cycles
device/sampling/colour-management/compositor setup have nothing to do with
towers vs. cabins), and one (`blocks.build_mesh`) converts the accumulated
voxel volume into the actual Blender object between the volume-writing
stages and lighting:

    materials.build_materials   (cabin, stub)
    terrain.build_terrain       (cabin, stub)  -- writes ctx.volume
    cabin.build_cabin           (cabin, stub)  -- writes ctx.volume
    scatter.build_scatter       (cabin, stub)  -- writes ctx.volume
    blocks.build_mesh           (cabin, NOT a stub -- the Phase 1 mesher)
    lighting.build_lighting     (cabin, stub)
    camera.build_camera         (REUSED from city.camera, via a small
                                  axis-swap shim -- see _CityCameraShim)
    render.configure            (REUSED from city.render)
    render.render                (REUSED from city.render)

Reuse note on `city.camera`: it expects three.js-named `camera_position`/
`camera_target` and internally swaps them to Blender's `(x, z, y)` (see
`city.layout`'s `COORDINATE_NOTE`). `cabin.layout.PRESETS` stores those two
keys as true Blender `(x, y, z)` instead (see `cabin.layout`'s
`COORDINATE_NOTE`), so `_CityCameraShim` below pre-swaps them right before
the call -- the only place in this whole package where an axis swap happens,
and it happens here specifically because of the reuse, not because this
package's own coordinates need one.

Reuse note on `city.render`: `_output_path()` inside `city/render.py`
hardcodes a `city_<preset>.png` filename prefix. Reusing it unmodified (as
instructed -- `city/render.py` is out of scope for this package) means
stills from this entrypoint land as `renders/city_<preset>.png`, not
`cabin_<preset>.png`. Documented here rather than silently left as a
surprise; not fixed, since fixing it means editing `city/render.py`.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

# Blender runs this script with an arbitrary cwd, so derive the directory
# that contains this file (and therefore the `cabin` and `city` packages)
# from __file__, never from cwd, and put it on sys.path so `from cabin
# import ...` / `from city import ...` resolve regardless of how/where
# blender was invoked.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from cabin import layout  # noqa: E402  (path insert must happen first)

if TYPE_CHECKING:
    import numpy as np

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class BuildContext:
    """Everything the build stages read from or write to.

    Attributes:
        preset: the resolved preset dict (a copy of `layout.PRESETS[preset_name]`,
            with any `--samples`/`--resolution` CLI overrides already applied).
            See `layout.PRESETS` for the full key list and their meaning.
        preset_name: the preset's name, e.g. `"dusk"` — for filenames/logging.
        seed: the master world-generation seed (drives terrain noise, tree
            placement, and is available to any stage that needs its own
            derived randomness via `layout.rng(seed)` — distinct from `rng`
            below, which is a ready-made instance for convenience).
        rng: a `random.Random` seeded from `seed`, shared by any stage that
            needs scene-level randomness (tree placement, terrain noise).
            Stages needing per-object randomness that must stay reproducible
            independent of iteration order should derive their own seed
            (e.g. `layout.rng(hash((ctx.seed, x, y)))`) rather than keep
            drawing from this shared stream.
        out_dir: output directory for renders/saved .blend files. Created if
            missing.
        volume: the block-id volume — `cabin.blocks.new_volume()`, shape
            `(layout.SIZE_X, layout.SIZE_Y, layout.SIZE_Z)`, dtype uint8.
            `terrain.build_terrain`, `cabin.build_cabin`, and
            `scatter.build_scatter` all write into this ONE shared array, in
            that order (each may read what the previous stage placed, e.g.
            `scatter` checking `blocks.get_block()` returns AIR before
            growing a tree). `blocks.build_mesh(ctx.volume, ...)` converts it
            to the actual Blender geometry exactly once, after every
            volume-writing stage has run and before `lighting.build_lighting`
            (which may want to find LAMP/CAMPFIRE block positions in the
            already-built object).
        materials: registry populated by `materials.build_materials`, read by
            every later stage. Expected keys: every value string in
            `layout.BLOCK_MATERIALS` (see that dict's docstring for the
            authoritative list and the two preset-driven emission keys).
        world_object: the single mesh object `blocks.build_mesh` returns,
            `None` until that stage has run. Stored here so
            `lighting.build_lighting` (and anything after it) can reference
            the built object without re-running the mesher.
    """

    preset: dict
    preset_name: str
    seed: int
    rng: object
    out_dir: Path
    volume: "np.ndarray"
    materials: dict = field(default_factory=dict)
    world_object: object = None
    #: Filename prefix for renders. Read by the REUSED `city.render._output_path`,
    #: which otherwise defaults to "city" and would drop cabin frames on top of
    #: the city's in the shared renders/ directory.
    output_prefix: str = "cabin"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="build_cabin.py",
        description="Build (and optionally render) the procedural voxel-cabin scene in Blender.",
    )
    parser.add_argument(
        "--preset",
        default="dusk",
        choices=sorted(layout.PRESETS.keys()),
        help="Named render preset from cabin.layout.PRESETS (default: dusk).",
    )
    parser.add_argument("--seed", type=int, default=7, help="Master world seed (default: 7).")
    parser.add_argument(
        "--out", type=Path, default=Path("renders/"), help="Output directory (default: renders/)."
    )
    parser.add_argument(
        "--samples", type=int, default=None, help="Override the preset's Cycles sample count."
    )
    parser.add_argument(
        "--resolution",
        type=str,
        default=None,
        metavar="WIDTHxHEIGHT",
        help='Override the preset\'s resolution, e.g. "1920x1080".',
    )
    parser.add_argument(
        "--no-render",
        action="store_true",
        help="Build the scene but skip rendering (used to test scene construction).",
    )
    parser.add_argument(
        "--save-blend",
        type=Path,
        default=None,
        metavar="PATH",
        help="Optional path to save the built scene as a .blend file.",
    )
    parser.add_argument(
        "--export-gltf",
        type=Path,
        default=None,
        metavar="PATH",
        help="Export the built scene to glTF (.glb) for interactive viewing in the browser.",
    )
    return parser.parse_args(argv)


def _resolve_preset(args: argparse.Namespace) -> dict:
    preset = dict(layout.PRESETS[args.preset])
    if args.samples is not None:
        preset["samples"] = args.samples
    if args.resolution is not None:
        try:
            w_str, h_str = args.resolution.lower().split("x")
            preset["resolution"] = (int(w_str), int(h_str))
        except ValueError as exc:
            raise SystemExit(
                f'--resolution must look like "1920x1080", got {args.resolution!r}'
            ) from exc
    return preset


def clear_scene() -> None:
    """Remove the default cube/camera/light so the cabin scene starts from
    an empty scene. Same logic as `build_city.py`'s `clear_scene()`,
    duplicated rather than imported since it is a small, generic bpy helper
    that lives on `build_city.py` itself (not part of the importable `city`
    package), and the reuse instruction for this entrypoint covers
    `city.camera`/`city.render` specifically, not `build_city.py`."""
    import bpy

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for collection in (bpy.data.meshes, bpy.data.lights, bpy.data.cameras):
        for block in list(collection):
            if block.users == 0:
                collection.remove(block)


def _run_stage(name: str, fn, ctx: BuildContext) -> None:
    logger.info("stage: %s", name)
    try:
        fn(ctx)
    except Exception:
        logger.error("stage %r failed", name)
        raise


class _CityCameraShim:
    """Adapts `BuildContext` for the REUSED `city.camera.build_camera`.

    That function reads `ctx.preset["camera_position"]` /
    `["camera_target"]` / `["camera_focal_length_mm"]` / `["dof_enabled"]` /
    `["dof_fstop"]` / `["dof_focus_distance"]` and internally swaps
    `camera_position`/`camera_target` from three.js-named `(x, y, z)` to
    Blender's `(x, z, y)` (see `city.layout.COORDINATE_NOTE`).
    `cabin.layout.PRESETS` stores those two keys as real Blender `(x, y, z)`
    already (see `cabin.layout.COORDINATE_NOTE`), so this shim pre-swaps
    `y`/`z` on a shallow copy of `ctx.preset` before handing it to
    `city.camera.build_camera` — undoing exactly the swap that function
    will apply, so the camera ends up exactly where `cabin.layout.PRESETS`
    says it should, in real Blender coordinates.

    Does NOT touch `blender/city/camera.py`, and does NOT mutate `ctx` or
    `ctx.preset` — every other stage keeps reading true Blender-space
    `camera_position`/`camera_target` from the real `ctx.preset` if it ever
    needs to (e.g. `lighting.py` aiming a light toward the camera).
    """

    def __init__(self, ctx: BuildContext) -> None:
        preset = dict(ctx.preset)
        x, y, z = preset["camera_position"]
        preset["camera_position"] = (x, z, y)
        x, y, z = preset["camera_target"]
        preset["camera_target"] = (x, z, y)
        self.preset = preset


def _build_world_mesh(ctx: BuildContext) -> None:
    """Convert `ctx.volume` into the single Blender mesh object, via the
    Phase 1 mesher (`cabin.blocks.build_mesh`). Runs after every stage that
    writes into `ctx.volume` (terrain/cabin/scatter) and before
    `lighting.build_lighting`, which may want to locate LAMP/CAMPFIRE
    blocks in the finished object."""
    from cabin import blocks

    stats = blocks.mesh_stats(ctx.volume)
    logger.info(
        "mesh: solid=%d naive_faces=%d culled_faces=%d quads=%d reduction=%.1fx (%.2fs)",
        stats["solid_blocks"],
        stats["naive_faces"],
        stats["culled_faces"],
        stats["quads"],
        stats["reduction_factor"],
        stats["elapsed_seconds"],
    )
    ctx.world_object = blocks.build_mesh(ctx.volume, "CabinWorld", ctx.materials)


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        # Blender passes its own args before `--`; only what follows is ours.
        argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []

    args = _parse_args(argv)
    preset = _resolve_preset(args)
    args.out.mkdir(parents=True, exist_ok=True)

    from cabin import blocks

    ctx = BuildContext(
        preset=preset,
        preset_name=args.preset,
        seed=args.seed,
        rng=layout.rng(args.seed),
        out_dir=args.out,
        volume=blocks.new_volume(),
        materials={},
    )
    logger.info(
        "preset=%s seed=%d volume=%dx%dx%d out=%s",
        ctx.preset_name,
        ctx.seed,
        *ctx.volume.shape,
        ctx.out_dir,
    )

    clear_scene()

    from cabin import cabin as cabin_stage
    from cabin import lighting, materials, scatter, terrain
    from city import camera as city_camera
    from city import render as city_render

    _run_stage("materials", materials.build_materials, ctx)
    _run_stage("terrain", terrain.build_terrain, ctx)
    _run_stage("cabin", cabin_stage.build_cabin, ctx)
    _run_stage("scatter", scatter.build_scatter, ctx)
    _run_stage("mesh", _build_world_mesh, ctx)
    _run_stage("lighting", lighting.build_lighting, ctx)
    _run_stage("camera", lambda c: city_camera.build_camera(_CityCameraShim(c)), ctx)
    _run_stage("render.configure", city_render.configure, ctx)

    if args.save_blend is not None:
        import bpy

        args.save_blend.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.save_blend))
        logger.info("saved .blend: %s", args.save_blend)

    if args.export_gltf is not None:
        _export_gltf(args.export_gltf)

    _setup_gui_viewport()

    if not args.no_render:
        _run_stage("render.render", city_render.render, ctx)
    else:
        logger.info("--no-render: skipping render.render")


def _setup_gui_viewport() -> None:
    """When running with a UI, open on a rendered view through the camera.

    Same idea as `build_city.py`'s helper of the same name: only fires when
    Blender is NOT in background mode, deferred through a timer since the
    screen areas are not laid out yet at the moment a `--python` script
    runs, and every failure here is swallowed — a demo that opens on the
    wrong shading is a much smaller problem than one that refuses to open.
    """
    import bpy

    if bpy.app.background:
        return

    def _apply() -> None:
        try:
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type != "VIEW_3D":
                        continue
                    for space in area.spaces:
                        if space.type != "VIEW_3D":
                            continue
                        space.shading.type = "RENDERED"
                        # Cabin world is ~100 units across (vs. city's
                        # 1600-unit ground plane) -- a far smaller clip_end
                        # is enough and keeps depth precision tighter.
                        space.clip_end = 2000.0
                        space.region_3d.view_perspective = "CAMERA"
            logger.info("gui: viewport set to Rendered, looking through the built camera")
        except Exception as exc:  # noqa: BLE001 — cosmetic only
            logger.warning("gui: could not configure viewport (%s)", exc)
        return None  # unregister the timer

    try:
        bpy.app.timers.register(_apply, first_interval=0.4)
    except Exception as exc:  # noqa: BLE001
        logger.warning("gui: timer unavailable (%s)", exc)


def _export_gltf(path: Path) -> None:
    """Export the built scene to a single .glb for interactive browser
    viewing — same rationale as `build_city.py`'s helper of the same name
    (Cycles gives light transport a rasteriser cannot, glTF hands the
    geometry/materials back to a real-time viewer for interactivity).

    Hides an object named `"CabinAtmosphere"` for the export, if
    `lighting.build_lighting` has created a fog/volume domain under that
    name (a Cycles-only construct that would export as a giant opaque box
    in a rasteriser) — harmless no-op if no such object exists yet (true
    for every preset until `lighting.py` is implemented).
    """
    import bpy

    path.parent.mkdir(parents=True, exist_ok=True)

    # The fog domain is a Cycles-only construct: a box with a volume shader and
    # no surface, invisible to the path tracer. A rasteriser has no such concept,
    # so exporting it would wrap the whole valley in an opaque cube. Check both
    # names — lighting.py calls it CabinFog; the earlier scaffold assumed
    # CabinAtmosphere, and a stale name here fails silently by exporting the box.
    atmosphere = bpy.data.objects.get("CabinFog") or bpy.data.objects.get("CabinAtmosphere")
    hidden = False
    if atmosphere is not None:
        atmosphere.hide_viewport = True
        atmosphere.hide_render = True
        hidden = True

    try:
        bpy.ops.export_scene.gltf(
            filepath=str(path),
            export_format="GLB",
            export_apply=True,
            export_gn_mesh=True,
            use_visible=True,
            export_cameras=True,
            export_lights=True,
            export_yup=True,  # glTF is Y-up; Blender is Z-up
        )
    finally:
        if hidden and atmosphere is not None:
            atmosphere.hide_viewport = False
            atmosphere.hide_render = False

    size = path.stat().st_size if path.exists() else 0
    logger.info("exported glTF: %s (%.1f MB)", path, size / 1e6)


if __name__ == "__main__":
    main()
