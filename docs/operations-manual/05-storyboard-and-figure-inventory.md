# Prototype Storyboard and CAD Figure Inventory

## 1. Storyboard Assumptions

- Target: a 24-30 page draft, depending on table flow and blocked sections.
- Format: 16:9 landscape using a 960 x 540 pt logical page.
- The Documentation Workspace opens as a blank authoring canvas and empty page rail for a new operations-manual run.
- Sage creates pages sequentially. A page enters the rail only when its shell exists; its preview updates as blocks settle.
- Prose may stream by phrase into a paragraph for the live experience, but the persisted block is committed atomically only after evidence and structure validation.
- Tables reveal in bounded row batches. CAD figures pause at a visible `Capturing technical figure` stage and settle only after the real capture is accepted.
- Capture and export always force settled rendering. Animation and activity glow never enter artifacts.

## 2. Proposed Page Sequence

Page numbers are provisional until deterministic pagination.

| Approx. page | Section/page | Primary content | Evidence state |
| ---: | --- | --- | --- |
| 1 | Cover | Title, draft banner, assembled product figure, document identity | Ready for prototype |
| 2 | Document control | Configuration, effectivity, revision history, approval status | Ready with release blockers shown |
| 3 | Table of contents | Generated links and page numbers | Compiler-derived |
| 4 | About this manual | Audiences, conventions, units, update/source policy | Ready for prototype |
| 5 | Safety conventions | Structured signal-word legend and symbol explanation | Blocked for release pending licensed Z535.6 review |
| 6 | General safety | Approved residual hazards and prohibited actions | Draft with engineering/safety review |
| 7 | Hazard-location map | Overall lift with scissor, under-platform, caster, electrical, and load zones | CAD-ready; hazard semantics require approval |
| 8 | Product overview | Intended applications, system overview, major features | Ready for prototype |
| 9 | Intended/prohibited use | Approved use cases, limitations, role boundaries | Draft with engineering review |
| 10 | Specifications | Rated capacity, travel, heights, platform, shipping weight, electrical baseline | Ready for prototype; effectivity required |
| 11 | Controls and indicators | Control-location overview and legend | CAD-ready; behavior partly blocked |
| 12 | Safety features | Brake mechanisms and trapped rollers; advertised safety bars, isolator, and relief valve tracked as unmapped | Brake/trapped-roller draft only; unmapped features blocked by `CONFLICT-008` |
| 13 | Pre-use inspection | Checklist plus inspection map | Legacy candidate; approval required |
| 14 | Loading and preparation | Stable-load prerequisites and load-placement figure | Blocked until load distribution/center is approved |
| 15 | Raise and lower | Numbered control sequence with before/after CAD views | Control sequence needs current approval |
| 16 | Move and park | Platform state, path, steering, brake procedure | Brake conflict must be resolved |
| 17 | Charging | Onboard charger overview and approved sequence | Blocked by current configuration instruction gap |
| 18 | Cleaning and storage | Approved cleaning and storage conditions | Blocked by missing current instructions |
| 19 | Inspection schedule | Daily/periodic task matrix by role | Legacy candidates; blocked for release |
| 20 | Safe maintenance state | Unloaded/lowered or supported state, energy sources, isolator | Blocked pending exact support/isolation procedure |
| 21 | Lift mechanism and cylinder | HLR service-orientation figures; qualified personnel only | CAD-ready; service text controlled |
| 22 | Hydraulic power pack | Component-identification figure and escalation boundary | CAD-ready; settings/service details blocked |
| 23 | Battery and control assembly | HLR component-identification figure | CAD-ready; chemistry/service details blocked |
| 24 | Troubleshooting | Symptom, operator check, stop-use, qualified-service action | Legacy candidate; current approval required |
| 25 | Service and parts | Contact checklist and link to controlled parts manual | Contact/OEM PN data missing |
| 26 | Inspection/maintenance record | Writable record table | Template-ready |
| 27 | Sources and standards | Evidence sources, applicability state, document history | Registry-derived |
| 28 | Parts-reference appendix | Major assembly index and parts-manual cross-references | Requires compatible published parts manual |

Blocked pages may be shown in the prototype as visibly incomplete review pages, but they must not read as executable instructions.

## 3. Figure Inventory

### `OM-FIG-001`: Assembled Product Hero

- Purpose: product identification and orientation.
- View: neutral-gray shaded isometric; no explosion.
- CAD scope: complete assembly.
- Pages: cover and product overview.
- Status: ready from CAD.

