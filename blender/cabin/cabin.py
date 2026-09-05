"""The spruce cabin: frame, walls, gabled roof, windows, hearth and campfire.

Runs SECOND of the volume-writing stages (terrain -> cabin -> scatter), on the
clearing terrain has already levelled. Writes block ids into `ctx.volume` only;
no Blender data is created here.

This building is the subject of the whole scene — the camera points at it and
the entire lighting concept is warm light leaving it. Two things therefore
matter more than they look:

* the interior must be genuinely HOLLOW. A solid box emits nothing through its
  windows, and the scene silently loses its point.
* LAMP blocks must sit in that air with a clear line to the glass, because
  `lighting.py` finds them by scanning the volume and puts real lights there.
"""

from __future__ import annotations

import logging

from . import layout
from .layout import Block

logger = logging.getLogger(__name__)

#: Height of the wall above the floor before the gable starts.
WALL_HEIGHT: int = 5

#: Roof overhang past the walls, in blocks. A roof flush with the wall reads as
#: a shed; the overhang is most of what makes it look like a cabin.
OVERHANG: int = 1


def _foundation(vol, ox: int, oy: int, oz: int, sx: int, sy: int) -> None:
    """A cobble course under the walls so the timber does not meet bare soil."""
    for x in range(ox - 1, ox + sx + 1):
        for y in range(oy - 1, oy + sy + 1):
            if 0 <= x < layout.SIZE_X and 0 <= y < layout.SIZE_Y:
                vol[x, y, oz - 1] = int(Block.COBBLE)


def _shell(vol, ox: int, oy: int, oz: int, sx: int, sy: int) -> None:
    """Log corner posts, plank infill walls, and a plank floor.

    Posts and infill are different blocks on purpose: a single-material box is
    exactly the flat look this is trying to avoid, and the corner posts are what
    make it read as timber-framed.
    """
    for z in range(oz, oz + WALL_HEIGHT):
        for x in range(ox, ox + sx):
            for y in range(oy, oy + sy):
                edge = x in (ox, ox + sx - 1) or y in (oy, oy + sy - 1)
                if not edge:
                    continue
                corner = x in (ox, ox + sx - 1) and y in (oy, oy + sy - 1)
                vol[x, y, z] = int(Block.SPRUCE_LOG if corner else Block.SPRUCE_PLANK)

    # Floor, and hollow out everything above it inside the walls.
    for x in range(ox + 1, ox + sx - 1):
        for y in range(oy + 1, oy + sy - 1):
            vol[x, y, oz] = int(Block.SPRUCE_PLANK)
            for z in range(oz + 1, oz + WALL_HEIGHT):
                vol[x, y, z] = int(Block.AIR)


def _roof(vol, ox: int, oy: int, oz: int, sx: int, sy: int) -> None:
    """Gabled roof, stepped in layers along y, with an overhang.

    Built as descending courses either side of a ridge — the Minecraft idiom,
    and it gives Cycles clean planar surfaces to catch the low dusk sun.
    """
    base = oz + WALL_HEIGHT
    half = (sy + 2 * OVERHANG) // 2

    for step in range(half + 1):
        z = base + step
        if z >= layout.SIZE_Z:
            break
        y_lo = oy - OVERHANG + step
        y_hi = oy + sy - 1 + OVERHANG - step
        if y_lo > y_hi:
            break
        for x in range(ox - OVERHANG, ox + sx + OVERHANG):
            if not (0 <= x < layout.SIZE_X):
                continue
            for y in (y_lo, y_hi):
                if 0 <= y < layout.SIZE_Y:
                    vol[x, y, z] = int(Block.SPRUCE_LOG)
        # Close the gable ends so the roof is not open to the sky.
        for y in range(y_lo, y_hi + 1):
            for x in (ox - OVERHANG, ox + sx - 1 + OVERHANG):
                if 0 <= x < layout.SIZE_X and 0 <= y < layout.SIZE_Y:
                    vol[x, y, z] = int(Block.SPRUCE_PLANK)

    # Cap the ridge line so there is no slot left along the top.
    ridge_z = base + half
    if ridge_z < layout.SIZE_Z:
        y_mid = oy + sy // 2
        for x in range(ox - OVERHANG, ox + sx + OVERHANG):
            if 0 <= x < layout.SIZE_X:
                for y in (y_mid - 1, y_mid, y_mid + 1):
                    if 0 <= y < layout.SIZE_Y:
                        vol[x, y, ridge_z] = int(Block.SPRUCE_LOG)


def _seal_roof(vol, ox: int, oy: int, oz: int, sx: int, sy: int) -> int:
    """Close any hole where interior air can still see the sky.

    Cheap insurance rather than trusting the gable maths: a single missed block
    lets the sky light the interior directly and the warm-window effect dies.
    Returns the number of holes patched, which the verification asserts on.
    """
    patched = 0
    for x in range(ox + 1, ox + sx - 1):
        for y in range(oy + 1, oy + sy - 1):
            z = oz + WALL_HEIGHT
            while z < layout.SIZE_Z:
                if vol[x, y, z] != int(Block.AIR):
                    break
                z += 1
            else:
                vol[x, y, oz + WALL_HEIGHT] = int(Block.SPRUCE_PLANK)
                patched += 1
    return patched


