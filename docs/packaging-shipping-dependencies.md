# Packaging & Shipping dependency, license and missing-component review

Status: **dependencies declared, exact-version license texts collected, missing-component behaviour
done. Redistribution clearance and the clean install are open.**
Recorded 2026-11-06. This is an engineering record, not legal clearance: no redistribution obligation
is decided here.

## Local development testing and redistribution are separate

- **Local development testing** (this machine, test profiles, the user's own desktop) installs these
  components from their public package indexes for the user's own use. Nothing is passed to anyone
  else, so no redistribution obligation applies to that testing, and none of the items below blocks it.
- **Redistribution** (an installer, a bundled runtime folder or a copied machine given to anyone else)
  conveys the components and their native libraries. That needs the decisions under "Redistribution
  obligations" first. Nothing in this branch builds or ships such a bundle.

## Components

Declared licenses are read from installed package metadata. "License text" says whether the installed
package carries a license file; the collected upstream texts are listed in the next section.

| Component | Version | Runs in | Declared license | License text | Declared in | Used for |
| --- | --- | --- | --- | --- | --- | --- |
| py3dbp | 1.1.2 | Host process | MIT (classifier only) | **No** (collected upstream) | `requirements-packaging.txt` | Arrangement proposals |
| reportlab | 5.1.0 | Host process | BSD | Yes | `requirements-packaging.txt` | Draft PDF report |
| charset-normalizer | 3.5.2 | Host process (reportlab) | MIT | Yes | reportlab's own dependency | reportlab dependency |
| trimesh | 5.2.0 | GLB worker | MIT | Yes | `requirements-packaging.txt` | GLB parsing and normalisation |
| numpy | 2.5.4 | GLB worker | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | Yes | `requirements-packaging.txt` (added 2026-11-06) | Imported directly by the worker |
| pillow | 13.0.0 | GLB worker | MIT-CMU | Yes | `requirements-packaging.txt` (added 2026-11-06) | Embedded textures |
| pywin32 | 312 | Host process (Windows) | PSF | Yes | `requirements.txt`, Windows only (added 2026-11-06) | Carrier key store (Windows DPAPI) |
| httpx | 0.28.1 | Host process | BSD-3-Clause | not checked | `requirements.txt` (added 2026-11-06; also installed by openai) | Carrier rating requests |
| fastapi / starlette / pydantic / uvicorn | 0.124.0 / 0.50.0 / 2.12.4 / 0.38.0 | Host process | MIT / BSD-3 / MIT / BSD-3 | not checked | `requirements.txt` | Application host (not packaging-specific) |
| cadquery-ocp-novtk | 7.9.3.1.1 | STEP worker (Python 3.11) | Apache-2.0 | **No** (collected upstream) | `requirements-packaging-step.txt` | STEP import (OpenCascade) |
| cadquery-ocp-proxy | 7.9.3.1.1 | STEP worker | Apache-2.0 | **No** (collected upstream) | `requirements-packaging-step.txt` | OCP import shim |
| three.js | 0.184.0 | Editor (browser) | MIT | Yes (`static/vendor/three/0.184.0`) | vendored | 3D view, OrbitControls, GLTFLoader |
| EasyPost API | service | Carrier provider | Service terms | n/a | n/a | Quote-only rating; fees in the rating notice |

Test-only, not shipped: pdfplumber 0.11.8 (MIT), Playwright 1.56.0 (Apache-2.0) and its browser.

Why the declarations were needed:

- numpy and Pillow were in the desktop runtime folder only because trimesh and reportlab pull them in.
  The GLB worker imports both directly, so they are now pinned at the versions that folder ships, and
  the native profile check (`desktop/runtime/packaging_config.py`, `desktop/src/packaging-config.cjs`)
  now requires them too, so a folder without them is caught when the profile loads, not on first import.
  Since 2026-11-07 that turns Packaging off for the session with a notice naming the missing package,
  and the rest of the desktop starts (see "Missing components").
- pywin32 was present in the test environment but listed nowhere. Its startup `.pth` file must be
  processed, so it cannot come from the packaging runtime folder, which is added without site
  processing. Checked 2026-11-07, correcting an earlier note of the same day: the regular desktop's
  interpreter (`C:\Python314`) has no pywin32 of its own, but that desktop's profile configures Sage
  (`codexRuntime`), and its backend adds Sage's verified dependency bundle (`codex-pilot-deps`,
  pywin32 312) as a site directory at startup (`desktop/runtime/codex_config.py`). In that setup the
  carrier key store saved, read back and removed a made-up value in a scratch folder, so that desktop
  can store a carrier key while Sage is configured; a desktop profile without `codexRuntime` cannot
  (`carrier_secure_store_unavailable`). No second pywin32 was installed into the interpreter's user
  site: it would load ahead of Sage's tested copy, which the ChatGPT account store also uses.
