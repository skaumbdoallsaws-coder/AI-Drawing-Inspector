# Sage on Codex in Documentation (plan, 2026-10-25)

## Why

The user, 2026-10-25: "connect codex to the documentation workflows and give him access to the necessary tools.
documentation has various types sage need to know them and what needed to write them ... I got a few assemblies you
can test with ... we will do a demo on it for yc".

Today Codex runs only in Facility Layout. With the ChatGPT plan sign-in (the desktop app's mode), every other chat
is refused: `codex_subscription_workflow_unavailable`. So in Workflows > Documentation, Sage cannot answer at all
on the desktop app. With an API key, Documentation goes to the older runtime: a regex fast path for fixed phrases,
then a model that only sees tool names, not what each document needs.

## What Sage gets

Sage on Codex in Workflows > Documentation (chat mode `documentation`):

1. **Knows the document types.** The five types of the app's registry (`documentation/registry.py`): Illustrated
   Parts Manual, Operations and Maintenance Manual, Product Specification Sheet, Assembly Work Instructions, and
   Inspection Sheet (planned, not built). For each: what it is for, its pages and outputs, and its release status.
2. **Knows what each one needs, and checks it for the loaded assembly.** Inputs per type, from the code and its
   docs, with the app's own check of whether this assembly has them:
   - Parts manual: the CAD occurrence catalog; trusted part numbers (missing ones print "Not specified"); grouping
     evidence (the library manual profile, CAD subassemblies, a process map, or names); an approved manual
     structure; figures the app captures from the 3D model.
   - Operations manual: the catalog; registered evidence for this assembly in `docs/operations-manual` (evidence,
     source, safety-symbol and nomenclature registers, with the identity claim); figures. Review export only.
   - Specification sheet: a reviewed profile `docs/specification-sheet/profiles/<assembly>.json`; approved claims in
     the evidence register; one product picture. Review export only.
   - Work instructions: a planning-ready Assembly Knowledge package; a saved default process map with detailed
     stages; nomenclature; figures. Prototype review export only.
   - Inspection sheet: not available yet.
   The authority for "ready" is the app's own state read for that type (the same function as its workspace's GET
   route). When it refuses, Sage gets the app's reason and the input it names.
3. **Reads the details.** The parts manual's sections, publication audit and the proposal's candidate groups; the
   bill of materials, whole or per section; the release gates and evidence summaries of the review-only types.
4. **Runs the app's own workflows on request.** The existing browser workflows, unchanged: propose the parts
   manual structure, build a draft, publish (PDF, or PDF + DOCX), and the parts manual's figure edits. Sage asks
   for one with a tool; the app runs it in the browser right after the reply, as the older runtime's tool calls run
   today, and the chat's status line reports the result (pages, captures, PDF link). Sage never claims a build or a
   PDF itself.

## Tools (MCP, served by a new documentation gateway)

| Tool | What it does |
| --- | --- |
| `inspect_documentation_context` | The loaded assembly, the open document type, every type with its purpose, outputs, needed inputs and live readiness, the library's other assemblies, and the workflows Sage can run. Called first. |
| `inspect_documentation_type` | One type in depth: parts manual sections, audit findings and proposal; the review-only types' release gate, evidence summary and plan summary. |
| `inspect_parts_manual_bom` | The bill of materials of the loaded assembly, or of one manual section: item, part number, description, quantity. |
| `run_documentation_workflow` | Queue one app workflow (or up to 5 figure edits) to run after the reply. Refused, with the reason, when the type is not available or the assembly lacks what it needs. |

Rules the gateway enforces, not the prompt:
- Read tools never write. They call the app's read functions only.
- One workflow per turn, or up to 5 figure edits in order (the browser runs at most 5 tool calls a turn); the
  arguments are checked against the browser tool's own schema.
- A workflow for a type the app reports blocked is refused with the app's reason.
- Parts manual, the browser workflows' own rules: a build (draft) approves a complete, conflict-free proposal;
  publishing needs an approved structure, or a proposal backed only by CAD-hierarchy or process-map evidence at
  0.80 confidence or more (`_partsManualTrustedProposalAssessment`). A library-profile proposal (MMLE-50D) is built
  first, then published with the approved structure.
- A turn has the same budget as Facility Layout (calls and seconds from `PilotSettings`).
- Identity is never a tool argument: the assembly is the one the chat request carries, and the principal comes from
  the host, as in Facility Layout. Note: the parts-manual and documentation routes have no per-user ownership
  check; these tools are no wider than the routes the Documentation workspace already calls.

## Wiring

