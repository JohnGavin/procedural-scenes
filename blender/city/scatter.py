"""Park trees + sky clouds — the scattered/instanced dressing.

Responsible for what `buildings.html`'s tree loop in `parkland()` and
`clouds()` do: ~110 trees scattered inside the park ellipse (excluding a
buffer around the pond), each a trunk + a conifer cone or a broadleaf blob;
plus soft cloud billboards scattered high above the scene. Consider Geometry
Nodes instancing here — this is exactly the kind of workload it exists for,
and it is one of the things this Blender rebuild should show off that the
three.js version cannot.

Consumes from `ctx.materials`: `trunk`, `leaf`.
Produces no new `ctx.materials` keys.
Uses `ctx.rng` (or a derived seed) for scatter placement — NOT `plot.seed`,
which belongs to `buildings.py`.

Not yet implemented — stub only.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_scatter(ctx) -> None:
    """Scatter park trees and sky clouds.

    Args:
        ctx: the `BuildContext` from `build_city.py`.
    """
    logger.info("[stub] scatter not yet implemented")
    return
