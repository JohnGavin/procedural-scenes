"""Tower geometry — one mesh (or mesh group) per `city.layout.Plot`.

Responsible for the podium/shaft/crown/mast construction that
`buildings.html`'s `tower()` does, driven entirely by `ctx.plots` (already
resolved by `city.layout.tower_plots()` — no layout maths happens here, only
geometry + material assignment). Use `plot.seed` (via `random.Random(plot.seed)`)
for any further per-building random choices (podium height, crown height,
mast presence, rooftop plant, colour variant) so the choices are
reproducible without disturbing `ctx.rng`.

Consumes from `ctx.materials`: `concrete`, `glass`, `crown`,
`window_emission` (when `ctx.preset["window_emission"]` is True).
Produces no new `ctx.materials` keys.

Not yet implemented — stub only.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_buildings(ctx) -> None:
    """Build every tower in `ctx.plots`.

    Args:
        ctx: the `BuildContext` from `build_city.py`.
    """
    logger.info("[stub] buildings not yet implemented")
    return
