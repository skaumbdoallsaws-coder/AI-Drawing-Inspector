# Packaging gaps 1-5 (branch packaging-gaps-2026-11-07)

Work on the five open gaps in `docs/packaging-shipping-completion-checklist.md`, done while the rack's
field reading and weighing are pending. Based on `dc6c199`. Not ported to the desktop. The first commit
(`89faa1b`) is backend only. The second (`42af949`) adds the controls to `static/packaging.js`, a file the
user is also editing (uncommitted) in the real checkout; the two sets of edits touch different functions
and were checked together before any port (see "Desktop port"). The third adds the contents guard
(2026-11-08, see "Contents guard").

## User decisions this follows (2026-11-07)

- Keep the USPS surface-marking rule (Packaging Instruction 9B).
- Do not hard-code "0.002 gauss at 7 ft means ground only". Publication 52 349.42 allows some domestic
  air with packaging, label and documentation, while 349.6 (and 327.12) have broader prohibition wording.
  Record the inconsistency and get a USPS ruling before implementing any eligibility rule.
- Keep the Test-mode connection test apart from the rack's shipping qualification: a separate, labelled
  synthetic ordinary-parcel document is used, and its results are never clearance to ship the racks.
- Leave real shipment eligibility unresolved, but do not let it block an independent connection test.
- (2026-11-08) Sage may recommend a classification but must not confirm the contents or change them from
  unconfirmed or unsupported to ordinary to enable quoting. A contents change needs the user's explicit
  confirmation, enforced by the backend on every editing path.

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
   stored so later quotes with the key are refused before sending until the key is replaced or recorded
   as the mode EasyPost reported (recording the same mode again changes nothing). The observed mode is
   also held in memory, so if the store cannot be written this process still refuses later requests.
   Recording the right mode in the first place is the user's check in the EasyPost dashboard; the alias
   is only a label and no mode is ever inferred from it. Carrier-account listing is refused without a
   request for a key recorded as test. Modes live in their own table; the sealed v1 key record is
   unchanged. The development environment can set `INSPECTORPRO_PACKAGING_EASYPOST_MODE`.
4. **Contents handling** (`handling.py`). Classes: `unconfirmed`, `ordinary_nonhazardous`,
   `magnetized_material`, `special_handling`, with an optional basis (`product_declaration` or
   `test_assumption`) and evidence. Magnetized and special-handling contents are reported as unsupported
   for rating (`contents_unsupported`), not merely unconfirmed. A test assumption is for synthetic
   connection-test parcels only: it can be quoted only with a key recorded as a test key. With the key
   recorded as production (`test_assumption_needs_test_key`, 409) or not recorded
   (`account_mode_unconfirmed`) it is refused before any request. The check is in
   `EasyPostRating.preflight`, which the Rates panel, saved designs and Sage all run before any request or
   reuse. The assessment still warns that its rates are not clearance (`contents_test_assumption`). A real
   product's classification is never changed to get a quote. The report lists the documented carrier
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
  EasyPost dashboard and it is recorded under Rates > Carrier account > Record key mode.
- New findings can appear on existing designs (movement, products that can touch). They are warnings
  unless a restraint requirement is recorded.
- **Behaviour change** (contents guard): an API client that creates, edits, undoes, redoes or saves a
  snapshot whose contents record differs from the saved one must send the user's confirmation
  (`?contents_confirmed=true` on `POST /documents`, `"contents_confirmed": true` in the other bodies).
  Saved designs and hashes are unchanged; the flag is never stored and is left out of idempotency
  fingerprints, so a confirmed retry of the same request is not a "request reused" conflict.

## UI (`static/packaging.js`)

No account-API call is needed to use any of this.

- **Product panel**: added-mass rows (up to 12: name, basis, mass, evidence; an unknown item keeps no
  mass); Contents (class, basis, evidence; a basis only once the contents are classified, and basis and
  evidence go together); a movement requirement (largest allowed clearance 0-50 mm, keep products
  apart, the reason).
- **Carton panel**: the weighed packed carton (gross kg and its weighing record), with the component
  estimate at the last save beside it.
- **Validation panel**: gross basis and component estimate; rate eligibility, including "test key only"
  for a test assumption; one predicted-clearance table per product (direction, clearance, what the
  bounding box meets) under the bounding-box notice.
- **Rates panel**: the key-mode line (`#account-mode`) and, when quoting is blocked, the reason
  (`#quote-block-reason`) with Compare and Refresh disabled: unsaved document, no key, mode not
  recorded, mode mismatch, unsupported contents, failed validation, or a test assumption with the key
  recorded as production. The key status is re-read from the server (a local read; nothing is sent to
  EasyPost) after every quote attempt, so a mismatch shows at once.
