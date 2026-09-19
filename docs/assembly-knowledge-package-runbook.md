# Assembly Knowledge Package Runbook

Status: implemented operator workflow

This runbook prepares a revisioned Assembly Knowledge Package (AKP) from a
native SolidWorks assembly. The canonical package extractor owns structure,
occurrence, and mate identity. The standalone extractor adds presentation
views, occurrence masks, and GLB geometry. It never invents a second identity
system.

## Safety Boundary

- Native CAD is read only.
- Deterministic preparation makes no model call.
- AI enrichment is disabled unless its separate flag is enabled.
- An enrichment call also requires an explicit spend approval bound to the
  exact package request.
- Package publication uses canonical ASCII JSON, optimistic concurrency,
  atomic replacement, retained backups, and source revision checks.
- A package can support planning without being production approved.
- Assembly structure, mates, names, and geometry do not prove manufacturing
  order.

## Prerequisites

1. SolidWorks is installed and can open the source assembly.
2. Build the canonical package CLI in the sibling
   `InspectorPro.SolidWorks` repository.
3. Build `SolidWorksExtractor` in Release mode.
4. Run commands from the `AI-Drawing-Inspector` repository root.
5. Set the preparation flag:

```powershell
$env:INSPECTORPRO_ASSEMBLY_KNOWLEDGE_PREPARE = '1'
```

The verified Tricycle source is:

```text
C:\Users\might\OneDrive\Desktop\Tricyle\SWPR-Tricycle.SLDASM
```

## 1. Extract Canonical Structure

The standalone package CLI is an approved entry point because it calls the
same `AssemblyPackageWriter` used by the SolidWorks bridge.

```powershell
$packageCli = '..\InspectorPro.SolidWorks\src\InspectorPro.PackageCli\bin\Debug\net48\inspectorpkg.exe'
$sourceRoot = 'C:\Users\might\OneDrive\Desktop\Tricyle'
$assembly = Join-Path $sourceRoot 'SWPR-Tricycle.SLDASM'
$work = '.runtime\package_prep\tricycle'
$extractRoot = Join-Path $work 'canonical'

& $packageCli extract-assembly --out $extractRoot --open $assembly
```

The command creates one `<sha256>.inspectorpkg` directory. Validate it before
continuing:

```powershell
& $packageCli validate-package '<full path to the .inspectorpkg directory>'
```

Stop if validation fails. Do not repair package JSON by hand.

## 2. Generate the Canonical Occurrence Map

This converts canonical component instance paths into stable AKP occurrence
IDs. The map is the only identity input accepted by the visual extractor.

```powershell
python tools\prepare_assembly_knowledge.py occurrence-map `
  --product-id tricycle `
  --extracted-package '<full path to the .inspectorpkg directory>' `
  --source-root $sourceRoot `
  --root-assembly $assembly `
  --configuration Default `
  --output (Join-Path $work 'occurrence_map.tsv') `
  --report (Join-Path $work 'occurrence_map_receipt.json')
```

The receipt must report one mapped component for every non-root occurrence and
zero model calls.

## 3. Capture Views, Masks, and GLB

Use the standalone extractor only for visual and geometry enrichment:

```powershell
$visualExtractor = 'SolidWorksExtractor\bin\Release\SolidWorksExtractor.exe'
$capture = Join-Path $work 'capture'
$extractJson = Join-Path $capture 'tricycle_extract.json'

& $visualExtractor $assembly `
  --output $extractJson `
  --full `
  --resolve `
  --views `
  --export-glb `
  --identity-masks `
  --occurrence-map (Join-Path $work 'occurrence_map.tsv')
```

Expected visual outputs include:

```text
SWPR-Tricycle_view_front.png
SWPR-Tricycle_view_top.png
SWPR-Tricycle_view_right.png
SWPR-Tricycle_view_isometric.png
SWPR-Tricycle_identity_mask_view_front.png
SWPR-Tricycle_identity_mask_view_top.png
SWPR-Tricycle_identity_mask_view_right.png
SWPR-Tricycle_identity_mask_view_isometric.png
SWPR-Tricycle_identity_mask_legend.tsv
SWPR-Tricycle_colored.glb
```

Stop if a visible mask color is absent from the legend, a legend occurrence is
unknown, repeated occurrences share an identity, or source files changed.

## 4. Publish Deterministic Evidence

```powershell
python tools\prepare_assembly_knowledge.py deterministic `
  --training-root generated\training `
  --product-id tricycle `
  --extracted-package '<full path to the .inspectorpkg directory>' `
  --source-root $sourceRoot `
  --root-assembly $assembly `
  --configuration Default `
  --capture-dir $capture `
  --assembly-base-name SWPR-Tricycle `
  --glb (Join-Path $capture 'SWPR-Tricycle_colored.glb') `
  --report (Join-Path $work 'deterministic_receipt.json')
```

For a new package, omit `--base-revision`. For an intentional update to an
existing package, supply the exact current package revision. A stale revision
must return a conflict rather than overwrite newer work.

The deterministic result should normally be `function_ready`. That means the
structure and deterministic evidence are valid; it does not mean process order
has been established.

