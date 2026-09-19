# Assembly Knowledge Extraction Reconnaissance

Status: P0.5 complete

Date: 2026-07-25

Reference source:

```text
C:\Users\might\OneDrive\Desktop\Tricyle\SWPR-Tricycle.SLDASM
```

No native CAD source file was modified. No model call was made.

## Decision

The canonical structured extraction authority is the versioned
`AssemblyPackageWriter` contract in the external
`InspectorPro.SolidWorks` repository.

Both of these entry points call that exact writer:

- `InspectorPro.PackageCli extract-assembly`
- the SolidWorks bridge `JobRunner.ExtractAssembly`

The standalone package CLI is therefore an approved preparation entry point
without creating a second package schema. The bridge remains the normal
application authorization and ingestion boundary.

The older `AI-Drawing-Inspector/SolidWorksExtractor` is enrichment-only. It
may emit presentation views, GLB meshes, and geometry summaries, but it must
not create canonical occurrence or mate identities.

## Fixture Run

The package CLI produced:

```text
package schema: 1.0
active configuration reported by CLI: Default
component occurrences: 26
mates: 52
unique occurrence names: 26
repeated source part files: 6
```

The package validator passed with zero errors and zero warnings. A second
extraction produced the same package ID, component order, mate order, and
structured payload after the extraction timestamp was normalized.

The enrichment-only extractor produced:

```text
presentation views: front, top, right, isometric
custom GLB: 26 component meshes, approximately 22 MB
native SolidWorks GLB: failed with SolidWorks error 256
```

Its reported count of 27 includes the root assembly; its custom GLB correctly
contains the same 26 occurrences as the canonical package.

## Field Coverage

| Required Stage B field | Status | Evidence / action |
| --- | --- | --- |
| Root assembly | Available | Manifest source document |
| Active configuration | Derivable, serialization gap | CLI reports `Default`; current manifest omits it |
| Available configurations | Missing | Add in P1 |
| Component instance identity | Available with risk | `IComponent2.Name2` is emitted as `components[].name` |
| Source part path | Missing from package | Only referenced filename is emitted; resolve and hash locally |
| Source part hash | Missing | Local source-manifest layer owns it |
| Occurrence hierarchy | Available | `level` and `parentName`; Tricycle itself is flat |
| Quantities | Available | Synthesized BOM and occurrence list |
| Suppressed/lightweight/virtual | Available | Canonical package |
| Hidden state | Read but dropped | Add to package schema in P1 |
| Transform | Available | Translation, rotation, scale, quaternion |
| Mate display name/type/endpoints | Available | 52 complete two-ended mate records |
| Stable mate identity | Derivable with warning | Display names are aliases; entity geometry is absent |
| Mate geometry | Deferred | Package explicitly reports `extractsMateGeometry: false` |
| Component custom properties | Missing | Root custom properties only |
| Material/mass properties | Missing | Enrichment extractor or later part package |
| Feature/geometry summaries | Enrichment-only | Older extractor can provide partial summaries |
| Candidate interface axes/bounds | Missing | P3 deterministic geometry work |
| Presentation views | Enrichment-only | Four named views verified |
| Occurrence identity masks | Missing | Existing colorizer keys by part filename and is not authoritative |
| Assembly GLB | Enrichment-only | Custom GLB verified; native export failed |
| Structured findings | Partial | Manifest warning strings only; add typed findings |

## Identity Contract

Canonical occurrence IDs will be derived from:

```text
normalized component instance path
+ active configuration
+ source assembly identity
```

Repeated uses of one part file must receive distinct occurrence IDs.

The existing Process Map `product_occurrence.sourceOccurrenceId` remains the
public linkage. New packages supply its CAD-native value for new maps.
Existing legacy maps retain their current IDs and bytes; migration is an
explicit mapping operation, never an implicit rewrite.

Mate display names such as `Concentric1` are aliases. P1 derives a mate ID
from participant occurrence IDs, mate type, normalized entity facts, and a
deterministic collision ordinal. Records lacking sufficient entity identity
are marked weak rather than presented as stable.

## Gaps Found During the Real Run

1. The root source hash was emitted as 64 zeroes while SolidWorks held the
   assembly open. P1 hashes source files before extraction and verifies them
   again afterward.
2. The CLI reports `Default`, but the assembly manifest's configuration field
   and configuration-sensitive package key are blank. P1 must serialize the
   active configuration before package identity is computed.
3. The Tricycle file has no authored subassemblies. Any wheel, frame,
   handlebar, or seat branch proposed later is semantic and inferred, not CAD
   structure.
4. Mate points, directions, radii, and persistent entity references are empty
   in package schema 1.0.
5. The old part colorizer assigns colors per filename and cycles a 20-color
   palette. It cannot identify repeated occurrences.
6. Native GLB export is not reliable on this SolidWorks installation. The
   custom mesh exporter is the verified fallback.

## Version Policy

Supported bridge package major version:

```text
1
```

Unknown major versions fail closed. Minor additions remain rejected by the
strict adapter until a frozen compatibility fixture and adapter version
explicitly support them.

The canonical adapter has an independent version. Package metadata records
both the bridge schema version and adapter version.

## P1 Revised Scope

Primary files:

```text
ai_inspector/assembly_knowledge/
  schema.py
  manifest.py
  extract_adapter.py
  identity.py
  repository.py
  validate.py

tests/
  test_assembly_knowledge_schema.py
  test_assembly_knowledge_adapter.py
  fixtures/assembly_knowledge/packages/bridge-v1.0/
```

External extractor changes:

```text
InspectorPro.SolidWorks/
  AssemblyExtraction.cs
  AssemblyDocumentPia.cs
  AssemblyExtractionBuilder.cs
  AssemblyPackageWriter.cs
```

P1, P2, and P3 may proceed under this authority decision.
