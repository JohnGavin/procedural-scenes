# Blender scenes

> **Two scenes now share this pipeline.** This document describes the city in
> detail; the voxel cabin (`blender/cabin/`, `blender/build_cabin.py`) reuses
> the same `render.py` and `camera.py` unchanged.
>
> All three web pages handle every scene, with a tab each, driven by the shared
> registry in `demos.js` — adding a demo is one entry there, not three edits:
>
> | Page | What it shows |
> |---|---|
> | `gallery.html` | the stills, with captions on what each demonstrates |
> | `pipeline.html` | the build graph, hover explanations, click-through to source |
> | `viewer.html` | the exported glTF, orbitable in the browser |
>
> They need an HTTP server (`python3 -m http.server 8731`) — `file://` blocks
> the `.glb` and source fetches. Deep-link a scene with `#city` or `#cabin`.

---

## The city, rebuilt in Blender

`buildings.html` draws a procedural city with three.js in the browser. This is
the same city plan rebuilt in Blender 5.2 through the `bpy` API, rendered with
Cycles on the GPU — kept deliberately comparable so the difference you see is
the renderer, not the city.

Same constants, same layout, both versions:

```
PITCH 24 · BLOCK 16 · COLS 5 × ROWS 7 · CORE_R 95
RIVER_X -104, RIVER_W 34 · PARK (112, 6, rx 64, rz 86) · BRIDGE_Z [-12, 36]
```

`blender/city/layout.py` is the single source of truth for all of it. It imports
no `bpy`, so it runs under plain `python3` and can be diffed against the
constants block at the top of `buildings.html`.

## Run it

```bash
nix-shell                       # Blender 5.2.0, pinned — see shell.nix

blender --background --python blender/build_city.py -- --preset noon
```

Presets: `noon`, `dusk`, `night`, `tiltshift`. Useful flags:

| Flag | Effect |
|---|---|
| `--seed N` | different city, same rules (default 7) |
| `--samples N` | override the preset's Cycles samples |
| `--resolution WxH` | override the preset's resolution |
| `--no-render` | build the scene and stop — fast structural check |
| `--save-blend PATH` | write a .blend to open in the GUI |
| `--out DIR` | output directory (default `renders/`) |

Renders land in `renders/`, which is gitignored.

## What Blender does here that three.js cannot

The point of the rebuild is not that it looks nicer. It is that several things
in this scene are *structurally* unavailable to a browser rasteriser.

| Feature | Why three.js can't | Where you see it |
|---|---|---|
| **Cycles path tracing** | Rasteriser: no true global illumination | Colour bleed from lit facades onto the street |
| **Emissive windows that light the city** | An emissive map lights nothing but itself | `night` — the towers are the only light source, and they illuminate the ground |
| **Real glass BSDF** | `MeshStandardMaterial` fakes it with a blue tint | Tower facades genuinely refract and reflect the sky |
| **Geometry Nodes** | No procedural graph; trees are 110 hand-placed meshes | Park scatter — change density or seed and the park repopulates |
| **Physically-based sky** | Approximated, then baked to a static env map | Sun elevation drives the sky, and the sky drives the light |
| **Volumetric atmosphere** | Not available | Aerial perspective; haze thickens toward the horizon |
| **Depth of field** | Post-process approximation only | `tiltshift` — a real lens effect from a real aperture |
| **Procedural node materials** | Needs texture files or canvas hacks | Every surface. No image assets at all |
| **OpenImageDenoise** | — | Usable images at 64–96 samples |

The lane markings are a small but honest example. In `buildings.html` they are
painted into a `<canvas>`, converted to a texture, and tiled. Here they are a
node graph. No canvas, no texture, no tiling seams.

## The four presets

| Preset | Sun | What it demonstrates |
|---|---|---|
| `noon` | 60° | GI, soft shadows, glass, aerial perspective |
| `dusk` | 4° | Warm low sun, window emission starting to read, DOF |
| `night` | −5° (below horizon) | Emissive windows as the *only* meaningful light source |
| `tiltshift` | 55° | f/1.4 miniature effect across the whole city |

Rendering all four at 960×540 / 96 samples takes about 13 seconds total on an
M2 Max.

