# MMLE-50D Synthetic Process Evidence

This directory is a synthetic demonstration evidence package for the MMLE-50D
Electric Mobile Lift. It exists to test whether Sage can retrieve source-like
manufacturing information, bind it to the real CAD occurrence catalog, and
produce a complete high-level Process Map.

The files are not OEM work instructions and are not approved production
requirements. They must never be represented as released manufacturing data.
The generated Assembly Knowledge Package is therefore planning-ready but not
production-eligible.

The package deliberately separates inputs:

- `assembly-routing.json` defines the candidate operation sequence and branches.
- `stage-details.json` defines the evidence-bound child process for each of the
  14 high-level stages.
- `in-process-inspection-plan.json` defines reviewable inspection intent.
- `functional-test-procedure.json` defines the end-of-line test intent.
- `resource-register.json` defines illustrative work centers and resources.
- `process-assumptions.json` records limitations and unresolved questions.
- `work-instruction-stage-03.json` defines a revisioned, operation-level
  scissor-mechanism benchmark with synthetic parts, tools, specifications,
  safety controls, quality checks, records, and CAD scene plans.

The Stage 03 benchmark is approved only for synthetic demonstration. Its exact
values make the operator-page workflow testable, but they do not close the
actual MMLE-50D manufacturing release findings and cannot authorize production.

The builder resolves functional group names to the stable occurrence IDs in the
real MMLE-50D product structure. The held-out expected topology used by tests is
stored outside this directory and is never included in Sage's evidence context.

## Build and verify

From the `AI-Drawing-Inspector` repository root:

```powershell
python tools\build_mmle_synthetic_process_knowledge.py
python tools\build_mmle_synthetic_process_knowledge.py --check
```

Open the application with the MMLE-50D assembly selected:

```text
http://127.0.0.1:8125/?assemblyProfile=MMLE-50D
```

Ask Sage:

```text
Generate a high-level process map for the complete MMLE-50D Electric Mobile
Lift. Use the registered assembly knowledge, include every required occurrence
exactly once, show one complete ghost preview, and wait for my approval. Do not
commit it.
```

The expected review-only result contains 14 operations, 4 synchronization
junctions, 18 connections, and all 206 required leaf occurrences. The proposal
must remain pending until a user explicitly approves it; generating or viewing
the preview must not alter the saved map.

After the high-level map is approved, select a stage and choose `Open`, or
double-click it. InspectorPro creates or reuses a separate child map and shows
that stage's detailed process as a ghost proposal. The parent map is unchanged,
and the child process is not written until it is explicitly approved. The
breadcrumb and Back command return to the parent high-level map.
