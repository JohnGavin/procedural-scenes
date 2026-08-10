"""Spruce forest scatter, ground clutter, and the campfire — writes into
`ctx.volume`.

Responsible for populating the world outside the cabin footprint and
clearing: spruce trees (a `Block.SPRUCE_LOG` trunk column topped/wrapped in
a `Block.SPRUCE_LEAVES` canopy — vary height/canopy shape per-tree via a
per-tree seed drawn from `ctx.rng` or `layout.rng(ctx.seed)`, not one fixed
shape stamped everywhere), thinning to nothing within
`layout.CLEARING_RADIUS` of `layout.CABIN_CENTRE` (check horizontal distance
only — trees should not grow through the cabin roof or walls, and should
also respect `layout.RIVER_BASE_X`/`RIVER_WIDTH` so none grow in the
riverbed), a `Block.PATH` from the cabin door toward the clearing edge
and/or the river, and the campfire: a small `Block.CAMPFIRE` cluster a few
blocks in front of the cabin door (with the `campfire_strength` preset key
in mind — `materials.py` reads that, this stage only needs to place the
blocks).

This stage runs AFTER `terrain.build_terrain` and `cabin.build_cabin` (both
of which it must not overwrite — check `blocks.get_block()` returns `AIR`
before placing a tree/path/campfire block, so scatter never grows a tree out
of the cabin's roof or paths through its walls).

Writes into `ctx.volume` via `cabin.blocks.fill_box`/`set_block`/`get_block`.
Consumes `ctx.materials` keys (once `materials.py` is implemented):
`spruce_log`, `spruce_leaves`, `path`, `campfire`. Produces no new
`ctx.materials` keys.

Not yet implemented — stub only.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_scatter(ctx) -> None:
    """Scatter the spruce forest, path, and campfire into `ctx.volume`.

    Args:
        ctx: the `BuildContext` from `build_cabin.py`.
    """
    logger.info("[stub] scatter not yet implemented")
    return
