"""Layout contract shared by every Blender cabin-building module.

Unlike `blender/city/layout.py` (a port of an existing three.js scene, so
Y-up-named to stay comparable), this package has no pre-existing reference —
it is built directly in Blender, so it is **native Blender Z-up throughout**.

COORDINATE_NOTE
----------------
Everything in this module — block coordinates, world positions, the river
course, the cabin footprint — is plain Blender space: +X east-west, +Y
north-south, +Z up. Block coordinates are integers `(bx, by, bz)`; world
position is `block * BLOCK_SIZE` on each axis. **No axis remapping happens
anywhere in this package.** Every sibling module places objects with
`obj.location = (x, y, z)` straight from block-space math, no `(x, z, y)`
swap like `city`'s modules need.

The one deliberate exception: `PRESETS[*]["camera_position"]` and
`["camera_target"]` are consumed by `city.camera.build_camera` (REUSED
unmodified from the city package — see `build_cabin.py`), which
unconditionally applies the three.js-style `(x, y, z) -> (x, z, y)` swap
internal to that module. `build_cabin.py` compensates for this at the call
site (a small shim that pre-swaps y/z just for that one call), so the values
stored here stay true Blender `(x, y, z)` like everything else in this file —
nothing in `layout.py` itself needs to know about the swap.

No `bpy` import happens here or in `__init__.py` — this module must be
importable with plain `python3` so it can be unit-tested (and the mesher
benchmarked) without a Blender runtime, and so the sibling modules
(`materials`, `terrain`, `cabin`, `scatter`, `lighting`, `blocks`) can all
import it without pulling in Blender.
"""

from __future__ import annotations

import math
import random
from enum import IntEnum

# ===== block palette =========================================================


class Block(IntEnum):
    """Every voxel type this world can contain. `AIR` MUST be 0 — the mesher
    (`blocks.py`) treats id 0 as "nothing here", both as the empty-volume
    fill value and as the padding value at the edge of the world."""

    AIR = 0
    GRASS = 1
    DIRT = 2
    STONE = 3
    COBBLE = 4
    SPRUCE_LOG = 5
    SPRUCE_PLANK = 6
    SPRUCE_LEAVES = 7
    GLASS = 8
    LAMP = 9
    WATER = 10
    SNOW = 11
    SAND = 12
    PATH = 13
    CAMPFIRE = 14


AIR: int = Block.AIR
"""Convenience alias — `blocks.py` and every consumer compares against this
constant rather than spelling out `Block.AIR` everywhere."""


BLOCK_MATERIALS: dict[int, str] = {
    Block.GRASS: "grass",
    Block.DIRT: "dirt",
    Block.STONE: "stone",
    Block.COBBLE: "cobble",
    Block.SPRUCE_LOG: "spruce_log",
    Block.SPRUCE_PLANK: "spruce_plank",
    Block.SPRUCE_LEAVES: "spruce_leaves",
    Block.GLASS: "glass",
    Block.LAMP: "lamp",
    Block.WATER: "water",
    Block.SNOW: "snow",
    Block.SAND: "sand",
    Block.PATH: "path",
    Block.CAMPFIRE: "campfire",
}
"""Contract between `blocks.build_mesh()` and `materials.build_materials()`.
Every key here (except `AIR`, which never gets a face) MUST have a matching
entry in the `ctx.materials` dict that `materials.py` populates — same key
string, e.g. `ctx.materials["spruce_log"]`. `blocks.build_mesh()` looks up
each emitted quad's material by `BLOCK_MATERIALS[block_id]`, builds one
mesh material slot per distinct key actually used in the volume (not one per
enum member — an unused block type never gets a slot), and sets
`polygon.material_index` accordingly. If `materials.py` has not populated a
key yet (Phase 1 stub), `build_mesh()` still creates the slot — just filled
with `None`, i.e. Blender's default grey material — so the mesher never
fails before `materials.py` is implemented."""