### `OM-FIG-002`: Major Systems Overview

- Purpose: identify platform, lift mechanism, hydraulic system, caster assemblies, battery/control system, and frame.
- View: neutral-gray isometric with restrained numbered group callouts.
- CAD scope: all ten curated MMLE manual groups.
- Status: ready from CAD and registry groups.

### `OM-FIG-003`: Residual-Hazard Location Map

- Purpose: identify approved crush/shear, under-platform, rolling/caster, load, and electrical hazard regions.
- View: neutral-gray assembly with transparent, semantically separate hazard overlays.
- CAD scope: complete assembly plus overlay targets.
- Status: geometry ready; hazard IDs/severity/avoidance blocked pending risk approval.

### `OM-FIG-004`: Published Dimensions

- Purpose: present OEM published lowered/raised height and platform dimensions.
- View: front/side orthographic line art with dimension labels from approved OEM claims.
- CAD scope: complete assembly.
- Status: review. Labels use OEM values; do not derive catalog dimensions from CAD extents.

### `OM-FIG-005`: Controls and Indicators

- Purpose: locate handle controls, BDI, battery switch, charger/plug, and other approved controls.
- View: assembled context plus detailed insets.
- CAD targets: `SW HANDLE`, `BDI`, `BATTERY SWITCH`, `CHARGER`, `CHGR PLUG`, handle.
- Status: location figure ready; functions/labels require current control evidence.

### `OM-FIG-006`: Parking-Brake Mechanisms

- Purpose: show both rear swivel-caster brake levers and identify engaged/released states when approved.
- View: isolated left/right swivel-caster assemblies, HLR.
- CAD groups: `Right Swivel Caster and Brake Assembly`, `Left Swivel Caster and Brake Assembly`.
- Status: geometry ready; state/action labels blocked by `CONFLICT-002`.

### `OM-FIG-007`: Pre-Use Inspection Map

- Purpose: map each checklist item to visible inspection areas.
- View: assembled neutral-gray figure with dots/numbered labels, not motion arrows.
- Targets: frame/platform damage, wheels/casters, cylinder/leak region, brakes, fasteners, controls.
- Status: CAD ready; checklist and acceptance criteria need approval.

### `OM-FIG-008`: Load Placement and Stability

- Purpose: show an approved load region, prohibited edge/tip loading, and center-of-gravity relationship.
- View: simplified technical diagram based on product geometry, not a decorative render.
- CAD scope: platform assembly.
- Status: blocked until load center/distribution and representative load rules are approved.

### `OM-FIG-009`: Raise/Lower Sequence

- Purpose: show lowered, intermediate, and raised states tied to procedure steps.
- View: three synchronized side/isometric captures; arrows are action annotations.
- CAD scope: platform, lift mechanism, cylinder, frame.
- Status: geometry/camera plan ready; exact control sequence and support state need approval.

### `OM-FIG-010`: Move-Lowered State

- Purpose: distinguish transport state from lifting state.
- View: assembly lowered with permitted push direction and brake/path annotations.
- CAD scope: complete assembly.
- Status: draft; movement conditions and brake sequence need approval.

### `OM-FIG-011`: Charging Connection

- Purpose: locate charger input, switch/indicator, and cable-routing region.
- View: battery/control assembly context and connector detail.
- CAD group: `Battery and Control Assembly`.
- Status: geometry ready; procedure blocked by `CONFLICT-001`.

### `OM-FIG-012`: Safe Maintenance Support State

- Purpose: show the exact approved maintenance-safety-bar/isolator support engagement and exclusion zone.
- View: side technical illustration with sequence/detail inset.
- CAD scope: unresolved. Platform/lift mechanism context alone is not a valid target for the advertised safety features.
- Required feature claims: `CLM-SAFETY-FEATURE-001`, `CLM-SAFETY-FEATURE-004`.
- Status: blocked by `CONFLICT-008`. The product page names maintenance safety bars and an isolator, but no exact CAD occurrences or approved engagement procedure are mapped. The renderer must not substitute nearby structure.

### `OM-FIG-013`: Lift Mechanism Service Orientation

- Purpose: identify the scissor structures, shafts, pivots, rollers, supports, and platform relationship.
- View: HLR exploded/isometric.
- CAD group: `Lift Mechanism Assembly` plus platform/frame context.
- Status: ready for component identification; no service method implied.

