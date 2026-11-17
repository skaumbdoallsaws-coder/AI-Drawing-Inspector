# MB7 - reference attachments and browser gate

## CHANGED

- `static/facility_layout_chat_attachments.js`: one composer queue now holds model imports and reference files with a shared three-file cap and two-upload limit. It routes drops by MIME type and extension, polls reference records, shows server refusal text, blocks send during checks, ignores results from an old conversation or layout, and clears the sent chips. The first reference chip displays a one-time AI-provider note; localStorage access is wrapped so it cannot block attachment.
- `static/facility_layout_transport.js`: added raw reference POST and scoped GET. The browser supplies Content-Length for the File body; the transport percent-encodes `X-Reference-Name`, reports XHR byte progress, and preserves structured server errors.
- `static/index.html`: added the second `+` menu item and hidden input, updated the drop prompt, wired the input to the shared composer, kept mixed IDs on retry, and changed the visible count to files. The chat payload still omits `attachments` when empty. Bumped the versions of both changed static scripts. New markup text is ASCII and the file remains LF.
- `tools/verify_model_import_chat_browser.py`: allowed only the scoped reference POST in the existing isolated server gate. Added `tools/verify_model_builder_browser.py`, which reuses that harness's temporary roots, blocked external network, forbidden-port check, browser routing and fake chat replies. It builds, registers and places the three requested cookbook assets through host functions and normal operations; applies a finish to the cabinet body; checks reference/menu/chip/payload behavior; and saves 3D screenshots. It makes no Sage or provider call.
- `tests/test_model_import_chat_attachments.js` and `tests/test_model_builder_browser_helpers.py`: pure mixed-chip, transport, privacy-note, retry, stale-response and offline verifier-helper checks.
- Confirmed the MB4b `recordDefaults` adjustment path and the `Built by Sage - <size basis>` asset-card line were already present. Neither consumer was changed.

## TESTS RUN

- `node tests/test_model_import_chat_attachments.js` through hidden `pythonw.exe tools/run_hidden.pyw`: 29/29 passed.
- `node tests/test_facility_layout_transport.js` through the same hidden runner: 31/31 passed.
- `python.exe -m pytest tests/test_model_builder_browser_helpers.py -q -p no:cacheprovider --basetemp=<fresh TEMP folder>` through the hidden runner: 5 passed. This file imports helpers only; it starts no browser, listener or server.
- `python.exe -m pytest tests/test_model_import_browser_harness.py -q -p no:cacheprovider --basetemp=<fresh TEMP folder>` through the hidden runner: 8 passed. This is the existing offline helper file, not the browser verifier.
- `git diff --check`: passed. Changed static and new Python files have LF line endings.

## NOT RUN

- The browser verifier and any server, as instructed. Run outside this sandbox with `python tools/verify_model_builder_browser.py --out <evidence-directory>`. The script writes `report.json` and, on reaching the 3D gate, `floor-sign-receiving-3d.png`, `flammable-cabinet-45gal-3d.png`, `eyewash-station-3d.png`, and `flammable-cabinet-part-finish-3d.png` under that directory. These are expected paths; no screenshots exist yet. It also saves menu, chip and refusal screenshots.
- The whole suite and any live Sage/provider turn.

## DEVIATIONS

- The reference file picker lists the supported formats; a dropped GIF is still routed to the reference endpoint so the server supplies the authoritative `reference_invalid` refusal. This also lets the isolated verifier check the real refusal path.
- Content-Length is set by the browser for a raw File upload. JavaScript does not set that forbidden request header manually.

## OPEN QUESTIONS

- The browser verifier's 3D framing and print legibility require the outside-sandbox screenshot review. Its JSON report records the actual screenshot paths and any console errors against a no-attachment baseline.

## CLAUDE REVIEW AND VERIFICATION (2026-11-17)

Reviewed:
- The composer queue: kinds, the 3-file cap across kinds, polling, refusals that show the server's text, the
  stale-response guard, and the retry snapshot by kind.
- The transport: raw POST, the URL-encoded name, XHR progress.
- The first-use provider note (localStorage inside try/catch), the menu and input markup, and the ?v= bumps.
- The new verifier's isolation: it reuses the import harness's temp roots, guard, forbidden ports and fulfilled
  chat POSTs, and makes no provider call.
No product issues found.

Re-run outside the sandbox:
- node attachments 29/29, transport 31/31;
- pytest browser_helpers 6 (with my addition), browser_harness 8.

Browser verifier (python -m tools.verify_model_builder_browser, outside the sandbox, isolated):
- All 14 checks pass: bootstrap, menu, model ready, reference ready with the first-use note, GIF refused, PDF
  refused while referencePdf is off, mixed send payload, three built models in 3D, part finish in 3D, browser
  errors, no inference and cleanup.
- Evidence: model-builder-night/out/mb7-browser (report.json and screenshots; not in the repo).

Verifier fixes (mine; the app was right both times):
1. Playwright could not read the small JSON body of the refused uploads ("Request content was evicted from
   inspector cache"), so gif_refused failed even though the chip showed the server's own refusal. The response
   status is now always recorded. The code is taken from the body, or, when Chromium has dropped the body, from the
   chip showing the server's exact refusal text for that code. A helper test pins those texts to
   reference_files.py.
2. Chromium logs every 4xx reply to the console, so the two deliberate refusals showed up as new browser errors. The
   check now allows exactly one 422 console line per deliberate refusal (two), no more and no fewer. Every other
   new error still fails.

My look at the 3D screenshots (gotcha a / f):
- Printed text reads correctly and forward in the real 3D view on all three models: RECEIVING, FLAMMABLE / KEEP
  FIRE AWAY, PUSH and EMERGENCY EYEWASH. Print colours match the contact sheets.
- The blue finish on the cabinet's body (a non-print part) leaves the doors and the label print unchanged.
This also covers MB6's "each recipe checked in the app" for these three. The other cookbook items share the same
print and part paths.
