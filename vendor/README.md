# vendor/ — three.js r180

Vendored so `buildings.html` runs offline from a `file://` URL with no CDN.
These are unmodified upstream build artifacts — do not edit them.

| File | Source |
|---|---|
| `three.module.js` | https://unpkg.com/three@0.180.0/build/three.module.js |
| `three.core.js` | https://unpkg.com/three@0.180.0/build/three.core.js |
| `addons/controls/OrbitControls.js` | https://unpkg.com/three@0.180.0/examples/jsm/controls/OrbitControls.js |
| `addons/objects/Sky.js` | https://unpkg.com/three@0.180.0/examples/jsm/objects/Sky.js |

Retrieved 2026-08-10. Licence: MIT (three.js, © 2010 three.js authors).

The directory layout mirrors the upstream paths so the import map in
`buildings.html` resolves `three` and `three/addons/…` without any source
changes:

```json
{ "three": "./vendor/three.module.js", "three/addons/": "./vendor/addons/" }
```

## Refreshing to a newer three.js

Bump the version in each URL above and re-download all four files together —
`three.module.js` and `three.core.js` are a matched pair and must not be mixed
across releases. Check the addon files for new bare-specifier imports
afterwards (`grep "from '" addons/**/*.js`); r180 imports only from `three`.
