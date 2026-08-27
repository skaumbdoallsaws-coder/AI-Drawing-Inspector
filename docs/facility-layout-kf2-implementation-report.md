# Facility Layout Knowledge Foundation KF2 Report

Date: 2026-08-26
Status: Complete

## Delivered

KF2 compiles the KF1 canonical registry into bounded knowledge surfaces without
creating another command definition:

- complete on-demand explanations for all 39 UI commands;
- complete stage-aware explanations for all 14 agent tools;
- ten compact stage slices with primary command guides, secondary stable IDs,
  support command IDs, applicable agent tools, and selection rules;
- deterministic capability, compatibility, prerequisite, prohibition, and
  follow-up queries;
- generated UI ribbon metadata and generated agent-tool metadata;
- exact static-ribbon, canonical registry, and runtime agent-tool parity;
- explicit preview, validation, receipt, and undo paths for every mutating
  command;
- context and response budget measurement using `bytes4-v1`;
- fail-closed overflow diagnostics with no semantic truncation;
- read-only HTTP endpoints under
  `/api/training/facility-layout/knowledge/`.

## Stage Slice Measurements

All measurements include their own measurement record and use canonical ASCII
JSON bytes.

| Stage | Bytes | Estimated tokens |
| --- | ---: | ---: |
| facility_envelope | 2,020 | 505 |
| macro_departments | 3,907 | 977 |
| primary_circulation | 3,136 | 784 |
| department_subdivisions | 4,395 | 1,099 |
| department_resources | 7,210 | 1,803 |
| seed_cells | 7,792 | 1,948 |
| repeated_modules | 7,872 | 1,968 |
| floor_communication | 4,474 | 1,119 |
| deterministic_validation | 3,411 | 853 |
| review_and_save | 4,050 | 1,013 |

Every slice is below 8,192 bytes and 2,048 `bytes4-v1` estimated tokens. Dense
asset and cell stages preserve a compact core guide and stable IDs for every
additional command; Sage retrieves the complete command contract before any
execution decision.

## Verification

KF2-specific suite:

```text
9 passed
```

Combined KF0-KF2 focused suite:

```text
54 passed
```

Full Facility Layout suite:

```text
689 passed, 13 failed, 1 skipped
```

The 13 failures exactly match the KF0 release-evidence quarantine. No new
Facility failure was introduced. Python compilation and `git diff --check`
also pass.

## Exit-Gate Disposition

- Every command intent, state, owner, and limit is retrievable: pass.
- Correct and prohibited use coverage: pass.
- Mutating-command execution paths: pass.
- Registry-to-UI and registry-to-agent parity: pass.
- Ten bounded stage slices: pass.
- Context target, hard limit, and tool-response boundary tests: pass.
- Overflow diagnostic without truncation: pass.

KF3, KF4, and the KF6 evaluation branch may proceed in parallel.
