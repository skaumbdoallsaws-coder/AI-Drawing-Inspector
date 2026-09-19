# Equipment Capability: Answers to the Five Questions

Reviewed 2026-09-09 against the six downloaded equipment document sets. These are engineering screening answers, not installed-equipment approval or executable machine instructions. No application, asset, or layout was changed.

Revision 2 incorporates the independent review's missing Doosan limits and records import requirements for source defects and model attribution. These requirements are documented, not implemented in Sage.

## Basis

- Worked examples are the illustrative jobs from the preceding conversation, not user-supplied production jobs. Dimensions describe the example finished part unless explicitly stated otherwise.
- "Supported" means the operation is documented. "Nominal check passes" means only the identified scalar or dimensional comparison passes. Neither means the complete setup is feasible.
- PDF page references below are one-based file pages, including covers. Printed pagination can differ.
- Machine-family manuals describe optional equipment as well as standard equipment. An option mentioned in a manual is not proof that our asset has it.
- ACER and Doosan sources here are brochures, not complete operating manuals. The Haas brochure is from 2018; its limits are not combined with current web specifications. Published paired imperial/metric dimensions can be rounded; they are not manufacturing tolerances.
- Preserve original values and units, check paired-unit consistency at their printed precision, and record any reviewed field-specific precedence. Do not apply a universal "metric wins" rule. Unresolved contradictions must not become active constraints.
- Bind each field to the exact model/variant, configuration, document revision/hash, page, and table row/column or figure condition. Shared family headings and merged cells require explicit applicability; proximity to another model's value is not evidence.
- None of these jobs has a demonstrated cycle time, finished-part tolerance, or complete collision/access check. Those require a defined setup and process, not just a machine data sheet.

## 1. Haas ST-30

**Example:** steel shaft, diameter 60 mm x length 300 mm, shoulder and external thread.

1. **Required operation:** supported in principle. The NGC manual describes rough turning and straight/taper threading, including G71 and G76. Tooling must match the steel and thread.
2. **Part fit and weight:** the finished outline is smaller than the 2018 brochure's 21 x 26 inch advertised capacity. That is only an envelope screen. The manual separately restricts workholding and chuck use; no applicable numerical workpiece-weight rating was found. Stock and holding allowance remain unchecked.
3. **Required equipment:** compatible chuck/jaws or collet, turning and threading tools/holders, correct offsets, and assessed tailstock/steady support if needed. These are setup requirements, not confirmed installed items.
4. **Limits:** brochure standard spindle 3,400 rpm, chuck 10 inches, bar capacity 3 inches, 12-station bolt-on turret. The manual additionally requires observing the chuck's own RPM, jaw and clamping limits; spindle RPM alone does not authorize a setup. Live tooling is optional.
5. **Still needed:** exact machine configuration, stock size/mass, material grade/hardness, shoulder/thread drawing, tolerance/finish, jaw engagement and chuck data, support arrangement, tool selection and verified program.

**Evidence:** [2018 ST-series brochure](../output/pdf/equipment-documents-2026-09-09/Haas-ST-series-brochure-20180207.pdf), PDF p.2. [2025 NGC operator manual](../output/pdf/equipment-documents-2026-09-09/Haas-lathe-NGC-operators-manual-2025.pdf), PDF pp.140-144, 389-393, 405-407. The manuals are different editions, not a single revision-bound machine specification.

## 2. Doosan DBC 130 II

**Example:** 1,200 x 900 x 700 mm housing, 1,500 kg; machine a mounting face and aligned bores.

