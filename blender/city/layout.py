"""Layout contract shared by every Blender city-building module.

This module is a **faithful port of the layout maths in `buildings.html`**
(the three.js version of this scene) — same block pitch, same river-meander
formula, same core/fringe tower-height decay, same park/pond geometry. Every
value here should trace back to a line in `buildings.html`; if you change a
number here, check whether the three.js scene should change too (and vice
versa) so the two stay comparable.

No `bpy` import happens here or in `__init__.py` — this module must be
importable with plain `python3` so it can be unit-tested without a Blender
runtime, and so the four sibling modules (`materials`, `terrain`,
`buildings`, `scatter`, `lighting`, `camera`, `render`) can all import it
without pulling in Blender.

COORDINATE_NOTE
----------------
three.js in `buildings.html` is **Y-up**: +Y is height, +Z points toward the
default camera. Blender is **Z-up**: +Z is height, +Y points "into" the
default view.

All constants and helpers in this module stay in **three.js-named terms** —
`x` is east-west, `z` is north-south ("depth" in the three.js scene), `h`/`y`
is height. Every consumer of this module MUST apply the same axis mapping
when placing objects in Blender:

    blender_xyz = (three_x, three_z, three_y)

i.e. three.js `(x, y, z)` becomes Blender `(x, z, y)` — three.js height
(`y`) becomes Blender height (`z`), and three.js depth (`z`) becomes
Blender's horizontal `y` axis. Do this conversion once, at the point each
sibling module places an object (`obj.location = (x, z, y)`), never inside
this module — `layout.py` never touches Blender coordinates.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

# ===== layout constants =====================================================
# The whole plan is driven by these — change PITCH/COLS/ROWS and the roads,
# blocks, bridges and highways all stay consistent (ported from the "layout
# constants" block at the top of buildings.html).

PITCH: float = 24.0
"""Block centre-to-centre spacing."""

BLOCK: float = 16.0
"""Block footprint (so the road corridor between blocks is PITCH - BLOCK = 8)."""

COLS: int = 5
"""City blocks east-west (three.js x)."""

ROWS: int = 7
"""City blocks north-south (three.js z)."""

CORE_R: float = 95.0
"""Radius (world units, from the origin) over which tower height decays from
downtown-max to fringe-min."""

RIVER_X: float = -104.0
"""Baseline x of the river's centreline before the meander term is added."""

RIVER_W: float = 34.0
"""River width."""

BRIDGE_Z: list[float] = [-12.0, 36.0]
"""The road-corridor z values that cross the river and get bridges."""


@dataclass(frozen=True)
class _Park:
    """Elliptical park footprint. Ported from the `PARK` const in
    buildings.html: `{ x: 112, z: 6, rx: 64, rz: 86 }`."""

    x: float = 112.0
    z: float = 6.0
    rx: float = 64.0
    """Ellipse semi-axis along x."""
    rz: float = 86.0
    """Ellipse semi-axis along z."""


@dataclass(frozen=True)
class _Pond:
    """Circular pond inside the park. Ported from the `pond` local const in
    `parkland()`: `{ x: PARK.x - 4, z: -18, r: 21 }`."""

    x: float = _Park().x - 4.0
    z: float = -18.0
    r: float = 21.0


@dataclass(frozen=True)
class _Y:
    """Layered heights, spaced generously to keep coplanar surfaces off each
    other. Ported from the `Y` const in buildings.html (JS `kerbTop` ->
    `kerb_top`, everything else is a direct name match)."""

    asphalt: float = 0.4
    park: float = 0.5
    river: float = 0.6
    pond: float = 0.8
    paint: float = 0.9
    kerb_top: float = 1.2


PARK = _Park()
POND = _Pond()
Y = _Y()


def col_x(i: int) -> float:
    """World x of block column `i` (0-indexed). Ported from `colX`."""
    return (i - (COLS - 1) / 2) * PITCH


def row_z(j: int) -> float:
    """World z of block row `j` (0-indexed). Ported from `rowZ`."""
    return (j - (ROWS - 1) / 2) * PITCH


def river_centre(z: float) -> float:
    """World x of the river centreline at depth `z`. Ported verbatim from
    `riverCentre`: a two-term sine meander added to `RIVER_X`."""
    return RIVER_X + 15 * math.sin(z * 0.016) + 7 * math.sin(z * 0.005)


# Downtown asphalt sheet half-extents, ported from the halfX/halfZ locals at
# the top of `streets()` in buildings.html.
HALF_X: float = col_x(COLS - 1) + PITCH / 2
HALF_Z: float = row_z(ROWS - 1) + PITCH / 2


# ===== seeded PRNG ===========================================================


def rng(seed: int) -> random.Random:
    """Return a seeded PRNG with a `.random() -> float in [0, 1)` method.

    This is Python's stdlib `random.Random`, NOT a port of the JS mulberry32
    generator in buildings.html — we deliberately do not try to bit-match the
    three.js PRNG stream. Layouts are reproducible per-seed (same seed always
    gives the same Blender scene) but will NOT match the three.js scene
    pixel-for-pixel or building-for-building. The seed is the only thing that
    needs to travel between runs for reproducibility.
    """
    return random.Random(seed)


