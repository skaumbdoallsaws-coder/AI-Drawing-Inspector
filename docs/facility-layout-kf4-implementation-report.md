# Facility Layout KF4 Implementation Report

Date: 2026-08-26

Status: Complete

## Scope

KF4 completes deterministic server-side feasibility analysis for the ten cell
strategies already available in the browser and adds the four K7 planning field
groups to every strategy contract. Existing strategy descriptions and the
browser geometry engine remain intact.

## Implemented

- The shared server strategy surface now covers line, L, U, grid, parallel,
  serpentine, loop, spine and branch, herringbone, and cluster layouts.
- The agent tool schema, runtime defaults, semantic registry, and browser
  strategy IDs use the same ordered ten-strategy vocabulary.
- The server sampler generates bounded candidate centers for every strategy.
  Final eligibility still comes from exact footprint, target containment,
  overlap, preferred gap, external obstacle, protected-space, and authored
  clearance checks.
- Feasible candidates are exposed separately in `rankedFeasibleRecords`.
  Rejected candidates remain available only as diagnostics with exact blocker
  codes and cannot become the selected recommendation.
- Output metrics now include required width and depth, physical and envelope
  area, minimum gap, contiguous free area, route evidence, operator-travel
  proxy, total movement, access status, clearance completeness, and expansion
  reserve. No throughput, ergonomic, or compliance claim is inferred.
- Explicitly locked or manual source placements block automatic rearrangement
  and remain unchanged.
- All ten strategy contracts report implemented server feasibility and include
  space model, interfaces, access assumptions, and result metrics.
- All eight named recipes are validated against the registered strategy and
  command IDs and cannot bypass the deterministic geometry engine.

## Shared Fixtures

`kf4-strategy-fixtures.json` freezes the ordered strategy IDs plus a feasible
large-zone case and an infeasible small-zone case. The Python analyzer and
browser pattern tests both consume this fixture.

## Verification

- KF4 strategy, semantic, and knowledge-contract tests: 48 passed.
- Agent runtime and integration compatibility tests: 126 passed.
- Browser pattern tests: 23 passed.

## Exit Gates

- Ten deterministic valid and invalid strategy fixtures: PASS.
- Candidate footprints do not overlap or leave the target zone: PASS.
- Authored clearances enforced; missing evidence visible: PASS.
- Locked and manual placements preserved: PASS.
- Server, agent schema, runtime, and browser strategy IDs agree: PASS.
- Recipes compile only to registered strategies and commands: PASS.
