"""Sun, sky, fog volume, and supplemental point lights.

Responsible for everything driven by the sun/sky/fog keys in
`cabin.layout.PRESETS`: a sun lamp at `ctx.preset["sun_elevation_rad"]` /
`["sun_rotation_rad"]` / `["sun_strength"]`, a Nishita sky background using
`["sky_air_density"]` / `["sky_dust_density"]` / `["sky_ozone_density"]`
(same node setup idea as `city.lighting`, independently built here since
`city`'s module is not part of the reuse list for this package — see
`build_cabin.py`'s module docstring for which two `city` modules ARE
reused), and a world/atmosphere volume scatter domain sized to
`layout.SIZE_X/Y/Z` with density `ctx.preset["fog_density"]` (skip building
the domain entirely when `fog_density` is `0.0` — the `interior` preset —
rather than adding a zero-strength volume Cycles still has to evaluate).

Also responsible for any supplemental point/area lights near `Block.LAMP`
and `Block.CAMPFIRE` positions that a pure Emission-shader surface under-
lights for bounce lighting (see `layout.BLOCK_FLAGS`'s `emissive` docstring)
— this stage would need to inspect `ctx.volume` for those block positions
via `cabin.blocks.get_block`, since `cabin.build_cabin` and
`scatter.build_scatter` are what actually placed them.

This stage runs AFTER `cabin.build_cabin` and `scatter.build_scatter` (so it
can find the LAMP/CAMPFIRE blocks they placed) and BEFORE the REUSED
`city.camera.build_camera` (so depth-of-field autofocus and any future
light-linking has a fully lit scene to reason about, though today neither
actually depends on lighting having run first).

Produces no `ctx.materials` keys — the CAMPFIRE/LAMP material's Emission
*strength* comes from the preset via `materials.py`, not this stage; this
stage only adds lights and the sky/sun/fog, never materials.

Not yet implemented — stub only.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_lighting(ctx) -> None:
    """Build the sun, sky, fog volume, and supplemental lights from
    `ctx.preset`.

    Args:
        ctx: the `BuildContext` from `build_cabin.py`.
    """
    logger.info("[stub] lighting not yet implemented")
    return