# ===== tower plots ============================================================


@dataclass(frozen=True)
class Plot:
    """One building footprint, fully resolved — `buildings.py` builds
    geometry straight from these fields without re-deriving any layout maths
    (block index, core/fringe decay, single-vs-split, vacant-lot roll, height
    formula, jitter). All positions/sizes are in three.js-named world units;
    see `COORDINATE_NOTE` at module top for the Blender axis mapping."""

    x: float
    """World x (three.js east-west)."""
    z: float
    """World z (three.js north-south / depth)."""
    w: float
    """Footprint width along x."""
    d: float
    """Footprint depth along z."""
    h: float
    """Shaft height above the kerb (world units) — NOT including podium or
    crown; `buildings.py` adds those on top, same as `tower()` does in
    buildings.html."""
    is_glass: bool
    """Whether this tower's shaft material pool is glass (True) or concrete
    (False) — ported from `tower()`'s `rand() < 0.42` roll."""
    seed: int
    """A plot-local seed (0 <= seed < 2**32), independent of the master
    layout seed, for `buildings.py` to derive further per-building random
    choices (podium height, crown height, mast, rooftop plant, material
    colour variant) via `random.Random(plot.seed)` without disturbing the
    layout RNG stream or needing to replay `tower_plots()`."""
    block_i: int
    """Column index of the parent block (0 <= block_i < COLS) — provenance only."""
    block_j: int
    """Row index of the parent block (0 <= block_j < ROWS) — provenance only."""
    k: float
    """Podium/height weight: 1.0 for a single tower filling the block, 0.5
    for one of four split fringe plots. Ported from the `k` field in the
    `plots` records inside `downtown()`."""


def tower_plots(seed: int) -> list[Plot]:
    """Resolve every building footprint in the downtown grid.

    Faithful port of `downtown()` in buildings.html: for each of the
    COLS x ROWS blocks, compute `core_t = max(0, 1 - hypot(bx, bz) / CORE_R)`
    (1.0 at the origin, 0.0 at/beyond CORE_R) and `t = core_t ** 1.5`. Near
    the core one tower fills the whole block; out in the fringe the block
    splits into four smaller corner plots. Each plot independently has a
    small chance of being a vacant lot (skipped). Height is
    `(4 + rand()*6 + t*(12 + rand()*52)) * k` — a small base height plus a
    core-weighted bonus, scaled by the podium/height weight `k`.
    """
    master = rng(seed)
    plots: list[Plot] = []

    for i in range(COLS):
        for j in range(ROWS):
            bx, bz = col_x(i), row_z(j)
            core_t = max(0.0, 1 - math.hypot(bx, bz) / CORE_R)
            t = core_t**1.5

            single = master.random() < 0.25 + t * 0.65
            if single:
                specs = [(bx, bz, BLOCK - 2.5, BLOCK - 2.5, 1.0)]
            else:
                specs = [
                    (bx + sx * BLOCK / 4, bz + sz * BLOCK / 4, BLOCK / 2 - 1.6, BLOCK / 2 - 1.6, 0.5)
                    for sx in (-1, 1)
                    for sz in (-1, 1)
                ]

            for px, pz, pw, pd, k in specs:
                if master.random() < 0.07:
                    continue  # vacant lot

                h = (4 + master.random() * 6 + t * (12 + master.random() * 52)) * k
                w_jit = pw * (0.85 + master.random() * 0.15)
                d_jit = pd * (0.85 + master.random() * 0.15)
                is_glass = master.random() < 0.42
                plot_seed = master.getrandbits(32)

                plots.append(
                    Plot(
                        x=px,
                        z=pz,
                        w=w_jit,
                        d=d_jit,
                        h=h,
                        is_glass=is_glass,
                        seed=plot_seed,
                        block_i=i,
                        block_j=j,
                        k=k,
                    )
                )

    return plots


# ===== render presets =========================================================
#
# Declarative-only: each preset is a flat dict of values the lighting/camera/
# render modules read by key. Key names are the contract — sibling agents
# code against these exact names, so do not rename without updating all of
# materials.py/lighting.py/camera.py/render.py.
#
# Keys (every preset has all of these):
#   sun_elevation_rad     float  — sun elevation angle above the horizon, radians.
#   sun_rotation_rad      float  — sun azimuth (compass rotation), radians.
#   sun_strength          float  — Blender sun-lamp strength (W/m^2-ish units).
#   sky_air_density       float  — Nishita sky "air" density (Rayleigh scattering).
#   sky_dust_density      float  — Nishita sky "dust" density (Mie scattering / haze).
#   sky_ozone_density     float  — Nishita sky "ozone" density (affects blue/sunset hue).
#   volumetric_density    float  — world/atmosphere volume scatter density (god-rays, haze).
#   window_emission       bool   — whether building windows use an emission shader.
#   window_emission_strength float — emission strength when window_emission is True.
#   camera_position        tuple[float, float, float] — three.js-named (x, y, z); see COORDINATE_NOTE.
#   camera_target           tuple[float, float, float] — three.js-named (x, y, z); see COORDINATE_NOTE.
#   camera_focal_length_mm float — camera lens focal length, millimetres.
#   dof_enabled            bool  — whether depth-of-field is on.
#   dof_fstop               float — aperture f-stop when dof_enabled is True.
#   dof_focus_distance      float | None — focus distance in world units; None
#                                          means "autofocus on camera_target".
#   samples                 int   — Cycles render samples.
#   resolution               tuple[int, int] — (width, height) in pixels.

