# Vendored Three.js Classic Build

Version: `three@0.128.0`

License: MIT, retained in `LICENSE`

Upstream files:

- `https://unpkg.com/three@0.128.0/build/three.min.js`
- `https://unpkg.com/three@0.128.0/LICENSE`
- Git tag: `https://github.com/mrdoob/three.js/tree/r128`

The files were copied without modification.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `build/three.min.js` | 603445 | `9274bbcec8d96168626c732b5d31c775aa8cfb7eaa0599bec0c175908a2c1ce2` |
| `LICENSE` | 1081 | `7dddf7c5b8fd10ee654db8857d75d104b5557889aa5a91fc4ca545ea7c07062f` |

This classic build preserves the existing global `window.THREE` contract for
legacy InspectorPro viewers. Facility Layout uses the isolated r184 module
runtime under `../0.184.0/`.

## Assembly viewer add-ons (2026-10-25)

Safety signs and lighting scenes on assemblies (`docs/assembly-signs-scenes-plan.md`) add two classic
(global `THREE`) add-ons from the same release, copied without modification from the npm package:

- Tarball: `https://registry.npmjs.org/three/-/three-0.128.0.tgz`
- npm integrity:
  `sha512-i0ap/E+OaSfzw7bD1TtYnPo3VEplkl70WX5fZqZnfZsE3k3aSFudqrrC9ldFZfYFkn1zwDmBcdGfiIm/hnbyZA==`
  (verified, with the npm SHA-1 `884dacca6a330e45600a09ec5439283f50b76aa6`)
- Tarball SHA-256: `df6a5d06dcd9a361831669f1b6dd081b2a43f9933d7b16de532417cc8d7c6153`; bytes: `6543441`
- The tarball's `build/three.min.js` is byte-identical to the file above.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `examples/js/geometries/DecalGeometry.js` | 8789 | `383cc0638a20ef3b9f53d80f7bed5dca5a85232104c173a1aebac835a51eb63a` |
| `examples/js/loaders/RGBELoader.js` | 12572 | `f6ba8cf5df528f1fd38b749d46cd7799a40b80d4eb1a5c5c072d31b1eae7f816` |