- httpx is imported directly by the rating adapter. It was only present because openai depends on it.
  It is declared in `requirements.txt` rather than the packaging runtime folder, so the folder (first on
  the path) cannot shadow the version openai uses.

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
listed packages' metadata. It does not see transitive packages or the native libraries described below,
so 0 blockers is not a clearance.

## Exact-version license texts (collected 2026-11-06)

The texts were collected for the exact versions shipped, from each project's tagged source or the
conda-forge build the wheel used. The wheel was built by CadQuery/ocp-build-system tag v7.9.3.1.1, which
compiles OCCT tag V7_9_3 with one CMake patch and takes the other native libraries from conda-forge.

- Location: `.runtime/pc-licenses/upstream/` in this worktree, with `manifest.json` (component, exact
  version, SPDX expression, version evidence, and for each file its source URL, retrieval time and
  SHA-256). Kept out of git: these are downloaded third-party texts for the release decision, not
  application code.
- Checks (re-run separately from the collection): 40 files, 0 SHA-256 mismatches, no unlisted or missing
  files, and all 70 DLLs in `cadquery_ocp_novtk.libs` are assigned to a component. Nothing downloaded
  was executed or unpacked.
- Versions marked "inferred" have no version string in the binary: the DLL link time matches one
  conda-forge build and the packages that use it pin the same version.

