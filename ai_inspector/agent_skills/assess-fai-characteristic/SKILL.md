---
name: assess-fai-characteristic
description: Evaluate one or more FAI rows from measured values and computed limits. Use for inspection status, deviation direction, and evidence-grounded characteristic assessment.
---

# Assess FAI Characteristics

Use the computed FAI fields as the controlling evidence.

## Procedure

1. Identify the requested characteristic or the current failed row from context.
2. Read nominal, lower limit, upper limit, measured value, status, direction, delta, and out-of-tolerance amount.
3. If measured is absent, call the characteristic pending. Do not infer pass or fail.
4. If measured is present, state measured versus nominal and limits before describing impact.
5. Separate measured fact from conditional engineering impact.
6. Keep the assessment scoped to the inspected part. Do not extend one failed row to every assembly instance.

## Grounding Rules

- Prefer computed limits and status over prose or visual estimates.
- Use the exact out-of-tolerance amount when available.
- Do not call an above-upper-limit result undersize or a below-lower-limit result oversize.
- Do not invent measurements, fit clearances, loads, lot history, tooling drift, or process capability.
- Do not claim scrap, rework, or accept-as-is evidence that the context does not provide.
- Describe downstream effects with conditional language unless exact mating or functional evidence is present.
- Use plain ASCII units and notation, including `+/-` and `deg`.

## Output

Give a concise assessment containing:

- characteristic identity and function when available
- measured result and computed tolerance comparison
- status and exact deviation direction
- evidence limitation or required clarification
