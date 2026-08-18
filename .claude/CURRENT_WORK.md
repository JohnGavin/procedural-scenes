# CURRENT_WORK — richard (procedural scenes)

**Last session:** 2026-08-11 (ended 2026-08-18)
**Repo:** `/Users/johngavin/docs_gh/proj/richard` — local git only, **no remote**
**Worktree:** `~/docs_gh/worktrees/richard/feat/cc-20260810-170618`
**Branch:** `feat/cc-20260810-170618` · **16 commits ahead of `main`, unmerged**

---

## Where things stand

Two finished, verified demos plus a generalised web layer. Working tree clean.

### Done

- **Blender 5.2.0 installed via Nix and pinned.** `shell.nix` resolves to the
  exact store path already built; `nix-build --dry-run` fetches 2.62 MiB and no
  Blender. GC root at `.nix-gcroot-blender` (gitignored) protects the 851 MiB
  closure from `nix-collect-garbage`.
- **Cycles Metal GPU confirmed** — `Apple M2 Max (GPU - 38 cores)`. This was the
  main open risk and it resolved favourably.
- **Demo 1 — procedural city** (`blender/city/`, `blender/build_city.py`):
  84 plots → 121 objects, 167 Geometry Nodes instances, four presets, 4–6 s
  per frame.
- **Demo 2 — voxel spruce cabin** (`blender/cabin/`, `blender/build_cabin.py`):
  greedy mesher at **123.7×** reduction, 161 spruce, four presets, 4–10 s.
  Reuses the city's `render.py`/`camera.py` unchanged.
- **Web layer generalised to N demos** via `demos.js`. `gallery.html`,
  `pipeline.html`, `viewer.html` each render a tab per demo with `#hash` deep
  links. Adding a demo is one registry entry.
- `docs/BLENDER.md`, `docs/LESSONS.md`, and four agent-memory files.

### Not done — pick up here

1. **Nothing is pushed.** No remote exists. If this work should survive the
   machine, create one and push the branch.
2. **The branch is unmerged.** 16 commits on `feat/cc-20260810-170618`.
3. Turntable animation implemented in both pipelines, never run end-to-end.
4. Glare/bloom wired but untuned per preset.
5. A third demo would exercise whether the `demos.js` generalisation actually
   holds — that was its whole point and it has only been tested at N=2.

---

## How to run things

```bash
# serve the pages (needed — file:// blocks .glb and source fetches)
python3 -m http.server 8731
#   http://127.0.0.1:8731/gallery.html#cabin
#   http://127.0.0.1:8731/pipeline.html#cabin
#   http://127.0.0.1:8731/viewer.html#cabin

# render
BL=/nix/store/dcga32d59a06hjwvfi1lxzp55v43wah1-blender-5.2.0/Applications/Blender.app/Contents/MacOS/Blender
$BL --background --python blender/build_cabin.py -- --preset dusk
$BL --background --python blender/build_city.py  -- --preset noon

# interactive + path traced (the only route that is both)
$BL --python blender/build_cabin.py -- --preset dusk --no-render
```

---

## Verified facts (do not re-derive)

| Fact | Value |
|---|---|
| Blender | 5.2.0 LTS, nixpkgs, store path `dcga32d59a06…` |
| Cycles device | `METAL`, Apple M2 Max, 38 GPU cores |
| View transform | AgX (default; dynamic enum reports `['NONE']`) |
| Disk | ~32 GB free — the binding constraint |
| Browser | **WebGL is dead in Chrome and Brave** on this machine. Use Edge |
| Machine | M2 Max, 12 CPU cores, 32 GB unified |

---

## Failed approaches — do not retry

| Tried | Outcome |
|---|---|
| Background `Agent` dispatch | **9 failures / 10.** Stalls with zero output; sometimes before creating a worktree. Write the code directly after two failures |
| Telling agents to poll/sleep for a pending tool | The sleep trips the 600 s watchdog. Sequence dependencies instead |
| World volume for atmosphere/fog | Renders pure black — unbounded optical depth. Use a bounded domain box |
| Compositor group fed from `NodeGroupInput` | Empty image, alpha 0. Source from `CompositorNodeRLayers` |
| `export_apply=True` alone for glTF | Silently exports zero Geometry Nodes instances. Add `export_gn_mesh=True` |
| Gating on `bl_rna` enum contents | Dynamic enums report `['NONE']`; stranded the render on CPU. Attempt the assignment, catch `TypeError` |
| Pinning nixpkgs to the registry tarball | Resolved to a *different* store path — would have re-downloaded 851 MiB. `<nixpkgs>` here is a flakehub weekly tree |
| Judging a render by exit code or file size | Every bug this session exited 0 with a plausible file. Sample pixel values and look at the image |

See `docs/LESSONS.md` for the full write-up.
