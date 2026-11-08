# Packaging gaps 1-5 (branch packaging-gaps-2026-11-07)

Backend work for the five open gaps in `docs/packaging-shipping-completion-checklist.md`, done while the
rack's field reading and weighing are pending. Based on `dc6c199`. Not ported to the desktop. No UI
file is changed in this commit: the packaging UI is the user's uncommitted work in the real checkout.

## User decisions this follows (2026-11-07)

- Keep the USPS surface-marking rule (Packaging Instruction 9B).
- Do not hard-code "0.002 gauss at 7 ft means ground only". Publication 52 349.42 allows some domestic
  air with packaging, label and documentation, while 349.6 (and 327.12) have broader prohibition wording.
  Record the inconsistency and get a USPS ruling before implementing any eligibility rule.
- Keep the Test-mode connection test apart from the rack's shipping qualification: a separate, labelled
  synthetic ordinary-parcel document is used, and its results are never clearance to ship the racks.
- Leave real shipment eligibility unresolved, but do not let it block an independent connection test.

## What each gap does

1. **Weight provenance on quotes** (`provenance.py`). Every saved quote records `weight_basis`: status
   `estimated` (sum of components) or `measured` (every package weighed packed), per-package components
   (product with its basis, evidence and exclusions; each added mass; inserts, calculated; carton; allowance),
   unknown items and exclusions. It also records `contents` (classification, basis, `transmitted_to_carrier:
   false`, `carrier_acceptance: "not_verified"`) and `account_mode` (declared, observed).
2. **Added product mass** (`Product.additional_mass`, up to 12 `MassItem`s). Each has its own basis
   (`unknown`, `user_measured`, `estimate`) and evidence. A known mass is added to the product's rated mass;
   unknown items are left out and listed (`added_mass_unknown`), never folded into the allowance.
   **Weighed packed carton**: `Package.measured_gross_kg` plus its weighing record becomes the rated
   weight. The component estimate stays beside it (`estimated_gross_kg`, `gross_basis`).
3. **Explicit key mode** (`credentials.py`, `quoting.py`, `rating.py`). The user records the saved key as
   `test` or `production` (`PUT /api/packaging/account/mode`, or `mode` when saving the key). No request
   is sent while the mode is unrecorded (`account_mode_unconfirmed`). Every response's mode is compared
   with the recorded mode. EasyPost reports the mode only in a response, so the request that reveals a
   mismatch has already been sent and its shipment created (a production one may be billed); this check
   cannot prevent or undo that request. It stops the quote at that response (`account_mode_mismatch`):
   nothing is saved, no further shipment is requested and nothing is retried, and the observed mode is
   stored so later quotes with the key are refused before sending until the mode is recorded again or the
   key replaced. Recording the right mode in the first place is the user's check in the EasyPost
   dashboard. Carrier-account listing is refused without a request for a key recorded as test. Modes live in their own table; the sealed v1 key record is unchanged.
   The development environment can set `INSPECTORPRO_PACKAGING_EASYPOST_MODE`.
4. **Contents handling** (`handling.py`). Classes: `unconfirmed`, `ordinary_nonhazardous`,
   `magnetized_material`, `special_handling`, with an optional basis (`product_declaration` or
   `test_assumption`) and evidence. Magnetized and special-handling contents are reported as unsupported
   for rating (`contents_unsupported`), not merely unconfirmed. A test assumption rates, with a warning
   that its rates are not clearance (`contents_test_assumption`). The report lists the documented carrier
   requirements and sources for magnetized material (USPS surface and air, UPS 5X-07, FedEx per 49 CFR
   173.21(d), the EasyPost `CLASS_9_MAGNETIZED` option, which is not sent) and applies no eligibility rule.
   Nothing about contents is sent to carriers.
5. **Movement and restraint** (`restraint.py`). For each product envelope and each of six directions,
   the predicted translational clearance under the bounding-box model: how far the box can slide before
   it meets insert material (pocket voids subtracted), another product or a carton wall, and what stops
   it. Rotation, foam compression and shipping protection are not modelled and remain unverified. Findings: `restraint_movement` (warning), `restraint_insufficient` (error
   against a recorded `Constraints.restraint` requirement), `products_can_touch` (error when the
   requirement asks to separate products), `restraint_not_verified` (work limits). Bounding boxes,
   rigid translation, cylinders as square prisms (travel overstated, never understated). The report row
   passes only against a recorded requirement and says it is not a transport-performance result.

## Compatibility

- Unused new fields are left out of the saved design, so existing design hashes and saved quotes stay
  valid (`test_unused_new_fields_are_left_out_of_the_saved_design`).
- **Behaviour change**: quotes now need a recorded key mode. After a port, the desktop's saved key
  (alias "EasyPost Test", mode not verified) refuses quotes until the user confirms the mode in the
  EasyPost dashboard and it is recorded. The UI has no control for it yet.
- New findings can appear on existing designs (movement, products that can touch). They are warnings
  unless a restraint requirement is recorded.

## UI still needed (in the user's packaging UI)

Key-mode selector and its mismatch message; added-mass rows; weighed-carton entry; contents basis and
evidence; restraint requirement; the per-direction travel table; the weight basis next to each quote.

## Tests

`tests/test_packaging_gaps.py` (offline: MockTransport and a Fernet codec). Existing tests now record
the TEST key's mode: `adapter(..., mode="test")` by default, `mode=None` for the mixed-reply guard,
`mode="production"` for carrier-account listing, and `"mode"` in the store-backed account saves.

## Still open

- The USPS ruling on Publication 52 349.42 against 349.6 and 327.12 (PCSC, 213 and 215.2).
- The packed rack's field reading and weighing.
- Restraint is a translational bounding-box prediction only; rotation, foam compression, drop, vibration,
  compression and stacking stay not evaluated.
