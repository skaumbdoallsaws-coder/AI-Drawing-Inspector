---
name: recommend-fai-disposition
description: Recommend accept, rework, reject, or engineering escalation for a supplier FAI result. Use when the user asks what to do with a measured characteristic or inspected part.
---

# Recommend FAI Disposition

Base the recommendation on computed FAI evidence and explicitly available disposition authority.

## Procedure

1. If an approved disposition policy matches the characteristic and deviation, state its final verdict directly.
2. Put the verdict and immediate action first: accept, rework, reject and replace, or scrap and replace.
3. Support it with one measurement sentence containing the measured value, controlling limit, and amount out of tolerance.
4. Do not ask engineering to decide a case already covered by delegated engineering authority.
5. Use `pass` only when a measured value is within computed limits.
6. Recommend rework or accept-as-is only when the approved evidence permits it.
7. When no approved policy matches, state that the case is not covered and name the single missing decision criterion or authority.

## Boundaries

- Do not convert `reject or escalate for disposition` into `scrap` without explicit authority.
- Do not invent lot containment, tooling drift, process capability, or inspection actions.
- Keep the conclusion scoped to the inspected part and characteristic.
- Do not repeat the same measurement, status, functional concern, or disposition.
- Do not first reject the part and then say engineering must decide whether to reject it.

## Output

Use no more than two sentences. For a policy-covered case: final disposition and next action; then the decisive measurement and policy basis. Do not list alternatives or unsupported repair methods.
