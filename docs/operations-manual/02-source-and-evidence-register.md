# Source and Evidence Register

The machine-readable records are in `source-register.json` and `evidence-register.json`. This document explains their use and records the key reconciliation decisions.

## 1. Source Hierarchy

| ID | Source | Use | Authority/limitation |
| --- | --- | --- | --- |
| `SRC-CAD-MMLE-EXTRACT` | MMLE-50D SolidWorks extraction | Component identity, structure, geometry, figure scope | Does not establish operating or safety claims |
| `SRC-CAD-MMLE-GLB` | MMLE-50D GLB | Browser rendering and CAD-grounded captures | Visual derivative, not a product specification |
| `SRC-IP-MMLE-REGISTRY` | InspectorPro assembly registry | Asset binding, internal revision, curated service groups | Internal metadata; not OEM release data |
| `SRC-OEM-MMLE-WEB-2026` | Current Lift Products MMLE product page | Current product description, specifications, controls, standard features | Commercial page; configuration/effectivity still requires approval |
| `SRC-OEM-MMLE-SERVICE-2012` | Lift Products MMLE-50D Service Manual | Legacy warnings, inspection, operation, service schedule, troubleshooting | Legacy configuration; battery and brake details conflict with current data/CAD |
| `SRC-MHI-LIFT-GUIDE-2020` | MHI LIFT guide | Product-category concepts and advisory safety context | Advisory guide; explicitly not a substitute for MH29.1 |
| `SRC-REF-TLIFT440` | User-supplied TLIFT440 operations manual | Presentation, page hierarchy, figure/text composition | Reference only; no product facts may transfer |
| `STD-ANSI-MH29-1-2020` | ANSI MH29.1-2020 | Primary US industrial scissors-lift standard | Paid/licensed; clause-level review not yet performed |
| `STD-ANSI-Z535-1-2022` | ANSI Z535.1-2022 | Safety colors | Paid/licensed; color tokens must be verified before release |
| `STD-ANSI-Z535-3-2022` | ANSI Z535.3-2022 | Criteria for safety symbols | Paid/licensed; symbol selection/evaluation review required |
| `STD-ANSI-Z535-4-2023` | ANSI Z535.4-2023 | Product safety signs and labels | Paid/licensed; relevant to labels/decals and their representation |
| `STD-ANSI-Z535-6-2023` | ANSI/NEMA Z535.6-2023 | Product-safety information in manuals | Paid/licensed; clause-level review not yet performed |
| `STD-ANSI-Z535-7-2024` | ANSI Z535.7-2024 | Product safety information in electronic media | Paid/licensed; relevant to the in-app/digital manual experience |
| `REG-OSHA-1910-145` | OSHA 29 CFR 1910.145 | Workplace accident-prevention signs/tags | Regulation; not the sole manual-layout standard |
| `REG-OSHA-1910-147` | OSHA 29 CFR 1910.147 | Employer energy-control obligations | Do not fabricate a customer-specific LOTO program |
| `REG-OSHA-1910-212` | OSHA 29 CFR 1910.212 | General machine guarding | Apply through risk review, not boilerplate claims |
| `STD-ISO-12100-2010` | ISO 12100:2010 | Risk-assessment and risk-reduction framework | Licensed standard; revision activity noted by ISO |
| `STD-ISO-13850-2015` | ISO 13850:2015 | Emergency-stop design principles | Applicability/configuration review required |
| `STD-ISO-13849-1-2023` | ISO 13849-1:2023 | Safety-related control-system design | Engineering design evidence required |
| `STD-IEC-60204-1-2016-A1-2021` | IEC 60204-1:2016+A1:2021 | Electrical equipment of machines | Licensed; configuration review required |
| `STD-ISO-7010-2019` | ISO 7010:2019 and amendments | Registered safety signs | Use licensed/current symbols; do not redraw approximations |
| `STD-BS-EN-1570-1-2024` | BS EN 1570-1:2024 | European lifting-table safety context | Applicability depends on intended market/configuration |
| `STD-ISO-14289-2-2024` | ISO 14289-2:2024 (PDF/UA-2) | Controlled PDF accessibility target | Conformance requires independent artifact validation and named review |
| `STD-W3C-WCAG-2-2` | WCAG 2.2 | Documentation Workspace accessibility target | Target Level AA for the complete authoring workflow |
| `LIB-PYMUPDF-1-27-2-3` | PyMuPDF 1.27.2.3 | Existing PDF renderer dependency | AGPL/commercial dual license; unresolved disposition blocks implementation/pilot |
| `LIB-PYTHON-DOCX-1-2-0` | python-docx 1.2.0 | Proposed DOCX exporter | MIT; dependency must be pinned/hash-locked and approved before use |

## 2. Product Facts Approved for Prototype Drafting

