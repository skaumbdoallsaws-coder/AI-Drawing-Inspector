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
