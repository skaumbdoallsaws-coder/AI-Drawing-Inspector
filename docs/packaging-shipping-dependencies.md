# Packaging & Shipping dependency, license and missing-component review

Status: **inventory and missing-component behaviour done; license review and clean install open.**
Recorded 2026-11-06 from the installed packages in this worktree's test environment. This is an
engineering inventory, not legal clearance: no redistribution obligation is decided here.

## Components

Declared licenses are read from installed package metadata. "License text" says whether the installed
package carries a license file.

| Component | Version | Runs in | Declared license | License text | Used for |
| --- | --- | --- | --- | --- | --- |
| py3dbp | 1.1.2 | Host process | MIT (classifier only) | **No** | Arrangement proposals |
| reportlab | 5.1.0 | Host process | BSD | Yes | Draft PDF report |
| charset-normalizer | 3.5.2 | Host process (reportlab) | MIT | Yes | reportlab dependency |
| pywin32 | 312 | Host process | PSF | Yes | Carrier key store (Windows DPAPI) |
| httpx | 0.28.1 | Host process | BSD-3-Clause | not checked | Carrier rating requests |
| fastapi / starlette / pydantic / uvicorn | 0.124.0 / 0.50.0 / 2.12.4 / 0.38.0 | Host process | MIT / BSD-3 / MIT / BSD-3 | not checked | Application host (not packaging-specific) |
| trimesh | 5.2.0 | GLB worker | MIT | Yes | GLB parsing and normalisation |
| numpy | 2.5.4 | GLB worker | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | Yes | trimesh dependency |
| pillow | 13.0.0 | GLB worker | MIT-CMU | Yes | Embedded textures |
| cadquery-ocp-novtk | 7.9.3.1.1 | STEP worker (Python 3.11) | Apache-2.0 | **No** | STEP import (OpenCascade) |
| cadquery-ocp-proxy | 7.9.3.1.1 | STEP worker | Apache-2.0 | **No** | OCP import shim |
| three.js | 0.184.0 | Editor (browser) | MIT | Yes (`static/vendor/three/0.184.0`) | 3D view, OrbitControls, GLTFLoader |
| EasyPost API | service | Carrier provider | Service terms | n/a | Quote-only rating; fees in the rating notice |

Test-only, not shipped: pdfplumber 0.11.8 (MIT), Playwright 1.56.0 (Apache-2.0) and its browser.

Where each one comes from:

- Host process: the application interpreter. In this test environment that is Python 3.14 with system
  site-packages, plus the packaging runtime folder on the path. The desktop's own interpreter was not
  inventoried here.
- GLB worker: only the runtime folder that the host passes to it (`-I -S -B`, no site processing, no
  inherited `PYTHON*` variables). Native startup binds that folder; other hosts use the interpreter's
  purelib.
- STEP worker: the separate Python 3.11 environment from `tools/setup_packaging_geometry.py`.

`tools/inventory_facility_python_dependencies.py --requirements requirements-packaging.txt` (and the same
for `requirements-packaging-step.txt`) records 0 machine blockers for both files. That tool reads only the
listed packages' metadata. It does not see transitive packages (numpy, pillow, charset-normalizer) or the
native libraries described below, so 0 blockers is not a clearance.

## Native libraries inside the STEP wheel

`cadquery-ocp-novtk` installs 70 DLLs in `cadquery_ocp_novtk.libs` and ships no license or notice text for
any of them. The upstream projects publish these licenses; check them against the exact builds before
redistributing:

| Libraries | Upstream license (to confirm) |
| --- | --- |
| Open CASCADE Technology (46 `TK*` toolkits) | LGPL-2.1 with the Open CASCADE exception |
| LibRaw (`raw`) | LGPL-2.1 or CDDL-1.0 |
| FreeImage | GPL-2.0/GPL-3.0 or the FreeImage Public License |
| FreeType | FreeType License or GPL-2.0 |
| OpenEXR, Iex, IlmThread, OpenEXRCore, Imath | BSD-3-Clause |
| libtiff, libpng16, zlib, libjpeg (`jpeg8`) | libtiff, libpng, zlib and IJG/BSD-style licenses |
| OpenJPEG (`openjp2`), OpenJPH | BSD-2-Clause |
| libwebp, libwebpmux, libsharpyuv | BSD-3-Clause |
| zstd, lcms2, LERC, liblzma, libdeflate | BSD-3/GPL-2.0, MIT, Apache-2.0, 0BSD/public domain, MIT |
| `msvcp140`, `vcomp140` | Microsoft Visual C++ redistributable terms |

## Missing components

Each optional component disables one feature. A missing one is reported as unavailable in this
installation, not as a bad file or a server fault. `GET /api/packaging/status` lists it under
`unsupported`.

| Missing | Status entry | When used | Test |
| --- | --- | --- | --- |
| STEP runtime not configured | `step_runtime_not_configured` | STEP option hidden; upload `step_runtime_unavailable` (503) | `test_packaging_step_import.py` |
| STEP worker cannot start | - | `step_runtime_unavailable` (503) | Not tested |
| numpy, trimesh or Pillow absent from the GLB worker's folder | `glb_import_runtime_missing` | `source_runtime_unavailable` (503), "Manual dimensions still work." | `test_packaging_missing_components.py` (real worker, empty folder) |
| py3dbp | `arrangement_runtime_missing` | `arrangement_unavailable` (503) in the editor and to Sage, "Manual packing still works." | `test_packaging_missing_components.py`, `test_codex_packaging_tools.py` |
| reportlab | `pdf_report_runtime_missing` | `report_unavailable` (503); the saved design is unchanged | `test_packaging_missing_components.py` |
| pywin32 (carrier key store) | - | `carrier_secure_store_unavailable`; no key is stored or read | `test_packaging_credentials.py` |
| httpx | - | The packaging API cannot load, so a host with packaging enabled does not start | Not tested. httpx is installed with the application's `openai` dependency. |
| py3dbp, trimesh or reportlab absent from a native profile's runtime folder | - | Profile rejected: `desktop_packaging_config_invalid` | `desktop/tests` (existing) |

The native profile check does not cover numpy or Pillow. If either is absent, GLB import fails at use with
the message above.

## Process boundaries

- Both import workers run as the signed-in Windows user. Process isolation is not an OS security sandbox.
- GLB worker: isolated interpreter flags, an environment reduced to the job folder and system paths, no
  console window, a 25 s limit with kill and reap, and a job folder removed afterwards. Covered by
  `test_packaging_worker_dependencies.py` and `test_packaging_shipping.py`.
- STEP worker: separate interpreter without site processing, output, file and time limits, and at most two
  imports at once.
- Carrier keys are protected with Windows DPAPI for the current user. Account discovery returns a
  sanitised allowlist.

## Open before a release

1. Collect license and notice texts for the 70 STEP DLLs, py3dbp and cadquery-ocp. Decide how LGPL
   components (Open CASCADE, LibRaw) are noticed and kept replaceable, and which option applies to
   FreeImage and FreeType. A person must make these decisions.
2. Declare pywin32 (Windows only) for the carrier key store. It is present in the test environment but no
   requirements file lists it.
3. Optionally add numpy and Pillow to the native runtime check, in both `desktop/runtime/packaging_config.py`
   and `desktop/src/packaging-config.cjs`. This is a desktop change and needs native tests.
4. Install on a clean Windows machine. Not attempted: no clean machine or VM is available here.
