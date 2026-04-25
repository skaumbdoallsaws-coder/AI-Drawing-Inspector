# incoming_fea/

This directory is the **staging area for FEA artifacts produced on the
SolidWorks 2024 SP5 worker computer** and committed back through git.

Nothing in this directory is consumed by the live application yet (Stage 4 of
the extractor hardening pass is extractor + handoff only). The artifacts here
are reviewed manually before any UI/backend integration.

## Layout

```
incoming_fea/
  <part-slug>/
    <study-slug>/
      <PartNumber>.json                          — Standard part-data extraction (created alongside FEA)
      <PartNumber>_fea_<study-slug>.glb          — Stress-coloured surface mesh + morph target
      <PartNumber>_fea_<study-slug>_results.json
      <PartNumber>_fea_<study-slug>_manifest.json
  .staging/                                       — Transient temp directory used by the runner
                                                    script. Empty in the steady state. Anything
                                                    here is the residue of an extraction that
                                                    failed before relocation; investigate, don't commit.
```

`<part-slug>` is a sanitised version of the `--part-number` you supplied to the
runner script (lowercase, ASCII alphanumerics + hyphens, runs of `_` collapsed).

`<study-slug>` is the deterministic slug derived by `MakeStudySlug()` in the
extractor from the SolidWorks study name (e.g. `"Static 1"` → `static_1`).

**Every successful run lands in this canonical layout regardless of how the
study was selected** — `-StudyName`, `-StudyIndex`, and `-AllowImplicit` all
end up in `<part-slug>/<study-slug>/` because the runner extracts into
`.staging/` first, reads the manifest to discover the actual slug, then
moves the artifacts into place. There is no `by_index_<n>/` or
`by_implicit_selection/` placeholder in the final layout.

A re-run of the same `(part, study)` pair refuses to overwrite the existing
directory unless the worker passes `-Force`. This prevents accidental re-runs
from quietly destroying earlier provenance.

## Workflow

The full worker workflow lives in
`SolidWorksExtractor/FEA_WORKER_README.md`. In short:

1. On the worker machine, run `scripts/run_fea_extract.ps1` with
   `-StudyName "<exact study name>"` (preferred) or `-StudyIndex <n>`.
2. The script writes the four files into the directory above.
3. The worker commits the new directory (no source edits) to a branch named
   `fea-worker-run-<YYYYMMDD>` and pushes.
4. On the source-of-truth computer, the artifacts are reviewed against the
   manifest before any downstream consumption.

## Reviewer-side validation (source-of-truth computer)

Before merging a `fea-worker-run-*` branch, run the validator on the canonical
directory the worker committed. It checks the four-file contract, the
manifest + results-JSON schema, filename / slug consistency, manifest-vs-
results numeric agreement, and (optionally) compares the extracted values
against an expected-values reference derived from the SolidWorks report.

```powershell
# Required: validate the four-file contract + schema
.\scripts\validate_fea_run.ps1 -Directory incoming_fea\<part-slug>\<study-slug>

# Optional: also compare against expected report values
.\scripts\validate_fea_run.ps1 `
    -Directory incoming_fea\<part-slug>\<study-slug> `
    -ExpectedReport scripts\expected_fea_mounting_plate.json
```

Exit codes: `0` = passed (warnings allowed), `1` = at least one failure
(do not merge), `2` = directory or manifest missing, `3` = bad CLI args.

The validator does not touch the running app and does not regenerate
artifacts; it is read-only audit.

## What NOT to commit here

- Anything outside the slug layout above.
- Original `.SLDPRT` / `.SLDDRW` source files. The manifest captures the
  source path; the file itself stays in its CAD library.
- Hand-edited results JSON. If an extracted file is wrong, fix the extractor
  on the source-of-truth computer instead.
- Files larger than git's comfortable transport limit. If your FEA GLB is
  many MB and you ship many runs per day, switch artifact transport to a
  shared folder or zipped release assets and keep git for code + manifests
  only (see the closing note in the Stage 4 spec).
