# Vendored Three.js Modules

Version: `three@0.184.0`

License: MIT, retained in `LICENSE`

Upstream package:

- Registry: `https://registry.npmjs.org/three`
- Tarball:
  `https://registry.npmjs.org/three/-/three-0.184.0.tgz`
- Git tag: `https://github.com/mrdoob/three.js/tree/r184`
- npm integrity:
  `sha512-wtTRjG92pM5eUg/KuUnHsqSAlPM296brTOcLgMRqEeylYTh/CdtvKUvCyyCQTzFuStieWxvZb8mVTMvdPyUpxg==`
- Tarball SHA-256:
  `5c8c75278504ff31cedcd736e043b06c18f2cbf220ad7f85fbfaa1a08d3b3626`
- Tarball bytes: `12661342`

The files below were copied without modification from the pinned npm package.
The core and every addon are the same version.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `build/three.core.min.js` | 384222 | `6486aa0d719cfa87ec88dc47223b59b1fb8417a1a407fc0e52467c943e2f8cc9` |
| `build/three.module.min.js` | 364998 | `36a60b0120335f89a80a0dab70292292b0ec414b3d05e83cd09a3ea428c6712a` |
| `examples/jsm/loaders/GLTFLoader.js` | 114959 | `97642d720f16cc9a0c9844934198e4d0c023bea8e89576d0f7545d03b2d103d2` |
| `examples/jsm/utils/BufferGeometryUtils.js` | 35539 | `d700b4c4584b9ff53a04692624d2363019f6d1df2978a207389168c6ae647a65` |
| `examples/jsm/utils/SkeletonUtils.js` | 11535 | `b1632a703206c3d830de9fcbe515696770d04b71a15ee6b50afa6d2c3298c86f` |
| `examples/jsm/controls/OrbitControls.js` | 40504 | `faabb4e8dfd9235ee4a9fd7c9a3d75f90f1689dbd4944bd6fd32117dacec5f93` |
| `examples/jsm/controls/PointerLockControls.js` | 5890 | `40d58db8018b85038939d4d8bff7112d4b8a0ad0367b37ae6f969eeee4310c25` |
| `examples/jsm/loaders/STLLoader.js` | 10715 | `023ed97f848b633d8bcd53d4db3b996d29d0c644088700691297c552257d480b` |
| `examples/jsm/renderers/CSS2DRenderer.js` | 7384 | `dc5f4c5075a3a330b7e679da943343dd86a0f2d745422194b5287e48d7204197` |
| `examples/jsm/environments/RoomEnvironment.js` | 4960 | `55f466192cc84298755a424c5e040345006b2ee1455589b3b54126c2ea4123f4` |
| `examples/jsm/loaders/HDRLoader.js` | 12444 | `fda66a24e0834b8fd166444d695589bf76dab1eb41f40cf1ba66a4fd4a9460ec` |
| `examples/jsm/geometries/DecalGeometry.js` | 10100 | `6b2da6ea840926dfb0278841f96067c02964c73644c7f189720e89fe9baa2b10` |
| `LICENSE` | 1081 | `8b378ebe60e2fe500158cb0ac71cb5e8b7d92953c2abcc63a0eb90499653b5bc` |
| `package.json` | 3574 | `8308e43d6d6dd4c636c2dfe2e724da07dcd9fe4349bba6afb56f2c5ba6625391` |
| `examples/jsm/postprocessing/UnrealBloomPass.js` | 14921 | `1158bb02f6467889aba19c1a788b9107054d7f6a558498b5e2152db5873bb859` |
| `examples/jsm/postprocessing/Pass.js` | 4218 | `444b409c235ead986893c472e720da1b779a56985c7d10b279c7944b52bd61c5` |
| `examples/jsm/shaders/CopyShader.js` | 729 | `a33057d5ac91c43304c186ac0e8816e62bb2ed471d3a00ff3018dfd5c0389718` |
| `examples/jsm/shaders/LuminosityHighPassShader.js` | 1291 | `5044f780b6e6cf863947f64c36fe1587132f7fbe395ada863cd1e5f0388dcf1e` |

The Facility appearance library (2026-10-19) added `RoomEnvironment.js`,
`HDRLoader.js` and `DecalGeometry.js` from the same verified tarball:
neutral reflections, Radiance `.hdr` scene lighting and projected equipment
decals. `HDRLoader` reads uncompressed RGBE files only.

The lighting plan's optional glow halo (2026-10-31, step L6) added
`UnrealBloomPass.js` and the three files it imports (`Pass.js`,
`CopyShader.js`, `LuminosityHighPassShader.js`). They came from the same
tarball, re-downloaded and checked against the SHA-256 and npm integrity
above. `EffectComposer` and `OutputPass` are not included: the halo is drawn
over the normal frame, which keeps its antialiasing and per-material tone
mapping.

No Draco, Meshopt, KTX2, Basis, or other decoder is included or approved by
this manifest. Compression support requires a separate measured dependency
decision.

InspectorPro's legacy viewers use the separately pinned local r128 classic
build. Facility Layout uses these r184 modules in an isolated adapter runtime;
objects are never exchanged between the two Three.js revisions. This boundary
was accepted by the compatibility and lifecycle gates in
`docs/facility-layout-p0-renderer-dependency-spike.md`.