| Component | Exact version | License (SPDX) | Texts | Open point |
| --- | --- | --- | --- | --- |
| Open CASCADE Technology (46 `TK*` DLLs) | 7.9.3 | LGPL-2.1-only WITH OCCT-exception-1.0 | 2 | Source offer; "uses Open CASCADE Technology" notice |
| FreeImage | 3.18.0 | FreeImage OR GPL-2.0-only OR GPL-3.0-only | 3 | License choice; conda-forge patched it |
| jxrlib (inside FreeImage.dll) | 1.1 | BSD-2-Clause | 2 | No upstream license file exists |
| FreeType | 2.12.1 | FTL OR GPL-2.0-or-later | 3 | License choice; FTL needs a credit line |
| OpenEXR (Iex, IlmThread, OpenEXR, OpenEXRCore) | 3.4.12 | BSD-3-Clause, plus PATENTS | 2 | Choice for the DWA files |
| Imath | 3.2.2 (inferred) | BSD-3-Clause | 1 | - |
| libjpeg-turbo (`jpeg8`) | 3.1.4.1 | IJG AND BSD-3-Clause AND Zlib | 2 | IJG credit sentence |
| Little CMS (lcms2) | 2.19 | MIT | 1 | - |
| LERC | 4.1.0 (inferred) | Apache-2.0, plus NOTICE | 2 | NOTICE must be reproduced |
| liblzma | 5.8.3 | 0BSD | 2 | - |
| libpng | 1.6.58 | libpng-2.0 | 1 | - |
| libwebp, libwebpmux, libsharpyuv | 1.6.0 | BSD-3-Clause, plus PATENTS | 2 | Ship PATENTS |
| OpenJPEG (`openjp2`) | 2.5.4 | BSD-2-Clause | 1 | - |
| OpenJPH | 0.27.3 | BSD-2-Clause | 1 | - |
| LibRaw | 0.21.5 | LGPL-2.1-only OR CDDL-1.0 | 3 | License choice; texts of code embedded in LibRaw not collected |
| LibTIFF | 4.7.1 | libtiff | 1 | - |
| zlib | 1.3.2 | Zlib | 1 | - |
| zstd | 1.5.7 | BSD-3-Clause OR GPL-2.0-only | 2 | Elect BSD-3-Clause |
| libdeflate | 1.25 (inferred) | MIT | 1 | - |
| Microsoft VC++ runtime (`msvcp140`, `vcomp140`) | 14.51.36231.0 | Microsoft Visual C++ runtime terms | URLs only | Needs the distributor's own Visual Studio license |
| RapidJSON (inside TKDEGLTF.dll and OCP.pyd) | 1.1.0.post20240409 (inferred) | MIT | 1 | - |
| pybind11 (inside OCP.pyd) | 2.13.6 (inferred) | BSD-3-Clause | 1 | BSD notice |
| {fmt} (inside OCP.pyd) | 12.0.0 or 12.1.0 | MIT with binary exception | 0 | Version not determinable |
| OCP bindings | 7.9.3.1.1 | Apache-2.0 AND BSD-3-Clause-LBNL | 2 | BSD notice for `pystreambuf.h` |
| cadquery-ocp-novtk wheel | 7.9.3.1.1 | Apache-2.0 | 1 | Wheel lacks its intended LICENSE |
| cadquery-ocp-proxy wheel | 7.9.3.1.1 | Apache-2.0 | 1 | - |
| py3dbp | 1.1.2 | MIT | 1 | No release tag; MIT text has no copyright line |

## Redistribution obligations (unresolved; a person must decide)

None of these blocks local development testing. Each blocks redistribution until decided:

1. **LGPL components** (Open CASCADE, and LibRaw if its LGPL option is chosen): ship the corresponding
   source with the application or a written offer valid for three years. For Open CASCADE that is tag
   V7_9_3 plus the ocp-build-system patch and build scripts. The license terms must allow reverse
   engineering for debugging the modified library. The wheel's packaging tool renamed every DLL to
   `<name>-<hash>.dll`; counsel should confirm that users can still replace the LGPL libraries.
2. **Open CASCADE exception**: the documentation needs a prominent notice that the product uses Open
   CASCADE Technology.
