# GIT PUSH PLAN -- YOLO-OBB Pipeline (M0-M12)

**Repository:** https://github.com/skaumbdoallsaws-coder/AI-Drawing-Inspector.git
**Branch:** main
**Date:** 2026-02-03
**Status:** NOT YET COMMITTED -- This is the staging plan.

---

## 1. Files to Stage

All files below were verified to exist on disk via `git status` and filesystem scan.

### Modified (tracked) files -- 8 files, +496/-110 lines

| File | Lines Changed | Description |
|------|--------------|-------------|
| `.gitignore` | +17 | Add ignores for tests/, debug/, onnx, sw_json_library/, datasets/ |
| `ai_inspector/comparison/diff_result.py` | +8/-0 | M10 - Add YOLO-aware diff fields |
| `ai_inspector/comparison/matcher.py` | +133 | M10 - Matcher upgrades for callout packets |
| `ai_inspector/comparison/sw_extractor.py` | +15 | Minor updates for pipeline compat |
| `ai_inspector/config.py` | +17 | M0 - Add YOLO pipeline configuration keys |
| `ai_inspector/extractors/__init__.py` | +30 | Expose new extractor modules |
| `ai_inspector/extractors/patterns.py` | +383/-110 | M5 - Major regex parser rewrite for GD&T callouts |
| `ai_inspector/pipeline/__init__.py` | +3 | Expose yolo_pipeline module |

### New (untracked) files to stage -- organized by milestone

**M0 - Scaffold & Contracts:**
- `ai_inspector/contracts.py` (NEW)

**M1 - YOLO Detection:**
- `ai_inspector/detection/__init__.py` (NEW)
- `ai_inspector/detection/classes.py` (NEW)
- `ai_inspector/detection/yolo_detector.py` (NEW)

**M2 - OBB Cropper:**
- `ai_inspector/extractors/cropper.py` (NEW)

**M3 - Rotation Selection:**
- `ai_inspector/extractors/rotation.py` (NEW)

**M4 - OCR Adapter:**
- `ai_inspector/extractors/ocr_adapter.py` (NEW)
- `ai_inspector/extractors/canonicalize.py` (NEW)

**M5 - Regex Parser:**
- `ai_inspector/extractors/crop_reader.py` (NEW)
  (patterns.py is modified, listed above)

**M6 - CalloutPacket:**
- `ai_inspector/schemas/__init__.py` (NEW)
- `ai_inspector/schemas/callout_packet.py` (NEW)
- `ai_inspector/schemas/callout_schema.py` (NEW)

**M7 - Unit Normalizer:**
- `ai_inspector/extractors/unit_normalizer.py` (NEW)

**M8 - Validator:**
- `ai_inspector/extractors/validator.py` (NEW)

**M9 - Quantity Expander:**
- `ai_inspector/comparison/quantity_expander.py` (NEW)

**M10 - Matcher Upgrades:**
  (matcher.py and diff_result.py are modified, listed above)

**M11 - Pipeline Orchestrator:**
- `ai_inspector/pipeline/yolo_pipeline.py` (NEW)

**M12 - Evaluation Harness:**
- `ai_inspector/fine_tuning/__init__.py` (NEW)
- `ai_inspector/fine_tuning/evaluate.py` (NEW)
  Note: `ai_inspector/fine_tuning/data_generator.py` already tracked.

**Infrastructure & Config:**
- `requirements.txt` (NEW -- YOLO-OBB dependencies)
- `datasets/callouts.yaml` (NEW -- placeholder class definitions)
- `claude_plan.md` (NEW -- architecture/milestone plan doc)
- `tests/__init__.py` (NEW -- empty, enables test discovery)
- `tests/README.md` (NEW -- test instructions placeholder)

**GITIGNORE NOTE for `datasets/sidecar_schema.json`:**
The current `.gitignore` has `*.json` which will block this file.
If you want to commit it, you must add an exception to `.gitignore`:
```
!datasets/sidecar_schema.json
```
Currently it contains only `{}` (empty placeholder), so it is low-priority.