## Performance

Cycles uses the GPU through Metal. Confirmed at runtime rather than assumed:

```
DEVICE_TYPES ['NONE', 'METAL']
Apple M2 Max (GPU - 38 cores)   METAL   enabled
```

`render.py` detects this at runtime and falls back to CPU cleanly if no GPU
backend is present. Measured, 960×540 @ 96 samples, M2 Max:

| Preset | Render |
|---|---|
| `noon` | 3.5 s |
| `dusk` | 3.9 s |
| `night` | 2.8 s |
| `tiltshift` | 3.8 s |

A 1920×1080 frame at 256 samples is roughly 20–30 s. Turntable animation is
available via `render_animation()` but is **not** wired to a CLI flag by
default — 240 frames is a deliberate decision, not something to trigger by
accident.

## Module layout

```
blender/
  build_city.py        entrypoint; owns the stage order and the ctx object
  city/
    layout.py          the contract: constants, tower_plots(), PRESETS
    materials.py       13 procedural node-graph materials
    terrain.py         ground, river, park, pond, streets, kerbs, bridges
    buildings.py       podium/shaft/crown towers, emissive window grids
    scatter.py         Geometry Nodes park scatter + street furniture
    lighting.py        sky, sun, bounded atmosphere domain
    camera.py          camera, DOF, turntable helper
    render.py          device detection, Cycles config, compositor
```

Stages run in a fixed order and each is wrapped so a failure names the stage
that broke.

## Blender 5.x notes

Several APIs moved in 5.x. Recorded here because each one fails in a way that
is easy to misdiagnose:

- **`sky_type = "NISHITA"` no longer exists.** It split into
  `SINGLE_SCATTERING` / `MULTIPLE_SCATTERING`, and `dust_density` became
  `aerosol_density`.
- **`ShaderNodeTexCoord` has no `World` output.** For world-space coordinates
  use `Geometry > Position`. This matters for the window grids: `Generated` and
  `Object` both stretch with object scale, so window cells would grow with
  tower height.
- **`GeometryNodeResampleCurve.mode` is now an input socket**, not a property,
  and it takes the menu label (`"Length"`).
- **Glare's settings are input sockets**, including the glare mode itself.
- **Dynamic enums report `['NONE']`.** `view_transform`, `look` and
  `compute_device_type` are populated at runtime, so static RNA introspection
  returns nothing useful while assignment works fine. Gating on the introspected
  list silently strands the render on CPU and on the default view transform.
  Attempt the assignment and catch `TypeError` instead.

Two traps that each produce a completely black frame, with no error:

- **A World volume is unbounded.** Every ray that does not hit geometry travels
  to infinity through the medium, so its optical depth is unbounded and it
  extinguishes. Measured 0.00033 mean pixel against 0.968 without it. No density
  is small enough to fix this; the atmosphere has to live in a bounded domain.
- **A scene `compositing_node_group` fed from `NodeGroupInput` outputs an empty
  image.** Blender never feeds that input. Source from a Render Layers node
  instead: 0.00033 mean / 0.000 alpha versus 0.761 / 1.000. This applies even
  when `render.use_compositing` is `False`.

## Reproducibility

`shell.nix` pins nixpkgs by revision and hash, and resolves to exactly the
Blender already in the local store. Verified: `nix-build shell.nix --dry-run`
fetches 2.62 MiB of stdenv tooling and **no Blender**.

A GC root at `.nix-gcroot-blender` (gitignored) stops `nix-collect-garbage`
deleting the 851 MiB closure. If it is ever removed:

```bash
nix-build shell.nix -A blender -o .nix-gcroot-blender
```

## Known limitations

- The Blender and three.js cities are **not** identical building-for-building.
  Both are seeded, but `layout.py` uses Python's `random.Random` rather than
  reimplementing the JS `mulberry32` stream. Same rules and same statistics; a
  different draw.
- Window emission is applied to tall towers (podium/shaft/crown) only, so at
  `night` the low fringe blocks stay dark.
- Turntable rendering is implemented but has had no full-length run.
- The glare/bloom compositor node is wired but its strength has not been tuned
  per preset.
