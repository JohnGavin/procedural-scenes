"""Material construction — populates `ctx.materials`.

Responsible for building every Blender material/shader node-graph used by
the other stages and registering it in `ctx.materials` under a fixed set of
keys. Every other module reads materials by name from that dict; it never
constructs its own.

Keys this module MUST populate (see `build_city.py`'s `ctx.materials`
docstring for the authoritative list):

    concrete        — building podium/shaft/crown material (or pool of variants)
    glass           — glass tower shaft material (or pool of variants)
    asphalt         — road/downtown-sheet material
    water           — river + pond material
    kerb            — kerbed block-platform material
    bridge          — bridge deck/ramp/pier/railing material
    trunk           — tree trunk material
    leaf            — tree crown material (non-conifer)
    crown           — building rooftop crown/plant-room material
    lane_paint      — dashed lane-marking material
    park_grass      — park lawn material
    gravel          — pond-loop path material
    window_emission — emissive window material, driven by
                       ctx.preset["window_emission"] / ["window_emission_strength"]

Not yet implemented — stub only.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_materials(ctx) -> None:
    """Populate `ctx.materials` with every key listed above.

    Args:
        ctx: the `BuildContext` from `build_city.py`.
    """
    logger.info("[stub] materials not yet implemented")
    return
