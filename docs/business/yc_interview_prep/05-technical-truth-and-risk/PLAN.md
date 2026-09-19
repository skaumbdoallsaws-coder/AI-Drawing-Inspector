# Area 05: Technical Truth and Risk

## Schedule

- Start: August 6, 2026
- End: August 8, 2026
- Time: 3 days, 6 hours

## What This Area Must Address

This area demonstrates technical command without burying the answer in architecture. It must explain how InspectorPro grounds AI in product data, where deterministic checks operate, what can fail, and how customer information is protected.

The work must address:

- CAD, drawing, BOM, FAI, and assembly-context ingestion.
- How product entities and evidence are linked.
- Deterministic calculations versus model reasoning.
- Prompt compilation, skills, tool validation, and execution receipts.
- Accuracy measurement and failure handling.
- Model-provider dependence and portability.
- Proprietary-data handling, deployment, and security boundaries.
- Performance, cost, and scaling risks.
- Technical defensibility beyond the selected model.

## Core Questions

- How does the product work technically?
- What does the model receive?
- What is deterministic and what is generated?
- How do you prevent hallucinated engineering conclusions?
- How accurate is it and how do you know?
- What happens when context is missing or contradictory?
- Can customer CAD be kept private?
- Are you dependent on Claude or OpenAI?
- What is technically difficult to reproduce?
- What currently fails most often?

## Daily Plan

### August 6: Architecture and Context

- Build a simple architecture diagram from source data to answer or action.
- Explain the functional-relationship and evidence layers.
- Prepare both plain-language and technical versions.

### August 7: Trust, Accuracy, and Security

- Document validators, guardrails, receipts, provenance, and abstention behavior.
- Inventory accuracy evidence and remaining evaluation gaps.
- Define current and planned customer-data boundaries.

### August 8: Dependence, Scale, and Defensibility

- Explain model portability and provider tradeoffs.
- Estimate latency and cost for the first workflow.
- Identify the proprietary product layer that compounds with customer use.
- Run technical red-team questions.

## Deliverables

- Plain-language architecture diagram.
- Technical architecture diagram.
- Deterministic-versus-model responsibility table.
- Accuracy and evaluation fact sheet.
- Security and data-handling summary.
- Model-dependence answer.
- Technical-risk register.
- Ten technical answer cards.

## Definition of Done

This area is complete when Shadrack can explain the system clearly to both a general investor and a technical partner, state limitations honestly, and show that engineering safety depends on deterministic controls and structured evidence rather than prompt wording alone.