## 5. Optional Bounded AI Enrichment

Do not enable this stage merely to complete deterministic preparation. It is
needed when visual and domain inference should propose functional roles,
interfaces, process branches, or operation families.

Set exactly one provider key and the enrichment flag:

```powershell
$env:INSPECTORPRO_ASSEMBLY_KNOWLEDGE_AI_ENRICHMENT = '1'
```

Preview the provider/model pricing policy before approving spend. Then run one
explicitly approved request:

```powershell
python tools\prepare_assembly_knowledge.py enrich `
  --training-root generated\training `
  --product-id tricycle `
  --package-id '<package ID from the deterministic receipt>' `
  --provider openai `
  --model '<approved multimodal model>' `
  --user-id '<operator ID>' `
  --session-id '<session ID>' `
  --idempotency-key '<unique stable request key>' `
  --cache-root .runtime\assembly_knowledge_cache `
  --approve-spend `
  --report (Join-Path $work 'enrichment_receipt.json')
```

The default policy makes one multimodal call and allows at most one
image-free schema correction. It makes no per-part or per-interface calls.
Unknown pricing fails closed unless the operator explicitly acknowledges it.

Do not put API keys in reports, package JSON, command history, or screenshots.

## 6. Review Inferred Claims

Run the app with these capability flags:

```powershell
$env:INSPECTORPRO_PROCESS_MAP_EDIT = '1'
$env:INSPECTORPRO_ASSEMBLY_KNOWLEDGE_REVIEW = '1'
$env:INSPECTORPRO_PROCESS_MAP_SEMANTIC_GENERATION = '1'
```

Open the Process Map and use the Assembly Knowledge review command. Review
work is by exception:

- Confirm a claim when evidence supports it.
- Edit a claim when the inferred wording is directionally right.
- Reject a false claim.
- Mark unknown when available evidence cannot establish it.
- Defer when a qualified reviewer or source is still needed.

Confirmation is auditable review evidence. It is not formal production
approval.

## 7. Evaluate the Package

```powershell
python tools\prepare_assembly_knowledge.py evaluate `
  --training-root generated\training `
  --product-id tricycle `
  --package-id '<package ID>' `
  --runtime-guards-verified `
  --runtime-guard-evidence tests/test_assembly_knowledge_process_map_integration.py `
  --report generated\training\tricycle\assembly_knowledge_evaluation.json
```

The report separates:

- hard safety metrics;
- review burden;
- model calls, images, tokens, price confidence, and maximum cost;
- package readiness; and
- controlled rollout eligibility.

Do not describe a `function_ready` package as planning-ready. A package reaches
`planning_ready` only after validated enrichment supplies reviewable process
candidates.

## 8. Generate a Process Map Proposal

Sage receives only the server-built `process_map.evidence` context bound to the
current package and source revisions. Sage drafts semantic process meaning.
Builder validates and compiles it. Deterministic layout and routing own world
coordinates.

The expected sequence is:

```text
observe trusted package and map state
draft one Semantic Process Plan
validate evidence, coverage, stages, and assumptions
build one complete ghost preview
review warnings and unresolved questions
approve once
apply atomically
receive created IDs and the new map revision
```

A changed CAD source, package revision, process map revision, or structure
revision invalidates the proposal.

## Recovery

### Source changed

Discard the pending proposal, re-extract, regenerate the occurrence map and
visuals, then publish a new package revision. Never relabel stale evidence as
current.

### Registry or package conflict

Read the current package revision and compare it with the operator receipt.
Do not bypass compare-and-swap. Package backups are recovery insurance, not a
merge mechanism.

### Provider timeout

The adapter performs only its bounded retry. Reuse the same semantic request
and cache key when retrying; use a new idempotency key only for a genuinely new
authorized request.

### Review burden exceeds 0.25 actions per occurrence

Stop rollout and improve extraction, evidence compilation, or enrichment.
Do not lower the threshold or silently shift preparation back to manual entry.

## Verified Tricycle Checkpoint

The current local package has:

```text
package ID: akp-e573bb32c6b95350b80a7a47
package revision: 2a7041062ce016f599c88d87ebd9c0518fd588a860bdc5e1463ebcda2d1cbc32
source occurrences: 27 including the root
component occurrences: 26
mates: 52
candidate interfaces: 37
presentation views: 4
identity masks: 4
source status: current
hard safety metrics: passed
required process inputs accounted for: 26 of 26
candidate process branches: 1
candidate operation stages: 10
unresolved process inputs: 0
readiness: planning_ready
production eligible: false
published enrichment provider: Anthropic
published enrichment model: claude-sonnet-4-5-20250929
published enrichment prompt: assembly-enrichment-economy-v7
published enrichment model calls: 2
submitted images: 5
input tokens: 36178
output tokens: 4841
estimated maximum cost: USD 0.158472
pending inferred claims: 11
rollout evaluator: passed
```

The package is ready for Sage to propose a process map. Its process semantics
remain inferred, supporting, and pending review. `planning_ready` does not make
the package production-approved, and the final process-map proposal still
requires explicit user approval before Builder can apply it atomically.
