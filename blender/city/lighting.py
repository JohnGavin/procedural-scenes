"""Sun, sky (Nishita), volumetrics — everything driven by `ctx.preset`.

Responsible for building a Blender sun lamp positioned from
`ctx.preset["sun_elevation_rad"]`/`["sun_rotation_rad"]`/`["sun_strength"]`;
a Nishita sky world shader driven by `ctx.preset["sky_air_density"]`/
`["sky_dust_density"]`/`["sky_ozone_density"]` (must use the SAME
elevation/rotation as the sun lamp so sky and shadows agree, mirroring how
`buildings.html` derives both the `Sky` object and the `DirectionalLight`
from one shared `sunDir`); and a volume scatter world/object driven by
`ctx.preset["volumetric_density"]`. This is one of the things this rebuild
should show off that three.js's `Sky.js` approximation cannot — real
physically-based Nishita atmospheric scattering plus volumetric god-rays.

Produces no `ctx.materials` keys (works on world/lamp data, not
`ctx.materials`), but MUST read `ctx.preset["window_emission"]` /
`["window_emission_strength"]` only indirectly — the actual window emission
material lives in `ctx.materials["window_emission"]`, built by materials.py;
lighting.py just decides overall exposure/scene brightness to match.

Not yet implemented — stub only.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_lighting(ctx) -> None:
    """Build sun, Nishita sky, and volumetrics from `ctx.preset`.

    Args:
        ctx: the `BuildContext` from `build_city.py`.
    """
    logger.info("[stub] lighting not yet implemented")
    return