1. **Required operation:** boring/milling supported; required face orientation may need refixturing or an optional angle/universal head.
2. **Part fit and weight:** the bare 1,200 x 900 mm footprint fits the standard 1,600 x 1,800 mm table; 1,500 kg is below its 15,000 kg rating. Fixture loading, rotational sweep and tool access remain unchecked.
3. **Required equipment:** engineered locating/clamping fixture, suitable boring/milling tools and holders; lifting equipment for loading. BT50 applies to the documented ATC arrangement; confirm installed options.
4. **Limits, archived configuration:** XYZ travel 3,000/2,000/1,600 mm; W stroke 700 mm; spindle 2,500 rpm; cutting feed 1-4,000 mm/min. ATC table: tool length 600 mm, tool-weight variants 25/30 kg. Enlarged tool diameters require specified empty neighboring pockets. Standard table 1,600 x 1,800 mm: 15,000 kg; optional 1,800 x 2,000 mm: 13,000 kg; optional 2,000 x 2,200 mm: 12,000 kg. These are distinct from APC capacities: 10 tonnes for 1,600 x 1,800 mm, 8 tonnes for 1,800 x 2,000 mm. Swing diameter is 3,900 mm without the semi-splash guard or 3,400 mm with it. Spindle-nose-to-table-center distance is 700-2,300 mm; it is not itself usable cutting reach with every tool. The 15,000 kg row's printed 3,306.9 lb is defective; use the kg value for that row and retain the source error explicitly.
5. **Still needed:** material, bore locations/diameters/depths/tolerances, fixture geometry/mass, datum scheme, tool lengths, installed table/APC/head and machining parameters.

**Evidence:** [archived DBC brochure, EN 160919](../output/pdf/equipment-documents-2026-09-09/Doosan-DBC-series-brochure-archived.pdf), PDF pp.13, 22-25. The spindle and configuration values here intentionally come from this archive, not the current web page.

## 3. ACER Dynamic 1760G

**Example:** five replacement pins, diameter 40 mm x length 250 mm; material unspecified.

1. **Required operation:** manual turning is the documented machine role. Facing and pin turning are candidate operations with appropriate tools; finished accuracy is not established by the brochure.
2. **Part fit and weight:** nominal finished-size screen passes the printed 245 mm cross-slide swing and 1,500 mm between-centers dimensions. Workpiece mass and an allowable supported/cantilevered weight are not established.
3. **Required equipment:** selected chuck/adapter or between-centers holding, cutting tools, gauging, and support as required. Three-/four-jaw chucks, live centers, steady/follow rests and taper attachment are listed options, not automatically installed.
4. **Limits as printed:** bed swing 430 mm; spindle bore 58 mm; 50-1,800 rpm in 12 steps; 7.5 hp; maximum tool section 25 x 25 mm; longitudinal feed 0.05-0.70 mm/rev; cross feed 0.025-0.35 mm/rev. Metric threading: 22 pitches spanning 0.5-7 mm, not every arbitrary pitch in that interval.
5. **Still needed:** material/hardness, stock dimensions/mass, drawing/tolerances, holding and support ratings, installed spindle-nose configuration, cutting tools and parameters. Numerical part-weight capacity is absent from the brochure.

**Evidence:** [ACER Dynamic/e-Lathe brochure](../output/pdf/equipment-documents-2026-09-09/ACER-Dynamic-and-eLathe-series-brochure.pdf), PDF pp.2-3, visually checked. Page 2 supplies row labels continued by the model columns on page 3; use the 1740G/1760G/1780G group, not e-Lathe specifications. Metric values above follow the printed table.

## 4. Nordson EFD E6

**Example:** continuous sealant bead around a 200 x 150 mm cover; thickness and mass unspecified.

1. **Required operation:** programmed dispensing paths are supported, including lines, circles, fills and repeated dots. A rectangular perimeter is a candidate line-path application; bead quality requires a compatible dispensing process.
2. **Part fit and weight:** the planar path fits within 620 x 500 mm travel. Available Z travel is 150 mm, not unconditional part-height clearance. Cover/fixture height and masses are missing. The E6 data sheet specifies 10 kg workpiece payload and 5 kg tool payload; assess the complete loads on the respective moving axes.
3. **Required equipment:** syringe barrel or dispensing valve/holder, compatible controller and fluid supply, tip/nozzle, secure workpiece fixture, teach pendant, and applicable safeguarding. The manual explicitly refers dispensing-system installation to the separate equipment manuals.
4. **Limits:** maximum travel speed XY/Z 800/320 mm/s. Do not use that as validated bead speed. The manual's Circle command separately permits 0.1-400 mm/s and 0.01-400 mm diameter; apply the limits of the command actually used. Configured axis limits and tool/fixture clearance also govern.
5. **Still needed:** cover height/mass, fixture and dispensing-head loads/offsets, sealant type/viscosity, bead width/height, adhesion/cure requirements, nozzle/valve/controller specifications, and a verified dispensing recipe. The robot manual does not establish fluid flow rate or deposited-volume accuracy.