The current Lift Products page supports these prototype facts for model MMLE-50D:

| Claim | Value | Status |
| --- | --- | --- |
| Intended applications | Order picking, die handling, assembly, and general lifting | Current OEM evidence; use as examples, not exhaustive authorization |
| Rated capacity | 1,100 lb | Current OEM evidence; engineering/effectivity approval required for release |
| Vertical travel | 44 in | Current OEM evidence |
| Lowered height | 19.5 in | Current OEM evidence |
| Raised height | 63.5 in | Current OEM evidence |
| Platform | 20.5 x 39.8 in | Current OEM evidence |
| Shipping weight | 436 lb | Current OEM evidence; do not label operating weight without confirmation |
| Battery | Onboard 12 V | Current OEM evidence |
| Charger | Internal, fully automatic 110 V charger | Current OEM evidence |
| Controls | Handle-mounted color-coded push buttons; battery-discharge indicator | Current OEM evidence |
| Running gear | Two front rigid polyurethane casters; two rear swivel polyurethane casters with brakes | Current OEM evidence and CAD support |
| Safety features | Trapped top/bottom rollers, retractable maintenance safety bars, maintenance isolator, emergency relief valve | Current OEM evidence; safety bars/isolator/relief valve lack approved CAD occurrence mappings and procedures |

The CAD extraction supports the physical presence of a battery box, battery switch, battery-discharge indicator, charger and plug, hydraulic power pack, cylinder, lift platform, scissor mechanisms, two swivel-caster brake levers, rigid casters, and structural covers. It does not by itself establish their rating or correct operating procedure. No occurrence is traceably identified as a maintenance safety bar or emergency relief valve; `BATTERY SWITCH` is not enough evidence to identify the advertised maintenance isolator.

## 3. Legacy Evidence Requiring Configuration Review

The 2012 service manual supplies useful candidate content:

- no riders and no access beneath an unsupported platform;
- avoid slopes, uneven/soft surfaces, unstable/unbalanced loads, overload, and pinch/shear zones;
- trained personnel and staying at the controls;
- pre-use checks for damage, wheels, cylinder leakage, vertical creep, brakes, and loose fasteners;
- movement with the table lowered;
- monthly lubrication of guides/grease points and six-month pivot/axle lubrication;
- hydraulic-oil replacement after an initial ten accumulated hours and then every twelve months;
- legacy troubleshooting and hydraulic/electrical diagrams.

These are **candidate claims**, not automatically approved instructions. The manual's old external-charger, battery-fluid, and right-brake-only language conflicts with current evidence.

## 4. Conflict Register

### `CONFLICT-001`: Battery and Charging

- Current OEM page: onboard 12 V battery, internal fully automatic 110 V charger.
- Legacy manual: disconnect battery socket, connect an external charger, inspect/add battery fluid, and follow detailed flooded lead-acid instructions.
- CAD: battery box, battery switch, BDI, charger assembly, and charger plug; part is named `Vintage Battery`, which is not trustworthy chemistry evidence.
- Decision: use the current onboard-charger architecture for the prototype. Do not draft electrolyte inspection, acid filling, external-charger connection, charge-current, or battery-removal instructions. Exact charging sequence remains `UNKNOWN` until approved current instructions are supplied.

### `CONFLICT-002`: Parking Brakes

- Legacy manual: brake on the right swivel caster.
- Current OEM page: rear swivel casters with brakes.
- CAD: both right and left swivel-caster assemblies contain a brake lever.
- Decision: prototype figures may identify both brake mechanisms. Exact required parking sequence must be approved; do not copy the right-side-only instruction.

### `CONFLICT-003`: Product Revision and Effectivity

- InspectorPro registry says revision `A`.
- No OEM drawing revision, serial range, build date, or configuration record was supplied.
- Decision: `A` is internal asset/source identity only. It must not populate the controlled product/document revision field. No OEM-revision claim and no production release.

### `CONFLICT-004`: CE Claim

- Current OEM page states CE certified.
- No declaration, notified-body record, harmonized-standard list, or exact configuration effectivity is available.
- Decision: retain as source evidence but omit the CE mark and compliance declaration from generated pages until verified.

### `CONFLICT-005`: Part Numbers

- InspectorPro has assigned stable library part numbers to the CAD definitions.
- The legacy service manual has a separate numbered spare-parts list.
- No approved mapping establishes that InspectorPro IDs are OEM service part numbers.
- Decision: operations-manual prose uses approved display descriptions. Any appendix must label internal IDs as `InspectorPro library ID`; unavailable OEM part numbers read `Not specified`.

### `CONFLICT-006`: Dimensions

