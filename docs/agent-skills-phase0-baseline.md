# Agent Skills Phase 0 Baseline

Generated: `2026-07-10T06:17:25.739473+00:00`
Git HEAD: `d519299f2141643329e46d7a20ab2c2ca75d33aa`
Telemetry database: `runtime_metrics\inspectorpro_metrics.sqlite`

## Classifier Baseline

| Metric | Value |
| --- | ---: |
| Calls | 136 |
| Success | 136 |
| Latency p50 | 2,014.7 ms |
| Latency p95 | 3,150.2 ms |
| Latency p99 | 5,826.9 ms |
| Input tokens p50 | 1,569 |
| Input tokens p95 | 1,593 |
| Total tokens / call mean | 1,628.6 |

A 2,000 ms serial timeout would reject `72` observed calls (`52.9%`). The Phase 2 shadow timeout derived from 1.5 x p95 is `4,750 ms`. Serial production routing remains unapproved until it is optimized and remeasured.

## Main Agent Baseline

| Metric | Value |
| --- | ---: |
| Calls | 325 |
| Latency p50 | 6,902.0 ms |
| Latency p95 | 11,340.6 ms |
| Input tokens p50 | 18,600 |
| Input tokens p95 | 21,512 |

## Static Prompt and Tool Inventory

| Agent | Base chars | Tool appendix chars | Combined chars | Approx. static tokens | Tools |
| --- | ---: | ---: | ---: | ---: | ---: |
| inspector | 8,188 | 1,939 | 10,127 | 2,532 | 8 |
| deviation-analyst | 27,965 | 2,573 | 30,538 | 7,635 | 12 |
| parts-finder | 1,944 | 914 | 2,858 | 715 | 1 |

Mode contracts: `8`
Frontend UI action types: `21`
Context sections inventoried: `28`

Mode addendum sizes:

- `facility_layout`: `1189` characters
- `plant_process`: `1022` characters
- `drawing`: `1012` characters
- `3dmodel`: `2057` characters
- `assembly`: `5005` characters
- `assembly_training`: `1394` characters
- `report`: `803` characters
- `report_fai`: `3432` characters

## Frozen Regression Bars

- `tests/test_viewport_intent_mapping.js`
- `tests/test_viewport_authorization_parity.py`
- `tests/test_fai_response_grounding.py`
- `tests/test_viewport_intent_classifier.py`
- `tests/test_mode_contract.py`
- `tests/test_agent_response_encoding.py`
- `tests/smoke_fai_motion_contract.py`

The complete tool names, UI action types, context-section inventory, per-agent telemetry, threshold counts, and token totals are in `agent-skills-phase0-baseline.json`.
