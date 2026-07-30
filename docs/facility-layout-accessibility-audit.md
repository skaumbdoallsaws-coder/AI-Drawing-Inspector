# Facility Layout Automated Accessibility Audit

## Scope

`tools/audit_facility_layout_accessibility.py` loads the production
InspectorPro shell and the real Facility Layout workspace in Chromium. It
collects source-bound automated evidence for:

- Keyboard-only traversal, shortcuts, asset placement, undo, and view tabs.
- Visible `:focus-visible` indicators.
- Accessible roles, names, and ARIA states from the rendered workspace.
- Polite live-region announcements during real actions.
- `prefers-reduced-motion: reduce` behavior.
- WCAG contrast calculations for rendered text and controls in light and dark
  themes.
- Page errors, console errors, and external-network isolation.

The audit does not simulate or claim a manual screen-reader review.

## Run

Start InspectorPro with the Facility Layout rollout flags enabled, then run:

```powershell
python tools/audit_facility_layout_accessibility.py `
  --app-url http://127.0.0.1:8023/ `
  --smoke
```

Run without `--smoke` for the full interaction sequence in both themes:

```powershell
python tools/audit_facility_layout_accessibility.py `
  --app-url http://127.0.0.1:8023/
```

The runner allows only the exact application origin. Every other HTTP or HTTPS
request is aborted and recorded. A caught request to the reserved
`facility-layout-a11y.invalid` origin acts as a blocking canary, and the audit
fails unless Playwright observes that abort without an external response. It
blocks service workers so a prior cache cannot bypass the request policy.

## Evidence

Generated artifacts are written under:

```text
tests/fixtures/facility_layout/accessibility/
```

The raw artifact contains observations, contrast samples, keyboard sequences,
ARIA snapshots, live-region mutations, network records, browser errors, and
source hashes. The summary is derived from raw observations and never trusts a
reported `passed` value without recomputing the required checks.

Focus screenshots are evidence that a keyboard-focused control rendered a
visible indicator. They are not substitutes for keyboard or screen-reader
testing.

## Interpretation

`automatedAuditPassed: true` means every automated category passed and the raw
evidence remains bound to the exact audited sources.

`releaseGateMet` remains `false` while the manual screen-reader checklist is
pending. The automated runner rejects evidence that claims it performed a
manual screen-reader audit.

The audit fails closed when:

- A required category or check is missing.
- A category's reported result conflicts with its observed checks.
- Contrast records are absent, malformed, non-finite, or below threshold.
- Any external response bypasses the blocking policy.
- The source binding is missing, incomplete, duplicated, or stale.
- Sources change during the run.
- The manual checklist artifact is missing or no longer marked pending.
