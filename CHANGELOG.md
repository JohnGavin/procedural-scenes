# Changelog

## 2026-08-10 (later) — Blender rebuild

### Completed

- **Installed Blender 5.2.0 LTS via Nix.** Verified before starting that
  `meta.platforms` includes `aarch64-darwin`, `broken = false`, and that the
  whole closure substitutes from `cache.nixos.org` — 189 paths, 851 MiB
  download, 2.88 GiB unpacked, **nothing compiled**.
- **Cycles Metal GPU confirmed working**: `DEVICE_TYPES ['NONE', 'METAL']`,
  `Apple M2 Max (GPU - 38 cores)`. This was the open risk — nixpkgs could
  plausibly have shipped Cycles CPU-only on Darwin. It did not.
- **Pinned the Nix environment** (`shell.nix` + a GC root at
  `.nix-gcroot-blender`) so the closure cannot be re-downloaded or collected.
- **Rebuilt the city in Blender**: 7 modules, ~2,900 lines, against a frozen
  `layout.py` contract shared with `buildings.html`. Four presets — `noon`,
  `dusk`, `night`, `tiltshift` — all rendering in 2.8–3.9 s at 960×540 / 96
  samples on the GPU.
- Written in parallel by four agents in separate git worktrees on disjoint
  files, then integrated and debugged centrally.
- `docs/BLENDER.md` — run instructions, feature-by-feature comparison against
  the three.js version, and the 5.x API notes.

### Failed Approaches

- **Dispatching the four parallel agents before Blender finished downloading.**
  All four stalled waiting on a binary that did not exist yet; two tripped a
  600 s no-progress watchdog while sleeping in the poll loop they had been told
  to use. No work was lost (all seven modules survived in their worktrees) but
  the wall-clock cost was real. Sequence the dependency next time, or dispatch
  with work that does not need the tool.
- **A World volume for the atmosphere.** Renders pure black: an unbounded
  medium gives every sky-bound ray infinite optical depth. Measured 0.00033
  mean pixel vs 0.968 without. Replaced with a bounded domain object.
- **A scene `compositing_node_group` sourced from `NodeGroupInput`.** Also
  renders pure black with zero alpha — Blender never feeds that input. Must
  source from a Render Layers node. Applies even with `use_compositing = False`.
- **Pinning `shell.nix` to the nixpkgs registry tarball.** Looked correct, but
  evaluated Blender to a *different* store path than the one already built, so
  entering the shell would have silently re-downloaded 851 MiB. `<nixpkgs>` on
  this machine resolves to a flakehub weekly tree. Caught only by checking that
  the pin resolved to the same store path.
- **Trusting `bl_rna` enum introspection.** `view_transform`, `look` and
  `compute_device_type` are dynamic enums that report `['NONE']` while
  assignment works. Gating on that list had stranded the render on CPU and on
  the default view transform.

### Accuracy / Metrics

- `tower_plots(7)` → 84 plots → 121 building objects; z-range 1.2–83.6, bases
  exactly on `Y.kerb_top`.
- Geometry Nodes park scatter → **167 instances**, verified via the evaluated
  depsgraph (a count of 0 is the classic silent mis-wiring, so it was asserted
  rather than eyeballed).
- All four presets verified non-blank by sampling mean pixel values, not by
  checking that the file exists — an early "success" was a 50 KB PNG that was
  entirely transparent.
- `nix-build shell.nix --dry-run` → 16 paths / 2.62 MiB, Blender absent.

### Known Limitations

- The two cities are not identical building-for-building: `layout.py` uses
  `random.Random` rather than reimplementing the JS `mulberry32` stream.
- Window emission covers tall towers only; fringe blocks stay dark at `night`.
- Turntable animation is implemented but has never been run to completion.
- Glare/bloom is wired but untuned per preset.
- The four agents' own verification suites never ran — the modules were
  verified centrally at integration instead, which caught real bugs but is
  less thorough per-module than what was specified.

## 2026-08-10

### Completed

- Created the project and initialised a local git repo (`main`, no remote).
- `buildings.html` — self-contained three.js scene, built in two stages:
  1. A simple 9×9 grid of extruded boxes with orbit controls and shadows.
  2. Rebuilt as a full city plan: CBD on a 5×7 block grid with height decay
     over a 95-unit core radius, podium/shaft/crown towers, a meandering
     river to the west with two road bridges, a park to the east with pond
     and 110 trees, a street grid with canvas-drawn dashed lane markings,
     atmospheric-scattering sky baked to an environment map, and procedural
     cloud billboards.
- Vendored three.js r180 into `vendor/` (4 files, 2.7 MB) and repointed the
  import map, so the page runs offline from a `file://` URL with no CDN.
- Surveyed disk usage (read-only) and emptied `~/.Trash` (137 items, 58 GB).
- Researched Houdini viability on this hardware; chose Blender instead.

### Failed Approaches

- **three.js from CDN only.** Worked, but left the page dependent on unpkg
  and unusable offline. Fixed by vendoring the four modules into `vendor/`.
  Note `three.module.js` re-exports from `three.core.js` — the pair must be
  downloaded together and never mixed across releases.
- **Opening the scene in Chrome / Brave.** Blank screen with
  `WebGL context could not be created … GL_VENDOR = Disabled`. The GPU
  process was not running; not a code fault. Works in Edge. An SVGRenderer
  fallback was started and abandoned once Edge was confirmed working.
- **`nix-collect-garbage --dry-run`** returned no output — `nix` is not on
  PATH in a non-interactive shell (session banner reports `nix:MISSING`).
  Must be re-run inside the Nix shell to size the reclaim.
- **Emptying Trash to free disk.** `~/.Trash` verified at 0 bytes, but `df`
  still reported 43 GB free: 24 APFS local Time Machine snapshots still
  reference the blocks, so the space is purgeable rather than free.

### Accuracy / Metrics

- `buildings.html`: 457 lines, syntax-checked with `node --check`. Rendering
  verified by the user in Edge; not verified by automation.
- Vendored dependency tree confirmed closed — both addons import only from
  `three`; `three.core.js` has no further relative imports.
- Hardware: M2 Max, 12 CPU cores, 38 GPU cores, 32 GB unified, Metal 4.
- Disk: 43 GB free of 926 GB (95% full).

### Known Limitations

- **Blender is not installed.** The install was interrupted before any
  download began. This is the next task.
- No remote repository — everything is local only.
- The scene's render output is unverified by automation; only a human has
  confirmed it displays.
- Chrome and Brave cannot display the scene on this machine until their GPU
  process is repaired.
- Disk remains the binding constraint for any 3D tooling; ~130 GB of
  zero-risk reclaim is identified but unexecuted.

### Research Findings

- Karma XPU does not support Apple Silicon GPU — CPU (Embree) only. Houdini
  22.0 docs. This is why Blender was chosen: Cycles uses Metal, Karma does not.
- Houdini OpenCL simulation *does* work on Apple Silicon (fixed in 19.5.551).
- SideFX no longer publishes tier pricing publicly; the `~$269/yr` Indie
  figure cited mid-session is unverified and should not be relied on.