### `OM-FIG-014`: Hydraulic Cylinder Assembly

- Purpose: identify cylinder, ram, barrel, bushings, mounts, spacers, and thrust components.
- View: HLR isolated/exploded.
- CAD group: `Hydraulic Cylinder Assembly`.
- Status: ready for qualified-service reference; adjustments/repair instructions blocked.

### `OM-FIG-015`: Hydraulic Power Pack Assembly

- Purpose: identify pump, motor, coil/valve, tank, and mounting context.
- View: HLR isolated/exploded.
- CAD group: `Hydraulic Power Pack Assembly`.
- Status: ready for identification; pressure/fluid/electrical service data blocked.

### `OM-FIG-016`: Battery and Control Assembly

- Purpose: identify battery box, BDI, switch, charger, plug, covers, and handle components.
- View: HLR isolated/exploded.
- CAD group: `Battery and Control Assembly`.
- Status: ready for identification; battery chemistry and service instructions blocked.

### `OM-FIG-017`: Caster and Frame Service Index

- Purpose: cross-reference brake, rigid-caster, caster-support, and base-frame sections in the parts manual.
- View: group-level HLR composition.
- CAD groups: right/left swivel caster, rigid caster, caster support structure, base frame/covers.
- Status: ready from approved parts-manual groups.

### `OM-FIG-018`: Hydraulic and Electrical Schematics

- Purpose: support qualified troubleshooting and service.
- Source: approved current 2D engineering diagrams, not inferred from 3D geometry.
- Status: blocked; the available diagrams are legacy and configuration applicability is unknown.

## 4. Existing CAD Group Coverage

The registry already supplies these reusable semantic groups:

1. Lift Platform Assembly
2. Lift Mechanism Assembly
3. Hydraulic Cylinder Assembly
4. Hydraulic Power Pack Assembly
5. Right Swivel Caster and Brake Assembly
6. Left Swivel Caster and Brake Assembly
7. Rigid Caster Assembly
8. Caster Support Structure
9. Battery and Control Assembly
10. Base Frame and Covers Assembly

These are valid figure scopes and parts-reference anchors. They are not by themselves operating-procedure steps.

## 5. Figure Request Contract

Each CAD figure request should include:

```json
{
  "figureId": "OM-FIG-015",
  "purpose": "component_identification",
  "sourceRevision": "...",
  "scope": {
    "manualGroupIds": ["..."],
    "occurrenceIds": []
  },
  "visibility": "isolate_scope",
  "displayStyle": "hidden_lines_removed",
  "viewCandidates": ["isometric", "front", "right"],
  "explosion": {
    "mode": "semantic_group",
    "spacing": "auto"
  },
  "annotationPolicy": "identification_dots",
  "requiredCallouts": [],
  "overlays": [],
  "capture": {
    "minWidth": 2400,
    "minHeight": 1800,
    "background": "white"
  },
  "altTextEvidence": ["..."],
  "approvalState": "draft",
  "status": "ready"
}
```

## 6. Live Generation Storyboard

For each page:

1. **Shell:** page master, header/footer, page title placeholder.
2. **Plan:** Sage status names the section and evidence coverage; no prose yet.
3. **Text:** approved claims are composed into semantic blocks and streamed visibly.
4. **Figure request:** page pauses and the blue Sage activity perimeter appears around the live CAD viewport.
5. **CAD action:** components are isolated, view/explosion applied, HLR or neutral style rendered.
6. **Capture:** accepted artifact is stored; the figure appears on the page and thumbnail.
7. **Tables/checklists:** rows appear in bounded batches from deterministic data.
8. **Safety/annotations:** structured panels and callouts render after their evidence validates.
9. **Settle:** page status becomes `ready`, `needs review`, or `blocked`; the next page is inserted below/after it.

The page rail must show actual page previews, not blank generic thumbnails. Revisiting a completed page never replays generation unless the user explicitly requests regeneration.

## 7. Demo-Safe Sequence

For a public prototype demonstration, use only pages whose content can be accurately supported now:

1. Cover
2. Product overview
3. Specifications
4. Major systems/controls location
5. Pre-use inspection draft with visible `review` badge
6. Lift mechanism technical figure
7. Hydraulic power pack technical figure
8. Source summary

Do not demonstrate charging, safety-bar/maintenance-isolator engagement, emergency-relief operation, hydraulic adjustment, or a final `published/approved` state until their evidence and CAD-mapping blockers are resolved.
