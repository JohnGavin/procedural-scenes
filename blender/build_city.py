"""Entry point for the Blender procedural-city rebuild.

Run inside Blender's own Python, e.g.:

    blender --background --python blender/build_city.py -- \\
        --preset dusk --seed 7 --out renders/

Everything after the bare `--` is this script's own argv; everything before
it is Blender's. This script does the layout-independent scaffolding
(argument parsing, scene clearing, stage sequencing) and delegates all
actual scene construction to the sibling `city.*` modules, each of which
currently is a stub (see `blender/city/*.py`).
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Blender runs this script with an arbitrary cwd, so derive the directory
# that contains this file (and therefore the `city` package) from __file__,
# never from cwd, and put it on sys.path so `from city import ...` resolves
# regardless of how/where blender was invoked.
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from city import layout  # noqa: E402  (path insert must happen first)
from city.layout import Plot  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class BuildContext:
    """Everything the eight build stages read from or write to.

    Attributes:
        preset: the resolved preset dict (a copy of `layout.PRESETS[preset_name]`,
            with any `--samples`/`--resolution` CLI overrides already applied).
            See `layout.PRESETS` for the full key list and their meaning.
        preset_name: the preset's name, e.g. `"dusk"` — for filenames/logging.
        seed: the master layout seed (drives `plots` and is available to
            stages that need their own derived randomness via
            `layout.rng(seed)` — distinct from `rng` below, which is a
            ready-made instance for convenience).
        rng: a `random.Random` seeded from `seed`, shared by any stage that
            needs scene-level (non-plot-local) randomness — e.g. `scatter.py`
            placing trees/clouds. Stages needing per-building randomness
            should prefer `plot.seed` (see `layout.Plot`) so their choices
            don't perturb this shared stream for other stages.
        out_dir: output directory for renders/saved .blend files. Created if
            missing.
        plots: every building footprint, from `layout.tower_plots(seed)`.
            `buildings.py` builds geometry from this list directly.
        materials: registry populated by `materials.build_materials`, read
            by every later stage. Expected keys (see `materials.py` for the
            authoritative docstring): `concrete`, `glass`, `asphalt`,
            `water`, `kerb`, `bridge`, `trunk`, `leaf`, `crown`,
            `lane_paint`, `park_grass`, `gravel`, `window_emission`.
    """

    preset: dict
    preset_name: str
    seed: int
    rng: object
    out_dir: Path
    plots: list[Plot]
    materials: dict = field(default_factory=dict)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="build_city.py",
        description="Build (and optionally render) the procedural city scene in Blender.",
    )
    parser.add_argument(
        "--preset",
        default="noon",
        choices=sorted(layout.PRESETS.keys()),
        help="Named render preset from city.layout.PRESETS (default: noon).",
    )
    parser.add_argument("--seed", type=int, default=7, help="Master layout seed (default: 7).")
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
        help=(
            "Export the built scene to glTF (.glb) for interactive viewing in "
            "the browser. Realises Geometry Nodes instances into real meshes."
        ),
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
    """Remove the default cube/camera/light so the city starts from an empty scene."""
    import bpy

    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    # Purge orphaned mesh/light/camera data left behind by the removed objects.
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


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        # Blender passes its own args before `--`; only what follows is ours.
        argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []

    args = _parse_args(argv)
    preset = _resolve_preset(args)
    args.out.mkdir(parents=True, exist_ok=True)

    ctx = BuildContext(
        preset=preset,
        preset_name=args.preset,
        seed=args.seed,
        rng=layout.rng(args.seed),
        out_dir=args.out,
        plots=layout.tower_plots(args.seed),
        materials={},
    )
    logger.info(
        "preset=%s seed=%d plots=%d out=%s", ctx.preset_name, ctx.seed, len(ctx.plots), ctx.out_dir
    )

    clear_scene()

    from city import buildings, camera, lighting, materials, render, scatter, terrain

    _run_stage("materials", materials.build_materials, ctx)
    _run_stage("terrain", terrain.build_terrain, ctx)
    _run_stage("buildings", buildings.build_buildings, ctx)
    _run_stage("scatter", scatter.build_scatter, ctx)
    _run_stage("lighting", lighting.build_lighting, ctx)
    _run_stage("camera", camera.build_camera, ctx)
    _run_stage("render.configure", render.configure, ctx)

    if args.save_blend is not None:
        import bpy

        args.save_blend.parent.mkdir(parents=True, exist_ok=True)
        bpy.ops.wm.save_as_mainfile(filepath=str(args.save_blend))
        logger.info("saved .blend: %s", args.save_blend)

    if args.export_gltf is not None:
        _export_gltf(args.export_gltf)

    _setup_gui_viewport()

    if not args.no_render:
        _run_stage("render.render", render.render, ctx)
    else:
        logger.info("--no-render: skipping render.render")


def _setup_gui_viewport() -> None:
    """When running with a UI, open on a rendered view through the camera.

    Only fires when Blender is NOT in background mode, so the headless render
    path is untouched. Deferred through a timer because at the moment a
    `--python` script runs the areas are not laid out yet, so walking the screen
    immediately finds nothing to configure.

    Entirely cosmetic — every failure here is swallowed. A demo that opens on
    the wrong shading is a much smaller problem than one that refuses to open.
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
                        space.clip_end = 20000.0  # the ground plane is 1600 across
                        space.region_3d.view_perspective = "CAMERA"
            logger.info("gui: viewport set to Rendered, looking through CityCamera")
        except Exception as exc:  # noqa: BLE001 — cosmetic only
            logger.warning("gui: could not configure viewport (%s)", exc)
        return None  # unregister the timer

    try:
        bpy.app.timers.register(_apply, first_interval=0.4)
    except Exception as exc:  # noqa: BLE001
        logger.warning("gui: timer unavailable (%s)", exc)


