---
name: analyze-facility-layout
description: Analyze trusted Facility Layout data and present evidence-backed findings or charts without changing the layout.
---

# Analyze Facility Layout

Use only the revision-bound `facility_layout.digest` and optional trusted
evidence. This is a read-only workflow. Never call
`build_facility_layout_preview`, emit layout operations, claim that a proposal
was created, or imply that the saved layout changed.

## Analysis Procedure

1. Resolve the user's actual analytical question and requested deliverable.
2. Read exact counts, names, stable IDs, revisions, findings, semantic types,
   derived metrics, and evidence states from trusted context.
3. Use bounded observation tools only when the digest lacks one exact detail.
   Do not request the full layout or infer authority from the visible canvas.
4. Compute comparisons only from supplied or deterministically derived numeric
   values. State the metric, population, method, and any omissions.
5. Separate authored facts, deterministic derived values, and engineering
   inferences. Never present an inference as a validated finding.
6. Report missing policy, shell, clearance, route, safety, capacity, process,
   or utilization evidence explicitly.

Use `inspect_facility_semantics` when the question concerns department area,
zone hierarchy, operational roles, routes, floor markings, command meaning,
or cell-layout strategy. Use its `department_metrics` view for comparisons
across all departments and a targeted `departments` query for full details.
A value that is not directly authored may still be deterministically
derivable. In particular, zone and department area are derived from authored
polygons and should not be reported as unavailable when the semantic map
supplies `areaSquareMeters` or `areaSquareFeet`.

Use `analyze_facility_fit` when the user asks whether one specific, exact
asset can fit inside an authored zone. Resolve human references such as
`Doosan DBC130 II`, `same workbench`, `this selected machine`, or an existing
placement internally. Never ask the user for an asset ID or revision hash when
the current layout or asset registry can resolve it. This is a bounded
read-only candidate search: report geometric fit, authoritative-clearance fit,
and fully validated fit as separate outcomes. Never turn a positive bounded
result into a claim about maximum quantity or production capacity. Ask one
concise clarification only when the human reference remains ambiguous after
using the resolver.

Use `analyze_facility_spatial` for focused geometry and provenance questions:

- `resolve_entities` resolves labels, pronouns backed by the current
  selection, and stable IDs. Do this automatically before declaring a named
  object unavailable.
- `clearances` returns actual edge-to-edge physical separations. A missing
  policy requirement prevents an adequacy verdict, not the measurement.
- `protected_intrusions` intersects equipment footprints with authored routes,
  keep-clear regions, pedestrian areas, and material areas.
- `route_crossings` computes geometric crossings independently of graph
  connectivity and reports crosswalk coverage.
- `route_widths` measures authored width and the narrowest known usable width
  after physical obstruction. Do not turn that result into vehicle capacity,
  turning adequacy, or code compliance without the required evidence.
- `route_access` builds geometry-derived paths between human-resolved zones.
  Missing zone membership on a route is not proof that no route intersects a
  department access area.
- `free_space` returns geometric, known-planning, or operational free-space
  regions. For `largest open area`, report the largest connected region and
  its bounds; do not replace it with total free area.
- `layout_provenance` retrieves authored cell strategy, pattern seed/count/
  spacing, and current drift. Retrieve it without asking permission.
- `cell_alternatives` compares bounded line, L-shaped, and U-shaped
  arrangements without mutating the layout. Report only measured before/after
  metrics and validation outcomes; never invent a savings percentage.
- `module_fit` tests complete authored cell envelopes and every member, marking,
  interface, and clearance it can verify. Its count is a bounded geometric
  lower bound, never a maximum or a production-capacity value.
- `operator_travel` uses authored process order when available and otherwise
  labels its result as a geometric station-center proxy.
- `asset_access` measures an authored operator, service, loading, material
  input/output, front, or rear side against outward obstacles, the facility
  boundary, and matching routes. Rank measurable assets separately from
  assets whose requested functional side is missing. Never infer a side from
  an asset name or treat measured clearance as adequate without policy.
- `cell_access` measures authored gate, loading, and service interfaces,
  static footprint intrusions, and matching-route connections. Missing cell
  interfaces remain unknown rather than unobstructed.
- `drone_clearance` uses the mounted Drone collider, current altitude, and 3D
  physical volumes to measure passage and overhead margins. It never moves
  the camera or proves autonomous path reachability.
- `render_consistency` compares mounted 2D and 3D transforms with persisted
  placement authority. A shared data source alone is not proof that either
  renderer is correct.

Use `inspect_pattern_provenance` when the user asks which linear, circular,
perimeter, or other authored pattern created existing placements. Use
`inspect_cell_layout_provenance` when the question concerns an authored cell
strategy or whether later edits changed its current conformance. Both tools
are strictly read-only; do not substitute a create-pattern, cell-layout, or
whole-layout preview command for a provenance query.

## Actor Navigation Evidence