**Evidence:** [E6-inclusive 2019 data sheet](../output/pdf/equipment-documents-2026-09-09/Nordson-EFD-E-series-data-sheet-2019.pdf), PDF p.2. [E-series operating manual](../output/pdf/equipment-documents-2026-09-09/Nordson-EFD-E-series-operating-manual.pdf), PDF pp.18-19, 29, 32, 36, 63-72, 103. The manual's current E2/E3/E5 specification table is not substituted for legacy E6 ratings.

## 5. ABB IRB 6650

**Example:** transfer a 40 kg casting using a 15 kg gripper, staging to CNC.

1. **Required operation:** material handling/machine tending is supported as an application, with a complete gripper/control installation.
2. **Part fit and weight:** stated masses total 55 kg before any omitted flange accessories. This is below both nominal variants, 125 kg/3.2 m and 200 kg/2.75 m, but does not pass the load diagram. Part dimensions, pose and reachability are unknown.
3. **Required equipment:** rated gripper and flange mounting, load data, controller, CNC interface, fixtures, and integrated guarding/interlocks.
4. **Limits:** use the variant's load diagram and working range. For the documented full-axis-5-motion case, both variants require:
   - `J5 = m*((Z+0.200)^2 + L^2) + J0L <= 250 kg*m^2`
   - `J6 = m*L^2 + J0Z <= 185 kg*m^2`
   Here mass is kg, distances metres, and J0 terms are load inertias. These checks do not replace the load diagram or path validation.
5. **Still needed:** variant, full attached mass, combined center of gravity/inertia, casting/gripper geometry, base and destination poses, entry clearance, CNC handshakes and validated motion.

**Evidence:** [ABB specification revision 1](../output/pdf/equipment-documents-2026-09-09/ABB-IRB-6600-6650-product-specification-rev1.pdf), PDF pp.7-8, 31-49, 57-64. Inertia equations were visually checked on PDF p.46. Different restricted-wrist conditions must not be silently substituted.

## 6. MMLE-50D

**Example:** support a 300 kg assembly at a platform height of 900 mm.

1. **Required operation:** lifting and positioning for assembly is documented. This is not a machining, personnel-lifting or autonomous-travel capability.
2. **Part fit and weight:** the load is below 1,100 lb (approximately 499 kg), before accounting for other supported loads. A 900 mm platform height lies inside 19.5-63.5 inches (495.3-1,612.9 mm). Part footprint and stability are unknown; platform size is 20.5 x 39.75 inches.
3. **Required equipment:** the complete battery/charger lift, functioning brake, and a stable load/support arrangement. Brake the unit when stationary. Any added fixture consumes load capacity and needs separate assessment.
4. **Limits:** the service manual requires stable, uniform loading on firm level ground, dry use, and lowered-platform travel. It prohibits overloading and warns against prolonged continuous operation; no numerical continuous-duty rating was found. It refers to a designated load-center rating without supplying a usable numeric value in this copy.
5. **Still needed:** assembly footprint/center of gravity, any fixture mass, loading/unloading method, operating surface and required duty. If 900 mm means the work surface on top of the assembly rather than platform height, the assembly height is also needed.

**Evidence:** [Maxx-Mobile brochure](../output/pdf/equipment-documents-2026-09-09/Lift-Products-Maxx-Mobile-brochure.pdf), PDF p.2; [MMLE-50D service manual](../output/pdf/equipment-documents-2026-09-09/Lift-Products-MMLE-50D-service-manual.pdf), PDF pp.3-7. Unit conversions above are arithmetic, not additional precision in the physical equipment.

## Source Hazards and Import Requirements

The following are constraints on any future ingestion, not alterations to the original PDFs. Source links above identify the immutable local documents; their SHA-256 values remain in the document folder's `verification.json`.

