---
name: recommend-fai-disposition
description: Recommend accept, rework, reject, or engineering escalation for a supplier FAI result. Use when the user asks what to do with a measured characteristic or inspected part.
---

# Recommend FAI Disposition

Base the recommendation on computed FAI evidence and explicitly available disposition evidence.

## Procedure

1. State the measured status before recommending an action.
2. Use `pass` only when a measured value is within computed limits.
3. Use `pending` when the measurement, limit, or controlling requirement is missing.
4. For an out-of-tolerance result, recommend reject or engineering disposition unless the context contains evidence supporting rework or accept-as-is.
5. Recommend rework only when the affected feature, remaining material, and a feasible correction path are supported.
6. Recommend accept-as-is only when authorized engineering evidence or a valid deviation approval is present.

## Boundaries

- Do not convert `reject or escalate for disposition` into `scrap` without explicit authority.
- Do not invent lot containment, tooling drift, process capability, or inspection actions.
- Keep the conclusion scoped to the inspected part and characteristic.
- Separate measured fact, likely functional concern, and disposition recommendation.

## Output

Give the recommendation, its controlling evidence, and the next decision owner or missing evidence in concise prose.