3. **License choices**: FreeImage (FreeImage Public License, which for this patched copy also needs a
   notice of where its source is), FreeType (FTL, which requires a credit line), LibRaw (LGPL-2.1 or
   CDDL-1.0, either with a source-availability statement), zstd (BSD-3-Clause), and the OpenEXR DWA
   files (BSD with DreamWorks' patent grant, or Apache-2.0).
4. **Notices to include in a release**: the FreeImage credit sentence, the Independent JPEG Group
   sentence, the LERC NOTICE, the libwebp and OpenEXR PATENTS files, and the BSD notices for pybind11,
   jxrlib and OCP's `pystreambuf.h`.
5. **Not collected**: texts for code inside LibRaw (dcraw, DCB/FBDD, X3F and Adobe DNG SDK parts),
   which exist only in its source headers; {fmt}, whose exact version cannot be determined.
6. **Microsoft runtime DLLs**: their signatures are valid, so the contents are unmodified (only
   renamed). Redistributing them requires the distributor's own Visual Studio license; the manifest
   records the Visual Studio 2026 distributable-code page.
7. **Wheel metadata**: the cadquery-ocp-novtk wheel lacks the LICENSE it was meant to include (a build
   script bug), and its Apache-2.0 metadata does not cover the bundled DLLs.
8. **py3dbp**: the repository has no tags; commit e69bbfa matches the installed files byte for byte. Its
   MIT text has no copyright line, so the attribution wording needs confirming.

## Missing components

Each optional component disables one feature. A missing one is reported as unavailable in this
installation, not as a bad file or a server fault. `GET /api/packaging/status` lists it under
`unsupported`.

| Missing | Status entry | When used | Test |
| --- | --- | --- | --- |
| STEP runtime not configured | `step_runtime_not_configured` | STEP option hidden; upload `step_runtime_unavailable` (503) | `test_packaging_step_import.py` |
| STEP worker cannot start, or starts without its geometry component (OCP) | - | `step_runtime_unavailable` (503), "STEP import is not available in this installation ... Manual dimensions still work." | `test_packaging_step_import.py` (real worker under an interpreter without OCP); native missing-components run |
| numpy, trimesh or Pillow absent from the GLB worker's folder | `glb_import_runtime_missing` | `source_runtime_unavailable` (503), "Manual dimensions still work." | `test_packaging_missing_components.py` (real worker, empty folder) |
| py3dbp | `arrangement_runtime_missing` | `arrangement_unavailable` (503) in the editor and to Sage, "Manual packing still works." | `test_packaging_missing_components.py`, `test_codex_packaging_tools.py` |
| reportlab | `pdf_report_runtime_missing` | `report_unavailable` (503); the saved design is unchanged | `test_packaging_missing_components.py` |
| pywin32 (carrier key store) | - | `carrier_secure_store_unavailable`; no key is stored or read. In the desktop it comes from Sage's dependency bundle, so a profile without Sage has no carrier key store | `test_packaging_credentials.py` |
| httpx | - | The packaging API cannot load, so a host with packaging enabled does not start | Not tested. Declared in `requirements.txt`. |
| py3dbp, trimesh, reportlab, numpy or Pillow absent from a native profile's runtime folder, or an unusable runtime folder, settings or storage folder | - | The desktop starts with Packaging off and says why once (reason `package:<name>`, `dependency-folder`, `settings` or `storage`); nothing from the refused runtime is used. Enabling Packaging (`tools/enable_desktop_packaging.py`) still refuses it | `desktop/tests`; native `.runtime/pc-native/unavail-pkg-01` |
| The STEP Python named by a native profile is missing or not allowed | - | Packaging starts without STEP import (`step_runtime_not_configured`) and the window says why; manual packing and saving work | `desktop/tests`; native `.runtime/pc-native/unavail-step-01` |

## Process boundaries

- Both import workers run as the signed-in Windows user. Process isolation is not an OS security sandbox.
- GLB worker: isolated interpreter flags, an environment reduced to the job folder and system paths, no
  console window, a 25 s limit with kill and reap, and a job folder removed afterwards. Before parsing,
  it puts itself under OS limits: 30 s of CPU, one process and, on Windows, 1.5 GiB of memory (a job
  object, like the STEP worker). If the limits cannot be set it does not parse
  (`source_limits_unavailable`). A worker whose host stopped therefore ends by itself. Covered by
  `test_packaging_worker_dependencies.py` and `test_packaging_shipping.py`.
- Job folders left by a host that stopped mid-import (`glb-*` under the packaging store, `step-*` under
  a host-configured STEP work folder, never the system temp folder) are removed at startup once they are
  an hour old. Links and junctions are skipped.
- STEP worker: separate interpreter without site processing, output, file and time limits, and at most two
  imports at once.
- Carrier keys are protected with Windows DPAPI for the current user. Account discovery returns a
  sanitised allowlist.

## Open before a release

1. The redistribution decisions above. A person (with counsel where needed) must make them; until
   then no installer or bundled runtime may be given to anyone else.
2. Install on a clean Windows machine. Not attempted: no clean machine or VM is available here.
