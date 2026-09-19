# Process Map Router Dependency Spike

Status: NO-GO for ELK.js as the authoritative persisted-route engine

Date: 2026-07-21

## Decision

InspectorPro will use the checked-in deterministic Python/JavaScript router for
incremental process-map edge routing. ELK.js is not added to the production
backend or used to author persisted route geometry in Phase 4.

## Evidence

- The packaged application serves FastAPI/Python and has no managed JavaScript
  runtime in its production dependency graph.
- Running ELK.js server-side would require shelling out to an assumed Node.js
  installation or deploying and supervising another service.
- Either option creates an unbounded operational dependency and a browser/server
  algorithm-drift risk, which violates the approved backend execution gate.
- The existing spatial engine already has byte-parity-tested Python and
  JavaScript implementations, canonical world geometry, obstacle fingerprints,
  bounded map limits, and deterministic tie breaking.

## Selected Fallback

Phase 4 extends the existing spatial engine with a bounded orthogonal candidate
router. Both implementations use the same contract, route policy, candidate
ordering, obstacle fingerprint, and route identifier. Persisted geometry is
accepted only after the current map is recompiled and the candidate is
regenerated.

## Packaging and Licensing

No dependency or license is added. The router ships as repository-owned source
inside the existing Python package and browser runtime.

## Bounds, Failure, and Cancellation

- Input remains capped by the spatial contract at 250 nodes, 400 edges, 80
  groups, and 128 persisted route points.
- Candidate lanes are bounded before scoring; routing does not launch a worker,
  process, service, or network request.
- A map with no valid candidate returns
  `no_obstacle_free_orthogonal_route`; it never draws through a card as a
  fallback.
- Browser route previews are synchronous and revision/fingerprint checked again
  before acceptance. Closing the preview discards all transient state.

## Future ELK Use

ELK may be reconsidered only as an optional browser-only full-map arrangement
preview. It cannot write authoritative geometry unless a future spike proves a
supported backend runtime, deterministic parity, bounded execution,
cancellation, packaging, and license compliance.
