# Section Recipes

Each recipe is a constrained generation contract. Sage may draft only the listed content types from evidence whose status satisfies the recipe. A section with unresolved required evidence is rendered as a review finding, not completed prose.

## Common Fields

Every planned section contains:

```text
sectionId
sectionType
title
audienceRoles[]
requiredClaimIds[]
optionalClaimIds[]
blocks[]
figureRequests[]
unresolvedFindings[]
approvalRequirements[]
status
```

## 1. Cover

**Purpose:** Identify the product and controlled document.

Required evidence:

- product display name and model;
- document title/number;
- document revision and release state;
- configuration/effectivity statement;
- approved logo/theme;
- assembled product figure.

Allowed blocks: title, subtitle, product figure, document metadata, release banner.

Forbidden inference: OEM revision, serial range, certification marks, customer identity, or release date.

Gate: all displayed metadata has an authoritative source; an unapproved document is marked `DRAFT` and identifies its approval status in document control.

## 2. Document Control and Revision History

**Purpose:** Establish ownership, effectivity, approvals, and changes.

Required evidence:

- source, plan, scene, and compiled revisions;
- named approval roles;
- configuration/effectivity status;
- revision history entries.

Allowed blocks: metadata table, revision table, approval table, distribution/status note.

Forbidden inference: approval from chat context or unsigned user intent.

Gate: release cannot exceed the least-complete required approval.

## 3. Table of Contents

**Purpose:** Provide deterministic navigation.

Evidence: compiled page/heading tree only.

Allowed blocks: section headings, figure/table lists, page references, bookmarks.

Forbidden inference: page numbers generated before pagination.

Gate: every entry resolves to an existing destination and all required sections appear.

## 4. About This Manual and Conventions

**Purpose:** Define audience, scope, terminology, safety-message interpretation, and document use.

Required evidence:

- approved audience roles;
- approved safety communication standard;
- release state and configuration scope.

Allowed blocks: role table, conventions, units, cross-reference rules, support/update statement.

Forbidden inference: generic legal disclaimers presented as engineering controls.

Gate: safety signal-word definitions match the licensed approved standard.

## 5. Safety

**Purpose:** Communicate residual hazards and required avoidance behavior before operation.

Required evidence:

- approved risk/hazard register;
- machine safety features and limits;
- applicable standard/regulatory records;
- approved safety symbol assets.

Candidate MMLE topics for review:

- no riders;
- crush/shear/pinch hazards around platform and scissor mechanisms;
- unsupported raised-platform access;
- rolling/caster foot hazards;
- unstable, unbalanced, or overloaded loads;
- slopes and unsuitable surfaces;
- stored hydraulic/electrical energy;
- charging/fire/electrical hazards;
- qualified-service boundaries.

Allowed blocks: structured safety panels, hazard-zone figures, prohibited-use table, PPE only where approved.

Forbidden inference: severity, PPE, safe distance, lockout steps, or emergency response without evidence.

Gate: each panel has hazard, consequence, avoidance, source, and approval; no unresolved severity.

## 6. Product Description and Intended Use

**Purpose:** Explain what the machine is and the applications/configuration for which it is intended.

Required evidence:

- current product description;
- configuration and rated limits;
- approved intended/prohibited uses.

Allowed blocks: overview prose, neutral shaded figure, feature list, intended-use and prohibited-use lists.

Forbidden inference: expanded applications based only on geometric plausibility.

Gate: examples from commercial material are labeled examples unless engineering approves them as the complete intended-use definition.

## 7. Specifications

**Purpose:** Present controlled values needed to select and operate the product.

Required evidence:

- rated capacity;
- travel, lowered/raised height, platform size;
- weight type and value;
- power/charger data;
- environmental and floor requirements if available.

Allowed blocks: specification table and dimension figure.

Forbidden inference: load center, duty cycle, slope, noise, IP rating, temperature range, hydraulic pressure, or operating weight from CAD.

Gate: every value has unit, value type, source, and effectivity. Missing required values block release or are visibly `Not specified` in review.

## 8. Controls, Indicators, and Safety Features

**Purpose:** Identify controls and explain their approved behavior.

Required evidence:

- control identity and location;
- approved state/action/result mapping;
- indicator interpretation;
- safety-feature identity and approved use.

Candidate figures: handle controls, BDI/battery switch, charger connection, brake levers, maintenance isolator, emergency relief feature.

Forbidden inference: button colors/functions, BDI thresholds, switch positions, emergency-lowering sequence, or isolator use based only on part names.

Gate: location-only figures may be drafted from CAD; behavioral text requires current approved operating data.

## 9. Receiving, Setup, and Pre-Use Inspection

**Purpose:** Establish readiness before first and daily use.

Required evidence:

- shipping/receiving requirements;
- approved setup steps;
- pre-use inspection checklist and reject criteria;
- responsible role.

Legacy candidate checks: damage, wheels, cylinder leakage, vertical creep, brakes, and fasteners.

Allowed blocks: checklist, inspection map, defect escalation, record field.

