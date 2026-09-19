# Scope and Governance

## 1. Objective

Build a reusable InspectorPro workflow that converts a loaded CAD assembly plus approved product evidence into a reviewed operations and maintenance manual. The MMLE-50D is the proof-of-concept product; the architecture must remain product-neutral.

The workflow must generate structured technical content, CAD-grounded figures, safety panels, procedures, tables, citations, and release artifacts without treating an LLM as an engineering authority.

## 2. Product and Configuration Boundary

| Field | Prototype value | Authority | Release status |
| --- | --- | --- | --- |
| Product | MMLE-50D Electric Mobile Lift | InspectorPro registry plus current Lift Products page | Identified |
| CAD asset | `asset-mobile-lift-mmle-50d` | InspectorPro assembly registry | Identified |
| Assembly revision | `A` | InspectorPro registry | Internal identity only; not proven OEM revision |
| CAD source | `generated/industrial_assets/local_library/mobile-lift-mmle-50d/extracted.json` | SolidWorks extraction | Geometry/identity evidence |
| Market baseline | United States | Project decision | Prototype only |
| Language | English (US) | Project decision | Prototype only |
| Page format | 16:9 landscape, 960 x 540 pt logical page | Project decision | Approved for the review workflow |
| Serial/effectivity | Unknown | No authoritative source | Release blocker |
| Electrical configuration | Current product page indicates onboard 12 V battery and internal automatic 110 V charger | Current OEM web page | Requires modeled-configuration approval |
| Safety certification | Current product page states CE certified | Current OEM web page | Do not publish as configuration certification without declaration/effectivity |

The compiler must bind every manual to an explicit `ProductConfiguration`. A model number alone is insufficient for production release.

## 3. Audiences and Role Boundaries

### Operator

May perform pre-use inspection, normal controls, load movement, parking/braking, approved charging, cleaning, and storage. The manual must not direct an operator to open guarded electrical/hydraulic areas or adjust pressure controls.

### Owner or Supervisor

Owns operator qualification, inspection records, workplace procedures, defect escalation, and retention of the controlled manual.

### Qualified Maintenance Technician

May perform only the maintenance and troubleshooting explicitly approved for that role and configuration. Electrical, hydraulic, stored-energy, and structural work requires qualified personnel and the employer's energy-control procedure.

### Engineering/Manufacturer Approver

Approves configuration effectivity, operating limits, residual risks, warning language, intervals, consumables, schematics, service procedures, and release metadata.

### Technical Publications Approver

Approves terminology, readability, figure references, page flow, revision control, citations, accessibility, and output integrity.

Sage is not an approver. Sage drafts, organizes, and explains evidence-bound content.

## 4. Evidence Classes

Every factual claim must use one class:

| Class | Meaning | Publication use |
| --- | --- | --- |
| `CAD_AUTHORED` | Identity, occurrence membership, geometry, transforms, mates, and visible interfaces extracted from CAD | Figures and component references; not operational limits |
| `OEM_CURRENT` | Current manufacturer-controlled product information | Preferred product baseline, subject to configuration/effectivity |
| `OEM_LEGACY` | Older manufacturer manual or service information | May be used only when applicability is explicitly approved |
| `STANDARD_REQUIREMENT` | Requirement or terminology from a controlled standard | Requires a licensed/current source and applicability review |
| `REGULATORY` | Applicable law or regulation | Must be current and jurisdiction-specific; legal review where required |
| `DERIVED` | Deterministic computation from trusted inputs | Publish with derivation and input provenance |
| `INFERRED` | Planner or reviewer interpretation | Draft/recommendation only until approved |
| `USER_AUTHORED` | Explicit user or customer instruction/metadata | Publish only within the user's authority and after validation |
| `UNKNOWN` | Evidence is absent, conflicting, or not applicable | Must remain unresolved; never filled by plausible text |

Evidence strength is not confidence theater. A high-confidence inference does not outrank authored product data.

## 5. Authority Order

For a claim about the prototype configuration, use this order:

1. approved configuration-specific engineering record;
2. current manufacturer manual/data tied to the same configuration and effectivity;
3. current manufacturer product page;
4. licensed applicable standards and regulations;
5. legacy manufacturer documentation after compatibility review;
6. CAD identity/geometry evidence;
7. deterministic derivation;
8. inference.

Sources lower in the list may supplement higher sources but may not silently override them. A conflict creates a finding, not an average.

## 6. Source-of-Truth Layers

1. `SourceRecord`: immutable source identity, location, date, hash, authority, and license.
2. `EvidenceClaim`: atomic claim linked to one or more sources, configuration, status, and conflict set.
3. `OperationsManualPlan`: approved section/page/block plan; it does not contain final prose by itself.
4. `DocumentationScene`: presentation overrides and editable document objects only.
5. `CompiledDocument`: deterministic merge of plan, approved claims, CAD references, theme, and scene.
6. `ArtifactSet`: revision-bound captures, PDF, DOCX, manifests, and validation receipts.