BLOCK_FLAGS: dict[int, dict[str, bool]] = {
    Block.GRASS: {"transparent": False, "emissive": False},
    Block.DIRT: {"transparent": False, "emissive": False},
    Block.STONE: {"transparent": False, "emissive": False},
    Block.COBBLE: {"transparent": False, "emissive": False},
    Block.SPRUCE_LOG: {"transparent": False, "emissive": False},
    Block.SPRUCE_PLANK: {"transparent": False, "emissive": False},
    Block.SPRUCE_LEAVES: {"transparent": True, "emissive": False},
    Block.GLASS: {"transparent": True, "emissive": False},
    Block.LAMP: {"transparent": False, "emissive": True},
    Block.WATER: {"transparent": True, "emissive": False},
    Block.SNOW: {"transparent": False, "emissive": False},
    Block.SAND: {"transparent": False, "emissive": False},
    Block.PATH: {"transparent": False, "emissive": False},
    Block.CAMPFIRE: {"transparent": False, "emissive": True},
}
"""Per-block flags the mesher (`transparent`) and the materials/lighting
stages (`emissive`) need. Precise meaning, since both are load-bearing:

`transparent` — this block does NOT hide its neighbours' faces, and its own
faces ARE still emitted even when solid blocks surround it. Concretely, in
`blocks.py`'s culling rule, a face between block A and neighbour B is
skipped only when B is present AND B is opaque (`transparent=False`) — a
transparent neighbour (glass/water/leaves) never culls A's face. The one
refinement: two adjacent voxels of the *same* transparent block id do NOT
emit a face between them (e.g. two touching WATER voxels have no interior
wall) — this avoids a doubled, mutually-occluding pair of alpha faces
inside a contiguous body of water or a dense leaf canopy, which would look
wrong and would also defeat the greedy-merge reduction target on exactly
the two block types most likely to appear in large contiguous blobs.

`emissive` — read by `materials.py` (to decide which blocks get an Emission
shader contribution, at a strength drawn from the preset — see
`campfire_strength`/`window_light_strength` below) and by `lighting.py`
(which may add real point lights near emissive blocks for bounce lighting
Cycles' pure-emission-surface path alone would under-light). `blocks.py`
itself never reads this flag — it exists here, not duplicated in
`materials.py`, so there is exactly one place that says "this block glows"."""


# ===== world extents ==========================================================

BLOCK_SIZE: float = 1.0
"""World units per voxel edge. One Blender unit per block throughout."""

SIZE_X: int = 96
SIZE_Y: int = 96
SIZE_Z: int = 48
"""Generated-region extents in blocks. Large enough for the cabin, its
clearing, the river, and a spruce forest backdrop; small enough that the
mesher and Cycles both stay fast — this is a dusk dioramas, not a city."""

GROUND_LEVEL: int = 8
"""Nominal terrain height in blocks (z). `terrain.py` perturbs around this
with noise; every other constant below that references a z-coordinate is
relative to this baseline."""

CABIN_ORIGIN: tuple[int, int, int] = (40, 40, GROUND_LEVEL)
"""Block-space `(x, y, z)` of the cabin footprint's minimum corner (the
south-west floor corner, at ground level)."""

CABIN_SIZE: tuple[int, int, int] = (11, 9, 7)
"""Cabin footprint `(width_x, depth_y, height_z)` in blocks, walls
included. `cabin.py` builds within
`[CABIN_ORIGIN, CABIN_ORIGIN + CABIN_SIZE)` on each axis."""

CABIN_CENTRE: tuple[float, float, float] = (
    CABIN_ORIGIN[0] + CABIN_SIZE[0] / 2,
    CABIN_ORIGIN[1] + CABIN_SIZE[1] / 2,
    CABIN_ORIGIN[2] + CABIN_SIZE[2] / 2,
)
"""Cabin footprint centre in world units — convenience for camera targets,
sun-facing choices, and scatter/lighting distance checks."""

CLEARING_RADIUS: float = 20.0
"""Radius, in blocks from `CABIN_CENTRE`'s x/y, of the area `scatter.py`
should keep clear (or thin out) of dense forest — the cosy-clearing-in-the-
woods look, not trees growing through the walls."""

RIVER_BASE_X: float = 14.0
"""Baseline x of the river centreline before the meander terms are added."""

RIVER_WIDTH: float = 7.0
"""River width in blocks."""

