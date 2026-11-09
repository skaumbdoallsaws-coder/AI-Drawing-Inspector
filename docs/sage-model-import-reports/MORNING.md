# Sage model import - morning report (2026-11-09)

Branch `sage-model-import` in `Documents\InspectorPro-FloorPlan\model-import`, based on the real repo's 396bc9e.
Codex built every phase, and Claude supervised, tested and committed. The branch is not ported: that happens with the
user.

## What the user gets

1. In a Facility Layout chat with Sage, the "+" button now offers **Attach 3D model (.glb, .zip)**. It is hidden in
   every other chat.
2. Each file becomes a chip that goes waiting -> uploading -> checking -> ready, or refused with its reason. A raw
   .obj/.fbx is turned away at once ("Download the glTF or GLB version"). Chips can be removed or retried.
3. When the message is sent, the attachments go with it. Sage then has three new tools:
   - `inspect_model_import`: parts, materials, size, licence/credit, and pictures of the source;
   - `prepare_model_asset`: a recipe (real size, pivot, rename/merge parts, material fixes, texture caps, copies,
     added simple shapes such as a pot and soil) gives a draft with pictures, which Sage looks at and corrects;
   - `register_model_asset`: installs the draft in the library with its CC BY credit kept.
   Sage's playbook covers licence rules, real-world size, looking before registering, and never altering a credit.
4. The new asset appears in the library without a restart and is placed like any other asset.

## Safety built in

- Downloads are only read by an isolated worker process (`python -I -S -B`, Job Object limits, timeouts, killed with
  its process tree). Nothing from a download is ever imported or executed.
- Limits: 128 MiB per upload. The import store is scoped per site and layout. Drafts are frozen, and registration
  never rebuilds a draft.
- Registration only adds new `asset-import-...` bundles. It never rewrites an existing asset or a placed asset's
  files, and never touches a saved layout. All 648 real catalog revisions are byte-identical under the new code.
- A chat request without attachments is unchanged; its request hash is the same as before.

## Evidence (all run on this machine)

| Check | Result |
|---|---|
| Model-import and neighbouring tests | 777 passed, 4 platform skips |
| Full regression (the 186 baseline failures come from untracked fixtures) | 177 failed / 3833 passed / 9 errors before and after: the same 186 failing ids, no new ones |
| Acceptance on the six real kitchen downloads (`tools/model_import_acceptance.py`) | all pass at their reference sizes |
| Browser check of the real UI on an isolated store (`tools/verify_model_import_chat_browser.py`) | 11/11 pass, no model or network call |
| Independent Codex review of the whole branch | SHIP WITH FIXES; both fixes made; re-review: SHIP |

Acceptance sizes and timings:

| Recipe | Size | Inspect | Prepare |
|---|---|---|---|
| fruit bowl | 0.52 m wide | 16 s | 16 s |
| serving board | 0.41 m deep, 0.32 m high | 3 s | 3 s |
| mugs | 0.095 m high | 1 s | 2 s |
| olive tree in a pot | 1.35 m high | 19 s | 16 s |
| basil pair | 0.30 m high | 14 s | 18 s |
| five vases | 0.88 m wide | 10 s | 12 s |

Browser check details: the menu shows only in the facility chat; a real GLB was ready in 2.5 s; an .obj was
explained; an unsupported zip was refused with its reason; the send payload carried both attachment ids and the chips
cleared.

## Known limits

- **No live Sage run yet.** No model calls were made overnight, so the first real turn (attach, prepare, look,
  register, place) needs the user's account.
- Rigged or skinned models are refused (1 of the 14 downloads: the fridge). Formats are .glb and .zip (glTF + files)
  only.
- Registration needs the private asset library on. The desktop app reads it from the user's normal settings, and the
  kitchen assets already depend on it. Without it, Sage gets a clear "off in this app" message.
- Pre-existing, not from this work: the telemetry store leaves sqlite connections to the garbage collector. This only
  matters for temp-folder cleanup on Windows.

## Commits (396bc9e..)

| Commit | Content |
|---|---|
| a0d4374 | plan rev 3 (agreed with Codex) + reference scripts |
| 8dd7643 | MI0a: reader and isolated worker |
| a20920f | MI0b: recipe, transforms, writer, drafts |
| a012d1c | MI0c: previews and thumbnails |
| 028c4a0 | MI4: chat attachments UI |
| c23480a | MI1, MI2a, MI3a: store and routes, catalog bundles and credit, attachment transport |
| a2676a4 | MI2b, MI3b: registration with receipts, Sage's three tools |
| 2dfdf01 | MI5: acceptance and browser check |
| b4e7267 | final review fixes |
| (this) | this report |

## Porting (MI6, with the user only)

The real working tree has the user's own uncommitted UI work. Before porting:

1. Agree on how to handle that work (commit it, or keep it aside).
2. Make a backup branch.
3. Cherry-pick the branch onto the real HEAD. Overlap is most likely in `static/index.html` and `server.py`.
4. Run the model-import tests and the browser check there.
5. Restart the desktop gracefully and check `?v=20261109-model-import-1`.
6. Do the first live Sage turn together.
