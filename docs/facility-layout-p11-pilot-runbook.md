# Facility Layout P11 Pilot Runbook

## Status

This runbook is for controlled pilot preparation. It does not declare the
Industrial Layout Platform release-ready. The generated P11 evidence report
is authoritative about unresolved gates.

## Safety

InspectorPro assists industrial layout planning and validation. It does not
replace required facility, safety, regulatory, or professional engineering
approval.

Every pilot layout requires review by the customer's designated facility,
safety, regulatory, and professional engineering authorities before physical
implementation. Browser feedback is advisory. Backend validation is the
software authority, but it is not regulatory approval.

## Pilot Roles

- Viewer: inspect layouts, proposals, and receipts.
- Editor: create and manually edit layouts and request proposals.
- Approver: approve and apply an exact proposal.
- Catalog curator: manage industrial asset catalog evidence.
- Authority curator: manage facility shells, policy sets, and vehicle profiles.
- Administrator: emergency pilot administration only.

Do not assign a single pilot account broad roles merely to simplify setup.
Keep editor and approver authority separate for write-capable exercises.
Pilot hosts must be constructed with `require_distinct_approver=true`.
Before a write-capable exercise, confirm bootstrap reports
`capabilities.makerCheckerRequired: true`. Stop the pilot if it reports false.
The default single-user local demo may leave this option disabled.

## Pilot Identity Ingress

The default local demo is a single-user mode. Bind it to loopback only and do
not expose it to another machine. A controlled multi-user pilot must terminate
TLS at an authenticated reverse proxy or equivalent trusted client boundary
and inject a distinct Facility Layout bearer identity on every backend
request. Do not place shared pilot bearer tokens in browser JavaScript.

Enable the product-host maker-checker boundary with:

```text
INSPECTORPRO_FACILITY_REQUIRE_DISTINCT_APPROVER=1
INSPECTORPRO_FACILITY_PILOT_IDENTITIES=<closed version 1 JSON document>
```

The identity document contains only SHA-256 token digests, principal IDs,
the exact `local` tenant and `site-local` site scope, and assigned roles. Raw
tokens must be at least 32 printable ASCII characters, must be provisioned
through the authenticated ingress, and must not be logged or committed.
At least one proposal maker and a different approver/apply principal are
required. Duplicate token hashes or principal IDs are rejected.

Startup fails closed when maker-checker mode is enabled without a valid,
distinct identity configuration. Before use, call the bootstrap endpoint
through each account and confirm:

```text
capabilities.principalAuthentication: bearer
capabilities.makerCheckerRequired: true
principal.principalId: <expected account>
```

The bootstrap `principalCapabilities` object is the UI authority for actions
available to that account. Global feature flags do not grant a role action.

## Preflight

1. Run:

   ```powershell
   python tools/verify_facility_layout_p11.py --run-suite-matrix
   ```

2. Review `tests/fixtures/facility_layout/release/p11-release-evidence.json`.
3. Confirm `evidenceGenerationPassed` is true.
4. Do not enable a pilot if any blocker relevant to its intended scope is
   unresolved.
5. Confirm all selected assets have redistribution or customer-use rights.
6. Confirm the site shell, policy set, vehicle profiles, and asset definitions
   are published, revisioned, and current.
7. Confirm offline operation and the WebGL fallback on the pilot workstation.
8. Record the exact application build, browser, GPU, display, and operating
   system.
9. Verify unauthenticated and invalid-bearer bootstrap requests return 401.
10. Verify the maker can propose but cannot approve its own proposal, and the
    distinct checker can approve and apply the exact bound proposal.

The seven Facility Layout feature flags are runtime-wired and default off.
Enable them in dependency order: viewer, asset library, manual editing,
constraints, routing, agent preview, and finally agent write. Do not enable
agent write unless the generated matrix is green for the exact build.

## Controlled Pilot Flow

1. Open the named site and layout.
2. Verify tenant, site, layout, shell, policy, vehicle, and catalog revisions.
3. Build or edit the layout manually first.
4. Run deterministic spatial and routing diagnostics.
5. Ask Sage for a semantic proposal only when the request is unambiguous.
6. Inspect the complete ghost preview in plan and 3D views.
7. Review assumptions, unresolved items, new hard findings, routes, and moved
   manual or automatic placements.
8. Dismiss the proposal if any part is unclear. Dismissal must leave the saved
   layout byte-identical.
9. Have an approver explicitly approve the exact proposal.
10. Apply once and retain the canonical receipt.
11. Reload the layout and retrieve the receipt from durable storage.
12. Obtain the required human engineering and safety approvals outside
    InspectorPro before implementation.

## WebGL and Offline Behavior

- WebGL loss must degrade the 3D view without changing layout identity or
  disabling the independent plan controller.
- WebGL restoration must resume demand-driven rendering.
- A failed or corrupt detail asset must fall back to a deterministic footprint.
- External network requests are not permitted for vendored Three.js runtime
  assets.
- If both the 3D view and plan view are unavailable, stop the pilot session.

## Stop Conditions

Stop agent-write activity immediately for:

- Any unapproved write.
- Any stale or altered proposal applied.
- Any cross-tenant or cross-site disclosure.
- Any receipt that does not match the applied revision and approved binding.
- Any data loss or silent schema conversion.
- Any severity-one safety, authorization, or persistence defect.
- Any repeated WebGL recovery failure that affects the independent plan view.
- Any unresolved source license for an asset intended for redistribution.

Preserve the layout files, receipts, logs, build identity, and reproduction
steps. Do not repair evidence by editing receipts or saved revisions.

## Rollback

The planned rollback order is:

1. Disable agent write.
2. Disable agent preview.
3. Disable routing and constraints if necessary.
4. Keep saved layouts readable.
5. Fall back to manual authoring or the legacy read-only viewer.

Rollback must not delete or convert layout documents. The P11 rollback drill
applies a receipt-backed proposal, cycles the runtime through all-off and
all-on states, proves the canonical layout and file tree remain byte-identical,
retrieves the durable receipt exactly, and confirms consumed proposal state
fails closed.

Proposal previews and approval state are intentionally volatile and fail
closed after restart. Canonical apply receipts are durable. An exact
idempotent retry may return the same canonical receipt; an altered retry must
fail closed.

## Pilot Evidence

For every approved apply, retain:

- Tenant, site, and layout IDs.
- Base and resulting revisions.
- Proposal and alternative IDs.
- Exact diff and dependency fingerprints.
- Approver principal and session binding.
- Idempotency key.
- Canonical receipt ID and SHA-256.
- Reopen/retrieval result.
- Human review outcome.

Do not place raw customer geometry, full labels, notes, or route coordinates in
general telemetry.