- **Carrier account dialog**: a mode choice that always starts unrecorded (a new key never inherits the
  old key's record) and **Record key mode** (`PUT /api/packaging/account/mode`; nothing is sent to EasyPost).
- **Quote results**: each quote's weight basis, the contents at quote time and the key mode (recorded and
  answered); each parcel says whether its rated weight was weighed or estimated.
- **Contents confirmation**: when the server refuses a contents change with
  `contents_confirmation_required`, the editor shows the server's description of the change and asks;
  OK resends the same request once with the confirmation, Cancel saves nothing. Save (create and edit),
  Undo, Redo and Apply saved design go through it. Save snapshot sends no design, so it never changes
  the contents.
- **Fix**: a first press on Save straight after typing in a field was lost: the field's `change` event
  (on blur) rebuilt the header under the pointer. Present at `dc6c199`. The header is now rebuilt only
  when the form first becomes dirty.

## Sage

Sage's quote tool returns the same refusals with plain instructions: `account_mode_unconfirmed`,
`account_mode_mismatch` (do not retry) and `test_assumption_needs_test_key` (do not change the contents
to get a quote).

## Contents guard

The contents record is the classification, its basis and its evidence. Only the user sets or changes it.

- `PackagingService.create`, `change` (edit, undo, redo) and `save_alternative` take the caller as
  `author`: `"user"` from the HTTP routes, `"sage"` from Sage's gateway, `"direct"` (the default) for
  in-process tests. The check runs inside the write transaction, before anything is written, against
  the saved design (for create, against an empty design).
- Sage: any change to the record is refused with `contents_change_needs_user` (403), even toward a more
  restrictive class, and nothing is saved. Sage's tool schemas have no confirmation field, and the
  edit/undo/redo descriptions tell Sage to keep the record as saved and recommend a change in its reply.
  An undo or redo that would change the record is refused the same way.
- The user: a change without `contents_confirmed: true` (a strict boolean) is refused with
  `contents_confirmation_required` (409) and a message naming the change; nothing is saved.
- A contract test (`test_every_production_editing_call_names_its_author`) parses every production module
  and requires each of these calls to name `"user"` or `"sage"`, so no new path can fall back to the
  unguarded default.

## Tests

- `tests/test_packaging_gaps.py` (offline: MockTransport and a Fernet codec). Existing tests now record
  the TEST key's mode: `adapter(..., mode="test")` by default, `mode=None` for the mixed-reply guard,
  `mode="production"` for carrier-account listing, and `"mode"` in the store-backed account saves.
  Mismatch: with a direct key and a saved key (including a failed store write), exactly one request is
  sent; a repeat, a refresh and an account listing are refused with nothing sent, and re-recording the
  same mode does not clear it. Test assumptions: refused on a production or unrecorded key, quoted on a
  test key; declarations quote on either.
- `tests/test_codex_packaging_quotes.py`: the same mismatch and test-assumption refusals through Sage.
- `tests/packaging_gaps_ui.test.cjs`: the UI's pure helpers (field reading, block reasons, mode text,
  movement rows, quote provenance).
- `tests/verify_packaging_gaps_ui.py`: headless browser check, mock only (in-process pilot, temp store,
  MockTransport, external requests aborted): mode selection, blocked quoting, added masses, weighed
  carton, movement table, save and reopen, quote provenance, magnetized contents blocked, a contents
  change that asks first (Cancel saves nothing, OK saves), and a mismatch that stops after the one
  request.
- `tests/test_packaging_contents_guard.py`: the user's routes (create, edit, undo, redo, snapshots), the
  guard itself and the production-caller contract. `tests/test_codex_packaging_tools.py`: Sage's edit,
  undo and redo refused with nothing written, edits that keep the record still saved, and no
  confirmation field in Sage's schemas. HTTP tests that seed classified contents act as the user and
  send the confirmation.

## Desktop port

Prepared, not run. The steps, backup and rollback are in the port plan kept with the local packaging
notes; the port waits for the user's go-ahead and their UI work.

## Still open

- The user's check of the saved key's mode in the EasyPost dashboard, then the live Test-mode
  connection test on a separate synthetic document. Offline and mock tests do not verify the carrier
  integration.
- The USPS ruling on Publication 52 349.42 against 349.6 and 327.12 (PCSC, 213 and 215.2).
- The packed rack's field reading and weighing.
- Restraint is a translational bounding-box prediction only; rotation, foam compression, drop, vibration,
  compression and stacking stay not evaluated.