RIVER_AMPLITUDE_1: float = 6.0
RIVER_AMPLITUDE_2: float = 2.0
RIVER_FREQ_1: float = 0.05
RIVER_FREQ_2: float = 0.013
"""Two-term sine meander coefficients — same idea as `city.layout.river_centre`
(a low-frequency wander plus a higher-frequency wobble), independently tuned
for this world's much smaller scale."""


def river_centre_x(by: int) -> float:
    """World x of the river centreline at block-row `by` (the north-south
    axis). A two-term sine meander, mirroring the technique in
    `city.layout.river_centre` but re-derived for this package's own scale
    and native Z-up axes (`by` here is a real Blender y-block-index, not a
    three.js z)."""
    return (
        RIVER_BASE_X
        + RIVER_AMPLITUDE_1 * math.sin(by * RIVER_FREQ_1)
        + RIVER_AMPLITUDE_2 * math.sin(by * RIVER_FREQ_2)
    )


# ===== seeded PRNG ============================================================


def rng(seed: int) -> random.Random:
    """Return a seeded PRNG with a `.random() -> float in [0, 1)` method.

    Python's stdlib `random.Random`. Same seed always gives the same cabin
    world (terrain noise, tree scatter, log-cabin detailing); no attempt is
    made to match any other engine's PRNG stream since this scene has no
    pre-existing reference to stay comparable with.
    """
    return random.Random(seed)


# ===== render presets ==========================================================
#
# Declarative-only: each preset is a flat dict of values the
# materials/terrain/cabin/scatter/lighting/camera/render stages read by key.
# Key names are the contract — sibling agents code against these exact
# names, so do not rename without updating every consumer.
#
# Keys (every preset has all of these):
#   sun_elevation_rad         float — sun elevation above the horizon, radians.
#   sun_rotation_rad          float — sun azimuth (compass rotation), radians.
#   sun_strength               float — Blender sun-lamp strength.
#   sky_air_density             float — Nishita sky "air" density (Rayleigh).
#   sky_dust_density             float — Nishita sky "dust" density (Mie / haze).
#   sky_ozone_density             float — Nishita sky "ozone" density (blue/sunset hue).
#   fog_density                   float — world/atmosphere volume scatter density,
#                                          for the evening-fog look between the
#                                          trees; 0.0 disables the volume entirely.
#   campfire_strength               float — Emission strength for CAMPFIRE-block
#                                            material (materials.py reads this).
#   window_light_strength             float — Emission strength for the warm
#                                              indoor light spilling from LAMP
#                                              blocks / lit windows.
#   camera_position   tuple[float, float, float] — true Blender (x, y, z); see
#                      the exception documented in COORDINATE_NOTE above —
#                      `build_cabin.py` pre-swaps this before handing it to the
#                      REUSED `city.camera.build_camera`, so store it here as
#                      the real Blender-space point you want the camera at.
#   camera_target      tuple[float, float, float] — same convention as above.
#   camera_focal_length_mm float — camera lens focal length, millimetres.
#   dof_enabled              bool — whether depth-of-field is on.
#   dof_fstop                 float — aperture f-stop when dof_enabled is True.
#   dof_focus_distance          float | None — focus distance in world units;
#                                               None means "autofocus on
#                                               camera_target" (computed by
#                                               city.camera from the
#                                               position-to-target distance).
#   samples                    int — Cycles render samples.
#   resolution                  tuple[int, int] — (width, height) in pixels.