- `codex_runtime/documentation_tools.py`: the guide (types and inputs), the tool specs, `DocumentationGateway`.
- `codex_runtime/documentation_pilot.py`: `inspect_documentation`, the turn: same journal, MCP bridge, App Server
  and replay protection as `pilot.inspect_facility`; instructions for Documentation; the result carries the queued
  browser calls (`tool_calls`) and a `codex_documentation` receipt.
- `server.py`: a documentation host (the app's read functions), and the gates: `_require_subscription_chat_route`,
  `agent_chat`, the stream route, the non-stream route (stream required), memory model metadata, and
  `/api/agent/chat/streaming-status` (`documentationRuntime`).
- On: whenever the Codex pilot is on and either the ChatGPT plan sign-in is used or
  `INSPECTORPRO_CODEX_DOCUMENTATION=1`; `INSPECTORPRO_CODEX_DOCUMENTATION=0` turns it off. With the plan sign-in
  Documentation was refused before, so nothing that worked changes.
- `static/index.html`: the stream request accepts Documentation Codex turns, with Sage's step list; before the queued
  workflow runs, the loaded assembly must still be the one Sage read; Sage's reply is kept and the app's status
  line follows it. `chat_stream_runtime.js`: a "Reading the documentation" phase.
- `codex_runtime/progress.py`: step labels for the four tools.

## Tests

- Unit and gateway tests (`tests/test_codex_documentation_tools.py`): the exact tool set, typed schemas, readiness
  for the user's assemblies, refusals, queueing limits, the budget, receipts, and a full turn with a stub transport.
- Route tests: Documentation goes to Codex; other modes stay as they were.
- Live, in the test copy UI on :8491 (`codex_ui.py`, the plan's usage, no money), on the user's assemblies:
  MMLE-50D (all four types have data), the tricycle (parts manual), the engine 100001 (parts manual). Questions about
  types and inputs, a parts manual build and publish, a refusal explained.
- Then the port to the real repo and a live check in the desktop app.

## Assemblies (test copy)

Copied read-only from the real repo on 2026-10-25: `400S_Sorted_Library/assemblies/100001*` and `100010*`,
`generated/training/tricycle`, `mmle-50d-497533f6`, `100001`. MMLE-50D was already there.

Also copied: `400S_Sorted_Library/part_number_registry.json` (untracked in the real repo, so it was missing here).
Without it MMLE-50D's 206 parts print "Not specified" and its work instructions stop at "ambiguous part number Not
specified"; with it all 206 have part numbers.

App state for them on 2026-10-25 (the GET routes, before any build), through the new tools:
- Parts manual: all four, 100% coverage, no conflicts. The tricycle (process map), 100001 and 100010 (CAD
  hierarchy) can publish directly; MMLE-50D (library profile) is built first.
- Operations manual and specification sheet: MMLE-50D only (review-ready); the others have no evidence or profile.
- Work instructions: MMLE-50D only (prototype-review-ready, 14 stages, 79 operations); the tricycle's package has
  no detailed process stages; 100001 and 100010 have no planning-ready package.

## Status

- 2026-10-25: built in the test copy. `tests/test_codex_documentation_tools.py` (30) and the route tests in
  `tests/test_codex_sage_route.py` pass with every existing Codex test (331 passed, 46 skipped) and the JS Codex
  tests.
- 2026-10-25, live on :8491 (codex_ui.py, gpt-6.1-sol on the ChatGPT plan, no money), driven by `doc_drive.py`:
  1. Tricycle, "What documents can you make for this assembly, and what does each one need?": one read, 81 s, an
     accurate table (parts manual ready from three process-map sections; the others blocked with the app's reason).
  2. Tricycle, "Publish the illustrated parts manual for this assembly as a PDF.": Sage queued
     generate_and_publish_parts_manual (approve_trusted_ready_candidates, generate_baseline_if_missing, open_pdf);
     the app approved the structure, captured 5 of 5 figures, all checks passed, and published an 8-page PDF; Sage's
     reply stayed above the app's status and PDF link. 14.5 min in the headless test browser (the first software-GL
     capture took about 9 min, the others about 30 s).
  3. Engine 100001, "Make the operations manual and the work instructions for this engine.": nothing queued; Sage
     said the registered evidence belongs to MMLE-50D and the engine needs a planning-ready Assembly Knowledge
     package and a detailed process map. 5.5 min, with the machine paging (under 1 GB free).
  Found and fixed on the way: Documentation turns had no turn identifier (codex_identity_required). Not run live:
  the MMLE-50D build (the machine ran out of memory for the headless browser); its readiness is covered by the
  gateway tests and the real-host probes.

## Not in this plan

- Inspection sheets (not built in the app).
- New document authoring abilities (text, images, themes) beyond the existing figure edits.
- Approving a parts manual structure as a separate step: the build and publish workflows already approve only a
  complete, conflict-free, trusted proposal, and stop at review otherwise.
