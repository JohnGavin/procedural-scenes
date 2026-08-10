# Changelog

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
