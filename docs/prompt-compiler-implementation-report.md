# Prompt Compiler Implementation Report

Status: implemented and live-validated for the Sage supplier FAI disposition workflow.

## Source Architecture

Prompt source now lives in versioned modules under `ai_inspector/prompts/`:

- Base modules define Sage identity, engineering honesty, and response style.
- Mode modules define assembly, report/FAI, drawing, and 3D-model behavior.
- Skill packages continue to define workflow-specific reasoning and tool access.
- `modules.json` records module IDs, versions, compatible agents and modes, and source paths.

The complete system prompt sent to the model remains a generated runtime artifact. It is assembled from selected modules and skills, hashed, and recorded in runtime metadata for debugging and evaluation.

## Context Compilation

The compiler derives required and optional context from the selected skill manifests. For FAI assembly-impact questions it keeps the failed characteristics, relevant feature data, matching assembly parts and mates, and requested motion context. Unrelated comparison, walkthrough, geometry-diff, and motion content is omitted.

Uploaded document content and the user's request are placed in explicit trust-boundary sections. Extracted document text is treated as evidence, not instructions.

## Tool Contract

The compiled path exposes provider-native tools only when selected skills permit them. Server validation, browser authorization gates, action-contract validation, and execution receipts remain authoritative. Legacy textual marker parsing remains available only for non-migrated and rollback paths.

## Measured Result

For the live piston FAI assembly-impact scenario:

- Compiled system prompt: approximately 8,871 characters, down from 35,314 characters. The increase from the first compiler checkpoint is the explicit executable-contract and composition-policy layer.
- Context reduction: approximately 56.7 percent from the unfiltered request context.
- Prompt modules: four explicitly versioned modules.
- Read-only explanation turns expose no viewport tools.
- Exact live smoke: 16 of 16 assertions passed.
- Existing FAI motion contract smoke: 32 of 32 assertions passed.

The live test used all nominal dimensions except the piston outside diameter at 88 mm. Sage reported the 90 mm nominal, the 89.95 mm lower limit, and the 1.95 mm shortfall without inventing scrap, rework, or a catastrophic failure mode.

## Migration Boundary

This checkpoint migrates the Sage supplier FAI disposition workflow. The legacy prompt remains the fallback for workflows that have not yet been moved to versioned modules. Future migrations should use the same sequence: define modules and skills, declare required context and allowed tools, add synthetic and live regressions, then activate the compiled route.
