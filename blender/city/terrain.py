"""Ground plane, streets, river, bridges, park lawn and pond.

Responsible for everything `buildings.html`'s `terrain()`, `streets()`,
`water()`, `bridges()`, and the lawn/pond part of `parkland()` build: the
1600x1600 ground plane, the downtown asphalt sheet + lane markings + kerbed
block platforms (using `city.layout.col_x`/`row_z`/`HALF_X`/`HALF_Z`), the
river mesh (using `city.layout.river_centre`), the two bridges (using
`city.layout.BRIDGE_Z`), and the park lawn ellipse + pond circle (using
`city.layout.PARK`/`POND`).

Consumes from `ctx.materials`: `asphalt`, `water`, `kerb`, `bridge`,
`lane_paint`, `park_grass`, `gravel`.
Produces no new `ctx.materials` keys.

Not yet implemented — stub only.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_terrain(ctx) -> None:
    """Build ground, streets, river, bridges, park lawn and pond.

    Args:
        ctx: the `BuildContext` from `build_city.py`.
    """
    logger.info("[stub] terrain not yet implemented")
    return
