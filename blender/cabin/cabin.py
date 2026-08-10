"""The cabin structure itself — walls, roof, door, windows, interior.

Named `cabin.py` inside the `cabin` package (so the stage is invoked as
`cabin.build_cabin`, matching `materials.build_materials` /
`terrain.build_terrain` / `scatter.build_scatter` /
`lighting.build_lighting`'s "module name == stage verb" pattern) —
`build_cabin.py` imports it as `from cabin import cabin as cabin_stage` (or
similar) to keep the package name and the module name visually distinct at
the call site.

Responsible for carving/placing the log-cabin structure into `ctx.volume`
within `[layout.CABIN_ORIGIN, layout.CABIN_ORIGIN + layout.CABIN_SIZE)`:
`Block.SPRUCE_LOG` corner posts and wall courses (or `SPRUCE_PLANK` for a
milled-lumber look — pick one consistent style), a hollow interior (leave
`Block.AIR`, do not fill solid), a door gap at floor level, `Block.GLASS`
window openings sized to read clearly at the camera distances in
`layout.PRESETS` (a single-block slit will disappear at the `dusk`/`snow`
preset's camera distance — check against `ctx.preset["camera_position"]`),
`Block.LAMP` blocks near windows/interior for the warm light spill the
brief asks for, a peaked roof (COBBLE or SPRUCE_PLANK), and — for the
`interior` preset specifically — whatever the `interior` camera in
`layout.PRESETS["interior"]` needs to see (a floor, a hearth, furnishing
blocks) that an exterior-only camera would never expose as missing.

This stage runs AFTER `terrain.build_terrain` (so the cabin is built on top
of already-placed ground, not floating over a not-yet-existing one) and
BEFORE `scatter.build_scatter` (so scatter can avoid placing trees inside
the footprint using `layout.CABIN_ORIGIN`/`CABIN_SIZE` — trust this stage to
have already carved the shape scatter must respect).

Writes into `ctx.volume` via `cabin.blocks.fill_box`/`set_block`. Consumes
`ctx.materials` keys (once `materials.py` is implemented): `spruce_log` or
`spruce_plank`, `glass`, `lamp`, `cobble`. Produces no new `ctx.materials`
keys.

Not yet implemented — stub only.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_cabin(ctx) -> None:
    """Carve/place the cabin structure into `ctx.volume`.

    Args:
        ctx: the `BuildContext` from `build_cabin.py`.
    """
    logger.info("[stub] cabin structure not yet implemented")
    return
