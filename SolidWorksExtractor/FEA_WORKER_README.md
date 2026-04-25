# FEA Worker README — SolidWorks 2024 SP5 Machine

This document is the **complete operating manual** for the worker computer that
runs the FEA extractor. It is intentionally strict: do exactly what is written
here, nothing more. Improvising is what causes the source-of-truth computer to
re-do the run.

The worker does **not** modify source code. Source code lives on, and is
authored on, the other machine. The worker only:

1. pulls the latest code,
2. builds it locally,
3. runs the extractor on a part with a solved Simulation study,
4. commits the generated artifacts back through git on a worker branch.

If you find yourself wanting to edit `.cs` files or change `run_fea_extract.ps1`
to make a run "work", **stop and report back instead**.

---

## 1. Prerequisites (one-time)

These must all be true on the worker computer before the first run:

- **Operating system**: Windows 10 or Windows 11, 64-bit.
- **SolidWorks 2024 SP5** installed and licensed.
- **SolidWorks Premium or Simulation add-in license** active. The extractor
  reaches Simulation through `swApp.GetAddInObject("SldWorks.Simulation")`;
  if that returns null you have no license / the add-in is disabled.
- **.NET Framework 4.8** runtime present (default on modern Windows; the
  extractor targets `v4.8`).
- **MSBuild 16+ or Visual Studio 2019+** (Community edition is fine).
  MSBuild is what builds `SolidWorksExtractor.csproj`. Locate it under
  `C:\Program Files\Microsoft Visual Studio\<ver>\<edition>\MSBuild\Current\Bin\MSBuild.exe`
  or install Visual Studio Build Tools.
- **Git for Windows** on `PATH`. The extractor records `git rev-parse HEAD`
  into the manifest as the worker's provenance — without git on PATH, the
  manifest's `extractor_git_commit` will be `null`.
- **PowerShell 5.1+** (default on Windows 10/11).
- **Write access to the local clone** of this repo (you will commit back).

---

## 2. One-time setup

1. Clone the repo to a path **without exotic characters** (avoid OneDrive
   paths if you can; if not, use the same OneDrive root we use here).

   ```powershell
   git clone <repo-url> C:\src\AI-tool
   cd C:\src\AI-tool
   ```

2. Build the extractor in **Debug** configuration:

   ```powershell
   & "C:\Program Files\Microsoft Visual Studio\<ver>\<edition>\MSBuild\Current\Bin\MSBuild.exe" `
     SolidWorksExtractor\SolidWorksExtractor.csproj /p:Configuration=Debug /v:minimal
   ```

   You should see `SolidWorksExtractor -> ...\bin\Debug\SolidWorksExtractor.exe`
   at the end. One pre-existing `CS0618` warning about `HoleGroup.Diameter` is
   expected and unrelated.

3. **Do not** copy `SolidWorksExtractor.exe` out of the repo. It loads C# code
   that resolves SolidWorks interop assemblies via paths the project knows;
   running it from a non-repo location is unsupported. The runner script
   always invokes `SolidWorksExtractor\bin\Debug\SolidWorksExtractor.exe`
   relative to the repo root — keep it that way.

4. Open SolidWorks 2024 manually once, accept any first-run dialogs, and make
   sure the Simulation tab is enabled in `Tools → Add-Ins`.

---

## 3. Per-run workflow (every part, every study)

### Step A — Pull the latest code

```powershell
cd C:\src\AI-tool
git fetch origin
git checkout main
git pull
git status --short
```

`git status --short` must show no source changes before extraction. If any
extractor or runner source changed locally, commit those source changes first,
then rebuild and run extraction from that committed HEAD. The runner enforces
this for extractor build inputs under `SolidWorksExtractor/` and
`scripts/run_fea_extract.ps1`, excluding only transient residue under
`incoming_fea/.staging/`.

### Step B — Rebuild if Step A changed any `.cs` file

```powershell
& "C:\Program Files\Microsoft Visual Studio\<ver>\<edition>\MSBuild\Current\Bin\MSBuild.exe" `
  SolidWorksExtractor\SolidWorksExtractor.csproj /p:Configuration=Debug /v:minimal
```

### Step C — Open the part in SolidWorks and verify the study is solved

- Open the `.SLDPRT` in SolidWorks 2024.
- In the Simulation tab, verify the study you intend to extract has a
  green checkmark (i.e. results are computed). If it does not, **solve it
  first inside SolidWorks**. The extractor explicitly rejects unsolved
  studies in explicit-selection mode (this is intentional; do not work
  around it).

### Step D — Run preflight (always — sanity-checks env + lists studies)

```powershell
.\scripts\run_fea_extract.ps1 -Active -Preflight
```

You will see:

- SolidWorks version
- Document path
- Simulation add-in availability — **must be `available`**, otherwise stop
- Studies table with index, name, type, results yes/no

If `Simulation add-in` shows `NOT available`, **stop**. Do not proceed. Fix
the license / add-in activation in SolidWorks.

### Step E — Run the extraction with **explicit study selection**

