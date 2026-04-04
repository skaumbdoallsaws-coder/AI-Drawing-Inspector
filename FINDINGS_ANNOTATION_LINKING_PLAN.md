# Findings Mode: Backend Annotation Linking

**Status: Plan — from Codex, implementation-ready**
**Date: 2026-04-04**

## Summary

Fix backend `apply_drawing_map_to_findings()` to reliably populate `feature.location` using deterministic drawing-map matching with profile context. Then simplify frontend to trust backend locations.

## Key Files

- `ai_inspector/utils/drawing_map.py` — enrichment + matcher
- `server.py:478` — where enrichment is called
- `static/index.html:8017` — frontend Findings mode

## Full Plan

See the Codex plan pasted by user — covers:
- Phase 1: Backend profile-aware matching (Steps 1-5)
- Phase 2: Frontend simplification (Steps 6-7)
- Phase 3: Observability (Steps 8-9)

## Acceptance Criteria for 1030017

- Central Through Bore → Section View C-C / RD1
- Cylindrical Boss → Section View C-C / RD2
- Bore End Chamfer → Drawing View2 / DetailItem665
- Square Mounting Plate → Drawing View2 / RD1 (254.00)
- ⌀22.23mm Mounting Holes → Drawing View1 / RD1