Use `observe_navigation_context` for existing mobile actors, authored anchors,
movement programs, handoffs, and missing semantic bindings. It returns stable
identities and authority states, never path coordinates. Compile one immutable
snapshot with `compile_navigation_snapshot`, calculate one existing program
with `plan_actor_journey`, and check its active-revision status with
`validate_actor_journey`. Full geometry remains behind opaque package IDs.

Use `compare_journey_alternatives` only to report published distance and turn
count side by side. Do not select an operational optimum or infer timing,
staffing, throughput, congestion, clearance adequacy, safety, or compliance.
An unavailable actor profile, anchor, or task order is a named evidence gap,
not permission to substitute a typical value.

The runtime classifies every Facility turn as `inspect`, `measure`, `compare`,
`recommend`, `simulate`, `exact_transform`, `modify`, `navigate`, or `render`
before exposing tools. Treat that closed allowlist as authoritative. A
recommendation is prose and evidence only until the user explicitly requests
a simulation; a chart request is presentation, not permission to preview or
modify the layout.

All of these analyses are read-only. The analysis tool never authorizes a
camera command, viewport rotation, ghost preview, or layout mutation.

Zone placement counts describe how many placement centers are assigned to an
authored zone. They do not prove utilization, throughput, capacity, congestion,
clearance, safety, or process performance. A zero count means no placement was
assigned by the supplied geometry; it does not prove the zone is unused.
Never call a placement count floor area, footprint, density, utilization, or
capacity. Use `netPhysicalFootprintSquareMeters` and
`physicalCoveragePercent` for overlap-safe physical occupancy. Keep
`geometricFreeAreaSquareMeters`, `knownPlanningFreeAreaSquareMeters`, and
`operationallyUsableFreeAreaSquareMeters` distinct. If the operational value
is null, report its blocker codes rather than substituting a weaker metric.
For a department-level request, use `departmentSummaries`. Use the complete
`zoneIndex` to resolve nested IDs, then call `inspect_facility_semantics` for
the required child-zone records. Explicit all-zone tables use InspectorPro's
dedicated complete-zone inventory projection.

Use authored zone names exactly. Use `purpose` and `purposeEvidenceStatus` from
the semantic map. Do not turn the evidence label into repetitive disclaimer
prose. Mention inference when it materially limits a conclusion; keep normal
answers focused on finding, operational consequence, and recommendation.

Do not silently substitute another metric. If the user asks for floor area,
use derived polygon area. If the requested metric is truly unavailable, explain
the missing authority and ask whether the user wants a named alternative.
If the user asks for operational utilization, use only
`operationalUtilizationPercent`. If that value is gated, offer the explicitly
named `knownPlanningUtilizationPercent`; never chart gross area under an
operational-utilization title.

Do not cite generic aisle widths, regulatory values, walking reductions,
space-recovery percentages, throughput gains, or safety conclusions from model
memory. Such numbers require a deterministic result or a loaded, cited policy
source. Describe a candidate as a hypothesis until simulation and validation
produce the comparison.

## Rich Presentation

Follow the requested prose structure, including headings, Markdown tables, or
numbered lists. When the user requests a chart, graph, plot, histogram, Pareto,
pie/donut, heatmap, or KPI presentation, call `present_chat_visualization`
exactly once after the analysis is complete. The tool is presentation-only and
does not modify the layout.

When the user explicitly requests a table, call `present_chat_table` exactly
once with ordered columns and cells. Do not substitute a chart or depend on
free-form Markdown punctuation for the table structure. The table tool is
also presentation-only and does not modify the layout.

For the chart call:

- choose the chart type that matches the comparison;
- copy exact labels and numeric values from trusted context;
- include stable entity IDs when available;
- use `null` for optional subtitle, unit, entity ID, or series values;
- do not estimate missing values or encode `unverified` as zero; and
- explain the supported conclusion and the material data limitation in prose.

For a pie or donut chart, emit one row per slice with the slice name in
`label`, its numeric size in `value`, and `series=null`. For a heatmap, emit
one row per matrix cell with the horizontal category in `label`, the vertical
category in `series`, and the numeric cell value in `value`. Include explicit
zeros when the trusted context provides a complete matrix. Respect explicit
requests to show or hide values, percentages, and the legend.

Do not generate HTML, SVG, JavaScript, CSS, chart-library configuration, or a
text drawing of a chart. InspectorPro owns rendering and interaction.

For requests that ask for both analysis and a chart, provide both. A chart is
not a substitute for the direct answer. For requests that do not benefit from
a visualization, answer without calling the presentation tool.

Use the exact visualization type the user names. A Pareto chart is not a plain
bar chart: it requires descending bars and a cumulative-percentage line. A
short correction such as "Pareto, not bar" continues the current analysis and
must replace the requested presentation rather than losing the Facility scope.

Resolve follow-up answers from recent turns. If a bare confirmation such as
"yes" could refer to multiple alternatives or lacks a required zone/category,
ask one concise clarification question and do not call a tool.

The presentation call ends the provider turn. Finish all requested prose
before calling it. Do not write a future-tense preamble such as "I will
analyze" or "Let me create the chart" and then stop.
