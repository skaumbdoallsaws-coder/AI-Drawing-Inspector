# InspectorPro Pilot / Demo Build Plan

## Purpose

Create a focused version of InspectorPro for customer pilot studies, investor/customer demos, and trade-show conversations.

This should not be a full rebuild of the product. The goal is to package the strongest existing workflows into a stable, predictable, professional experience with fewer fragile surfaces.

## Core Principle

Every visible button, tab, and workflow in the pilot/demo build must either:

- Work reliably.
- Be disabled with a clear reason.
- Be removed from the pilot surface.

## Recommended Approach

Keep the current development app as the full experimental environment, but add a separate pilot/demo mode:

- `DEV_MODE=true`: all experimental workflows visible.
- `PILOT_MODE=true`: only stable, scripted, customer-ready workflows visible.

This avoids forking the entire product too early while still allowing a cleaner customer-facing build.

## What The Pilot/Demo Build Should Be

- Focused InspectorPro Pilot Edition.
- Same core app and data assets.
- Fewer workflows exposed.
- Better wiring and guardrails.
- Scripted demo data.
- Stable startup process.
- Basic user/security framing.
- Clear measurement and logging.

## Workflows To Include First

### 1. Drawing / CAD Context

Use cases:

- Drawing checking.
- CAD feature context.
- Drawing/part comparison if stable.

Value:

- Helps engineering release cleaner drawings.
- Catches missing or unclear callouts earlier.
- Reduces late manufacturing questions.

### 2. FAI / Supplier Disposition

Use cases:

- Supplier asks whether to keep, rework, scrap, or escalate a part.
- Agent answers using drawing, CAD, FAI, assembly/function context, and evidence.

Value:

- Strong business-value demo.
- Shows how product context reduces email loops and delayed decisions.
- Good pilot workflow because success can be measured.

### 3. Assembly / Process Training

Use cases:

- Interactive product or process walkthrough.
- Assembly sequence explanation.
- Two-way training where users can ask questions during the process.

Value:

- Strong visual workflow.
- Helps onboarding and cross-functional product understanding.
- Useful for both factory and office personnel.

### 4. Facility Layout

Use cases:

- Facility layout viewport.
- Flow routes.
- Capacity reasoning.
- Clearance and layout tradeoff questions.

Value:

- Visually strong.
- Shows that InspectorPro can reason beyond a single part.
- Good example of operations/manufacturing intelligence from spatial context.

### 5. Mode-Aware Sage

Use cases:

- Sage understands the active mode: drawing, assembly, plant process, facility layout, FAI, etc.
- Sage avoids answering with the wrong workflow context.

Value:

- Makes the app feel coherent.
- Prevents cross-mode hallucination.
- Supports the product thesis: one context layer, many role-aware workflows.

## What To Hide Or Disable

- Unfinished tabs.
- Debug controls.
- Experimental edit-to-SolidWorks flows unless fully scripted.
- Anything requiring fragile live extraction during a demo.
- Anything that depends on unknown customer files without preprocessing.
- Overly broad agent tools that are not needed for the pilot workflow.
- Any surface that produces unclear errors or inconsistent state.

## Wiring Needed

### Startup

- One startup command.
- Known default port.
- Clear health check.
- No manual hidden setup steps.
- Friendly failure if required assets or API keys are missing.

### Data Package

- One known demo/pilot data package.
- CAD models.
- Drawings/PDFs.
- BOM.
- FAI or inspection records.
- Assembly context.
- Facility layout, if included.

### Demo Routes

Each workflow should have:

- A scripted starting state.
- A known prompt or user action.
- Expected answer/output.
- Recovery path if the AI call fails.
- Optional short backup video.

### Mode-Specific Agent Behavior

- Sage receives the active mode every turn.
- Sage receives compact facts for the selected workflow.
- Sage uses deterministic endpoint results when available.
- Sage does not invent distances, counts, inspection values, or disposition evidence.

### Error Handling

Replace silent failures with:

- Clear user-facing message.
- Known limitation if applicable.
- Suggested next action.
- Logged backend error for debugging.

## Pilot Readiness Requirements

### Scope

- Pick 1-2 workflows for the first customer pilot.
- Define the business problem.
- Define the users involved.
- Define what success looks like.

### Security Basics

Minimum pilot answer:

- Named pilot users only.
- Basic login or protected access.
- Customer data not used to train public models.
- Controlled storage location.
- Data deletion plan after the pilot.
- API keys and secrets protected.

Future enterprise answer:

- Microsoft Entra ID / Azure AD, Okta, or SAML/OIDC.
- Role-based access control.
- Company/workspace separation.
- Audit logs.
- Customer-approved model/provider options.

### Measurement

Track:

- Time to answer.
- Number of clarification loops avoided.
- Issues caught earlier.
- Rework/scrap risk reduced.
- User feedback by department.
- Before/after comparison.
- Token usage and model cost.

### Human Review

- AI answers are advisory.
- Human approves disposition decisions.
- Human approves new product context before it becomes trusted context.
- Important decisions are logged.

## Deployment Direction

For the first pilot, prioritize a desktop/web experience.

Reason:

- CAD, drawings, BOMs, FAI tables, and 3D models need screen space.
- Engineers, quality, manufacturing engineers, and purchasing users are likely on laptops/desktops.
- Security, files, and setup are easier to control.

Mobile/tablet access can come later for:

- Shop-floor training.
- Service troubleshooting.
- QR-code access to product context.
- Voice questions near equipment.
- Viewing work instructions.

Recommended positioning:

> InspectorPro pilot runs as a controlled web/desktop experience inside a defined customer environment. Tablet or mobile access can be added later for service and shop-floor workflows.

## Backend Map Needed

Before a serious pilot, create a backend system map that documents:

- Frontend-to-backend flow.
- API endpoint groups.
- Data storage locations.
- AI/model call points.
- SolidWorks bridge boundary.
- Authentication/security gaps.
- Audit/logging points.
- Pilot deployment diagram.

This map will help answer customer questions about security, model usage, data protection, and deployment.

## Open Questions

- Which workflow should be the first real customer pilot?
- Which customer data package should be used first?
- Do we add basic login before the first pilot or run controlled local access?
- Which AI model/provider should be the default pilot configuration?
- Should pilot mode be controlled by environment variable, config file, or URL flag?
- What should be the first measurable success metric?