PRESETS: dict[str, dict] = {
    "noon": {
        # High sun, crisp shadows, clean daylight haze — matches the default
        # three.js lighting rig (elevation 34deg, azimuth 128deg) but pushed
        # higher to read as "noon" rather than "late afternoon".
        "sun_elevation_rad": 1.0472,  # 60 deg
        "sun_rotation_rad": 2.2340,  # 128 deg, same azimuth as buildings.html
        "sun_strength": 3.5,
        "sky_air_density": 1.0,
        "sky_dust_density": 1.0,
        "sky_ozone_density": 1.0,
        "volumetric_density": 0.006,
        "window_emission": False,
        "window_emission_strength": 0.0,
        "camera_position": (215.0, 135.0, 235.0),  # matches buildings.html camera.position
        "camera_target": (0.0, 14.0, 0.0),  # matches buildings.html controls.target
        "camera_focal_length_mm": 35.0,
        "dof_enabled": False,
        "dof_fstop": 5.6,
        "dof_focus_distance": None,
        "samples": 128,
        "resolution": (1920, 1080),
    },
    "dusk": {
        # Low, warm sun; longer shadows; haze picks up more colour.
        # 4 deg, not 10: at 10 the multiple-scattering sky still reads as
        # ordinary daylight, and dusk was near-indistinguishable from noon.
        # Below ~5 deg the sun's path through the atmosphere is long enough
        # for Rayleigh scattering to actually strip the blue and go warm.
        "sun_elevation_rad": 0.0698,  # 4 deg
        "sun_rotation_rad": 2.2340,
        "sun_strength": 4.5,  # low sun loses much of its energy to the atmosphere
        "sky_air_density": 1.8,
        "sky_dust_density": 3.0,  # more Mie scattering = warmer, hazier horizon
        "sky_ozone_density": 2.4,
        "volumetric_density": 0.014,
        "window_emission": True,
        "window_emission_strength": 3.0,
        "camera_position": (260.0, 90.0, 200.0),
        "camera_target": (0.0, 20.0, 0.0),
        "camera_focal_length_mm": 50.0,
        "dof_enabled": True,
        "dof_fstop": 2.8,
        "dof_focus_distance": None,  # autofocus on camera_target
        "samples": 256,
        "resolution": (1920, 1080),
    },
    "night": {
        # Sun below the horizon; scene reads almost entirely by window
        # emission + a faint hemisphere fill (lighting.py's job).
        "sun_elevation_rad": -0.0873,  # -5 deg, just below horizon
        "sun_rotation_rad": 2.2340,
        "sun_strength": 0.05,
        "sky_air_density": 1.0,
        "sky_dust_density": 0.6,
        "sky_ozone_density": 1.0,
        "volumetric_density": 0.02,
        "window_emission": True,
        "window_emission_strength": 6.0,
        "camera_position": (180.0, 60.0, 260.0),
        "camera_target": (0.0, 18.0, 0.0),
        "camera_focal_length_mm": 35.0,
        "dof_enabled": False,
        "dof_fstop": 4.0,
        "dof_focus_distance": None,
        "samples": 256,
        "resolution": (1920, 1080),
    },
    "tiltshift": {
        # Noon-like light but a tight aperture + close focus plane so
        # camera.py can rack the DOF into a miniature-diorama look.
        "sun_elevation_rad": 0.9599,  # 55 deg
        "sun_rotation_rad": 2.2340,
        "sun_strength": 3.2,
        "sky_air_density": 1.0,
        "sky_dust_density": 1.2,
        "sky_ozone_density": 1.0,
        "volumetric_density": 0.006,
        "window_emission": False,
        "window_emission_strength": 0.0,
        # Pulled back and up. At (140, 220, 160) with a 100mm lens the camera
        # sat ~300 units out with a ~20 deg field of view — a telephoto crop of
        # four towers, not a diorama. The miniature illusion needs the WHOLE
        # subject small in frame with a shallow plane across it, so: further
        # out, steeper down, and a lens long enough to compress without cropping.
        "camera_position": (330.0, 430.0, 360.0),
        "camera_target": (0.0, 10.0, 0.0),
        "camera_focal_length_mm": 85.0,
        "dof_enabled": True,
        "dof_fstop": 1.4,
        # Explicit, and it must match the new camera-to-target distance
        # (~640 units) or the focus plane sits in empty air in front of the city.
        "dof_focus_distance": 640.0,
        "samples": 320,
        "resolution": (1920, 1080),
    },
}
