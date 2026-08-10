"""Spruce forest, written into the voxel volume.

Runs THIRD and last of the volume-writing stages (terrain -> cabin -> scatter),
so it can read what the other two placed and refuse to grow a tree through the
roof or out of the river.

Note this is voxel writing, not Blender Geometry Nodes: the trees become part of
the single world mesh the greedy mesher produces. The city package scatters with
Geometry Nodes because its trees are separate objects; here a tree is just
blocks, and keeping them in the volume means they get the same face-culling and
merging as everything else.
"""

from __future__ import annotations

import logging
import math

from . import layout
from .layout import Block

logger = logging.getLogger(__name__)

#: Trees to attempt. Each rejected placement is cheap, so this is an upper
#: bound rather than a target — the placement rules decide the real count.
ATTEMPTS: int = 900

#: Keep this clear of trunks entirely, so the cabin sits in a clearing.
CLEAR_RADIUS: float = layout.CLEARING_RADIUS * 0.72


def _surface_z(vol, x: int, y: int) -> int | None:
    """Height of the first air block above the ground column, or None.

    Scans downward from the sky, which is much cheaper than up from the bedrock
    and naturally ignores caves we do not have.
    """
    for z in range(layout.SIZE_Z - 1, 0, -1):
        b = vol[x, y, z]
        if b != int(Block.AIR):
            return z + 1
    return None


def _too_near_camera(x: int, y: int) -> bool:
    """True if a tree here would crowd the lens.

    The camera sits among the trees, and a spruce a few blocks in front of it
    fills a third of the frame with an out-of-context slab of bark. Clearing a
    radius around the camera keeps the foreground readable without thinning the
    forest anywhere it actually shows.
    """
    cam = layout.PRESETS["dusk"]["camera_position"]
    return math.hypot(x - float(cam[0]), y - float(cam[1])) < 16.0


def _blocks_view(x: int, y: int) -> bool:
    """True if a tree here would stand between the camera and the cabin.

    The dusk camera looks at the cabin from a fixed spot; a spruce dropped on
    that sight line hides the subject of the entire scene. Cheap 2-D distance
    from the point to the camera-target segment is plenty at this scale.
    """
    cam = layout.PRESETS["dusk"]["camera_position"]
    tgt = layout.PRESETS["dusk"]["camera_target"]
    ax, ay = float(cam[0]), float(cam[1])
    bx, by = float(tgt[0]), float(tgt[1])

    dx, dy = bx - ax, by - ay
    span = dx * dx + dy * dy
    if span <= 0:
        return False
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / span))
    px, py = ax + t * dx, ay + t * dy
    return math.hypot(x - px, y - py) < 4.5


def _spruce(vol, x: int, y: int, base: int, rnd) -> int:
    """Grow one conifer: bare trunk, then tiered canopy narrowing upward.

    Spruce specifically, not a lollipop — at dusk these are read as silhouettes
    against the sky, so the tapering tiered profile is doing almost all of the
    work of saying "pine forest".
    """
    height = rnd.randint(9, 15)
    if base + height + 3 >= layout.SIZE_Z:
        return 0

    placed = 0
    for z in range(base, base + height):
        vol[x, y, z] = int(Block.SPRUCE_LOG)
        placed += 1

    # Canopy tiers: widest low down, shrinking to a tip. Alternate radii give
    # the stepped silhouette real spruces have.
    tier_top = base + height + 1
    tier_bottom = base + max(2, height // 3)
    for z in range(tier_bottom, tier_top + 1):
        frac = (tier_top - z) / max(1, tier_top - tier_bottom)
        # Squared falloff, not linear: a linear taper gives a cone that still
        # reads as a blocky lump. Squaring keeps the skirt wide low down and
        # pulls the upper canopy in sharply, which is the spruce silhouette.
        r = int(round(0.2 + (frac ** 1.6) * 3.4))
        if z % 2 == 0:
            r = max(0, r - 1)                    # the tiering
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if dx * dx + dy * dy > r * r + 1:
                    continue
                px, py = x + dx, y + dy
                if not (0 <= px < layout.SIZE_X and 0 <= py < layout.SIZE_Y):
                    continue
                if vol[px, py, z] == int(Block.AIR):
                    vol[px, py, z] = int(Block.SPRUCE_LEAVES)
                    placed += 1
    if tier_top + 1 < layout.SIZE_Z:
        vol[x, y, tier_top + 1] = int(Block.SPRUCE_LEAVES)
    return placed


def build_scatter(ctx) -> None:
    """Populate the valley with spruce, respecting terrain, cabin and camera."""
    vol = ctx.volume
    rnd = layout.rng(ctx.seed + 4242)
    cx, cy, _ = layout.CABIN_CENTRE

    trunks = 0
    rejected = {"not_grass": 0, "clearing": 0, "sightline": 0, "near_camera": 0, "edge": 0}

    for _ in range(ATTEMPTS):
        x = rnd.randrange(2, layout.SIZE_X - 2)
        y = rnd.randrange(2, layout.SIZE_Y - 2)

        d = math.hypot(x - cx, y - cy)
        if d < CLEAR_RADIUS:
            rejected["clearing"] += 1
            continue

        # Denser toward the edges so the clearing feels enclosed by woodland.
        density = min(1.0, 0.18 + (d - CLEAR_RADIUS) / 42.0)
        if rnd.random() > density:
            continue

        z = _surface_z(vol, x, y)
        if z is None or z + 12 >= layout.SIZE_Z:
            rejected["edge"] += 1
            continue

        # Only on grass: never in the river, on the sand banks, or on the path.
        if vol[x, y, z - 1] != int(Block.GRASS):
            rejected["not_grass"] += 1
            continue

        if _blocks_view(x, y):
            rejected["sightline"] += 1
            continue

        if _too_near_camera(x, y):
            rejected["near_camera"] += 1
            continue

        if _spruce(vol, x, y, z, rnd):
            trunks += 1

    logger.info(
        "scatter: %d spruce planted (rejected: %s)",
        trunks, ", ".join(f"{k}={v}" for k, v in rejected.items()),
    )
