# Codex Desktop Deployment

## Current Authentication: ChatGPT Plan

The regular local profile was switched to independent Sign in with ChatGPT
(SIWC) subscription sharing on **2026-10-16**. Facility Layout Sage uses
`gpt-6.1-sol`; the connected account's model catalog does not expose the previous
API model. No automatic model or API-key fallback is permitted. This verifies
technical development access, not commercial-distribution approval.

The profile retains its existing identity, data roots, Private Gym startup
document, dependency bundle and edit-approval controls. Only `codexRuntime`
changed: `schemaVersion: 2`, `authMode: "chatgpt_plan"`,
`allowPaidInference: false`, `model: "gpt-6.1-sol"`, and
`credentialTarget: "InspectorPro/ChatGPT/inspectorpro-application"`.

- Press Alt to reveal the native menu, then use **Sage > ChatGPT account** for
  sign-in, account switching or sign-out. Manual workflows work while signed out.
- Account records and tokens are encrypted with Windows user-scoped DPAPI in
  `<dataRoot>/chatgpt-auth/accounts.sqlite`. They are not stored in profile JSON,
  renderer storage, tool arguments or logs. API vault credentials remain untouched.
- OAuth uses PKCE, state, nonce and verified ID-token signatures/claims. Refresh
  token rotation is serialized through SQLite; account changes invalidate active
  tool leases. Threads are bound to account identity as well as document identity.
- The runtime receives only the selected OAuth access token in its isolated child
  environment. No personal Codex session/cache is imported. No toolkit code is used.
- Subscription failures stop the request. Other, unmigrated Sage/agent routes and
  the legacy paid cross-agent summarizer are blocked in this mode instead of
  silently invoking a paid API. Other non-Sage AI workflows are not migrated by
  this change and may retain their own independently configured providers.
- The pinned model catalog forces code mode and multi-agent tools despite ordinary
  feature flags. The adapter derives a single-model catalog from the pinned binary,
  clears those forced tool modes, disables local REPL and hosted tool discovery,
  and uses standard Responses streaming. The model identity is unchanged.
  MCP functions are enumerated directly because SIWC rejects hosted `tool_search`.
  The real runtime's native-tool inventory and read-only write rejection were tested.
- Public research uses the same subscription, streamed Responses, explicit source
  provenance and existing privacy checks. Its local size/time/tool-result limits
  remain enforced; SIWC does not accept server-side `max_tool_calls` or
  `max_output_tokens`, so the observed tool limit is not a server execution cap.
- Plan limits apply. Reconnect through the account menu after expired/revoked
  permission; review usage at <https://chatgpt.com/settings/usage>.

Verification evidence (untracked local runtime artifacts):

- `.runtime/chatgpt-subscription-guards-07/evidence.json`: 18 authorized MCP tools,
  no native shell/browser/delegation, file-write canary rejected.
- `.runtime/chatgpt-sage-live-02/live-evidence.json`: two real read-only turns,
  30 zones / 288 assets, same-thread resumption, source unchanged.
- `.runtime/chatgpt-sage-research-01/live-evidence.json`: real search and selected
  source read with citations, source unchanged.
- `.runtime/chatgpt-sage-edit-02/live-evidence.json`: real collision rejection,
  corrected preview, test-only approval and exact-content undo on a disposable copy.
- `.runtime/chatgpt-subscription-desktop-01/subscription-desktop-check.json`:
  actual Electron Sage UI response with `authMode: chatgpt_plan`, no API fallback,
  and unchanged saved Private Gym. The native run shut down cleanly without forcing.

Rollback: close InspectorPro, restore
`../.runtime/desktop-native/application-profile.before-chatgpt-20261016.json`
to `application-profile.json`, then reopen. This explicitly restores paid API
usage; it is not automatic. Never copy account tokens into the API credential vault.
The earlier activation hashes below describe the original API activation, not
the current subscription profile.