- Current OEM page supplies published operating dimensions.
- CAD bounding extents differ because model extents, orientation, handles, and manufacturing geometry are not guaranteed to represent catalog envelope measurements.
- Decision: use current OEM dimensions in the specifications table. Use CAD only for visual scale and figure generation unless a deterministic measurement is explicitly labeled derived.

### `CONFLICT-007`: Maintenance Data

- The legacy manual supplies intervals but no confirmed current hydraulic fluid grade, quantity, torque values, approved grease, or current service procedure.
- Decision: intervals may appear only as `legacy candidate` during review. Production publication remains blocked until approved maintenance data is supplied.

### `CONFLICT-008`: Advertised Safety Features Versus Modeled CAD

- Current OEM page: retractable maintenance safety bars, maintenance isolator, and emergency relief valve are listed as standard features.
- CAD: no approved occurrence mapping exists for any of those feature identities.
- Decision: block every caption, callout, procedure, or figure that asserts/depicts those features until the exact configuration and occurrence mappings are approved. A generic component-name resemblance is not mapping evidence.

### `CONFLICT-009`: Internal Revision in Controlled Fields

- CAD identity: revision is null.
- InspectorPro registry: internal asset revision is `A`.
- Existing parts-manual output has displayed `Rev A` without qualifying its internal provenance.
- Decision: remediate the shared document-control path before reuse. Suppress the field or label it as `InspectorPro asset rev A - not OEM document revision`; add a regression test.

## 5. Required Evidence Gaps

Conflicts have competing evidence. Gaps have no adequate current evidence at all. The machine-readable register tracks thirteen release-blocking gaps:

| Gap | Missing authority | Affected content |
| --- | --- | --- |
| `GAP-001` | Configuration/serial/build effectivity | Whole release |
| `GAP-002` | Current charging and battery instructions | Controls, charging, storage |
| `GAP-003` | Current brake/parking sequence | Inspection, moving, parking |
| `GAP-004` | Load center/distribution/securement limits | Intended use, specs, loading, operation |
| `GAP-005` | Maintenance-isolator/support procedure | Safety and maintenance |
| `GAP-006` | Current maintenance intervals, fluids, lubricants, torque, pressure, tools, and criteria | Maintenance and troubleshooting |
| `GAP-007` | Current electrical/hydraulic schematics | Troubleshooting and service |
| `GAP-008` | Approved service contacts and OEM part mapping | Service and parts reference |
| `GAP-009` | Configuration-specific risk assessment and approved safety messages | Safety and every procedure |
| `GAP-010` | Environmental, duty, floor, and slope limits | Specs, use, operation, storage |
| `GAP-011` | Licensed standards review and named approvals | Document control and publication |
| `GAP-012` | Approved PyMuPDF/renderer license disposition | PDF implementation, pilot, and commercial release |
| `GAP-013` | Provenance-aware controlled revision fields | Cover, headers/footers, and parts-manual regression |

The planner must report gap coverage independently from conflicts and claim coverage.

## 6. Standards Acquisition Plan

Before production implementation can claim standards alignment:

1. Purchase or otherwise lawfully obtain ANSI MH29.1-2020 and the applicable Z535 package: at minimum Z535.1, Z535.3, Z535.4, Z535.6, and Z535.7 for the in-app electronic presentation.
2. Record edition, amendment/corrigenda status, license restrictions, custodian, and source hash where permitted.
3. A named standards reviewer verifies edition currency directly with the SDO and records reviewer/date/authoritative URL; a pre-coding web check cannot satisfy this gate.
4. Have engineering/safety reviewers create clause-level applicability records. Do not upload copyrighted full text into prompts unless the license allows it.
5. Store short, purpose-limited requirement summaries linked to the controlled source, not copied standard clauses.
6. If EU release is in scope, obtain EN 1570-1 and the relevant declaration/technical-file evidence before using CE language.
7. Validate ISO 7010 symbols from licensed assets; never generate safety symbols from prose or image generation.

## 7. Reference-Manual Assessment

The TLIFT440 manual is a useful benchmark because it combines procedures, warning panels, assembly illustrations, product features, troubleshooting, maintenance records, and a parts appendix.

Reuse these presentation concepts:

- 16:9 landscape page rhythm with clear section openings;
- procedure text adjacent to the relevant figure;
- selective red highlights and hardware/detail insets;
- visible safety-signal hierarchy;
- combined owner/operator/service content with explicit section boundaries;
- maintenance log and troubleshooting table.

Improve these weaknesses:

- add document control, effectivity, revision history, approval receipts, and source provenance;
- prevent duplicate numbering, typographical errors, and hidden/stray text;
- require tools, torque, acceptance criteria, and role boundaries where procedures need them;
- provide bookmarks, links, tagged reading order, alt text, and accessible table structure;
- keep product facts separate from styling templates.

The reference manual may guide layout, but its text, product specifications, warnings, and artwork are not evidence for the MMLE-50D.