PRESETS: dict[str, dict] = {
    "dusk": {
        # The primary preset: low warm sun, glowing windows and campfire,
        # light fog threading the spruce trunks. 4 deg (not 10) for the same
        # reason as city's dusk preset — below ~5 deg is where Rayleigh
        # scattering actually strips the blue instead of reading as ordinary
        # daylight.
        "sun_elevation_rad": 0.0698,  # 4 deg
        "sun_rotation_rad": 3.9270,  # 225 deg — warm rim light across the cabin's window side
        "sun_strength": 2.5,
        "sky_air_density": 1.8,
        "sky_dust_density": 3.0,
        "sky_ozone_density": 2.4,
        "fog_density": 0.02,
        "campfire_strength": 8.0,
        "window_light_strength": 4.0,
        # ~59 units out and raised, not ~29. At the original distance a 35mm
        # lens filled the frame with one cabin wall; the brief wants the cabin
        # IN a valley — river behind, forest around it — so the shot needs to
        # see most of the 96-block world, not a close-up of the timber.
        "camera_position": (88.0, 8.0, 36.0),
        "camera_target": (45.5, 44.5, 12.0),
        "camera_focal_length_mm": 35.0,
        "dof_enabled": True,
        "dof_fstop": 2.0,
        "dof_focus_distance": None,  # autofocus on camera_target
        "samples": 256,
        "resolution": (1920, 1080),
    },
    "night": {
        # Sun below the horizon; the campfire and windows carry the scene.
        "sun_elevation_rad": -0.0873,  # -5 deg
        "sun_rotation_rad": 3.9270,
        "sun_strength": 0.03,
        "sky_air_density": 1.0,
        "sky_dust_density": 0.6,
        "sky_ozone_density": 1.0,
        "fog_density": 0.03,
        # Raised hard from 10/6. At those values the render was a black frame
        # with four lit rectangles floating in it — the emitters were visible
        # but lit nothing around them, so the cabin had no form at all. The
        # point of the night preset is that these ARE the light, so they have
        # to be strong enough to actually model the walls and ground.
        "campfire_strength": 55.0,
        "window_light_strength": 30.0,
        # Closer than dusk — at night the lit windows and fire are the subject,
        # and the surrounding valley is invisible anyway.
        "camera_position": (74.0, 16.0, 22.0),
        "camera_target": (45.5, 44.5, 11.0),
        "camera_focal_length_mm": 35.0,
        "dof_enabled": False,
        "dof_fstop": 4.0,
        "dof_focus_distance": None,
        "samples": 320,  # small emissive sources need more samples to clean up
        "resolution": (1920, 1080),
    },
    "snow": {
        # Soft daylight winter look — crisper air, less haze than dusk.
        "sun_elevation_rad": 0.4363,  # 25 deg
        "sun_rotation_rad": 2.5307,  # 145 deg
        "sun_strength": 2.8,
        "sky_air_density": 1.2,
        "sky_dust_density": 0.8,
        "sky_ozone_density": 1.0,
        "fog_density": 0.01,
        "campfire_strength": 6.0,
        "window_light_strength": 2.0,  # daylight — less contrast needed
        # Widest of the four: snow is a landscape look, so show the whole valley.
        "camera_position": (96.0, 2.0, 38.0),
        "camera_target": (44.0, 46.0, 12.0),
        "camera_focal_length_mm": 32.0,
        "dof_enabled": True,
        "dof_fstop": 4.0,
        "dof_focus_distance": None,
        "samples": 200,
        "resolution": (1920, 1080),
    },
    "interior": {
        # Camera inside the cabin, looking out — same dusk sky/sun as the
        # `dusk` preset (glimpsed through windows), campfire relocated
        # conceptually to an interior hearth (cabin.py's call whether it
        # reuses the CAMPFIRE block for one).
        "sun_elevation_rad": 0.0698,
        "sun_rotation_rad": 3.9270,
        "sun_strength": 1.0,  # mostly blocked by walls/roof
        "sky_air_density": 1.8,
        "sky_dust_density": 3.0,
        "sky_ozone_density": 2.4,
        "fog_density": 0.0,  # no interior fog
        "campfire_strength": 0.0,  # no exterior campfire visible from inside
        "window_light_strength": 5.0,
        "camera_position": (46.0, 41.0, 10.0),  # inside the footprint
        "camera_target": (45.5, 47.0, 10.5),  # looking toward the back wall/window
        "camera_focal_length_mm": 24.0,  # wide — cramped interior
        "dof_enabled": True,
        "dof_fstop": 1.8,
        # Left as autofocus (None), not an explicit distance: an explicit
        # value has to match the camera-to-target distance exactly (see
        # city's `tiltshift` preset comment for what goes wrong when it
        # doesn't), and at these close interior ranges autofocus is both
        # simpler and safer than hand-computing that distance.
        "dof_focus_distance": None,
        "samples": 200,
        "resolution": (1920, 1080),
    },
}
