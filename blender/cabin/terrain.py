"""Ground, river, snow cover, and the clearing — writes into `ctx.volume`.

Responsible for filling the base terrain into `ctx.volume` BEFORE
`cabin.build_cabin` and `scatter.build_scatter` run (both of those stages
read/write on top of what this stage lays down, so stage order in
`build_cabin.py` matters and must not change): rolling ground around
`layout.GROUND_LEVEL` (some per-column height noise via `ctx.rng` or
`layout.rng(ctx.seed)`, not a perfectly flat slab), the river channel
carved out and filled with `Block.WATER` (using `layout.river_centre_x()`
and `layout.RIVER_WIDTH`), a sandy/muddy bank a block or two either side of
the water, and — thinned out within `layout.CLEARING_RADIUS` of
`layout.CABIN_CENTRE` — a `Block.SNOW` cap on exposed top faces when
`ctx.preset` calls for it (the `snow` preset; check `ctx.preset_name` or add
a dedicated preset key if a boolean is cleaner once this is implemented).

Reads block ids from `cabin.layout.Block`. Writes into `ctx.volume` via
`cabin.blocks.fill_box`/`set_block` (never index the numpy array directly —
see `blocks.py`'s module docstring for why). Produces no `ctx.materials`
keys of its own.

Not yet implemented — stub only.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_terrain(ctx) -> None:
    """Fill ground, river, banks, and (preset-dependent) snow into
    `ctx.volume`.

    Args:
        ctx: the `BuildContext` from `build_cabin.py`.
    """
    logger.info("[stub] terrain not yet implemented")
    return