---

## 2. Files to NOT Stage (Excluded)

These files/directories appear in `git status` as untracked but must NOT be committed:

| Path | Reason |
|------|--------|
| `400S_Parts_Manual.pdf.pdf` | Large PDF, not source code |
| `400S_Sorted_Library/` | Local data output |
| `400S_Unmatched_Files/` | Local data output |
| `ASME-Y14.5-2018-R2024-Dimensioning-and-Tolerancing.pdf` | Copyrighted ASME standard PDF |
| `Drawing_Analysis_By_Type/` | Local analysis output |
| `PDF VAULT ARCHIVED/` | Large PDF archive |
| `PDF VAULT/` | Large PDF archive |
| `Parts with missing description/` | Local data output |
| `SolidWorksExtractor/` | Separate VBA tool, not part of pipeline |
| `ai_inspector_unified.ipynb` | Dev notebook, not production code |
| `analyze_json_library.py` | One-off analysis script |
| `drawing_samples_batch/` | Local drawing samples |
| `nul` | Empty/junk file (Windows artifact) |
| `old_manual_data/` | Legacy data |
| `old_notebooks/` | Legacy notebooks |
| `old_scripts/` | Legacy scripts |
| `rag_visual_db/` | Local RAG database |
| `sw_json_library.zip` | Large zip archive |
| `test_v4_modules.ipynb` | Dev notebook |
| `vba_extraction_legacy/` | Legacy VBA code |
| `debug/` | Pipeline debug output (already in .gitignore) |
| `__pycache__/` | Python cache (already in .gitignore) |
| `*.pt, *.pth, *.bin` | Model weights (already in .gitignore) |
| `*.onnx` | Model exports (already in .gitignore) |

---

## 3. Suggested Commit Strategy

**Recommendation: Single commit.**

Rationale:
- All 12 milestones (M0-M12) were designed and built together as a unified pipeline.
- The modules have tight inter-dependencies (contracts.py is imported by every module;
  detection feeds into cropper feeds into OCR feeds into packets feeds into matcher).
- Splitting into per-milestone commits would create intermediate states where imports
  fail, which makes `git bisect` less useful, not more.
- The total changeset is ~30 files and ~2000 lines -- large but cohesive.
- This is a greenfield pipeline addition, not a refactor of existing code that needs
  granular history.

Alternative (if reviewer prefers): split into 3 commits:
1. Infrastructure: `.gitignore`, `contracts.py`, `config.py`, `requirements.txt`, `datasets/`
2. Pipeline modules: all M1-M12 new files + modified files
3. Tests: `tests/` folder

But the single commit is cleaner for this case.

---

## 4. Commit Message Draft

```
Add YOLO-OBB callout detection pipeline (M0-M12)

Implement end-to-end pipeline for detecting and reading GD&T callouts
from engineering drawings using YOLO11-OBB oriented bounding boxes.

Pipeline stages:
- M0:  Typed contracts (DetectionResult, CalloutPacket, ReaderResult)
- M1:  YOLODetector wrapper with OBB confidence filtering
- M2:  OBB polygon cropper with affine rotation
- M3:  Rotation selection (0/90/180/270) via OCR confidence scoring
- M4:  OCR adapter supporting EasyOCR, Tesseract, and LightOn
- M5:  Regex-based GD&T parser (tolerances, threads, finishes, GD&T)
- M6:  CalloutPacket schema and lifecycle helpers
- M7:  Unit normalizer (inch/mm canonicalization)
- M8:  Validator with confidence and schema checks
- M9:  Quantity expander (4X -> 4 individual callouts)
- M10: Matcher upgrades for YOLO callout packets
- M11: YOLOPipeline orchestrator (detect -> crop -> read -> match)
- M12: Evaluation harness with CER/WER/IoU metrics

Infrastructure: requirements.txt, .gitignore updates, dataset placeholders.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
```

---

## 5. Push Commands