def _windows(vol, ox: int, oy: int, oz: int, sx: int, sy: int) -> int:
    """Glass at eye height on two sides, with wall above and below.

    Two sides rather than one so light spills in more than one direction, which
    is what makes the dusk shot read from more than a single camera angle.
    """
    z = oz + 2
    placed = 0
    for x in (ox + 3, ox + 4, ox + sx - 5, ox + sx - 4):
        for y in (oy, oy + sy - 1):
            if 0 <= x < layout.SIZE_X and 0 <= y < layout.SIZE_Y:
                vol[x, y, z] = int(Block.GLASS)
                placed += 1
    for y in (oy + 3, oy + 4):
        for x in (ox, ox + sx - 1):
            if 0 <= x < layout.SIZE_X and 0 <= y < layout.SIZE_Y:
                vol[x, y, z] = int(Block.GLASS)
                placed += 1
    return placed


def _doorway(vol, ox: int, oy: int, oz: int, sx: int, sy: int) -> None:
    """An open 1x2 doorway with a path doorstep — no door block."""
    dx = ox + sx // 2
    dy = oy + sy - 1
    for z in (oz + 1, oz + 2):
        vol[dx, dy, z] = int(Block.AIR)
    if dy + 1 < layout.SIZE_Y:
        vol[dx, dy + 1, oz] = int(Block.PATH)


def _hearth_and_chimney(vol, ox: int, oy: int, oz: int, sx: int, sy: int) -> None:
    """Cobble chimney up the gable end, with a small hearth inside."""
    hx, hy = ox + 1, oy + 1
    vol[hx, hy, oz + 1] = int(Block.CAMPFIRE)          # fire in the hearth
    for x in (hx, hx + 1):
        for y in (hy, hy + 1):
            for z in range(oz + 1, oz + WALL_HEIGHT + 6):
                if z >= layout.SIZE_Z:
                    break
                if (x, y) == (hx, hy) and z == oz + 1:
                    continue
                if x == hx and y == hy:
                    continue                           # keep the flue clear
                vol[x, y, z] = int(Block.COBBLE)


def _lamps(vol, ox: int, oy: int, oz: int, sx: int, sy: int) -> list[tuple[int, int, int]]:
    """Emissive lamps inside, placed in air near the windows.

    `lighting.py` scans for these and adds real point lights at their positions,
    so where they sit is what actually shapes the warm spill through the glass.
    """
    z = oz + 3
    spots = [(ox + 3, oy + sy // 2, z), (ox + sx - 4, oy + sy // 2, z), (ox + sx // 2, oy + 2, z)]
    placed = []
    for x, y, zz in spots:
        if 0 <= x < layout.SIZE_X and 0 <= y < layout.SIZE_Y and zz < layout.SIZE_Z:
            vol[x, y, zz] = int(Block.LAMP)
            placed.append((x, y, zz))
    return placed


def _campfire(vol, ox: int, oy: int, oz: int, sx: int, sy: int) -> tuple[int, int, int]:
    """Ring of cobble with fire in it, outside the door.

    Offset toward the camera side so it is never hidden behind the cabin — the
    brief makes it a key light source, and a light source you cannot see does
    not sell the shot.
    """
    cx = ox + sx // 2 + 4
    cy = oy + sy + 4
    cz = oz
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            x, y = cx + dx, cy + dy
            if not (0 <= x < layout.SIZE_X and 0 <= y < layout.SIZE_Y):
                continue
            if dx == 0 and dy == 0:
                vol[x, y, cz] = int(Block.CAMPFIRE)
            elif abs(dx) + abs(dy) == 2:
                vol[x, y, cz] = int(Block.COBBLE)
    return (cx, cy, cz)


def _woodpile(vol, ox: int, oy: int, oz: int, sx: int, seed: int) -> None:
    """A couple of stacked logs and a stump — small signs of habitation."""
    rnd = layout.rng(seed + 77)
    x0 = ox - 3
    for i in range(3):
        y = oy + 2 + i
        if 0 <= x0 < layout.SIZE_X and 0 <= y < layout.SIZE_Y:
            vol[x0, y, oz] = int(Block.SPRUCE_LOG)
            if rnd.random() < 0.6:
                vol[x0, y, oz + 1] = int(Block.SPRUCE_LOG)
    sx_stump = ox + sx + 2
    if sx_stump < layout.SIZE_X:
        vol[sx_stump, oy + 1, oz] = int(Block.SPRUCE_LOG)


def build_cabin(ctx) -> None:
    """Write the cabin, hearth, lamps, campfire and woodpile into `ctx.volume`."""
    vol = ctx.volume
    ox, oy, oz = layout.CABIN_ORIGIN
    sx, sy, _ = layout.CABIN_SIZE

    _foundation(vol, ox, oy, oz, sx, sy)
    _shell(vol, ox, oy, oz, sx, sy)
    _roof(vol, ox, oy, oz, sx, sy)
    patched = _seal_roof(vol, ox, oy, oz, sx, sy)
    windows = _windows(vol, ox, oy, oz, sx, sy)
    _doorway(vol, ox, oy, oz, sx, sy)
    _hearth_and_chimney(vol, ox, oy, oz, sx, sy)
    lamps = _lamps(vol, ox, oy, oz, sx, sy)
    fire = _campfire(vol, ox, oy, oz, sx, sy)
    _woodpile(vol, ox, oy, oz, sx, ctx.seed)

    interior_air = 0
    for x in range(ox + 1, ox + sx - 1):
        for y in range(oy + 1, oy + sy - 1):
            for z in range(oz + 1, oz + WALL_HEIGHT):
                if vol[x, y, z] == int(Block.AIR):
                    interior_air += 1

    logger.info(
        "cabin: origin=%s size=%s interior_air=%d windows=%d lamps=%d campfire=%s roof_patched=%d",
        (ox, oy, oz), (sx, sy, WALL_HEIGHT), interior_air, windows, len(lamps), fire, patched,
    )
