# Facility Layout P11 Licensing Inventory

## Scope

The executable inventory covers locally vendored browser JavaScript and the
current industrial asset readiness manifest. It records package versions,
license artifacts, file hashes, and uncovered artifacts.

Generate it with:

```powershell
python tools/verify_facility_layout_p11.py --skip-accelerated-soak
```

## Vendored Browser Packages

The verifier inventories:

- `@floating-ui/core` 1.7.5, MIT.
- `@floating-ui/dom` 1.7.6, MIT.
- `three` 0.128.0, MIT.
- `three` 0.184.0, MIT.

Every JavaScript file under `static/vendor/` must be covered by one package
record and a retained license text.

## Industrial Assets

Placement-ready and visual-ready are not equivalent to redistribution rights.
An asset with `publicReady: false` must remain private/local or customer-owned
until its source and redistribution terms are documented.

The current P2 readiness manifest is included by hash in the generated
inventory. Any asset listed under `notPublicReadyAssetIds` blocks public
redistribution.

## Remaining Distribution Review

Before distributing a pilot build:

1. Produce the Python dependency inventory for the exact packaged build.
2. Record each dependency's version, source, license, and required notices.
3. Confirm fonts, icons, images, CAD models, fixtures, and sample datasets.
4. Confirm customer-provided assets remain within the customer's authorized
   scope.
5. Preserve license and notice files in the distributed package.

The generated P11 inventory remains blocked until industrial asset rights and
the packaged Python dependency review are complete. This is a distribution
gate, not a browser-runtime uncertainty: the vendored Floating UI and Three.js
artifacts are already hash-bound to retained MIT license texts.