def _export_gltf(path: Path) -> None:
    """Export the built scene to a single .glb for interactive browser viewing.

    This is the bridge back to the three.js side of the project: Cycles gives
    light transport a rasteriser cannot, but it gives up interactivity to do it.
    Exporting to glTF hands the Blender-authored geometry and materials back to
    a real-time viewer, so the city can be orbited and zoomed again.

    What survives the trip: geometry, PBR base colour / metallic / roughness,
    emission (so the night windows still glow), and object hierarchy. What does
    not: the volumetric atmosphere, true glass refraction, and every bounce of
    global illumination — those are properties of the renderer, not the scene.

    Geometry Nodes instances are realised into real meshes on the way out
    (`export_apply=True` evaluates modifiers), which is why the exported tree
    count matches what Cycles renders rather than coming out empty.
    """
    import bpy

    path.parent.mkdir(parents=True, exist_ok=True)

    # The atmosphere domain is a Cycles-only construct — a box with no surface
    # shader. In a rasteriser it would export as a giant opaque cube wrapped
    # around the whole city, hiding everything. Pull it out for the export.
    atmosphere = bpy.data.objects.get("CityAtmosphere")
    hidden = False
    if atmosphere is not None:
        atmosphere.hide_viewport = True
        atmosphere.hide_render = True
        hidden = True

    try:
        bpy.ops.export_scene.gltf(
            filepath=str(path),
            export_format="GLB",
            export_apply=True,          # evaluate modifiers
            # `export_apply` alone evaluates the Geometry Nodes modifier but
            # leaves its output as *instances*, which the exporter then drops —
            # the park came out with zero trees while still reporting success.
            # `export_gn_mesh` realises that instanced geometry into real
            # meshes. Checked by counting vertices in the .glb, not by trusting
            # the exit code.
            export_gn_mesh=True,
            use_visible=True,           # honours the hide above
            export_cameras=True,
            export_lights=True,
            export_yup=True,            # glTF is Y-up; Blender is Z-up
        )
    finally:
        if hidden and atmosphere is not None:
            atmosphere.hide_viewport = False
            atmosphere.hide_render = False

    size = path.stat().st_size if path.exists() else 0
    logger.info("exported glTF: %s (%.1f MB)", path, size / 1e6)


if __name__ == "__main__":
    main()