Run these commands in order from the project root:

```bash
# ---- Step 1: Stage modified tracked files ----
git add .gitignore
git add ai_inspector/config.py
git add ai_inspector/extractors/__init__.py
git add ai_inspector/extractors/patterns.py
git add ai_inspector/pipeline/__init__.py
git add ai_inspector/comparison/diff_result.py
git add ai_inspector/comparison/matcher.py
git add ai_inspector/comparison/sw_extractor.py

# ---- Step 2: Stage new pipeline files (M0-M12) ----
git add ai_inspector/contracts.py
git add ai_inspector/detection/__init__.py
git add ai_inspector/detection/classes.py
git add ai_inspector/detection/yolo_detector.py
git add ai_inspector/extractors/cropper.py
git add ai_inspector/extractors/rotation.py
git add ai_inspector/extractors/ocr_adapter.py
git add ai_inspector/extractors/canonicalize.py
git add ai_inspector/extractors/crop_reader.py
git add ai_inspector/schemas/__init__.py
git add ai_inspector/schemas/callout_packet.py
git add ai_inspector/schemas/callout_schema.py
git add ai_inspector/extractors/unit_normalizer.py
git add ai_inspector/extractors/validator.py
git add ai_inspector/comparison/quantity_expander.py
git add ai_inspector/pipeline/yolo_pipeline.py
git add ai_inspector/fine_tuning/__init__.py
git add ai_inspector/fine_tuning/evaluate.py

# ---- Step 3: Stage infrastructure files ----
git add requirements.txt
git add datasets/callouts.yaml
git add claude_plan.md
git add tests/__init__.py
git add tests/README.md

# ---- Step 4: Verify staging (should show ~27 files) ----
git status

# ---- Step 5: Commit ----
git commit -m "$(cat <<'EOF'
Add YOLO-OBB callout detection pipeline (M0-M12)

Implement end-to-end pipeline for detecting and reading GD&T callouts
from engineering drawings using YOLO11-OBB oriented bounding boxes.

Pipeline stages:
- M0:  Typed contracts (DetectionResult, CalloutPacket, ReaderResult)
- M1:  YOLODetector wrapper with OBB confidence filtering
- M2:  OBB polygon cropper with affine rotation
- M3:  Rotation selection (0/90/180/270) via OCR confidence scoring
- M4:  OCR adapter supporting EasyOCR, Tesseract, and LightOn
- M5:  Regex-based GD&T parser (tolerances, threads, finishes, GD&T)
- M6:  CalloutPacket schema and lifecycle helpers
- M7:  Unit normalizer (inch/mm canonicalization)
- M8:  Validator with confidence and schema checks
- M9:  Quantity expander (4X -> 4 individual callouts)
- M10: Matcher upgrades for YOLO callout packets
- M11: YOLOPipeline orchestrator (detect -> crop -> read -> match)
- M12: Evaluation harness with CER/WER/IoU metrics

Infrastructure: requirements.txt, .gitignore updates, dataset placeholders.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"

# ---- Step 6: Push to GitHub ----
git push origin main

# ---- Step 7: Verify ----
git log --oneline -1
git status
```

---

## 6. Pre-Push Checklist

- [ ] Run `python -c "import ai_inspector"` to verify no import errors
- [ ] Run `python -m pytest tests/ -v` if tests exist
- [ ] Confirm no PDFs, model weights, or large files are staged
- [ ] Confirm `git diff --cached --stat` shows only expected files
- [ ] Confirm `datasets/sidecar_schema.json` is NOT staged (blocked by .gitignore)

---

## 7. File Count Summary

| Category | Count |
|----------|-------|
| Modified tracked files | 8 |
| New pipeline files (M0-M12) | 18 |
| New infrastructure files | 5 |
| **Total files to stage** | **31** |
| Files explicitly excluded | 20+ directories/files |

---

*This plan was generated by analyzing `git status`, `git diff --stat`, and filesystem*
*scan of the ai_inspector/ directory tree.*