Protocol references: [App Server integration](https://developers.openai.com/siwc/token-sharing-open-source/codex-app-server),
[profiles and sessions](https://developers.openai.com/siwc/token-sharing-open-source/profiles-and-sessions),
[models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference).

## Original API Activation

Status: **activated in the regular local desktop profile on 2026-10-15** after
all five final native gates passed. See `sage-codex-readonly-pilot.md` for the
accepted evidence and scope; earlier failed runs remain retained.

Active profile: `../.runtime/desktop-native/application-profile.json`.
Rollback backup/record: `../.runtime/codex-desktop-activation-20261015-01/`.
Record SHA256: `5b65d9ac7596dfb5e5b2481aaadcd05061f89a2eb6e811f8442da956422c70ff`.
Original profile SHA256: `7e1de780ebf8a4df348032ed8fb83b03d2b05d714508ab4a1f771ab748c350d2`.
Activated profile SHA256: `dd3d97deb64d45bdd2dad28e17b1e23007511692c5e8cfe6a02d15259b16d2b7`.
Bundle: `../.runtime/codex-bundle-20261015-01/`.
Package SHA256: `a6b95077683953dcd65ad7182ec1bf17862a4d4c35ad9113b2dc6434fe1e79c4`.
The approved existing API credential was provisioned in the profile-specific
Windows vault; no credential appears in these records.

The normal shortcut was launched after activation. Backend readiness was 21.263
seconds, Private Gym opened, and two read-only Sage requests completed through
Codex, including thread resumption after a UI reload. The app was left open.
Post-activation observations and journal references are in
`.runtime/codex-desktop-normal-smoke-20261015.json`. Existing server-conversation
memory settings were preserved, not silently enabled by deployment.

Activation guards ignore unrelated Codex system-helper executables, but still
refuse inaccessible candidate InspectorPro/backend/Codex runtime processes.
The loopback probe allows five seconds for Windows to report connection refusal
(measured at 2.076 seconds here); timeouts remain unknown and refuse activation.

Normal application mode continues to run the existing checkout through its
existing shortcut. Only rendering/managed diagnostics require a source snapshot.
The normal Codex release is a separate, dependency-only bundle: no application
source, generated resources, stores or shortcuts are migrated. In particular,
the existing private catalog, geometry, manual workflow content and `/generated`
resources retain their current source-root-relative resolution.

## API Configuration Contract (Version 1)

The API-authenticated normal application profile may contain this exact optional object. Paths
below are illustrative. Preserve the existing profile except this object.
No other Codex fields are accepted.

```json
{
  "codexRuntime": {
    "schemaVersion": 1,
    "model": "gpt-5.5",
    "editPreviews": true,
    "allowPaidInference": true,
    "dependencyRoot": "C:\\InspectorProBundle\\.runtime\\codex-pilot-deps",
    "binary": "C:\\InspectorProBundle\\.runtime\\codex-pilot-deps\\codex_cli_bin\\bin\\codex.exe",
    "packageSha256": "REPLACE-WITH-VERIFIED-64-LOWERCASE-HEX-PACKAGE-HASH",
    "pilotRoot": "C:\\InspectorProData\\codex-pilot",
    "credentialTarget": "InspectorPro/Codex/EXISTING-PROFILE-ID"
  }
}
```

- Presence opts in to the bounded runtime. Remove `codexRuntime` to disable it.
  `editPreviews: false` keeps the runtime enabled without edit previews.
  `allowPaidInference` must be the JSON boolean `true`, not a string or number.
- Version 1 supports GPT-5.5 and API authentication. No ChatGPT subscription,
  personal Codex login, OAuth cache, credential-file fallback or automatic model
  fallback is used. The API account must have access and billing authorization.
- `pilotRoot` is exactly `<dataRoot>/codex-pilot`, disjoint from facility/library
  stores and optional dependencies. Logical profile/backend/store IDs, startup
  document, existing gateway settings and renderer storage partition stay intact.
- The executable is exactly `<dependencyRoot>/codex_cli_bin/bin/codex.exe`.
  Normal mode's dependency root is outside and not an ancestor of the app root,
  and is disjoint from data/facility/library stores. No checkpoint is required
  for normal mode. Existing embedded diagnostic-snapshot dependencies remain
  supported only with their separate-source checkpoint; this is not the normal
  application deployment path.
- The backend verifies `packageSha256` against the exact package manifest, all
  recorded file bytes/hashes, exact inventory (including rejection of extra
  modules), all distribution versions, pins, interpreter tag and platform before
  reading a credential or adding dependencies. Updating both dependencies and
  their manifest without changing the approved profile hash fails startup.
  Bytecode caches are not copied, are rejected at validation, and the backend
  disables bytecode writes before loading optional dependencies.
- Dependency inventory traversal validates shared ancestors once per visited
  directory and checks every child for links/junctions. Every file is still
  hashed on each startup; there is no timestamp-only verification cache. On the
  1,674-file, 481 MB bundle, a local profiling run improved from 32.4 seconds to
  5.15 seconds. Native load acceptance is separate from this profiling result.
- Pins: `openai-codex-cli-bin==0.162.1`, `mcp==2.3.0`,
  `jsonschema==4.26.0`. `inspectorpro-codex-package.json` is the per-release full
  installed dependency lock: all distribution versions, interpreter tag,
  platform, byte counts and SHA-256s. Nothing is resolved or downloaded at launch.
- Dependencies are appended with `site.addsitedir` after normal application
  dependencies, including processing the tested pywin32 `.pth`. They are never
  prepended to `PYTHONPATH` and never installed into the base Python environment.

For version 1, `application_backend.py` alone obtains the key and sets these backend variables:

```text
INSPECTORPRO_CODEX_READONLY_PILOT=1
INSPECTORPRO_CODEX_EDIT_PREVIEWS=1   (or 0 from the explicit profile boolean)
INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE=1
INSPECTORPRO_CODEX_BINARY=<validated bundle executable>
INSPECTORPRO_CODEX_PILOT_ROOT=<dataRoot>/codex-pilot
INSPECTORPRO_CODEX_MODEL=gpt-5.5
INSPECTORPRO_CODEX_API_KEY=<read from the current user's Windows vault>
```

The Electron supervisor strips inherited `INSPECTORPRO_CODEX_*` and `CODEX_*`
settings from its application backend child, without mutating the parent.
The Python launcher clears those namespaces again, and sets explicit disabled
or empty values before importing `server.py`. Its existing non-overriding dotenv
loader therefore cannot re-enable the route or supply a different Codex key.
Other legacy provider configuration remains unchanged. Packaging never reads,
prints or copies `.env` files. Only explicitly authorized native-test or activation
credential provisioning can read a selected key file; normal startup uses the vault.

## Credential Provisioning

No existing desktop vault wrapper was found. `codex_credentials.py` uses Windows
`CredReadW`/`CredWriteW`, generic credentials and local-machine persistence for
the current user. Microsoft's [credential structure documentation](https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentialw)
specifies that this persistence is for subsequent logons of the same user on the
same computer, not another user's credential set or roaming to another machine.

After approval, run interactively as the same unelevated Windows user that runs
InspectorPro (replace the ID with the existing profile's `profileId`):

```powershell
python -B desktop/tools/provision-codex-credential.py --profile-id EXISTING-PROFILE-ID
```

The prompt hides input and refuses noninteractive/fallback echo. Never put a key
on the command line, in profile JSON, in a release manifest or renderer IPC.
Provisioning explicitly replaces the credential at that profile-scoped target.
There is no provisioning IPC or renderer key-management surface.

The Python host reads only `InspectorPro/Codex/<profileId>`. Missing/invalid vault
entries fail startup with fixed errors, without fallback to `OPENAI_API_KEY`.
Native credential buffers are zeroed before release. Split writes to Python
stdout/stderr redact the actual key before reaching desktop logs. The runtime's
existing child-environment isolation and suppressed raw Codex stderr remain
necessary. Python strings/environment memory cannot be guaranteed zeroized;
this is not isolation from a compromised process running as the same OS user.

## Prepare And Validate

Use the **same Python interpreter as the native shortcut**. The actual accepted
release and activation are recorded above; commands below are reusable examples.
Choose absolute paths. `$release` must be new and outside `$source`, for example
a sibling under the shared workspace. It must not overlap user stores. Only the
tested optional dependency tree is copied, with no downloads or source snapshot.

```powershell
$source = 'C:\Users\might\OneDrive\Desktop\InspectorPro\AI-Drawing-Inspector'
$release = 'C:\Users\might\OneDrive\Desktop\InspectorPro\codex-bundle-APPROVED-ID'
python -B tools/codex_desktop_pack.py prepare-bundle --source $source --destination $release --dependency-dir "$source\.runtime\codex-pilot-deps"
python -B tools/codex_desktop_pack.py verify-bundle --release $release
```

Preparation copies only the tested optional dependency tree, executes the pinned
binary's bounded `--version` probe with a minimal credential-free environment,
and records a complete dependency inventory. It does not start App Server, call a
model, launch Electron, access the vault or alter an installed profile.

The hash inventory proves byte identity, not test acceptance, vendor provenance
or a signed installer. Retain `packageSha256` and `bundleSha256` with the actual
backend/native evidence. A bundle is content-pinned and must never be edited in
place: create a fresh directory for any change. This tool does not set Windows
ACLs or prevent same-user writes after validation. Stop the application before
any approved runtime change; startup verification is not a defense against a
concurrently compromised OS user. Run serially, with no
competing heavy suites or native runs. Keep native test stores, memory databases,
metrics and pilot state on disposable copies, not the installed layout store.

The native pilot launcher now requires `--release-root` and verifies it through
the packaging module before fixture preparation or key-file access. It uses the
normal checkout's entry, cwd, installed Electron, fixture preparation helper and
source-layout reads, plus the bundle's pinned binary. `pilotRoot` is
`<output-root>/codex-pilot`. There is no old
bootstrap `PYTHONPATH` or inherited runtime-flag/key bypass.

`application-code-evidence.json` records before/after SHA-256 inventories for
`server.py`, backend modules, frontend source, desktop source/runtime/tools,
package manifests and the native launcher/reliability/pack tools. It excludes
generated/user resources, secrets, caches and installed dependency trees. Code
changes during the run or a changed/invalid dependency bundle fail acceptance.
`codex-desktop-acceptance.json` is the final result after evidence verification
and exact test-credential cleanup; retain it alongside existing scenario reports
and captured stdout/stderr. Freeze app-code changes during native acceptance and
compare this inventory again before promotion. A bundle pin alone does not freeze
the live application's code or its base Python/Electron environment.

An approved native run additionally requires `--provision-test-credential` before
the launcher may read the explicitly selected `--api-key-file`. This is the only
test-launcher exception to file-free credential provisioning above. It chooses a
new random `codex-test-<UUID>` profile ID, refuses an already-existing vault target,
and provisions only `InspectorPro/Codex/<that-ID>`. Its `finally` deletes only that
exact test credential after all scenario rounds, including failure/interruption.
The narrow delete API rejects ordinary profile IDs, full vault paths and wildcards.
A failed deletion cannot print a passing launcher result. A forcibly killed
launcher cannot execute `finally`; retain its isolated profile ID for explicit
test-target cleanup, never enumerate/delete other credentials.

```powershell
# Prepared for main's approval, not executed by this implementation:
python -B tools/check_codex_sage_desktop.py --live --reliability-check editing --release-root $release --api-key-file 'C:\PATH\TO\EXPLICIT-API-KEY-FILE' --provision-test-credential --output-root .runtime/codex-desktop-edit-NEW-ID --port 8537
```

Startup/load, recovery/restart, editing, cancellation and memory/document-switch
scenarios remain supported. `--reliability-check editor-change` delegates the
readonly editor-context revocation test with `editPreviews: false` and enforced
memory; controlled load remains startup-only. Existing Electron stdout/stderr files and scenario
reports remain captured. Main owns `codex_desktop_reliability.py` and
`desktop/tools/application-codex-check.cjs`; neither was changed by this launcher
adaptation. The first legacy native edit attempt's `required_context_budget`
failure came from the intentionally stripped inherited route flags selecting the
legacy path, not from a demonstrated Codex defect.

## Promotion Procedure

1. Finish backend collision/correction, preview, approval/apply/receipt/undo and
   native UI gates. Record the package hash and application-code evidence. Keep the
   read-only memory/reload/switch and interruption/recovery gates as applicable.
2. Obtain main's explicit approval. Close the normal desktop cleanly, preserving
   unsaved drafts through its normal lifecycle. Confirm its owned backend exits.
3. Preserve the actual shortcut and normal checkout. The observed profile is
   `C:\Users\might\OneDrive\Desktop\InspectorPro\.runtime\desktop-native\application-profile.json`,
   under the **workspace root**, not the `AI-Drawing-Inspector` checkout. From the
   repository root this is `../.runtime/desktop-native/application-profile.json`;
   from `desktop/` it is `../../.runtime/desktop-native/application-profile.json`.
   Resolve the actual shortcut arguments before any approved write; do not guess
   from an old snapshot or create a root checkpoint. Snapshot only the exact
   existing profile bytes to a fresh rollback file, and record their SHA-256.
   Do not copy, relocate, reset or fork any user store or generated resource.
4. Re-run `verify-bundle`, compare its package hash with the native evidence, and
   re-hash the application code against the recorded after-inventory. Any code or
   dependency difference invalidates approval until reviewed/retested. Provision
   the API credential under the existing profile ID if needed. Main may then
   atomically add the explicit `codexRuntime` object to that same profile, keeping
   every other field unchanged, including `modelGateway`, IDs and storage roots.
   Record the enabled profile's hash for rollback conflict detection. Validate
   the profile and package before reopening. No source-code installation or
   shortcut switch is part of this deployment.
5. Reopen the existing normal shortcut. Confirm normal readiness and the
   intended saved-layout identity before authorized paid inference. This is not
   a mandate to test edits on the real layout. Native acceptance belongs on copies.

### Activation CLI

Run from `AI-Drawing-Inspector`. Replace the `FINAL-*` directories with main's
reviewed final editing, editor-change, recovery, startup and memory outputs.
Each loop iteration adds another `--acceptance REPORT REPORT_SHA256 EVIDENCE_SHA256`.
All supplied reports must pass and bind to the same current application-code
inventory and approved bundle. Retain the reviewed hashes; do not regenerate
them merely to bypass a refusal. Use a fresh rollback directory.

```powershell
$profile = '..\.runtime\desktop-native\application-profile.json'
$runs = @('.runtime/FINAL-editing', '.runtime/FINAL-editor-change',
          '.runtime/FINAL-recovery', '.runtime/FINAL-startup', '.runtime/FINAL-memory')
$activation = @('tools/activate_codex_desktop_profile.py', 'activate',
    '--profile-file', $profile, '--profile-sha256', (Get-FileHash -LiteralPath $profile -Algorithm SHA256).Hash.ToLowerInvariant(),
    '--release', '..\.runtime\codex-bundle-20261015-01',
    '--package-sha256', 'a6b95077683953dcd65ad7182ec1bf17862a4d4c35ad9113b2dc6434fe1e79c4',
    '--backup', '..\.runtime\codex-profile-activation-APPROVED-ID', '--enable-edit-previews')
foreach ($run in $runs) {
    $report = Join-Path $run 'codex-desktop-acceptance.json'
    $evidence = Join-Path $run 'application-code-evidence.json'
    $activation += @('--acceptance', $report,
        (Get-FileHash -LiteralPath $report -Algorithm SHA256).Hash.ToLowerInvariant(),
        (Get-FileHash -LiteralPath $evidence -Algorithm SHA256).Hash.ToLowerInvariant())
}
python -B @activation  # Dry-run: no profile writes, key-file reads or vault access.

# Only after main's approval and clean desktop/backend shutdown:
python -B @activation --apply --desktop-stopped --allow-paid-inference
```

Apply checks processes and the profile's listener in addition to the explicit
stopped assertion. Keep the app closed and code frozen throughout. By default it
reuses an existing valid profile-scoped vault credential. If provisioning is
needed, append `--provision-credential --api-key-file '..\.env'` to the approved
apply command; only the path is on the command line. An existing credential is
not overwritten without the additional explicit `--replace-credential` flag.
Do not run concurrent credential provisioning. The helper preserves exact prior
profile bytes and a rollback record before adding only `codexRuntime`, and returns
the record path/hash. Source files, shortcuts and user stores are not rewritten.

## Rollback

For normal mode, close the desktop cleanly and confirm the current profile hash
matches the enabled hash recorded during promotion. Verify the backup's original
hash, then atomically restore those exact prior profile bytes. If either hash has
changed, stop and reconcile the later edits; do not overwrite them. Reopen the
same shortcut. The dependency bundle, credential and pilot journal remain intact
for diagnosis; no user data, source code or engineering commits are rolled back.

Using the `rollbackRecord` and `rollbackRecordSha256` returned by activation:

```powershell
python -B tools/activate_codex_desktop_profile.py rollback --profile-file $profile --record-file $rollbackRecord --record-sha256 $rollbackRecordSha256
# After approval and clean shutdown, repeat with --apply --desktop-stopped.
```

Rollback never reads, restores or deletes vault credentials, including a key
explicitly replaced during activation.

The older `prepare`/`verify`/`promote`/`rollback` commands are diagnostic snapshot
tooling only. **Do not use them to promote the normal checkout.** Their existing
file-transaction tests cover backup integrity, interrupted installation and
conflict refusal, but are not a normal-profile deployment authorization.

Removing `codexRuntime` and restarting is the route-only disable procedure; do
not delete the pilot journal or undo engineering commits to disable inference.
Full rollback retains vault credentials and pilot state rather than deleting
unrelated or potentially needed recovery information.

## Focused Verification

From the repository root, run these serially. Choose a new pytest basetemp for
each run; the existing output directory must not contain anything valuable.

```powershell
New-Item -ItemType Directory -Path desktop/.runtime -Force
python -B -m pytest -q -p no:cacheprovider desktop/tests/test_codex_desktop_pack.py desktop/tests/test_codex_desktop_launcher.py desktop/tests/test_application_gateway_profile.py --basetemp desktop/.runtime/codex-bundle-review-NEW-ID
python -B -m pytest -q -p no:cacheprovider desktop/tests/test_codex_profile_activation.py --basetemp desktop/.runtime/codex-profile-review-NEW-ID
$env:TEMP = Join-Path (Get-Location) 'desktop\.runtime'
$env:TMP = $env:TEMP
node --test desktop/tests/codex-configuration.test.cjs desktop/tests/application-gateway.test.cjs desktop/tests/runtime-supervisor.test.cjs
```

These are unit/file-transaction checks with fake binaries, vault calls and
supervisor children. They are not native acceptance, real vault provisioning,
real inference, clean-machine distribution or a production-support guarantee.
Installed-profile promotion and real vault access
remain approval-gated. No commit was created by this work.

Focused implementation verification on 2026-10-15 (serial, fake vault/children):

- 98 Python tests passed in 57.92 s across package, launcher and gateway-profile
  tests, using `desktop/.runtime/codex-bundle-pytest-20261015b`.
- After adding `editor-change`, all 49 launcher tests passed in 4.91 s using
  `desktop/.runtime/codex-editor-change-pytest-20261015a`.
- All 37 Node checks above passed in 2.812 s. Scoped tracked-file diff whitespace
  checks passed. Pytest emitted the existing LangSmith/Pydantic V1 Python 3.14 warning.

Main reported preparing `../.runtime/codex-bundle-20261015-01` with package hash
`a6b95077683953dcd65ad7182ec1bf17862a4d4c35ad9113b2dc6434fe1e79c4`
and bundle hash
`7e8635ad8953cd0490709ecdd44e540e662fa3fb1c76d38b493d90bc9d780e61`.
Retain the actual prepare/verify output as authority for those hashes.
Implementation files are frozen for main's native acceptance; docs and tests are
outside the application-code evidence inventory. No native window, real
credential-vault entry, installed-profile write or promotion was performed by
this implementation work.

## Facility Authoring Expansion, 2026-10-15

The regular desktop profile still uses the live application checkout. Its
existing Codex bundle, credential target, shortcut and startup-layout selection
were not changed for the facility-tool expansion. Restarting loads the new
49-operation schema, targeted wall/floor/decal operations and material proofs.

Local authoring and approved commit/Undo checks passed; the new live native
attempt is quota-blocked, not accepted. Details and exact evidence are recorded
in `sage-codex-readonly-pilot.md` under Authoring Expansion. Do not cite the older
five native gates as proof that this expanded inventory passed native acceptance.

After that attempt, the normal shortcut reopened the saved Private Gym,
maximized. Backend instance `2062efaa-4947-4282-a3a2-40e3d6b52450` reached
application-ready at 30.932 seconds on port 8480. Native UI confirmed the Private
Gym tab and Saved status. At that checkpoint, no further paid request was sent
after quota exhaustion.
The original Private Gym and Factory 02 files retained their pre-test SHA256
hashes. The failed disposable test shut down unforced with no owned-runtime
orphans; the normal application is intentionally left running.

## Public Research Addition, 2026-10-15

The live checkout now includes revision-bound public search and selected-source
reading through InspectorPro MCP. Native Codex web/browser/shell capabilities
remain disabled. The default research adapter uses the existing dedicated Codex
API credential and configured model; no vault or installed-profile change was
made. `INSPECTORPRO_CODEX_WEB_RESEARCH=0` is the backend disable switch.

The existing Anthropic/gateway reader can be selected explicitly with
`INSPECTORPRO_CODEX_RESEARCH_PROVIDER=anthropic`; provider failures never cause
fallback. Source receipts feed the existing unreviewed source cards and Sage's
streaming progress. The normal app must be restarted to load the new inventory.
It was not restarted during this work, and user layouts were not changed.

After the user restored credits, one bounded live Sage chat turn passed in
34.107 seconds using the existing vault credential and `gpt-5.5`. It completed
context inspection, public search and selected-page reading through three real
MCP calls, with two research receipts and eight receipt-derived source cards in
the final SSE payload. The answer cited U.S. Access Board parking guidance and
did not claim layout compliance. Evidence:
`.runtime/codex-public-research-live-01/live-evidence.json`.

The source gym and disposable copy remained unchanged; runtime shutdown left no
owned orphan processes. The prior quota blocker did not recur in this research
test. Native source-card clicks and the separate expanded-authoring acceptance
were not exercised, and the user's running app was not restarted. Local tests
still use controlled provider responses; live receipts are provider-reported
retrieval rather than independently archived page bytes. Implementation and
controls are detailed in `sage-codex-readonly-pilot.md`.

## Direct Facility Edits, 2026-10-16

Sage's facility composer defaults to **Apply directly**. **Preview first** is a
persisted user option, captured with each turn. Old clients without this field
remain preview-only. Changing to Preview first before commit revokes direct
consent for an in-flight edit.

The MCP runtime still only stages one immutable, validated batch. The trusted
editor authorizes eligible batches using standing direct consent, with an exact
revision/diff/dependency binding. It skips the visible ghost and approval click,
not validation. Authorization provenance is included in the approval fingerprint;
the durable receipt records the requested mode and backend policy. Shell and
arbitrary commits remain unavailable to the model.

Direct eligibility is backend-owned: up to 20 targeted routine operations and
20 affected/created entities. Deletions, replacements, zone reshaping, whole
settings collections, physical ground/perimeter changes, and parking reviews
still require explicit preview approval. These conservative limits do not imply
engineering certification. Receipt-bound Undo restores one complete direct batch
immediately only while its saved revision is current. Manual draft Undo is unchanged.

Verification: real disposable Private Gym direct batch, permission and stale
revision rejection, exact receipt Undo, retained Preview first behavior, frontend
context/cancellation fences and same-transaction retry. The subscription test in
`.runtime/codex-direct-live-02/live-evidence.json` passed a model-driven collision,
correction, direct authorization and exact Undo. User source content was unchanged.
The first sandboxed attempt could not access encrypted sign-in; the authorized
retry used ChatGPT plan usage with no API fallback.

The normal desktop uses this live checkout; restart it to load the new backend
and frontend together. No profile, credential target, or model switch is needed.

Native verification passed in `.runtime/codex-direct-desktop-02`: the actual Sage
composer displayed Apply directly, Preview first persisted, and a read-only
ChatGPT-plan inspection completed with no API fallback or source-layout change.
The captured `subscription-sage.png` was visually inspected. Native verification
covered the controls and read-only chat; direct mutation/Undo was verified by the
live disposable-copy harness and real editor-session integration tests, not by
writing to the user's open gym. Both normal shutdowns were unforced and clean.

## Authoring Timeout Recovery, 2026-10-16

The blank-layout basketball request exhausted the 240-second turn budget after
nine schema rejections. Required fields were returned six at a time, encouraging
field guessing. Focused `inspect_facility_operation_contracts` now exposes the
actual operation schemas and reachable definitions. Schema errors group missing
fields and include the affected operation contracts. Partial streamed answers
now display the classified timeout instead of the generic user-stop message.

`add_floor_path` compiles bounded polylines, arcs and circles into the existing
editable floor markings. This avoids model-authored hundreds-of-segments batches;
it does not bypass geometry validation, revision checks, review thresholds or
receipt Undo. Plan reads expose the existing corner-origin world bounds and
identify when authored ground, rather than the display plan, is authoritative.
Floor-finish contracts explicitly forbid overlapping or vertically stacked finishes.

Live subscription evidence: `.runtime/codex-court-live-02/live-evidence.json`.
The request returned in 163.416 seconds with no schema rejections; its court-floor
and markings draft committed and undid exactly on a disposable copy. This proves
execution recovery, not a completed basketball installation: unsupported elevated
hoops were rejected and omitted, and the response correctly reported the missing
mounting setup. The source layout was unchanged. The running desktop needs a
restart to load these changes; no restart was performed without fresh approval.
