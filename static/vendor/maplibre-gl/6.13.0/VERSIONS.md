# Vendored MapLibre GL JS Module Build

Version: `maplibre-gl@6.13.0` (published 2026-10-06)

License: BSD-3-Clause, retained in `LICENSE.txt`

Upstream package:

- `https://registry.npmjs.org/maplibre-gl/-/maplibre-gl-6.13.0.tgz`
- npm integrity, checked against the downloaded tarball:
  `sha512-ELXk4h+xl0URFQEnVbAN6MGn61P6jq4amUWHiskLVsvHCaKdf1Zq6G8UNOD0AQ3UaXoL5ECc8ovz8yqYEBGPKw==`
- Source: `https://github.com/maplibre/maplibre-gl-js/tree/v6.13.0`

The files were copied from `package/dist/` (and `package/LICENSE.txt`) without modification.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| `maplibre-gl.mjs` | 1079357 | `389731e8581cc59d484e867b051db73ae034a76f0691d2890a2a1a7d2495bdf3` |
| `maplibre-gl-worker.mjs` | 508314 | `53a2dd60f76c7b9201a3cc007b755d98ce4b52403843fef5c90c41780fe62e91` |
| `maplibre-gl.css` | 83290 | `20fc3054e6c769ae9502ec5c7ea46dae05b544fdc4fca2108553fb8c07265bf3` |
| `LICENSE.txt` | 5984 | `ee5fc05a0677eaf69601d2c7db0d9ecd6cc27c3abc1d0733bc9ed34707cf8ef2` |

Only the Site tab's globe flight uses it (`facility_layout_site_globe.js`). The module is
imported on the first flight, not at page load, and it starts its worker from
`maplibre-gl-worker.mjs` beside it.
