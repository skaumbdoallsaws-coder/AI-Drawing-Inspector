# Native Facility UI Parity

Date: 2026-09-15 (America/Chicago)

## Finding

The normal desktop shortcut exposed a guarded development profile, not a fully
enabled desktop release. Two integration defects made it unnecessarily different
from the web application:

1. `desktop_runtime_bridge.js` forced `externalCommandSurface: false`, exposing
   the workspace's standalone command row below the existing host ribbon.
2. Attachment renamed `trainFacilityLayoutAuthoring`. This broke the integrated
   workspace CSS and host lookups, including the rules hiding the standalone
   Geometry inspector. The preload unlocked only the central workspace, so the
   existing ribbon and asset-library rail stayed inert.

The independent desktop storage profile also started in the default dark theme;
it does not inherit the browser's saved appearance settings.

## Change

- Keep the existing workspace ID and the host's external-command-surface option.
- Bind preload recovery to that exact existing element.
- Capture the integrated facility command bar, asset-library button, playback
  controls and theme button during attachment. Allow their input only under the
  same verified facility/recovery gate. Replaced or ambiguous surfaces receive
  no inherited grant.
- Keep workflow selectors, global actions, Sage, Save, backend authentication,
  and unsupported workflow operations restricted. No capability flags or
  backend route permissions were expanded.

## Verification

- All **602 Node tests passed**, including the real-session/kernel bridge tests.
  Added coverage for integrated surfaces, frozen/recovery states, detached roots,
  replacement controls, ambiguous selectors and disconnection during attachment.
- Native full-app runs exercised trusted mouse input for Pan, Select, opening
  and closing Asset Library, theme switching, and both Plan/3D tabs. Both runs
  passed these checks, plus two manual edits/Close/Cancel and the uncovered
  Process Map lifecycle refusal.
- Inspected `integrated-facility-3d.png`: the extra command row and standalone
  Geometry pane are absent. This screenshot is not an exhaustive GLB audit.
- Restarted the user's existing native shortcut through normal Close, verified
  the corrected Plan view, switched to light theme, and opened the populated
  asset library through Windows UI input. No equipment was added or saved.

Evidence root, relative to the workspace (one directory above this project):
`.runtime/desktop-acceptance/ui-parity-evidence/`.

| Native run | UI checks | Broader recovery result |
| --- | --- | --- |
| `inspectorpro-runtime-20260915-201324-8f0e2ff9` | Passed | `desktop_acknowledgment_hold_timeout` during pending Apply |
| `inspectorpro-runtime-20260915-201836-ae1ecf31` | Passed | Restart returned `requires-recovery`, with `desktop_held_operation_unsettled` |

Both original reports are retained. The second run was performed after the Node
suite completed; its different failure does not establish a timing fix or prove
that concurrent test load caused the first timeout. Overall native recovery
reacceptance is **pending**, not passed. No timeout was extended and no recovery
requirement was bypassed. Earlier accepted evidence is historical, not proof of
a successful current full rerun.

Both test Electron processes exited with diagnostic streams closed. The user's
normal native app was intentionally left open, with its own managed backend.

Original manual-layout SHA-256 remains:
`a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`.

## Remaining

Diagnose the two retained pending-Apply failures, complete desktop Save/provider
and broader workflow integration, and obtain the corresponding acceptance
evidence before treating this shortcut as a fully enabled application. The
profile continues to use an isolated copy and only the assets prepared for it.
