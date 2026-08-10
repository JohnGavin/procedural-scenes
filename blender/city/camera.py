"""Camera placement, focal length, and depth-of-field.

Responsible for building a Blender camera at `ctx.preset["camera_position"]`
looking at `ctx.preset["camera_target"]` (both three.js-named `(x, y, z)` —
apply the `(x, z, y)` axis remap documented in `city.layout`'s
`COORDINATE_NOTE` before setting `obj.location`), with focal length
`ctx.preset["camera_focal_length_mm"]`. When `ctx.preset["dof_enabled"]` is
True, enable depth-of-field with `ctx.preset["dof_fstop"]` and either an
explicit `ctx.preset["dof_focus_distance"]` or, when that key is `None`,
autofocus by computing the distance from `camera_position` to
`camera_target`. This is one of the things this rebuild should show off that
three.js's `OrbitControls` pinhole camera cannot — real physically-based
depth-of-field (see the `tiltshift` preset).

Not yet implemented — stub only.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def build_camera(ctx) -> None:
    """Build the scene camera from `ctx.preset`.

    Args:
        ctx: the `BuildContext` from `build_city.py`.
    """
    logger.info("[stub] camera not yet implemented")
    return