| ID | Source evidence | Required treatment |
| --- | --- | --- |
| DBC-UNIT-01 | Doosan PDF p.25, DBC 130 II, 1,600 x 1,800 mm table-load row: `15000 (3306.9)` under kg (lb). | Preserve both printed values. For this reviewed field use 15,000 kg; calculated conversion is approximately 33,069.3 lb using 1 lb = 0.45359237 kg. Mark the printed pound value invalid, not an alternative capacity. Apply no family-wide correction by inference. |
| DBC-CONFIG-01 | Doosan PDF pp.23, 25: table size, APC configuration, splash guard and model determine different limits. | Select an explicit configuration. Do not carry standard-table capacity onto an optional table/APC, or use the unguarded swing for a guarded setup. |
| EFD-EDITION-01 | Nordson data sheet p.2 versus manual p.12: E2 workpiece 5 versus 10 kg; E5 tool 5 versus 5.5 kg. The latter manual also pairs 5.5 kg with 7.7 lb, which is inconsistent. | Keep edition-specific records unresolved for E2/E5. Neither current-model column supplies E6 values. The E6 record remains scoped to its own 2019 data-sheet column. Do not select a value merely because its document is newer. |
| MMLE-MODEL-01 | Lift Products brochure p.6 gives 330 lb at a 9-inch load center for MXE-150, not MMLE-50D. | Reject that attribution to MMLE-50D. Its numeric load-center condition remains unavailable; a sibling's rating does not establish it. |
| MMLE-SUPPORT-01 | MMLE service manual pp.3-7 mixes fork, table and platform terminology; the brochure p.2 gives a platform size. | Preserve the terminology mismatch. Do not infer fork spacing, support geometry or a platform load distribution from generic fork instructions. Confirm the actual support arrangement separately. |
| ACER-UNITS-01 | ACER brochure p.3, middle 1760G floor-dimension values: 105 x 40 inches versus 265 x 110 cm. Exact conversion of the former is 266.7 x 101.6 cm. | Record conflicting unit pairs. In particular the width discrepancy is not simple rounding. Do not promote the review's suggested 265 x 110 cm footprint as an unqualified fit constraint; this is not part of the existing pin-size check. |
| EFD-RANGE-01 | Nordson data sheet p.2: memory `1-99 programs / 1-9,999 points per program`. | Preserve range structure: maximum 99 programs and 9,999 points per program, not 199 and 19,999. Model-wide applicability must remain explicit. |

### Required Import Acceptance Cases

These cases must pass before the reviewed knowledge becomes executable constraints. They are not claims of tests already implemented or run.

1. DBC-UNIT-01 produces 15,000 kg and retains the defective raw pound field plus reviewed precedence; it never activates a roughly 1,500 kg capacity derived from that typo.
2. DBC 130 II table configurations resolve to 15,000 / 13,000 / 12,000 kg as applicable. APC and splash-guard cases resolve separately, without borrowing DBC 130L II options.
3. E6 stays at its own documented 10 kg workpiece / 5 kg tool payloads; sibling E2/E5 disagreements do not mutate it.
4. MXE-150's load-center rating cannot be assigned to MMLE-50D. Missing MMLE load-center data remains missing.
5. Haas ST-25/ST-35 values and ACER 1740G/1780G lengths cannot migrate into ST-30 and 1760G records. Model-column ambiguity blocks activation.
6. Inconsistent unit pairs remain inactive unless a field-specific resolution is recorded; raw evidence is retained. ACER floor dimensions exercise this case.
7. Nordson memory ranges parse with their separators and correct upper bounds. Optional, continuous, short-time and nominal ratings retain their distinct meanings.

The independent review supported 29 answers and classified the original Doosan Q4 as partial. Q4 has now been amended; no independent re-review of this revision or executable ingestion validation is claimed.

## What Has Actually Been Answered

For all six examples, the operation is a documented candidate application. The specified dimensions or nominal loads pass the limited comparisons stated above. None of those comparisons proves all five questions have an unconditional "yes" answer.

The manuals provide reusable equipment rules. A job supplies the part, material, tool, fixture, load distribution, and target requirements to which those rules are applied. Missing job data should be requested once and retained; it should not cause Sage to ask again for limits already present in the documents.

This audit can support later capability modeling, but no profile, process binding, machine program, or live feasibility evaluator was created by this review.
