# CURRENT_WORK — richard (3D city scene)

**Last session:** 2026-08-10
**Repo:** `/Users/johngavin/docs_gh/proj/richard` — local git only, **no remote**
**Branch:** `main` · **HEAD:** `ef3b14f`

---

## Where things stand

A working three.js city scene exists and is committed. The next task —
**install Blender and rebuild the scene there, jazzed up** — was started and
interrupted before anything was installed.

### Done

- `buildings.html` — self-contained three.js scene: CBD on a 5×7 block grid,
  meandering river west with two bridges, park east with pond and 110 trees,
  street grid with dashed lane markings, atmospheric sky, cloud billboards.
  Seeded PRNG; `r` reseeds.
- `vendor/` — three.js r180 vendored (4 files, 2.7 MB). Page runs fully
  offline from `file://`. See `vendor/README.md` for source URLs and refresh
  procedure.
- Opens at `file:///Users/johngavin/docs_gh/proj/richard/buildings.html`

### NOT done — resume here

**Blender is not installed.** The last action was `brew info --cask blender`,
which the user interrupted. Nothing was downloaded or installed.

Next step: install Blender (`brew install --cask blender`, ~1–2 GB), then
write a `bpy` script that rebuilds the same city plan and shows off what
Blender does that three.js cannot.

---

## Verified environment facts (do not re-derive)

| Fact | Value |
|---|---|
| Machine | MacBook Pro, Apple M2 Max (Mac14,6) |
| CPU / GPU | 12 cores (8P + 4E) / 38-core GPU, Metal 4 |
| Memory | 32 GB unified |
| Disk | **43 GB free of 926 GB (95% full)** — the binding constraint |
| Browser | **WebGL is dead in Chrome and Brave** (GPU process fails to start). **Use Edge** — confirmed working |

### Research settled this session

- **Karma XPU does NOT support Apple Silicon GPU.** Houdini 22.0 docs:
  *"Karma XPU currently only supports CPU and NVIDIA GPU hardware"*;
  *"Machines without an NVIDIA GPU (e.g. Apple Silicon) will only make use of
  the Embree CPU device."* A web summary claiming a Metal backend exists is
  contradicted by the official docs.
  https://www.sidefx.com/docs/houdini/solaris/karma_xpu.html
- **OpenCL sims DO work** on Apple Silicon (OpenCL 3.0; M1-era Pyro compile
  errors fixed in build 19.5.551). FLIP has a "Use GPU" toggle, device index 0.
- Houdini current version is **22.0**. SideFX no longer publishes prices on
  the buy page — the `~$269/yr` Indie figure quoted earlier is **unverified**.
- **Decision: Blender over Houdini** — Cycles uses the 38-core GPU via Metal,
  Karma would not. Free, ~4 GB vs ~10 GB.

---

## Disk state

Emptied `~/.Trash` (137 items, 58 GB) — verified 0 bytes. **`df` did not
change**: 24 APFS local Time Machine snapshots still reference those blocks,
so the space is *purgeable*, not free. It surfaces automatically under disk
pressure, or immediately via
`tmutil thinlocalsnapshots / 60000000000 4` (deletes local snapshots; external
Time Machine backups unaffected). **Not run — needs user say-so.**

Reclaim options the user declined for now:

| Action | Frees | Risk |
|---|---|---|
| Model caches (lm-studio, whisper, solana, ollama, nomic.ai) | ~27 GB | None — re-downloadable |
| `nix-collect-garbage -d` | 20–40 GB (unconfirmed) | None — rebuildable |
| `~/Downloads/flicks/downloading/` stalled `.!qB` partials | ~10 GB | Low |
| `*_old` dirs (`.pyenv_old`, `venv311_old`, `scikit_learn_data_old`) | ~9 GB | Low |

`~/Downloads/100GOPRO/` (62 GB) is **personal irreplaceable footage — archive,
never delete.** `~/Downloads/flicks/` (94 GB) is media; user's call.

---

## Failed approaches — do not retry

| Tried | Outcome |
|---|---|
| three.js from unpkg CDN only | Works, but offline-fragile. Fixed by vendoring into `vendor/` |
| Opening the scene in Chrome / Brave | Blank screen — WebGL context creation fails, GPU process disabled. Not a code bug. Use Edge |
| `nix-collect-garbage --dry-run` in a non-interactive shell | Returned nothing — `nix` not on PATH there (session banner reports `nix:MISSING`). Re-run inside the Nix shell |
| Emptying Trash to free space | Trash is empty but `df` unchanged — APFS snapshots hold the blocks |

---

## Plan for the Blender scene

Replicate the `buildings.html` layout, then use Blender-specific capability
that three.js cannot match:

- **Geometry Nodes** for procedural block/tower generation and tree scatter
  (rather than hand-placed instances)
- **Cycles + Metal GPU** path tracing — real GI, soft shadows, caustics on water
- **Nishita sky** with physically-based sun angle
- **Volumetric atmosphere** for god rays between towers
- **Emissive window grids** for a dusk/night variant
- **Real glass BSDF** on tower facades with roughness variation
- **Depth of field** for a tilt-shift miniature look
- **Turntable animation** rendered to video
- Optional: **glTF export** back into `buildings.html` for a higher-quality
  interactive web scene

Keep the same layout constants as the three.js version so the two stay
comparable: 5×7 blocks, 24-unit pitch, 16-unit footprints, river west, park
east, arterials at z = −12 and z = 36.