Choose the study by **name** (preferred) or by **index**:

```powershell
# By name (preferred — name is meaningful and survives re-ordering in SW)
.\scripts\run_fea_extract.ps1 -Active -PartNumber 1234567 -StudyName "Static 1"

# By index (only when name is unstable or contains characters that confuse the shell)
.\scripts\run_fea_extract.ps1 -Active -PartNumber 1234567 -StudyIndex 0
```

The runner script enforces explicit selection and **refuses to run without a
selector**. If you genuinely want the legacy "first completed static study"
fallback, opt in with `-AllowImplicit` — but that is reserved for special
situations. The selection mode is recorded in the manifest's
`study.selection_mode` field (`"explicit-name"`, `"explicit-index"`, or
`"implicit"`) so the reviewer on the source-of-truth machine can spot any
implicit run on review.

Before the extractor starts, the runner prints the exact `Git HEAD` commit
that the run must use for provenance. If the runner reports dirty extraction
source, stop: commit those source changes first, then rerun extraction from the
clean committed worktree.

Every successful run lands in the canonical staging directory:

```
incoming_fea\<part-slug>\<study-slug>\
```

regardless of which selector you used. The runner extracts into a temp
directory under `incoming_fea\.staging\` first, reads the manifest the
extractor produces to discover the real `<study-slug>`, then moves the
four artifacts into the canonical directory. There is no `by_index_<n>` or
`by_implicit_selection` placeholder in the committed layout.
View PNGs are not part of worker FEA staging; the runner and extractor skip
view screenshot export for this path.

If the canonical directory already contains artifacts (you are re-running
the same part + study combination), the script **refuses** to overwrite
unless you also pass `-Force`. Without `-Force` it exits with code 3 and
leaves the new artifacts in the temp staging directory for inspection.
This is intentional: re-runs of the same study should be deliberate, not
accidental, because they destroy prior provenance.

(See `incoming_fea/README.md` for the exact filename contract.)

### Step F — Sanity-check the manifest

Open the `*_manifest.json` file the script reports. Verify:

- `study.name` matches the SolidWorks study you chose.
- `study.selection_mode` is `"explicit-name"` or `"explicit-index"`,
  **not** `"implicit"` (unless you intentionally used `-AllowImplicit`).
- `solidworks_version` is the version you ran on.
- `extractor_git_commit` is a real SHA, not `null`, and it exactly matches
  the `Git HEAD` value printed by the runner before extraction. If it is null
  or different, install git / fix PATH / commit source changes and rerun.
- `visualization.approximate` is `false`; normal worker runs must not ship
  synthetic CAD-tessellation heatmaps as FEA GLBs.
- `warnings` list does not contain anything alarming. The two known-always
  warnings are:
  - `"Per-node strain (max_strain_node) is not exposed via the COSMOSWorks API; left null."`
  - `"Load/fixture entity_kind (face/edge/vertex) is not exposed via the COSMOSWorks API; left null on every item."`
  Anything else (especially `Could not get reaction forces`, `GetTranslationalDisplacement failed`, etc.) is a real signal — flag it in the commit message.

### Step G — Commit and push on a worker branch

Branch name format: `fea-worker-run-YYYYMMDD` (one branch per day is fine).

```powershell
git checkout -b fea-worker-run-2026-04-24
git add incoming_fea\1234567\static_1\
git commit -m "fea: 1234567 / Static 1 — worker run 2026-04-24"
git push -u origin fea-worker-run-2026-04-24
```

**The only files you should commit are inside `incoming_fea/`.** No source
edits. No `bin/` artifacts. Use `git status` before staging to be sure.

---

## 4. Inspect-only modes (no extraction)

```powershell
# Preflight (env + studies, no extraction)
.\scripts\run_fea_extract.ps1 -Active -Preflight

# List studies in the active doc
.\scripts\run_fea_extract.ps1 -Active -ListStudies

