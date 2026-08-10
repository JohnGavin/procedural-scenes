"""Material construction — populates `ctx.materials`.

Responsible for building every Blender material/shader node-graph the other
stages reference by name and registering it in `ctx.materials` under the
keys `layout.BLOCK_MATERIALS` uses (`"grass"`, `"spruce_log"`, `"glass"`,
etc. — see that dict's docstring in `cabin/layout.py` for the authoritative
key list; every value in `BLOCK_MATERIALS` MUST end up as a key here).

Two of those keys need to read the preset, not just build a fixed look:

    "campfire" — Emission strength should come from
        `ctx.preset["campfire_strength"]`.
    "lamp"     — Emission strength should come from
        `ctx.preset["window_light_strength"]`.

`blocks.build_mesh()` looks up materials by these exact key strings and
tolerates missing ones (unfilled slot -> Blender's default grey material),
so this stage can be implemented incrementally without breaking the mesher.

Not yet implemented — stub only.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_materials(ctx) -> None:
    """Populate `ctx.materials` with one entry per `layout.BLOCK_MATERIALS`
    value, plus any preset-driven emission strength (see module docstring).

    Args:
        ctx: the `BuildContext` from `build_cabin.py`.
    """
    logger.info("[stub] materials not yet implemented")
    return
