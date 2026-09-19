# Launch InspectorPro

Double-click **InspectorPro - Manual Layout** on the Windows desktop.

The shortcut starts the ordinary local web application when necessary, waits
for it to respond, and opens `fl-reference-manual-20260812` in the default
browser. It reuses a responding InspectorPro instance rather than starting a
new server on each click. It normally uses port 8000; an unrelated server is
not stopped, and a free port in 8000-8009 is selected instead.

This is the **browser version**, not an accepted interactive Electron release.
The native desktop editing/research gates are unchanged. Existing `.env`
configuration and the existing library/layout stores are used without copying
or saving the manual layout.

- Launcher: `scripts/launch_inspectorpro.ps1`
- Shortcut installer: `scripts/install_inspectorpro_shortcut.ps1`
- Startup logs: `.runtime/browser-launcher/`

No terminal commands are needed for normal use. Closing the browser leaves the
local server available for the next launch; restarting Windows stops it, and
the next shortcut launch starts it again. Slow startup may take a minute.
The browser launcher's readiness wait is separate from the unchanged 45-second
managed-Electron acceptance deadline.

Verified on September 15, 2026: startup, second-launch reuse, shortcut target,
manual layout ID/revision, 827 placements, 45 zones, and enabled asset library.
The shortcut was invoked. Browser UI inspection was unavailable through the
connected browser tool; no new screenshot acceptance is claimed. The saved
manual-layout SHA remained `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`.
