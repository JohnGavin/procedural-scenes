"""`city` — the Blender procedural-city package.

No `bpy` import here: this file must stay importable by plain `python3` so
`layout.py` can be unit-tested without a Blender runtime. `bpy`-dependent
modules (`materials`, `terrain`, `buildings`, `scatter`, `lighting`,
`camera`, `render`) are imported directly by `build_city.py`, not re-exported
here, so that importing `city` alone never requires Blender.
"""

from __future__ import annotations

from city.layout import (
    BLOCK,
    BRIDGE_Z,
    COLS,
    CORE_R,
    HALF_X,
    HALF_Z,
    PARK,
    PITCH,
    POND,
    PRESETS,
    RIVER_W,
    RIVER_X,
    ROWS,
    Y,
    Plot,
    col_x,
    river_centre,
    rng,
    row_z,
    tower_plots,
)

__all__ = [
    "BLOCK",
    "BRIDGE_Z",
    "COLS",
    "CORE_R",
    "HALF_X",
    "HALF_Z",
    "PARK",
    "PITCH",
    "POND",
    "PRESETS",
    "RIVER_W",
    "RIVER_X",
    "ROWS",
    "Y",
    "Plot",
    "col_x",
    "river_centre",
    "rng",
    "row_z",
    "tower_plots",
]
