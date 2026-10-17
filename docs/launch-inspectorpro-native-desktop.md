# Launch InspectorPro Native Desktop

Double-click **InspectorPro Desktop** on the Windows desktop. This starts
Electron directly, not the default browser. It uses the normal runtime entry,
not the automated acceptance runner, and stays open for manual use.

The shortcut uses the installed Electron development runtime. It is not a
packaged installer. Its executable and project folders must remain in place.

The ordinary application window and desktop shortcut use the existing blue
InspectorPro logo, not the Electron runtime icon. The multi-resolution Windows
icon is `desktop/assets/inspectorpro.ico`, generated from `static/logo.png` with
`python desktop/tools/build-application-icon.py`. Native branding changes take
effect after closing the application normally and opening the shortcut again.
An older pinned Electron shortcut may need to be unpinned and the InspectorPro
window pinned instead; the installer does not change existing taskbar pins.

## Current Profile - 2026-09-16

The shortcut now selects the normal `--application` entry, not the restricted
managed diagnostic shell. Ordinary web-application functionality is available
through the protected native backend, including editing, explicit Save, the
asset library, and Sage. This does not certify every workflow or AI request.
See [native end-to-end results and known limitations](desktop-application-end-to-end.md).
The [workflow connection checks](desktop-workflow-connections.md) cover native
downloads, panel restoration, existing documents and cross-workflow draft retention.

- Opens `fl-reference-manual-20260812` in the Facility Layout workspace.
- Opens the original manual layout and full asset library, not an acceptance copy.
- Changes remain unsaved until you explicitly use Save. Save now modifies this
  real layout; test-run Saves were confined to isolated copies.
- Uses protected backend port `8480`; the shell starts and owns that backend.
- Does not carry the old diagnostic input locks or endpoint allowlist.
- Model capability, prototype, installed-data, and permission requirements still
  apply. A grayed-out contextual command can legitimately require a selection;
  Save requires a changed draft.

Profile: `../.runtime/desktop-native/application-profile.json`, relative to the
project. Its `dataRoot` contains native profile state and logs; `facilityRoot`
points at the existing application layout store. The old `.lnk` was backed up
with a `.managed-<timestamp>.bak` suffix.

Close the native window normally to let the shell handle pending state and shut
down its owned backend. The separate **InspectorPro - Manual Layout** shortcut
is the browser launcher and is not the native application.

## Sage Gateway - October 1, 2026

The normal profile now enables the model gateway. Facility Layout planning uses
`gpt-6-astra`; routing uses Haiku and web research uses Claude. Close and reopen
the native app, then use a new Sage planning conversation. Existing generation
sessions retain their old binding and are not automatically migrated.

The profile's `modelGateway` field points to `config/sage-gateway.json` and the
private `.runtime/model-gateway/dependencies` installation. No global Python
upgrade or API key in the profile is required. Model selection and rollback are
documented in [the gateway report](sage-model-gateway-implementation.md).
Planning reliability and latency limitations remain open; this default change
does not certify unrestricted generation or demo readiness.

## Recreate the Shortcut

### Authoring Tools Promotion - October 13, 2026

The normal shortcut now uses the project-owned Electron 44.3.0 runtime at
`desktop/node_modules/electron/dist/electron.exe`. It still uses the existing
`--application` profile and opens `fl-private-gym-20261007`. The previous shortcut
was backed up with a `.runtime-target-<timestamp>.bak` suffix. This is the
development desktop runtime, not a new packaged installer.

Decals, Wall Lettering, Component Materials, Interior Walls, Floor Surfaces, and
Replace Asset passed native ribbon/dialog checks on an isolated Gym copy. See
[manual authoring tools](facility-manual-authoring-tools.md) for evidence and
verification limits. Surfaces commands are under **More** when ribbon space is
limited; component finishes are under **Appearance**.

The shortcut installer accepts any valid application startup layout ID.
`-RepairRuntimeTarget` explicitly updates the runtime of an existing normal
shortcut only when its application/profile/Python arguments match exactly;
it backs up the shortcut before changing it.

Run `scripts/install_inspectorpro_native_shortcut.ps1` with absolute `-Electron`
and `-ProfileFile` arguments, plus `-Python` if required. The installer refuses
to overwrite a different shortcut. `-UpgradeManagedProfile` permits an explicit
upgrade of the recognized old managed shortcut, with a backup. Application mode
passes `--application`, never an acceptance-runner or research-unlock flag.

## Historical Launch Verification - 2026-09-15

The following records the older isolated profile, not the current shortcut.

- Launched the installed `.lnk`; its target is `electron.exe`, with normal window
  state and no acceptance-runner or capability-unlock arguments.
- Managed backend reported ready in 5.34 seconds; the shell recorded
  `application-loaded` at 12.22 seconds from startup.
- Inspected the native `InspectorPro` window using Windows Computer Use. The
  manual facility is visible in Plan view, with the Electron menu/title bar and
  no browser address bar. This is startup verification, not full UI acceptance;
  label/ruler crowding and 3D/library interaction remain separate checks.
- Original manual-layout SHA-256 remains
  `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`.
- No application code, capability gates, or saved layout was changed for this
  shortcut. The native app and its owned backend were left running for the user.