# Same against a file path instead of the active doc
.\scripts\run_fea_extract.ps1 -PartFile "C:\parts\Mounting Plate.SLDPRT" -Preflight
```

Inspect-only modes can run on any document and never write to `incoming_fea/`.

---

## 5. Strict rules (do not break these)

1. **Do not modify source code.** Code lives on the source-of-truth computer.
   Worker commits should only contain `incoming_fea/...` files.
2. **Do not skip preflight on a new part.** It's the only way to confirm the
   Simulation add-in is reachable before you spend time on extraction.
3. **Always use explicit study selection** (`-StudyName` or `-StudyIndex`).
   `-AllowImplicit` is opt-in only and should be rare.
4. **Do not run extraction from dirty extractor or runner source.** Commit
   source changes first. The runner refuses normal extraction when
   extractor build inputs under `SolidWorksExtractor/` or
   `scripts/run_fea_extract.ps1` have uncommitted changes, and the manifest's
   `extractor_git_commit` must match the printed `Git HEAD`.
5. **Do not solve studies via the runner script.** The extractor reads
   results; it does not solve. If a study is unsolved, solve it **inside
   SolidWorks** first — the explicit-selection path will refuse it otherwise.
6. **Do not accept approximate visualization as a normal FEA GLB.** If FE
   connectivity is unavailable, the run must fail clearly instead of writing a
   CAD-tessellated heatmap into canonical staging.
7. **Do not edit the generated artifacts.** If something looks wrong, leave
   it as-is and report. Hand-editing destroys provenance.
8. **Do not copy `SolidWorksExtractor.exe` out of the repo.** Always run it
   from `bin/Debug/`. The runner script enforces this.
9. **Do not rebuild in Release** unless explicitly told to. The repo is on
   Debug builds for everyone today.
10. **Do not commit anything from `bin/`, `obj/`, `.vs/`, or other build
   output.** `git status -s` should show only `incoming_fea/...` paths
   before you commit.
11. **Do not run `--batch-parts` on a folder of parts in this stage.** FEA
   batching is out of scope; the runner script + extractor are designed for
   one part / one study per invocation.

---

## 6. Filename + manifest contract (cheat sheet)

For one extraction run, the staging directory contains exactly:

```
incoming_fea\<part-slug>\<study-slug>\
  <PartNumber>.json                                — standard part data
  <PartNumber>_fea_<study-slug>.glb                — stress-coloured surface mesh + morph target
  <PartNumber>_fea_<study-slug>_results.json       — schema v2 results
  <PartNumber>_fea_<study-slug>_manifest.json      — provenance manifest
```

No view PNGs or approximate visualization artifacts are allowed in this
canonical directory.

Manifest top-level fields (manifest_version `"1"`):

- `timestamp_utc`, `extractor_version`, `extractor_git_commit`, `solidworks_version`
- `source.document_path`, `source.part_number`
- `study.name`, `study.slug`, `study.index`, `study.type`, `study.selection_mode`
- `outputs[]` — list of generated filenames in this directory
- `visualization.{mode, approximate}` — must report a solver-backed FE mesh
  with `approximate: false` for a normal mergeable worker run
- `summary.{max_von_mises_mpa, max_displacement_mm, safety_factor, yield_strength_mpa, material, surface_node_count, element_count, has_morph_target}`
- `warnings[]` — any non-fatal extraction warnings collected during the run

Results JSON top-level fields (schema_version `"2"`):

- v1 compat: `study_name`, `study_type`, `units`, `summary`, `has_morph_target`
- v2 expansion: `study`, `units_detail`, `material`, `mesh`, `loads[]`, `fixtures[]`, `results`, `warnings[]`

If a field is `null` in the JSON, it means the COSMOSWorks API did not
expose that value during this run — never invented or guessed.

---

## 7. Troubleshooting

- **"Extractor not built"** — Step 2 not done. Run MSBuild.
- **"Simulation add-in NOT available"** — License or add-in not active.
  Open SolidWorks → Tools → Add-Ins → enable "SolidWorks Simulation".
  Confirm a Simulation license is checked out (Tools → License).
- **"No study named 'X' was found"** — The exact name (case-insensitive)
  did not match any study. Run `-ListStudies` to see the canonical names.
- **"Study 'X' rejected: analysis type is 'frequency' (need 'static')"** —
  You picked a non-static study; explicit selection is static-only by
  design. Pick the right study or accept that it cannot be extracted.
- **"Study 'X' rejected: no results available — study has not been solved"** —
  Solve the study **inside SolidWorks** first.
- **`extractor_git_commit` is null in manifest** — git not on PATH on the
  worker. Install Git for Windows and rerun.
- **Filenames have unexpected slugs** — Check the SolidWorks study name.
  The slug is `MakeStudySlug(study.Name)`: lowercase ASCII alphanumerics,
  hyphens preserved, everything else becomes `_`, runs collapsed,
  64-char cap, fallback `study_<index>` for empty.
- **Runner exits with code 3** — Canonical directory `incoming_fea\<part-slug>\<study-slug>\`
  already exists and contains artifacts from a prior run. Either remove that
  directory and re-run, or pass `-Force` if you intentionally want to overwrite
  prior provenance. The newly extracted artifacts are left in
  `incoming_fea\.staging\<part>-<timestamp>\` for inspection.
- **`incoming_fea\.staging\` is non-empty in the steady state** — A prior
  extraction failed or was interrupted before relocation. Inspect the
  contents, then delete the orphan staging dir before re-running.

---

## 8. What "done" looks like for a single run

After Step G:

- A new branch `fea-worker-run-YYYYMMDD` exists on origin.
- That branch has exactly one commit, touching only files under
  `incoming_fea/<part-slug>/<study-slug>/`.
- The reviewer on the source-of-truth computer can:
  - check out the branch,
  - read the manifest,
  - cross-reference `solidworks_version` + `extractor_git_commit`,
  - confirm `study.selection_mode` is `explicit-name` (not `implicit`),
  - look at the results JSON values against the SolidWorks Simulation
    report you ran on,
  - decide whether to merge the branch and surface the artifacts to the app.
