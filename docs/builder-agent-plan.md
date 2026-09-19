# Builder Agent Plan

## Purpose

Builder is the in-app authoring and developer agent for InspectorPro. It lets authorized users create, correct, and maintain structured engineering assets directly from the app: process maps, assembly training flows, inspection profiles, skills, prompts, and eventually code.

Builder is not just another chat agent. It is the system-editing layer.

## Core Idea

Add Builder as a fourth agent next to Iris, Sage, and Scout.

When Builder is selected:

- the same right-side chat pane becomes a live work-log / terminal-style pane
- the same input box accepts commands
- Builder streams progress, commands, validation output, file changes, and final results
- Builder can modify structured app files through controlled tools
- every change is validated and reloads the affected UI

## First Version Target

Builder v1 should be narrow and valuable:

**Structured Asset Editor for Training / Process Maps**

Builder v1 should edit existing app content, not app source code yet.

Primary use cases:

- "Move this process node under that subsystem."
- "Rename this step."
- "Add a quality checkpoint after this operation."
- "This component belongs to this subassembly, not that one."

## V1 Capabilities

- Add Builder as the fourth agent in the agent selector.
- Route Builder messages to a new backend endpoint, not `/api/agent/chat`.
- Show terminal-style live logs in the agent pane.
- Read active app context:
  - active tab
  - active training/process map
  - selected node
  - selected assembly/component
  - current JSON asset path
- Edit structured JSON assets:
  - process map nodes
  - parent/child relationships
  - labels
  - descriptions
  - procedure steps
  - training metadata
- Validate changes:
  - no duplicate node IDs
  - no orphan nodes
  - no broken parent references
  - no broken edge references
  - valid schema
- Reload the UI after save.
- Keep backup/version file before writing.
- Report exactly what changed.

## V1 Non-Goals

Do not start with:

- arbitrary code editing
- arbitrary shell access
- prompt/skill editing
- git commits
- SolidWorks extraction
- library promotion
- production deployment actions

Those come later.

## V1 Example Flow

User:

```text
Move the filter housing under the cooling loop.
```

Builder:

```text
Reading active process map...
Selected asset: cooling_tower_process_map.json
Found node: filter_housing
Current parent: inlet_manifold
Proposed parent: cooling_loop
Updating parent reference...
Validating process map...
No duplicate IDs.
No orphan nodes.
No broken edges.
Saving backup...
Writing updated JSON...
Reloading Training tab...
Done.
```

Final:

```text
Moved Filter Housing from Inlet Manifold to Cooling Loop. Updated 1 parent reference and 2 affected edge paths.
```

## Architecture

```text
Frontend Builder Agent
  -> /api/builder/send or /api/builder/session
  -> Builder Runtime Adapter
  -> Embeddable Agent Runtime
  -> Builder Orchestrator
  -> Skill/Workflow Router
  -> Approved Builder Tools
  -> File edits / validation / UI reload
  -> Streaming log back to UI
```

## Embeddable Agent Runtime

Builder needs an embeddable coding-agent runtime, or an adapter around one. The goal is not to create a simplified customer chat experience first. For owner/developer use, the app should show the same raw work stream that is useful in the terminal today.

The runtime adapter is the bridge between InspectorPro and the agent process:

```text
Builder UI
  -> Builder Runtime Adapter
  -> Codex/Claude-like Agent Runtime
  -> Local tools, files, repo, app server
  -> Event stream back to Builder UI
```

The adapter should stream structured events while preserving the raw terminal feel:

```text
skill_selected
assistant_message
tool_call
shell_command
stdout
stderr
file_read
file_patch
test_result
approval_needed
interruption
final_answer
```

Owner mode should render these events verbosely, almost exactly like the current terminal session. That includes command text, stdout/stderr, patch previews, validation output, and approval prompts. Later customer/admin modes can collapse the same event stream into cleaner summaries, but the internal Builder should remain transparent and interruptible.

Runtime requirements:

