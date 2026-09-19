# Facility Layout Reference Factory Archive

Date: 2026-08-27

Status: Preserved; default workspace reset to blank

## Default Layout

The application default remains `fl-main`, now named `Blank Facility Layout`.
It contains no zones, routes, placements, or floor markings. Its current saved
revision is:

`54cee1725b4a2103b00f4b2f98ca66a8e31245383a9291be953968bd10f85a4c`

This gives every new Facility Layout session an empty deterministic base
without deleting the manually constructed factory used as the visual and
semantic reference.

## Preserved Reference

The complete manual factory is registered as:

- layout ID: `fl-reference-manual-20260812`
- display name: `Reference Factory - Manual Build`
- archived revision:
  `a40b2541e31c30487ec0b9040b65051a596ee23ffe2629956cf1851d53276088`
- original `fl-main` source revision:
  `8551e0b324df6dc17413d0ef8b6ad7f3bab438ba8558dc00320149bf7f855aa0`
- content: 45 zones, 8 routes, 827 placements, and 50 floor markings

The original source revision remains retrievable through repository history.
The archive is therefore a named working reference, not a flattened image or
an approximate reconstruction.

## Reproduction

The idempotent migration utility is:

`tools/archive_reference_facility_and_reset_default.py`

The machine-readable verification receipt is:

`tests/fixtures/facility_layout/knowledge_foundation/default-layout-reset-receipt.json`

The receipt verifies that `fl-main` stayed the default layout ID, the reference
layout is registered, the semantic content counts match the source, and the
exact original source revision can still be loaded.
