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
| `examples/jsm/loaders/STLLoader.js` | 10715 | `023ed97f848b633d8bcd53d4db3b996d29d0c644088700691297c552257d480b` |
| `examples/jsm/renderers/CSS2DRenderer.js` | 7384 | `dc5f4c5075a3a330b7e679da943343dd86a0f2d745422194b5287e48d7204197` |
| `LICENSE` | 1081 | `8b378ebe60e2fe500158cb0ac71cb5e8b7d92953c2abcc63a0eb90499653b5bc` |
| `package.json` | 3574 | `8308e43d6d6dd4c636c2dfe2e724da07dcd9fe4349bba6afb56f2c5ba6625391` |

No Draco, Meshopt, KTX2, Basis, or other decoder is included or approved by
this manifest. Compression support requires a separate measured dependency
decision.

InspectorPro's legacy viewers use the separately pinned local r128 classic
build. Facility Layout uses these r184 modules in an isolated adapter runtime;
objects are never exchanged between the two Three.js revisions. This boundary
was accepted by the compatibility and lifecycle gates in
`docs/facility-layout-p0-renderer-dependency-spike.md`.
