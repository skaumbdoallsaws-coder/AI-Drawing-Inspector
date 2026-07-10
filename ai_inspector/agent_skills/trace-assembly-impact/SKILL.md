---
name: trace-assembly-impact
description: Trace an FAI deviation from the controlled feature to mating parts and relevant assembly motion. Use when the user asks what a failed dimension affects or why it matters in the product.
---

# Trace Assembly Impact

Build an evidence chain across the loaded product assets.

## Procedure

1. Start from the exact failed characteristic and measured direction.
2. Resolve the characteristic to its semantic feature when a feature map is available.
3. Identify the mating interface and immediate neighboring parts from assembly evidence.
4. Resolve one affected assembly instance unless evidence proves a broader condition.
5. Identify the relevant semantic motion group only when the package explicitly maps that group to the affected parts or function.
6. Label each link as measured fact, product-data fact, or conditional engineering inference.

## Boundaries

- Do not jump directly from a tolerance failure to a catastrophic mechanism failure.
- Do not invent clearance, force, wear rate, noise, service life, or time-to-failure.
- Do not claim every repeated instance is defective because one inspected part failed.
- If the cross-asset join is incomplete, state the missing link instead of guessing.

## Output

Explain the chain as: failed characteristic -> controlled feature -> mating interface -> affected instance or motion group -> likely concern.
