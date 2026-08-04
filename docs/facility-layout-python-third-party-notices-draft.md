# Facility Layout Pilot Python Third-Party Notice Draft

> **DRAFT - MACHINE GENERATED - NOT LEGAL CLEARANCE**
>
> This document records installed metadata for direct Python
> requirements. It does not determine obligations, approve
> redistribution, or replace review of the exact packaged artifact.

## Inventory Binding

- Generated: `2026-08-04T19:42:14Z`
- Requirements SHA-256: `351e2a9fe4d6fa1f7f9490f0293a9dba7dfddcd8f735dafb8a7e88828bae94d4`
- Inventory tool SHA-256: `b73a5d0c855a34f07aa171ab192e5c3dccb47eb497461c794621f7534463c026`
- Machine assessment: **BLOCKED** (29 blockers)
- Human legal approval: **NOT PERFORMED**
- Release clearance claimed: **NO**

## Direct Requirements

| Requirement | Installed distribution | Version | Metadata license declaration | Review |
| --- | --- | --- | --- | --- |
| `ultralytics` | MISSING | `MISSING` | MISSING | blocked |
| `transformers>=5.0.0` | transformers | `4.57.1` | Apache 2.0 License | blocked |
| `torch` | torch | `2.9.1` | BSD-3-Clause | blocked |
| `Pillow` | pillow | `12.0.0` | MIT-CMU | blocked |
| `numpy` | numpy | `2.3.5` | Copyright (c) 2005-2025, NumPy Developers. All rights reserved. Redistribution and use in source and binary forms, with or without modification, are permitte... | blocked |
| `scipy` | scipy | `1.16.3` | Copyright (c) 2001-2002 Enthought, Inc. 2003, SciPy Developers. All rights reserved. Redistribution and use in source and binary forms, with or without modif... | blocked |
| `pyyaml` | PyYAML | `6.0.3` | MIT | blocked |
| `shapely` | MISSING | `MISSING` | MISSING | blocked |
| `fastapi` | fastapi | `0.124.0` | MIT | blocked |
| `uvicorn[standard]` | uvicorn | `0.38.0` | BSD-3-Clause | blocked |
| `python-multipart` | python-multipart | `0.0.20` | Apache-2.0 | blocked |
| `playwright` | playwright | `1.56.0` | Apache-2.0 | blocked |
| `elevenlabs` | elevenlabs | `2.24.0` | MIT | blocked |
| `anthropic` | anthropic | `0.75.0` | MIT | blocked |
| `openai` | openai | `2.8.1` | Apache-2.0 | blocked |
| `python-dotenv` | python-dotenv | `1.2.1` | BSD-3-Clause | blocked |
| `PyMuPDF` | PyMuPDF | `1.27.2.3` | Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License | blocked |
| `faster-whisper>=1.1.0` | MISSING | `MISSING` | MISSING | blocked |

## Machine Blockers

- `commercial_or_dual_license_review_required` (`numpy`): Installed metadata contains commercial or dual-license terms: proprietary.
- `commercial_or_dual_license_review_required` (`pymupdf`): Installed metadata contains commercial or dual-license terms: commercial_license, dual_license.
- `commercial_or_dual_license_review_required` (`scipy`): Installed metadata contains commercial or dual-license terms: proprietary.
- `direct_requirement_missing` (`faster-whisper`): The active direct requirement is not installed.
- `direct_requirement_missing` (`shapely`): The active direct requirement is not installed.
- `direct_requirement_missing` (`ultralytics`): The active direct requirement is not installed.
- `direct_requirement_unpinned` (`anthropic`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`elevenlabs`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`fastapi`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`faster-whisper`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`numpy`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`openai`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`pillow`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`playwright`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`pymupdf`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`python-dotenv`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`python-multipart`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`pyyaml`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`scipy`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`shapely`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`torch`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`transformers`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`ultralytics`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `direct_requirement_unpinned` (`uvicorn`): The direct requirement is not bound to one exact version or a hash-bound direct URL.
- `installed_version_outside_declared_specifier` (`transformers`): Installed version 4.57.1 does not satisfy >=5.0.0.
- `pymupdf_dual_agpl_commercial_review_required` (`pymupdf`): PyMuPDF distribution requires explicit human review of its AGPL/commercial licensing path.
- `strong_copyleft_review_required` (`numpy`): Installed metadata contains strong-copyleft terms: gnu_affero, gnu_gpl, gpl.
- `strong_copyleft_review_required` (`pymupdf`): Installed metadata contains strong-copyleft terms: gnu_affero, gpl.
- `strong_copyleft_review_required` (`scipy`): Installed metadata contains strong-copyleft terms: gnu_affero, gnu_gpl, gpl.

## Human Review Required

Before distributing a pilot build, a qualified reviewer must:

1. Inventory the exact packaged artifacts and transitive dependencies.
2. Confirm the governing license path for every distribution.
3. Review required attribution, notice, source-offer, and disclosure terms.
4. Resolve every machine blocker, including the PyMuPDF licensing path.
5. Approve the final notice text and retain that approval separately.

This draft intentionally contains no statement that the Facility Layout
pilot, its Python dependencies, or this notice has legal clearance.