Forbidden inference: unpacking equipment, fastener torque, commissioning tests, battery activation, or pass/fail tolerances.

Gate: each check has a method, acceptable condition, reject action, and role.

## 10. Operating Procedures

**Purpose:** Describe normal raise, lower, load, unload, and stop behavior.

Required evidence:

- prerequisites and load limits;
- control actions and expected results;
- load placement/securement rules;
- stop/abnormal behavior;
- approved sequence.

Allowed blocks: numbered procedures, contextual safety panels, CAD step figures, verification statements.

Forbidden inference: safe load center, cycle limits, rapid lowering, bypass/recovery actions, or control behavior not in approved current data.

Gate: each procedure passes role, prerequisite, action, expected-result, and hazard coverage validation.

## 11. Moving and Parking

**Purpose:** Define when and how the mobile unit can be moved or secured.

Required evidence:

- permitted platform/load state during movement;
- approved floor/slope conditions;
- steering/push points;
- brake count and use;
- unattended state.

Allowed blocks: movement-state figure, brake procedure, path checklist.

Forbidden inference: tow/push force, grade limit, speed, or permission to move a raised/loaded unit.

Gate: resolve the legacy right-brake/current dual-brake conflict before publication.

## 12. Charging

**Purpose:** Explain the approved onboard-charger procedure and charging safety.

Required evidence:

- battery chemistry/type and rating;
- charger input and connection point;
- approved switch/platform/brake state;
- indicator meanings;
- environment/ventilation and prohibited conditions;
- completion/disconnection sequence.

Allowed blocks: charging procedure, control/connector figure, warning panel.

Forbidden inference: electrolyte service, battery removal, external charger, charge current, timing, or indicator thresholds.

Gate: `CONFLICT-001` resolved by current configuration-specific instructions. Until then this section remains blocked.

## 13. Cleaning and Storage

**Purpose:** Preserve the machine without introducing damage or hazards.

Required evidence:

- approved cleaning agents/methods;
- electrical/water restrictions;
- storage environment and machine state;
- battery storage/charging requirements.

Legacy evidence says dry environment, but current ranges and cleaning methods are missing.

Forbidden inference: pressure washing, solvents, corrosion treatment, storage temperature, or long-term battery interval.

Gate: approved current instructions required for release.

## 14. Inspection and Maintenance

**Purpose:** Present scheduled tasks with clear role and energy state.

Required evidence:

- current approved maintenance schedule;
- task methods, tools, consumables, quantities, torque/tolerance, acceptance criteria;
- isolation/support state;
- record requirements.

Allowed blocks: schedule table, maintenance-point figures, qualified-service procedures, records.

Forbidden inference: legacy interval adoption, generic grease/oil, pressure adjustment, structural repair, chain lubrication on a configuration without verified chains.

Gate: all release tasks have complete method and product authority. Legacy candidates remain findings, not instructions.

## 15. Troubleshooting

**Purpose:** Help users recognize faults and take role-appropriate actions.

Required evidence:

- approved symptom/cause/action matrix;
- role boundary and stop-use criteria;
- current schematics where referenced.

Allowed operator actions: visual checks, control-state checks, approved charging, and escalation only when explicitly supported.

Forbidden inference: relief-valve adjustment, hydraulic opening, electrical rewiring, seal replacement, or pressure change by an operator.

Gate: every row classifies action role and leaves no safety-critical continuation path after a stop-use condition.

## 16. Service, Replacement Parts, and Technical Support

**Purpose:** Direct qualified users to approved service resources.

Required evidence:

- manufacturer/customer service contact;
- approved service-parts identifiers;
- warranty/service policy if included;
- configuration/revision data to provide with a service request.

Allowed blocks: contact card, service information checklist, parts-reference cross-links.

Forbidden inference: OEM part numbers from CAD filenames or InspectorPro library IDs.

Gate: no fake contact data or part-number mapping.

## 17. Inspection and Maintenance Records

**Purpose:** Provide structured records without claiming to replace customer systems.

Required evidence: approved inspection/maintenance task IDs and retention policy.

Allowed blocks: date, machine ID, hour meter if available, task/result, defect/action, technician, signature.

Forbidden inference: regulatory retention duration.

Gate: fields correspond to actual approved tasks and are accessible in PDF/DOCX.

## 18. Sources, Standards, and Document History

**Purpose:** Make evidence and authority transparent.

Required evidence: source register, applicable-standard register, approvals, and artifact manifest.

Allowed blocks: source list, standards list with applicability status, revision history, generated-with note.

Forbidden inference: compliance claims based on bibliography alone.

Gate: source links, editions, dates, and statuses match the registered records.

## 19. Parts-Reference Appendix

**Purpose:** Link operations/service figures to the approved Illustrated Parts Manual.

Required evidence: published parts-manual revision and stable semantic group/component identities.

Allowed blocks: major assembly index, selected service figure references, approved OEM part numbers where available.

Forbidden inference: reproducing internal library IDs as manufacturer part numbers.

Gate: cross-document revision compatibility and live destinations pass validation.
