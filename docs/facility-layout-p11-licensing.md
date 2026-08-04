# Facility Layout P11 Licensing Inventory

## Scope

The executable inventory covers locally vendored browser JavaScript, the
current industrial asset readiness manifest, and machine-observed metadata for
the direct Python requirements. It records versions, license metadata, source
hashes, and uncovered artifacts without claiming legal clearance.

Generate it with:

```powershell
python tools/verify_facility_layout_p11.py --skip-accelerated-soak
```

Refresh the direct Python evidence and draft notice with:

```powershell
python tools/inventory_facility_python_dependencies.py
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

1. Resolve the machine blockers in the direct Python inventory.
2. Inventory the exact packaged transitive dependencies and required notices.
3. Obtain qualified human review of each governing license path, especially
   PyMuPDF's AGPL/commercial alternatives.
4. Confirm fonts, icons, images, CAD models, fixtures, and sample datasets.
5. Confirm customer-provided assets remain within the customer's authorized
   scope.
6. Preserve license and notice files in the distributed package.

The generated P11 inventory remains blocked until industrial asset rights and
the packaged Python dependency review are complete. This is a distribution
gate, not a browser-runtime uncertainty: the vendored Floating UI and Three.js
artifacts are already hash-bound to retained MIT license texts.

The aggregate verifier fails closed unless all of these independent facts are
true in the source-bound Python inventory:

- The machine dependency assessment passes.
- A qualified human explicitly records approval.
- That approval explicitly claims legal clearance for the reviewed
  distribution.
- The inventory's own release gate is true.

An `approved` field without `legalClearanceClaimed: true`, or a legal approval
that disagrees with the inventory release gate, cannot clear the P11 licensing
gate.
