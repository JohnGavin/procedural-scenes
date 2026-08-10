"""Render engine configuration and the actual render/save call.

Two entry points:

- `configure(ctx)` — set the render engine to Cycles, samples from
  `ctx.preset["samples"]`, resolution from `ctx.preset["resolution"]`, and
  wire up compositor nodes (this is where any post-processing this rebuild
  wants to show off — e.g. glare, bloom on `window_emission` materials —
  would live).
- `render(ctx)` — trigger the render and write the output into `ctx.out_dir`
  (created if missing), named after `ctx.preset_name` and `ctx.seed`. Must
  respect the `--no-render` CLI flag, which `build_city.py` handles by
  simply not calling this function — `render.py` itself does not need to
  know about that flag.

Not yet implemented — stub only.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def configure(ctx) -> None:
    """Configure the Cycles render engine, samples, resolution, and compositor.

    Args:
        ctx: the `BuildContext` from `build_city.py`.
    """
    logger.info("[stub] render.configure not yet implemented")
    return


def render(ctx) -> None:
    """Trigger the render and write output into `ctx.out_dir`.

    Args:
        ctx: the `BuildContext` from `build_city.py`.
    """
    logger.info("[stub] render.render not yet implemented")
    return