No renderer may rediscover product facts. No DOCX exporter may bypass the compiled document.

## 7. Release States

| State | Meaning | Required marking |
| --- | --- | --- |
| `research` | Sources are being collected and reconciled | Internal only |
| `draft` | Evidence-bound draft exists; unresolved findings remain | `DRAFT`, with approval status and unresolved release controls shown in document control |
| `review` | Content and figures are complete enough for named reviewers | `FOR REVIEW` |
| `approved` | Required approval receipts are present | Controlled revision |
| `published` | PDF was produced from the approved revision and passed publication QA | Controlled artifact |
| `superseded` | A later approved revision exists | Superseded marking and retention |

The MMLE-50D proof of concept cannot move past `draft` until the release blockers in the package README are resolved.

## 8. Explicit Non-Goals for the First Pass

- certify the product or declare legal compliance;
- author a customer-specific lockout/tagout program;
- create missing electrical/hydraulic engineering data;
- invent torque values, lubricants, pressure settings, dimensions, or part numbers;
- treat the old service manual as automatically applicable to the current configuration;
- provide field repair instructions for safety-critical hydraulic or electrical systems;
- implement general-purpose desktop publishing or unrestricted Word round-tripping;
- copy the supplied reference manual's copyrighted prose or artwork.

## 9. Approval Matrix

| Content | Engineering | Safety/EHS | Technical publications | Product owner |
| --- | ---: | ---: | ---: | ---: |
| Product specs/effectivity | Required | Review | Review | Required |
| Intended/prohibited use | Required | Required | Review | Required |
| Safety panels/residual hazards | Required | Required | Required | Review |
| Operating procedures | Required | Required | Required | Review |
| Maintenance/service | Required | Review | Required | Review |
| Figures/callouts | Required for technical accuracy | Review | Required | Optional |
| PDF/DOCX formatting | Review | Optional | Required | Review |
| Final release | Required | Required | Required | Required |

Approval receipts must identify person, role, scope, document revision, timestamp, and disposition. A chat acknowledgement is not a release receipt.

The receipt must validate against [approval-receipt.schema.json](approval-receipt.schema.json). Approval is revision-bound: any change to source, evidence, plan, figure, safety message, or compiled document outside the receipt scope invalidates that approval for the changed content.

## 10. Required Reviewer Assignments

Named people cannot be inferred from project files. The following assignments are Phase 0 entry blockers and must be completed by the pilot owner:

| Assignment ID | Required role | Named person | Organization/identity | State |
| --- | --- | --- | --- | --- |
| `REVIEWER-ENGINEERING` | Product/configuration engineering authority | Not assigned | Not supplied | `BLOCKED` |
| `REVIEWER-SAFETY` | Safety/EHS authority | Not assigned | Not supplied | `BLOCKED` |
| `REVIEWER-TECH-PUBS` | Technical-publications authority | Not assigned | Not supplied | `BLOCKED` |
| `REVIEWER-PRODUCT` | Product owner/release authority | Not assigned | Not supplied | `BLOCKED` |
| `REVIEWER-LEGAL` | Open-source and standards licensing authority | Not assigned | Not supplied | `BLOCKED` |
| `REVIEWER-ACCESSIBILITY` | Accessibility conformance reviewer | Not assigned | Not supplied | `BLOCKED` |

No agent may fill these names with a plausible person. The application must reject an approval receipt whose authenticated identity does not match the assigned reviewer for the role and scope.

## 11. Supersession, Withdrawal, and Evidence Invalidation

Published artifacts are immutable. A new revision never overwrites an earlier PDF, DOCX, manifest, hash, or approval receipt.

- `superseded`: a later approved revision replaces an artifact for ordinary use; the old artifact remains retained and visibly marked in InspectorPro.
- `withdrawn`: a safety, configuration, evidence, or licensing defect makes continued use unacceptable; distribution links are disabled and the reason is retained.
- Evidence hash changes or a source becoming inapplicable creates a disposition review. Affected claims, sections, figures, and publication receipts are traversed by dependency identity.
- A safety-significant invalidation triggers engineering and safety review plus the approved recipient-notification process; Sage cannot decide recall scope.
- External DOCX edits create a new uncontrolled file only. V1 has no route that promotes it back to `approved` or `published`.

Every publication receipt must record status, predecessor/successor identity where applicable, disposition reason, actor, and timestamp. The UI must warn when a user opens or downloads a superseded artifact and must block a withdrawn artifact.
