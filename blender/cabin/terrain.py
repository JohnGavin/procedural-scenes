"""Voxel terrain: rolling ground, a meandering river, the cabin clearing, a path.

Runs FIRST of the three volume-writing stages (terrain -> cabin -> scatter), so
everything else stands on what this lays down. It writes block ids into
`ctx.volume` and creates no Blender data at all — `blocks.build_mesh` turns the
finished volume into geometry once, later.

Everything is derived from `ctx.seed` and the constants in `layout.py`, so the
same seed always produces the same valley.
"""

from __future__ import annotations

import logging

import numpy as np

from . import layout
from .layout import Block

logger = logging.getLogger(__name__)

#: Flat water surface height, in blocks. The brief asks for "gentle river
#: reflections", and a reflection only reads if the surface is a single plane —
#: a stepped or noisy water top scatters the highlight into mush. So the river
#: is filled to exactly this z everywhere, never following the terrain.
WATER_LEVEL: int = layout.GROUND_LEVEL - 1

#: How deep the channel is cut below the water surface. Enough for the bed to be
#: visible through the water without the banks becoming cliffs.
RIVER_DEPTH: int = 3

#: Soil depth under the grass skin before stone takes over.
DIRT_DEPTH: int = 3


def _heightmap(seed: int) -> np.ndarray:
    """Terrain surface height per (x, y) column, in blocks.

    Summed sines rather than true noise: it is cheap, seamless, and at this
    scale reads as gentle woodland relief. The seed only shifts the phases —
    the character of the landscape stays the same, which is what makes the
    scene reproducible while still varying.
    """
    rnd = layout.rng(seed)
    px, py = rnd.random() * 100.0, rnd.random() * 100.0

    xs = np.arange(layout.SIZE_X, dtype=np.float64)[:, None]
    ys = np.arange(layout.SIZE_Y, dtype=np.float64)[None, :]

    h = (
        layout.GROUND_LEVEL
        + 2.4 * np.sin((xs + px) * 0.075)
        + 1.9 * np.cos((ys + py) * 0.061)
        + 1.1 * np.sin((xs + ys) * 0.041)
        + 0.6 * np.cos((xs - ys) * 0.093)
    )
    # Clamp well clear of the volume roof; the cabin, trees and sky all live
    # above this and the mesher would happily let terrain eat the whole box.
    return np.clip(np.round(h), 4, layout.GROUND_LEVEL + 6).astype(np.int32)


def _river_mask() -> tuple[np.ndarray, np.ndarray]:
    """(channel, bank) boolean masks over the x/y grid.

    The centreline comes from `layout.river_centre_x`, so the meander is part of
    the shared contract rather than a local invention — scatter and lighting can
    ask the same question and get the same answer.
    """
    xs = np.arange(layout.SIZE_X, dtype=np.float64)[:, None]
    ys = np.arange(layout.SIZE_Y, dtype=np.int64)[None, :]

    centre = np.array([layout.river_centre_x(int(y)) for y in range(layout.SIZE_Y)])[None, :]
    dist = np.abs(xs - centre)

    # A little wobble on the edge so the bank is not a drawn rectangle.
    wobble = 0.8 * np.sin(ys * 0.31) + 0.5 * np.cos(ys * 0.17)
    half = layout.RIVER_WIDTH / 2.0 + wobble

    channel = dist < half
    bank = (dist >= half) & (dist < half + 2.2)
    return channel, bank


def _clearing_mask() -> np.ndarray:
    """Disc of flattened ground the cabin sits on.

    The cabin needs level ground under its whole footprint, and a cabin sunk
    into a slope on one side looks like a bug rather than a building. Flattening
    a disc slightly larger than the clearing radius also gives the campfire and
    doorstep somewhere sensible to sit.
    """
    cx, cy, _ = layout.CABIN_CENTRE
    xs = np.arange(layout.SIZE_X, dtype=np.float64)[:, None]
    ys = np.arange(layout.SIZE_Y, dtype=np.float64)[None, :]
    return np.hypot(xs - cx, ys - cy) < layout.CLEARING_RADIUS * 0.62


