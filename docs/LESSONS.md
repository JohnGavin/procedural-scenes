# Lessons from building these scenes

Written 2026-08-11, after the three.js city, the Blender city, and the voxel
cabin. Each item below cost real time and would cost it again.

The same material is mirrored into agent memory at
`~/.claude/projects/-Users-johngavin-docs-gh-proj-richard/memory/` so future AI
sessions inherit it; this file is the human-readable record.

## 1. Exit code 0 proves nothing about a render

**Every single rendering bug in this project exited 0 and produced a
plausible-looking file.** Not one was caught by the exit status.

- A 50 KB PNG that was entirely **transparent** — displayed as white, which read
  as "blown out" rather than "empty".
- Two independent bugs each produced a **fully black frame**: mean pixel 0.00033
  against 0.968 when fixed.
- A glTF export that reported success while containing **zero trees**.

**Do:** sample mean/max pixel values and assert `0.005 < mean < 0.97`. Check
alpha separately. Count nodes in exported artifacts. And **actually look at the
image** — every composition problem here (camera too close, foreground clutter,
dusk indistinguishable from noon) was invisible in logs and obvious in the frame.

**Also:** in background mode `matrix_world`, `object.dimensions` and
`view_layer.objects` are stale until `bpy.context.view_layer.update()`. One
"buildings are flat!" panic was a stale read, not a bug. Measure twice.

## 2. Bisect against a known-good baseline

When the city rendered black, guessing at causes was slow and wrong. Building a
minimal cube-and-sun scene that rendered correctly, then adding our modules one
at a time, found the cause in minutes. Do that early, not late.

## 3. Probe the API, don't recall it

Blender 5.x moved a lot (see `docs/BLENDER.md` for the full list). Every one was
found by introspecting the live runtime. Guessing socket names wasted attempts;
`dir()`, `bl_rna.properties` and a two-line probe script settled each in seconds.

The inverse trap also bit: **`"Fac"` is a valid socket identifier** even though
the display name is `"Factor"`. Nine correct lines were nearly "fixed" into
breakage. Verify before correcting.

## 4. Dynamic enums lie to introspection

`view_transform`, `look` and `compute_device_type` report `['NONE']` under
static RNA introspection while assignment works fine. Gating on that list
silently stranded the render on **CPU** and on the default view transform.
Attempt the assignment; catch the exception.

## 5. A Nix pin is only proven by the store path

Pinning to the nixpkgs *registry* tarball looked right, evaluated fine, and
resolved Blender to a **different store path** than the one already built —
entering that shell would have re-downloaded 851 MiB. `<nixpkgs>` here resolves
to a flakehub weekly tree, not the registry.

**Do:** evaluate the pin and compare the resulting store path against what you
already have; confirm with `nix-build --dry-run`. Add a GC root for large
closures — one under `/tmp` does not count.

## 6. Shared code needs namespaced outputs

`city/render.py` is reused by the cabin pipeline. Its output filename was
hardcoded `city_<preset>.png`, so the first cabin render **silently overwrote
two city renders** — same directory, same names, exit code 0. Caught only by
reading the log line, which announced a filename the cabin pipeline had no
business producing.

**Do:** when a module is shared across pipelines, drive output paths from the
context, not a constant.

## 7. Sequence dependencies before parallelising

Four agents were dispatched while Blender was still downloading. They could not
proceed, and the instruction to poll-and-sleep tripped a no-progress watchdog.
Work survived in their worktrees, but the wall-clock was wasted.

Background agent dispatch failed **9 of 10 times** across these sessions —
usually stalling with zero output. Parallel agents on **disjoint files** is
still the right decomposition (merges were conflict-free whenever agents ran),
but check the worktree before assuming work is lost, and stop retrying after two
zero-output failures.

## 8. Interactivity and light transport are different products

Four PNGs are not a substitute for an orbitable scene, and this was presented as
finished before that trade-off was surfaced. The honest framing:

| | three.js | Cycles stills | Blender GUI |
|---|---|---|---|
| Interactive | yes | no | **yes** |
| True GI / real glass / volumetrics | no | **yes** | **yes** |
| Runs anywhere | **yes** | n/a | no |

The GUI is the only place you get both. Say which one you are delivering.
