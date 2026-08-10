"""`cabin` — the Blender procedural voxel-cabin package.

No `bpy` import here: this file must stay importable by plain `python3` so
`layout.py` (and `blocks.py`'s meshing/benchmarking logic, which only
imports `bpy` inside the one function that needs it) can be exercised
without a Blender runtime. `bpy`-dependent modules (`materials`, `terrain`,
`cabin`, `scatter`, `lighting`) are imported directly by `build_cabin.py`,
not re-exported here, so that importing `cabin` alone never requires
Blender.
"""

from __future__ import annotations

from cabin.layout import (
    AIR,
    BLOCK_FLAGS,
    BLOCK_MATERIALS,
    BLOCK_SIZE,
    CABIN_CENTRE,
    CABIN_ORIGIN,
    CABIN_SIZE,
    CLEARING_RADIUS,
    GROUND_LEVEL,
    PRESETS,
    RIVER_BASE_X,
    RIVER_WIDTH,
    SIZE_X,
    SIZE_Y,
    SIZE_Z,
    Block,
    river_centre_x,
    rng,
)

__all__ = [
    "AIR",
    "BLOCK_FLAGS",
    "BLOCK_MATERIALS",
    "BLOCK_SIZE",
    "CABIN_CENTRE",
    "CABIN_ORIGIN",
    "CABIN_SIZE",
    "CLEARING_RADIUS",
    "GROUND_LEVEL",
    "PRESETS",
    "RIVER_BASE_X",
    "RIVER_WIDTH",
    "SIZE_X",
    "SIZE_Y",
    "SIZE_Z",
    "Block",
    "river_centre_x",
    "rng",
]
