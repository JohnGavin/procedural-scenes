# Procedural scenes: three.js and Blender

Two procedurally generated scenes, each built twice over — once as an
interactive browser scene and once path traced in Blender's Cycles — so the
difference you see between them is the *renderer*, not the content.

Everything is generated from code. There are **no image textures, no downloaded
models, and no asset packs** anywhere in this repository.

## The scenes

| | |
|---|---|
| **Procedural city** | A CBD on a block grid with height decay toward the core, a meandering river with bridges, and a park. `buildings.html` is the three.js original; `blender/city/` rebuilds the same plan in Cycles. |
| **Spruce cabin at dusk** | A Minecraft-style voxel valley — cabin with a lit interior, campfire, spruce forest, river, evening fog. Generated block by block; no Minecraft, no Mineways, no MCprep. |

## What Cycles buys, and what it costs

The point of building each scene twice is that some things are *structurally*
unavailable to a browser rasteriser:

| Feature | Rasteriser | Cycles |
|---|---|---|
| Emissive surfaces that **light other things** | no | yes |
| True global illumination | no | yes |
| Real glass transmission / refraction | faked | yes |
| Volumetric atmosphere | no | yes |
| Depth of field from a physical aperture | approximated | yes |
| **Interactive** | **yes** | no |

The `night` presets make the trade clearest: in Cycles the lit windows and the
campfire are the only light sources and they illuminate everything around them.
In the browser viewer the same surfaces glow but warm nothing.

Blender's own GUI is the one place you get both — orbit and zoom with Cycles
re-converging live.

## Running it

```bash
nix-shell                       # pinned Blender 5.2, see shell.nix

# render a still
blender --background --python blender/build_city.py  -- --preset noon
blender --background --python blender/build_cabin.py -- --preset dusk

# interactive AND path traced
blender --python blender/build_cabin.py -- --preset dusk --no-render
```

Presets: city `noon dusk night tiltshift`, cabin `dusk night snow interior`.
Add `--seed N` for a different scene under the same rules, `--export-gltf PATH`
for the browser viewer, `--save-blend PATH` for the GUI.

## Browsing it

```bash
python3 -m http.server 8731
```

| Page | What it is |
|---|---|
| `gallery.html` | the rendered stills, with notes on what each demonstrates |
| `pipeline.html` | the build pipeline as a diagram — hover any node or edge, click through to the code |
| `viewer.html` | the exported scenes, orbitable in the browser |
| `buildings.html` | the original three.js city |

An HTTP server is required: `file://` blocks the `.glb` and source fetches.
Each page has a tab per scene and takes a `#city` / `#cabin` deep link.

Adding a scene means one entry in `demos.js` — the pages are generic renderers
over that registry.

## Notes

- `docs/BLENDER.md` — feature-by-feature comparison and the Blender 5.x API
  changes this ran into, several of which fail silently.
- `docs/LESSONS.md` — what went wrong and why, including two separate bugs that
  each rendered a completely black frame while exiting successfully.
- `shell.nix` pins nixpkgs by revision and hash. Cycles uses the GPU via Metal
  on Apple silicon; it falls back to CPU cleanly.
- `vendor/` holds unmodified three.js r180 build artifacts (MIT) so the pages
  run offline. See `vendor/README.md` for provenance.

Built with [Claude Code](https://claude.com/claude-code).