def _fill_columns(volume: np.ndarray, height: np.ndarray) -> None:
    """Stone / dirt / grass layering, vectorised over z.

    One comparison per z-slice against the whole height field beats a Python
    loop over 442k cells by orders of magnitude, and this runs on every build.
    """
    zs = np.arange(layout.SIZE_Z, dtype=np.int32)[None, None, :]
    h = height[:, :, None]

    volume[:] = np.where(
        zs < h - DIRT_DEPTH,
        int(Block.STONE),
        np.where(zs < h - 1, int(Block.DIRT), np.where(zs < h, int(Block.GRASS), int(Block.AIR))),
    ).astype(np.uint8)


def _carve_river(volume: np.ndarray, height: np.ndarray, channel: np.ndarray, bank: np.ndarray) -> None:
    """Cut the channel, lay a sand bed, and fill to a single flat water level."""
    bed = WATER_LEVEL - RIVER_DEPTH

    for z in range(bed, layout.SIZE_Z):
        layer = volume[:, :, z]
        if z < bed + 1:
            layer[channel] = int(Block.SAND)          # bed
        elif z <= WATER_LEVEL:
            layer[channel] = int(Block.WATER)         # flat surface, see WATER_LEVEL
        else:
            layer[channel] = int(Block.AIR)           # nothing above the water

    # Sandy shore wherever land meets the channel, following the real ground.
    ys, xs = np.nonzero(bank)
    for bx, by in zip(ys, xs):
        top = int(height[bx, by]) - 1
        if top < 0 or top >= layout.SIZE_Z:
            continue
        if volume[bx, by, top] == int(Block.GRASS):
            volume[bx, by, top] = int(Block.SAND)


def _flatten_clearing(volume: np.ndarray, height: np.ndarray, clearing: np.ndarray) -> int:
    """Level the cabin site and return the ground height chosen."""
    level = int(layout.GROUND_LEVEL)

    xs, ys = np.nonzero(clearing)
    for bx, by in zip(xs, ys):
        for z in range(level, layout.SIZE_Z):
            if volume[bx, by, z] == int(Block.AIR):
                break
            volume[bx, by, z] = int(Block.AIR)        # shave anything above level
        for z in range(0, level):
            if volume[bx, by, z] == int(Block.AIR):
                volume[bx, by, z] = int(Block.DIRT)   # fill any dip up to level
        volume[bx, by, level - 1] = int(Block.GRASS)
        height[bx, by] = level

    return level


def _path(volume: np.ndarray, height: np.ndarray, seed: int) -> int:
    """A winding path from the cabin door toward the river bank.

    Deliberately not a straight line — a ruler-straight path through woodland
    reads as programmer-art. It wanders by a block or two as it goes.
    """
    rnd = layout.rng(seed + 991)
    cx, cy, _ = layout.CABIN_CENTRE
    start_x = int(cx)
    y = int(cy)

    placed = 0
    x = start_x
    while x > 2:
        x -= 1
        if rnd.random() < 0.45:
            y += rnd.choice((-1, 1))
        y = max(1, min(layout.SIZE_Y - 2, y))
        for dy in (0, 1):
            yy = min(layout.SIZE_Y - 1, y + dy)
            top = int(height[x, yy]) - 1
            if 0 <= top < layout.SIZE_Z and volume[x, yy, top] in (int(Block.GRASS), int(Block.DIRT)):
                volume[x, yy, top] = int(Block.PATH)
                placed += 1
    return placed


def build_terrain(ctx) -> None:
    """Write ground, river, clearing and path into `ctx.volume`."""
    volume = ctx.volume
    height = _heightmap(ctx.seed)

    _fill_columns(volume, height)

    channel, bank = _river_mask()
    _carve_river(volume, height, channel, bank)

    clearing = _clearing_mask()
    level = _flatten_clearing(volume, height, clearing)

    path_blocks = _path(volume, height, ctx.seed)

    water = int((volume == int(Block.WATER)).sum())
    logger.info(
        "terrain: height %d-%d, clearing level %d, water %d blocks, path %d blocks",
        int(height.min()), int(height.max()), level, water, path_blocks,
    )