- stream events over WebSocket or Server-Sent Events
- preserve session history
- allow the user to interrupt, redirect, or continue
- request approval before risky actions
- support file reads, patches, validations, and controlled command execution
- keep a durable audit trail of what changed and why
- separate owner/developer permissions from customer-admin permissions

## Frontend

- Add Builder icon/avatar.
- When Builder is selected:
  - use same input field
  - render responses as terminal-style logs
  - support streaming updates
  - show status: idle/running/needs approval/done/error
- Add controls:
  - Stop
  - Continue
  - Apply
  - Revert last change
  - Open diff
- Keep logs visible so the user can interrupt mid-task.

## Backend

Create a Builder service with:

- session management
- active context intake
- structured tool calls
- event streaming
- file backup/write utilities
- validators
- audit log

Suggested endpoints:

```text
POST /api/builder/session/start
POST /api/builder/session/send
POST /api/builder/session/stop
GET  /api/builder/session/{id}/events
POST /api/builder/apply
POST /api/builder/revert
```

For streaming, use either:

```text
WebSocket: /ws/builder/{session_id}
```

or:

```text
Server-Sent Events: /api/builder/session/{id}/events
```

## Builder Tools

V1 tools should be narrow:

```text
get_active_context
read_process_map
find_process_node
move_process_node
rename_process_node
add_process_node
update_process_step
validate_process_map
backup_asset
write_asset
reload_training_asset
show_diff
revert_last_asset_change
```

Each tool should return structured output and a human-readable log line.

## Safety

Even in owner mode, Builder should ask before:

- overwriting an asset
- deleting nodes
- renaming IDs
- changing many nodes at once
- applying uncertain matches

For v1, Builder should not run arbitrary shell commands. It should only call approved tools.

## Skill Model

Builder should use its own skills:

### Process Map Editing Skill

- move nodes
- rename nodes
- add/remove relationships
- preserve schema validity

### Training Procedure Editing Skill

- edit steps
- add checkpoints
- update role-specific instructions

### Asset Validation Skill

- schema checks
- broken reference checks
- duplicate ID checks
- graph integrity checks

### Diff Explanation Skill

- explain before/after changes
- summarize impact

## Expansion Plan

### Phase 1: Process Map / Training Asset Builder

- Edit process maps and training JSON.
- Validate and reload the Training tab.
- Keep backups and simple rollback.

### Phase 2: Inspection Profile Builder

Builder can edit and improve part profiles:

- rename semantic features
- regroup SolidWorks operations under semantic features
- add/edit feature descriptions
- add expected drawing locations
- add highlight regions
- validate inspection profile JSON

Example:

```text
The boss face counterbore is described wrong. It should be the pin boss seating face.
```

### Phase 3: Library Intake Builder

Builder orchestrates intake workflows:

- active SolidWorks document detection
- part number validation
- extraction
- GLB export
- projections
- profile packet creation
- draft profile validation
- promote to library

This uses controlled local worker tools, not arbitrary shell.

### Phase 4: Skill / Prompt Contract Builder

Authorized users can edit structured agent behavior:

- mode contracts
- skill contracts
- company wording policies
- FAI disposition language
- GD&T standards
- tool permission policies

Builder should version each skill/prompt change.

Example:

```text
Update FAI wording so failures say reject for engineering disposition, not scrap.
```

### Phase 5: Developer Owner Mode

For owner/admin use only:

- inspect repo
- patch frontend/backend
- run tests
- restart local server
- stage/commit changes
- edit code with diffs
- stream terminal output

This is closest to the Codex terminal experience inside the app.

### Phase 6: Customer Admin Mode

For deployed customers:

- edit company standards
- edit process maps
- edit training flows
- edit inspection templates
- manage permissions
- no source-code access

## Long-Term Vision

Builder becomes the way companies build and maintain their own product/process intelligence inside InspectorPro.

Instead of relying on developers to update JSON, prompts, or workflows, authorized engineers can say what is wrong, approve the change, and the system updates itself with validation and traceability.
