"""
InspectorPro - FastAPI Web Server
Thin wrapper around the SpatialInspector engine for engineering drawing QC inspection.
"""
# Updated: proper HTTP error codes for malformed requests
# Reloaded: ASME prompt improvements (feature #109) - reinstalled package
# Reloaded: Feature #125 - auto-annotation bounding box locations in inspection prompt

import os
import re
import io
import base64
import json
import logging
import math
import shutil
import threading
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai_inspector.spatial import SpatialInspector
from ai_inspector.spatial.profile_validator import validate_all_profiles
from ai_inspector.utils.drawing_map import (
    apply_drawing_map_to_findings,
    load_drawing_map,
    sanitize_part_number,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("inspectorpro")

# Global inspector instance
inspector: SpatialInspector = None

# Scout browser search engine (populated at startup if Playwright available)
search_engine = None  # Optional[BrowserSearchEngine]

# Local STT: faster-whisper (lazy-loaded on first transcription)
_whisper_models: Dict[str, Any] = {}  # device-keyed cache: "cpu" -> model, "cuda" -> model
_whisper_lock = threading.Lock()
_whisper_fallback_count = 0
_whisper_bad_devices: set = set()  # devices that failed at runtime (e.g. "cuda" if cublas missing)


def _resolve_whisper_device() -> str:
    """Resolve the preferred whisper device from env or auto-detection."""
    configured = os.getenv("WHISPER_DEVICE", "auto").lower()
    if configured in ("cpu", "cuda"):
        return configured
    # auto: prefer CUDA only if torch reports it AND it hasn't failed before
    if "cuda" not in _whisper_bad_devices:
        try:
            import torch
            if torch.cuda.is_available():
                return "cuda"
        except ImportError:
            pass
    return "cpu"


def _get_whisper_model(device: str = None):
    """Get or create a whisper model for the given device. Thread-safe, cached per device."""
    if device is None:
        device = _resolve_whisper_device()
    if device in _whisper_models:
        return _whisper_models[device], device
    with _whisper_lock:
        if device in _whisper_models:
            return _whisper_models[device], device
        from faster_whisper import WhisperModel
        model_size = os.getenv("WHISPER_MODEL_SIZE", "base.en")
        compute_type = "float16" if device == "cuda" else "int8"
        logger.info(f"Loading faster-whisper model '{model_size}' on {device} ({compute_type})...")
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        _whisper_models[device] = model
        logger.info(f"faster-whisper model loaded on {device}")
        return model, device


async def _fallback_openai_transcribe(audio_bytes, filename=None):
    global _whisper_fallback_count
    _whisper_fallback_count += 1
    if _whisper_fallback_count == 1:
        logger.warning("Local STT failed — falling back to OpenAI Whisper API")
    elif _whisper_fallback_count == 5:
        logger.error("Local STT has failed 5 times — check faster-whisper installation")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="Local STT failed and no OPENAI_API_KEY for fallback")

    try:
        import openai
        client = openai.OpenAI(api_key=api_key)
        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = filename or "recording.webm"
        transcript = await asyncio.to_thread(
            client.audio.transcriptions.create,
            model="whisper-1", file=audio_file, response_format="text",
        )
        return {"text": transcript.strip()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {str(e)}")


# Assembly reverse-lookup data (populated at startup)
assembly_part_lookup: Dict[str, List[str]] = {}   # part_number -> [assembly_number, ...]
assembly_profiles: Dict[str, dict] = {}            # assembly_number -> loaded JSON dict


def _find_highlight_boxes_path(part_number: str, library_dir: str | Path) -> Optional[Path]:
    """Locate ``{part}_highlight_boxes.json`` in the inspection library."""
    safe_part_number = sanitize_part_number(part_number)
    if not safe_part_number:
        return None

    library_path = Path(library_dir)
    filename = f"{safe_part_number}_highlight_boxes.json"

    direct = library_path / filename
    if direct.exists():
        return direct

    for candidate in (
        library_path / "drawings" / filename,
        library_path / "highlight_boxes" / filename,
    ):
        if candidate.exists():
            return candidate

    return None


def _find_dimension_descriptions_path(part_number: str, library_dir: str | Path) -> Optional[Path]:
    """Locate ``{part}_dimension_descriptions.json`` in the inspection library."""
    safe_part_number = sanitize_part_number(part_number)
    if not safe_part_number:
        return None

    library_path = Path(library_dir)
    filename = f"{safe_part_number}_dimension_descriptions.json"

    direct = library_path / filename
    if direct.exists():
        return direct

    return None


def _ensure_assembly_files():
    """Copy assembly profile and view images into 400S_Sorted_Library/assemblies/ if not already there."""
    assemblies_dir = Path("400S_Sorted_Library/assemblies")
    assemblies_dir.mkdir(parents=True, exist_ok=True)

    # Copy assembly JSON files from project root into assemblies/ dir
    for src in Path(".").glob("*_assembly.json"):
        dest = assemblies_dir / src.name
        if not dest.exists():
            shutil.copy2(str(src), str(dest))
            logger.info(f"Copied {src.name} -> {dest}")

    # Copy assembly view PNGs (e.g. 6000056_view_front.png) from project root
    for src in Path(".").glob("*_view_*.png"):
        # Only copy if the corresponding assembly JSON exists in assemblies/
        # Extract potential assembly number: 6000056_view_front.png -> 6000056
        stem_parts = src.stem.split("_view_")
        if len(stem_parts) == 2:
            assy_num = stem_parts[0]
            assy_json = assemblies_dir / f"{assy_num}_assembly.json"
            if assy_json.exists():
                dest = assemblies_dir / src.name
                if not dest.exists():
                    shutil.copy2(str(src), str(dest))
                    logger.info(f"Copied {src.name} -> {dest}")

    # Copy colored GLB files (e.g. 6000056_colored.glb) from project root
    for src in Path(".").glob("*_colored.glb"):
        dest = assemblies_dir / src.name
        if not dest.exists():
            shutil.copy2(str(src), str(dest))
            logger.info(f"Copied {src.name} -> {dest}")


def _load_assembly_profiles():
    """Scan assemblies/ dir for *_assembly.json, build reverse-lookup maps."""
    global assembly_part_lookup, assembly_profiles

    assemblies_dir = Path("400S_Sorted_Library/assemblies")
    if not assemblies_dir.exists():
        logger.info("No assemblies/ directory found, skipping assembly profile loading.")
        return

    assembly_files = sorted(assemblies_dir.glob("*_assembly.json"))
    if not assembly_files:
        logger.info("No assembly profiles found in assemblies/ directory.")
        return

    total_mappings = 0
    for assy_file in assembly_files:
        # Extract assembly number from filename: 6000056_assembly.json -> 6000056
        assy_number = assy_file.stem.replace("_assembly", "")
        try:
            with open(assy_file, "r", encoding="utf-8-sig") as f:
                assy_data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load assembly profile {assy_file.name}: {e}")
            continue

        assembly_profiles[assy_number] = assy_data

        # Build reverse lookup: part_number -> [assembly_number, ...]
        components = assy_data.get("components", [])
        seen_parts = set()
        for comp in components:
            # Only include Part components, skip Assembly type
            if comp.get("type") != "Part":
                continue

            # Extract part number from referencedFileName by stripping extension
            ref_file = comp.get("referencedFileName", "")
            if ref_file:
                # e.g. "038-892.SLDPRT" -> "038-892", "023-346_1.SLDPRT" -> "023-346"
                part_num = Path(ref_file).stem
                # Strip SolidWorks configuration suffixes like _1, _2 from filename
                part_num = re.sub(r'_\d+$', '', part_num)
            else:
                # Fallback: extract from component name by stripping instance suffix (-1, -2)
                part_num = re.sub(r'-\d+$', '', comp.get("name", ""))

            if part_num and part_num not in seen_parts:
                seen_parts.add(part_num)
                if part_num not in assembly_part_lookup:
                    assembly_part_lookup[part_num] = []
                if assy_number not in assembly_part_lookup[part_num]:
                    assembly_part_lookup[part_num].append(assy_number)
                    total_mappings += 1

        # Also index by new part numbers from partDataCache
        # Prefer customProperties.PartNo (stable) over identity.partNumber
        part_data_cache = assy_data.get("partDataCache", {})
        for old_key, part_data in part_data_cache.items():
            ident = part_data.get("identity") or {}
            new_pn = ((ident.get("customProperties") or {}).get("PartNo", "")).strip()
            if not new_pn:
                new_pn = (ident.get("partNumber") or "").strip()
            if new_pn and new_pn not in seen_parts:
                seen_parts.add(new_pn)
                if new_pn not in assembly_part_lookup:
                    assembly_part_lookup[new_pn] = []
                if assy_number not in assembly_part_lookup[new_pn]:
                    assembly_part_lookup[new_pn].append(assy_number)
                    total_mappings += 1

    logger.info(f"Loaded {len(assembly_profiles)} assembly profile(s), {total_mappings} part-to-assembly mappings")


def _component_matches_aliases(component_name: str, aliases: set) -> bool:
    """Check if a componentName matches any alias using exact prefix matching.

    ComponentName format is '{part_number}-{instance}' or '{part}_{config}-{instance}'.
    Substring matching would false-positive: alias '101' would match '1015001-1'.
    Instead, strip the trailing instance suffix and check for exact match.
    """
    # Strip instance suffix: '1015003-1' -> '1015003', '022-807_2-1' -> '022-807_2'
    base = re.sub(r'-\d+$', '', component_name)
    if base in aliases:
        return True
    # Also strip config suffix: '022-807_2' -> '022-807'
    base_no_config = re.sub(r'_\d+$', '', base)
    return base_no_config in aliases


MAX_MATE_LINES = 20  # Cap mate lines to prevent context size explosion


def _compute_nearby_parts(available_parts: list, selected_pns: set, max_neighbors: int = 5) -> dict:
    """Compute nearest parts using minimum distance across all instances."""
    # Build instance map: pn -> list of [x,y,z]
    instance_map = {}
    desc_map = {}
    for ap in available_parts:
        pn = ap.get("part_number", "")
        c = ap.get("centroid_mm")
        if pn and c:
            instance_map[pn] = c  # already a list of [x,y,z] arrays
            desc_map[pn] = ap.get("description", "")

    result = {}
    for sel_pn in selected_pns:
        if sel_pn not in instance_map:
            continue
        sel_positions = instance_map[sel_pn]
        distances = []
        for pn, positions in instance_map.items():
            if pn == sel_pn:
                continue
            # Min distance across all instance pairs (closest instance wins)
            min_d = float('inf')
            for sp in sel_positions:
                for tp in positions:
                    d = math.sqrt((sp[0]-tp[0])**2 + (sp[1]-tp[1])**2 + (sp[2]-tp[2])**2)
                    if d < min_d:
                        min_d = d
            distances.append({
                "part_number": pn,
                "description": desc_map.get(pn, ""),
                "distance_mm": round(min_d, 1),
                "instances": len(positions)
            })
        distances.sort(key=lambda x: x["distance_mm"])
        result[sel_pn] = distances[:max_neighbors]
    return result


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize SpatialInspector and optional Playwright browser on startup."""
    global inspector, search_engine
    logger.info("Initializing SpatialInspector with library_dir='400S_Sorted_Library'...")
    inspector = SpatialInspector(library_dir="400S_Sorted_Library")
    logger.info("SpatialInspector initialized successfully.")

    # Copy assembly files into library and build reverse-lookup maps
    try:
        _ensure_assembly_files()
        _load_assembly_profiles()
        logger.info(f"Assembly lookup contains {len(assembly_part_lookup)} part numbers across {len(assembly_profiles)} assemblies")
    except Exception as e:
        logger.error(f"Failed to load assembly profiles: {e}", exc_info=True)

    # Start Playwright browser engine for Scout web search (optional)
    try:
        from ai_inspector.search.browser_engine import BrowserSearchEngine
        search_engine = BrowserSearchEngine()
        await search_engine.start()
        logger.info("Scout browser search engine started")
    except Exception as e:
        logger.warning(f"Scout browser search engine unavailable: {e}")
        search_engine = None

    yield

    # Shutdown
    if search_engine:
        await search_engine.stop()
    logger.info("Shutting down InspectorPro server.")


app = FastAPI(
    title="InspectorPro",
    description="Engineering drawing quality inspection API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- API Endpoints ----------


@app.get("/api/profiles")
async def list_profiles():
    """Return list of all available inspection profiles."""
    try:
        profiles = inspector.list_profiles()
        return profiles
    except FileNotFoundError as e:
        logger.error(f"Library directory not found: {e}")
        raise HTTPException(status_code=500, detail="Inspection library not available")
    except Exception as e:
        logger.error(f"Error listing profiles: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/detect-pn")
async def detect_part_number(filename: str = Query(..., description="Filename to detect part number from")):
    """Auto-detect part number from a filename."""
    try:
        result = inspector.detect_part_number(filename)
        return result
    except ValueError as e:
        logger.warning(f"Invalid filename for detection: '{filename}': {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error detecting part number from '{filename}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/reference-views/{part_number}")
async def get_reference_views(part_number: str):
    """Return base64-encoded CAD reference view images for a part number."""
    try:
        views = inspector.get_reference_views(part_number)
        return views
    except FileNotFoundError as e:
        logger.warning(f"No reference views for '{part_number}': {e}")
        raise HTTPException(status_code=404, detail=f"No reference views found for part number '{part_number}'")
    except ValueError as e:
        logger.warning(f"Invalid part number for reference views: '{part_number}': {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting reference views for '{part_number}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/drawing-map/{part_number}")
async def get_drawing_map(part_number: str):
    """Return a normalized drawing map for a part number."""
    safe_pn = sanitize_part_number(part_number)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")

    try:
        drawing_map = load_drawing_map(safe_pn, "400S_Sorted_Library")
        if drawing_map is None:
            raise HTTPException(
                status_code=404,
                detail=f"No drawing map found for part number '{safe_pn}'",
            )
        return drawing_map
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting drawing map for '{safe_pn}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/inspect")
async def run_inspection(
    file: UploadFile = File(...),
    part_number: str = Form(...),
    send_reference_views: bool = Form(True),
):
    """Run a full inspection on an uploaded drawing."""
    # Validate part_number is not empty or whitespace
    if not part_number or not part_number.strip():
        raise HTTPException(status_code=422, detail="part_number is required and cannot be empty")

    try:
        drawing_bytes = await file.read()
        filename = file.filename or "unknown"

        # Validate file is not empty
        if len(drawing_bytes) == 0:
            raise HTTPException(status_code=422, detail="Uploaded file is empty")

        logger.info(f"Running inspection: part={part_number}, file={filename}, ref_views={send_reference_views}")

        result = inspector.inspect(
            drawing_bytes=drawing_bytes,
            filename=filename,
            part_number=part_number,
            send_reference_views=send_reference_views,
        )

        logger.info(f"Inspection complete for {part_number}: {result.get('gap_summary', {}).get('completeness', 'N/A')}")

        resolved_part_number = result.get("part_number") or part_number
        drawing_map = load_drawing_map(resolved_part_number, "400S_Sorted_Library")
        enriched_features, drawing_map_metadata = apply_drawing_map_to_findings(
            result.get("features", []),
            drawing_map,
        )

        result["features"] = enriched_features
        result["drawing_map"] = drawing_map
        result["drawing_map_metadata"] = drawing_map_metadata

        # Load VLM highlight boxes if cached
        hl_path = _find_highlight_boxes_path(resolved_part_number, "400S_Sorted_Library")
        logger.info(
            "Highlight boxes lookup: part=%r sanitized=%r path=%s",
            resolved_part_number,
            sanitize_part_number(resolved_part_number),
            str(hl_path) if hl_path else None,
        )
        if hl_path is not None:
            try:
                with open(hl_path, "r", encoding="utf-8-sig") as hf:
                    result["highlight_boxes"] = json.load(hf)
                logger.info(f"Loaded highlight boxes for {resolved_part_number} from {hl_path}")
            except Exception as e:
                logger.warning(f"Failed to load highlight boxes: {e}")
        else:
            logger.info(f"No cached highlight boxes found for {resolved_part_number}")

        # Load dimension descriptions if available
        dd_path = _find_dimension_descriptions_path(resolved_part_number, "400S_Sorted_Library")
        if dd_path is not None:
            try:
                with open(dd_path, "r", encoding="utf-8-sig") as df:
                    result["dimension_descriptions"] = json.load(df)
                logger.info(f"Loaded dimension descriptions for {resolved_part_number}")
            except Exception as e:
                logger.warning(f"Failed to load dimension descriptions: {e}")

        # ── Load part JSON once (shared by sketch + hybrid comparison) ──
        part_json = None
        part_json_path = Path("400S_Sorted_Library") / f"{sanitize_part_number(resolved_part_number)}.json"
        if part_json_path.exists():
            try:
                with open(part_json_path, "r", encoding="utf-8-sig") as pf:
                    part_json = json.load(pf)
            except Exception as e:
                logger.warning(f"Failed to load part JSON: {e}")

        # ── Legacy sketch comparison (unchanged) ──
        if drawing_map and part_json and part_json.get("sketches"):
            try:
                from ai_inspector.comparison.sketch_dimension_matcher import compare_sketch_dims
                sketch_comp = compare_sketch_dims(part_json, drawing_map)
                logger.info(
                    "Sketch dim comparison: %d dims, %d strong, %d weak, %d mismatch, %d unmatched",
                    sketch_comp["totalSketchDims"],
                    sketch_comp["matchedStrong"],
                    sketch_comp["matchedWeak"],
                    sketch_comp["valueMismatch"],
                    sketch_comp["unmatched"],
                )
                result["sketchDimComparison"] = sketch_comp
            except Exception as e:
                logger.warning(f"Sketch dim comparison failed: {e}")

        # ── Hybrid comparison: expected (drawing_map) vs observed (uploaded file) ──
        logger.info("HYBRID BLOCK: drawing_map=%s, drawing_bytes=%d bytes", bool(drawing_map), len(drawing_bytes) if drawing_bytes else 0)
        if drawing_map:
            try:
                from ai_inspector.comparison.observed_extractor import extract_observed_dimensions
                from ai_inspector.comparison.expected_builder import build_expected_registry
                from ai_inspector.comparison.hungarian_matcher import hungarian_match

                logger.info("HYBRID: imports OK, running observed extractor...")
                observed = extract_observed_dimensions(drawing_bytes, filename, drawing_map)
                logger.info("HYBRID: %d observed dims, running expected builder...", len(observed))
                expected = build_expected_registry(drawing_map, part_json)
                logger.info("HYBRID: %d expected dims, running matcher...", len(expected))
                hybrid = hungarian_match(
                    expected, observed,
                    part_number=resolved_part_number,
                )
                result["hybridDimComparison"] = hybrid.to_dict()
                logger.info(
                    "HYBRID OK: %d exp, %d obs, %d matched, %d missing, %d extra",
                    hybrid.total_expected, hybrid.total_observed,
                    hybrid.matched, hybrid.missing, hybrid.extra,
                )
            except Exception as e:
                import traceback
                logger.error(f"HYBRID FAILED: {e}\n{traceback.format_exc()}")

        if isinstance(result.get("findings"), dict):
            result["findings"]["features"] = enriched_features

        # Resolve ASME references for inspection findings
        asme_findings = []
        seen_ft = set()
        for feature in result.get("features", []):
            refs = _resolve_asme_refs_for_finding(feature)
            for ref in refs:
                if ref["feature_type"] not in seen_ft:
                    seen_ft.add(ref["feature_type"])
                    asme_findings.append({"finding_name": feature.get("name", ""), **ref})
        if asme_findings:
            result["asme_checklist_findings"] = asme_findings

        return result
    except HTTPException:
        raise  # Re-raise HTTPExceptions as-is
    except FileNotFoundError as e:
        logger.warning(f"Profile not found for part '{part_number}': {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        logger.warning(f"Invalid input for inspection: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error during inspection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/validate-profiles")
async def validate_profiles():
    """Run the profile validator and return results as JSON."""
    try:
        results = validate_all_profiles("400S_Sorted_Library")
        return results
    except FileNotFoundError as e:
        logger.error(f"Library directory not found for validation: {e}")
        raise HTTPException(status_code=500, detail="Inspection library not available for validation")
    except Exception as e:
        logger.error(f"Error validating profiles: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/profile-details/{part_number}")
async def get_profile_details(part_number: str):
    """Return full inspection profile details for a part number.

    Includes feature names, types, expected counts, and spatial descriptions.
    Used by the Agent to provide pre-inspection context about a part.
    """
    # Sanitize part_number to prevent path traversal
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")

    # Try to find the inspection profile JSON on disk
    library_dir = Path("400S_Sorted_Library")
    profile_path = library_dir / f"{safe_pn}_inspection_profile.json"
    if not profile_path.exists():
        profile_path = library_dir / f"{safe_pn}.json"
    if not profile_path.exists():
        raise HTTPException(status_code=404, detail=f"No profile found for part number '{part_number}'")

    try:
        with open(profile_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)

        # Return a curated subset focused on what the agent needs
        features = []
        for feat in data.get("features", []):
            features.append({
                "name": feat.get("name", ""),
                "type": feat.get("type", ""),
                "count": feat.get("count", 1),
                "spatial_description": feat.get("spatial_description", ""),
            })

        return {
            "part_number": data.get("part_number", safe_pn),
            "part_name": data.get("part_name", ""),
            "part_description": data.get("part_description", ""),
            "features": features,
            "view_expectations": data.get("view_expectations", {}),
        }
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in profile for '{part_number}': {e}")
        raise HTTPException(status_code=500, detail="Invalid profile data")
    except Exception as e:
        logger.error(f"Error reading profile for '{part_number}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/part-properties/{part_number}")
async def get_part_properties(part_number: str):
    """Return physical properties and features from the raw part JSON."""
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")

    library_dir = Path("400S_Sorted_Library")
    json_path = library_dir / f"{safe_pn}.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="Part data not found")

    with open(json_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)

    return {
        "identity": data.get("identity", {}),
        "physical": data.get("physical", {}),
        "features": data.get("features", {}),
    }


@app.get("/api/3d-model/{part_number}")
async def get_3d_model(part_number: str):
    """Serve the raw STL file for a part number, or 404 if not found."""
    # Sanitize part_number to prevent path traversal
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")

    stl_path = Path("400S_Sorted_Library") / f"{safe_pn}.stl"
    # Fallback: check parts/{pn}/revA/ for revision-stored STL
    if not stl_path.exists():
        rev_stl = Path("400S_Sorted_Library/parts") / safe_pn / "revA" / f"{safe_pn}.stl"
        logger.info(f"[3D Model] Root STL not found, checking revision path: {rev_stl} exists={rev_stl.exists()}")
        if rev_stl.exists():
            stl_path = rev_stl
    if not stl_path.exists():
        logger.warning(f"[3D Model] No STL found for {safe_pn}")
        raise HTTPException(status_code=404, detail=f"No 3D model found for part number '{part_number}'")

    return FileResponse(
        path=str(stl_path),
        media_type="application/octet-stream",
        filename=f"{safe_pn}.stl",
    )


@app.get("/api/part-glb/{part_number}")
async def get_part_glb(part_number: str):
    """Serve the per-feature colored GLB for a part, or 404 if not available."""
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")

    # For revisioned parts, prefer parts/{pn}/revA/ to avoid stale root-level assets
    rev_path = Path("400S_Sorted_Library/parts") / safe_pn / "revA" / f"{safe_pn}_colored.glb"
    root_path = Path("400S_Sorted_Library") / f"{safe_pn}_colored.glb"
    glb_path = rev_path if rev_path.exists() else root_path
    if not glb_path.exists():
        raise HTTPException(status_code=404, detail=f"No feature-colored GLB for part '{part_number}'")

    return FileResponse(
        path=str(glb_path),
        media_type="model/gltf-binary",
        filename=f"{safe_pn}_colored.glb",
    )


@app.get("/api/part-features/{part_number}")
async def get_part_features(part_number: str):
    """Serve the feature color map JSON for a part, or 404 if not available."""
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")

    # For revisioned parts, prefer parts/{pn}/revA/ to avoid stale root-level assets
    rev_json = Path("400S_Sorted_Library/parts") / safe_pn / "revA" / f"{safe_pn}_feature_colors.json"
    root_json = Path("400S_Sorted_Library") / f"{safe_pn}_feature_colors.json"
    json_path = rev_json if rev_json.exists() else root_json
    if not json_path.exists():
        raise HTTPException(status_code=404, detail=f"No feature color data for part '{part_number}'")

    with open(json_path, "r", encoding="utf-8-sig") as f:
        data = json.load(f)
    return data


@app.get("/api/part-revisions/{part_number}")
async def get_part_revisions(part_number: str):
    """List available revisions for a part."""
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")

    parts_dir = Path("400S_Sorted_Library/parts") / safe_pn
    if not parts_dir.exists() or not parts_dir.is_dir():
        return {"revisions": [], "part_number": safe_pn}

    revisions = sorted([
        d.name[3:]  # strip "rev" prefix
        for d in parts_dir.iterdir()
        if d.is_dir() and d.name.lower().startswith("rev")
    ])
    return {"revisions": revisions, "part_number": safe_pn}


@app.get("/api/part-glb-rev/{part_number}")
async def get_part_glb_revision(part_number: str, revision: str = Query(...)):
    """Serve a specific revision of the per-feature colored GLB for a part."""
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    safe_rev = re.sub(r'[^\w]', '', revision)
    if not safe_pn or not safe_rev:
        raise HTTPException(status_code=400, detail="Invalid part number or revision")

    glb_path = Path("400S_Sorted_Library/parts") / safe_pn / f"rev{safe_rev}" / f"{safe_pn}_colored.glb"
    if not glb_path.exists():
        # Fallback: serve STL if GLB not available
        stl_path = Path("400S_Sorted_Library/parts") / safe_pn / f"rev{safe_rev}" / f"{safe_pn}.stl"
        if stl_path.exists():
            return FileResponse(stl_path, media_type="model/stl")
        raise HTTPException(status_code=404, detail=f"No GLB or STL for part '{part_number}' revision '{revision}'")

    return FileResponse(path=str(glb_path), media_type="model/gltf-binary", filename=f"{safe_pn}_colored.glb")


@app.get("/api/part-feature-diff/{part_number}")
async def get_part_feature_diff(part_number: str, revA: str = Query(...), revB: str = Query(...)):
    """Compare features between two part revisions."""
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    safe_a = re.sub(r'[^\w]', '', revA)
    safe_b = re.sub(r'[^\w]', '', revB)

    base_dir = Path("400S_Sorted_Library/parts") / safe_pn
    json_a = base_dir / f"rev{safe_a}" / f"{safe_pn}_feature_colors.json"
    json_b = base_dir / f"rev{safe_b}" / f"{safe_pn}_feature_colors.json"

    if not json_a.exists() or not json_b.exists():
        raise HTTPException(status_code=404, detail="Revision feature data not found")

    with open(json_a, encoding="utf-8-sig") as f:
        features_a = json.load(f).get("features", [])
    with open(json_b, encoding="utf-8-sig") as f:
        features_b = json.load(f).get("features", [])

    # Feature diff: match by cad_feature_id, compare fields
    map_a = {f["cad_feature_id"]: f for f in features_a}
    map_b = {f["cad_feature_id"]: f for f in features_b}
    ids_a = set(map_a.keys())
    ids_b = set(map_b.keys())

    # Helper: compare two feature dicts and return field-level diffs including parameters
    def _compare_feature_fields(fa, fb):
        diffs = {}
        for field in ["face_count", "display_label", "type", "sw_name"]:
            if fa.get(field) != fb.get(field):
                diffs[field] = {"old": fa.get(field), "new": fb.get(field)}
        # Compare parameters dict (dimensional values for diff detection)
        params_a = fa.get("parameters", {})
        params_b = fb.get("parameters", {})
        if params_a or params_b:
            _LENGTH_TOL = 0.01   # mm
            _ANGLE_TOL = 0.1     # degrees
            _BOOL_FIELDS = {"is_through"}
            param_diffs = {}
            all_param_keys = set(list(params_a.keys()) + list(params_b.keys()))
            for pk in all_param_keys:
                va = params_a.get(pk)
                vb = params_b.get(pk)
                if va == vb:
                    continue
                if pk in _BOOL_FIELDS:
                    param_diffs[pk] = {"old": va, "new": vb}
                elif isinstance(va, (int, float)) and isinstance(vb, (int, float)):
                    tol = _ANGLE_TOL if ("angle" in pk or "deg" in pk) else _LENGTH_TOL
                    if abs(va - vb) >= tol:
                        param_diffs[pk] = {"old": va, "new": vb}
                else:
                    param_diffs[pk] = {"old": va, "new": vb}
            if param_diffs:
                diffs["parameters"] = param_diffs
        return diffs

    changed = {}
    for fid in ids_a & ids_b:
        fa = map_a[fid]
        fb = map_b[fid]
        diffs = _compare_feature_fields(fa, fb)
        if diffs:
            changed[fid] = {
                "display_label_a": fa.get("display_label", ""),
                "display_label_b": fb.get("display_label", ""),
                "color_name": fb.get("color_name", ""),
                "changes": diffs,
            }

    # Stage 2: Match unmatched features by type + subtype similarity
    # Codex review fixes: (1) canonical subtypes, (2) size-aware similarity,
    # (3) global best-match instead of greedy, (4) empty subtypes handled
    unmatched_a = {fid: map_a[fid] for fid in ids_a - ids_b}
    unmatched_b = {fid: map_b[fid] for fid in ids_b - ids_a}

    modified = {}
    matched_a = set()
    matched_b = set()

    # --- Helpers ---
    _SUBTYPE_SYNONYMS = {
        "cbore": "counterbore", "counterbore": "counterbore",
        "csk": "countersink", "countersink": "countersink",
        "tapped": "tapped", "clearance": "clearance",
        "dowel": "dowel", "ream": "ream",
    }

    def _hole_subtype(name: str) -> str:
        """Extract canonical functional subtype from a hole name."""
        name_lower = name.lower()
        for kw, canonical in _SUBTYPE_SYNONYMS.items():
            if kw in name_lower:
                return canonical
        return "_other"

    _SIZE_RE = re.compile(r'[Mm](\d+(?:\.\d+)?)')

    def _extract_size(name: str) -> float:
        """Extract metric size (e.g. M12 → 12.0) from a hole name, or 0."""
        m = _SIZE_RE.search(name)
        return float(m.group(1)) if m else 0.0

    def _feature_similarity(name_a: str, name_b: str) -> float:
        """Size-aware similarity: word overlap penalized by size difference."""
        wa = set(name_a.lower().replace("x", " ").split())
        wb = set(name_b.lower().replace("x", " ").split())
        if not wa or not wb:
            return 0.0
        word_score = len(wa & wb) / max(len(wa), len(wb))
        # Penalize large size differences (M12 vs M3 = 0.25 penalty, M12 vs M10 = 0.83 penalty)
        sa, sb = _extract_size(name_a), _extract_size(name_b)
        if sa > 0 and sb > 0:
            size_ratio = min(sa, sb) / max(sa, sb)  # 0..1, higher = more similar
            return word_score * (0.3 + 0.7 * size_ratio)  # size contributes 70% weight
        return word_score

    def _global_best_match(candidates_a, candidates_b, feat_map_a, feat_map_b, threshold):
        """Global best-match: score all pairs, pick highest first (Hungarian-lite)."""
        scored = []
        for fid_a in candidates_a:
            na = feat_map_a[fid_a].get("sw_name", "")
            for fid_b in candidates_b:
                score = _feature_similarity(na, feat_map_b[fid_b].get("sw_name", ""))
                if score >= threshold:
                    scored.append((score, fid_a, fid_b))
        scored.sort(key=lambda x: -x[0])  # highest score first
        used_a, used_b = set(), set()
        pairs = []
        for score, fid_a, fid_b in scored:
            if fid_a in used_a or fid_b in used_b:
                continue
            pairs.append((fid_a, fid_b))
            used_a.add(fid_a)
            used_b.add(fid_b)
        return pairs

    if unmatched_a and unmatched_b:
        # Group unmatched by type
        by_type_a = {}
        for fid, feat in unmatched_a.items():
            ftype = feat.get("type", "")
            by_type_a.setdefault(ftype, []).append(fid)
        by_type_b = {}
        for fid, feat in unmatched_b.items():
            ftype = feat.get("type", "")
            by_type_b.setdefault(ftype, []).append(fid)

        for ftype in set(by_type_a.keys()) & set(by_type_b.keys()):
            list_a = list(by_type_a[ftype])
            list_b = list(by_type_b[ftype])

            if ftype == "holeWizard":
                # Group by canonical subtype
                sub_a = {}
                for fid in list_a:
                    st = _hole_subtype(map_a[fid].get("sw_name", ""))
                    sub_a.setdefault(st, []).append(fid)
                sub_b = {}
                for fid in list_b:
                    st = _hole_subtype(map_b[fid].get("sw_name", ""))
                    sub_b.setdefault(st, []).append(fid)

                for subtype in set(sub_a.keys()) & set(sub_b.keys()):
                    # Global best-match within subtype (0.5 threshold — size-aware)
                    pairs = _global_best_match(sub_a[subtype], sub_b[subtype], map_a, map_b, 0.5)
                    for fid_a, fid_b in pairs:
                        fa, fb = map_a[fid_a], map_b[fid_b]
                        diffs = _compare_feature_fields(fa, fb)
                        if not diffs:
                            diffs["cad_feature_id"] = {"old": fid_a, "new": fid_b}
                        modified[f"mod_{fid_a}"] = {
                            "revA_id": fid_a, "revB_id": fid_b, "type": ftype,
                            "display_label_a": fa.get("display_label", fid_a),
                            "display_label_b": fb.get("display_label", fid_b),
                            "color_name_a": fa.get("color_name", ""),
                            "color_name_b": fb.get("color_name", ""),
                            "changes": diffs,
                        }
                        matched_a.add(fid_a)
                        matched_b.add(fid_b)
            else:
                # Non-hole features: global best-match by name similarity
                pairs = _global_best_match(list_a, list_b, map_a, map_b, 0.5)
                for fid_a, fid_b in pairs:
                    fa, fb = map_a[fid_a], map_b[fid_b]
                    diffs = _compare_feature_fields(fa, fb)
                    if not diffs:
                        diffs["cad_feature_id"] = {"old": fid_a, "new": fid_b}
                    modified[f"mod_{fid_a}"] = {
                        "revA_id": fid_a, "revB_id": fid_b, "type": ftype,
                        "display_label_a": fa.get("display_label", fid_a),
                        "display_label_b": fb.get("display_label", fid_b),
                        "color_name_a": fa.get("color_name", ""),
                        "color_name_b": fb.get("color_name", ""),
                        "changes": diffs,
                    }
                    matched_a.add(fid_a)
                    matched_b.add(fid_b)

    # Remaining truly unmatched
    added = [{"cad_feature_id": fid, "display_label": map_b[fid].get("display_label", fid),
              "type": map_b[fid].get("type", ""), "color_name": map_b[fid].get("color_name", "")}
             for fid in unmatched_b if fid not in matched_b]
    removed = [{"cad_feature_id": fid, "display_label": map_a[fid].get("display_label", fid),
                "type": map_a[fid].get("type", ""), "color_name": map_a[fid].get("color_name", "")}
               for fid in unmatched_a if fid not in matched_a]

    summary_parts = []
    if changed: summary_parts.append(f"{len(changed)} feature(s) changed")
    if modified: summary_parts.append(f"{len(modified)} feature(s) modified across revisions")
    if added: summary_parts.append(f"{len(added)} added")
    if removed: summary_parts.append(f"{len(removed)} removed")

    return {
        "part_number": safe_pn,
        "revA": safe_a,
        "revB": safe_b,
        "changed_features": changed,
        "modified_features": modified,
        "added_features": added,
        "removed_features": removed,
        "unchanged_features": sorted(ids_a & ids_b - set(changed.keys())),
        "summary": ", ".join(summary_parts) if summary_parts else "No changes detected",
    }


# ---------- Assembly Configuration Generation ----------

def _generate_assembly_configurations(assy_data, part_color_legend):
    """Auto-generate part group presets from assembly hierarchy."""
    configs = []
    components = assy_data.get("components", [])
    pdc = assy_data.get("partDataCache", {})

    # Build partDataKey (old_key) -> part_number lookup from legend
    key_to_pn = {}
    for item in part_color_legend:
        key_to_pn[item["old_key"].lower()] = item["part_number"]
    all_pns = set(key_to_pn.values())
    if len(all_pns) < 2:
        return configs  # No point in configs for single-part assemblies

    # --- 1. Sub-assembly groupings (dedup by referencedFileName, recursive DFS) ---
    subassy_types = {}  # referencedFileName -> display_name
    for comp in components:
        if comp.get("type") == "Assembly" and comp.get("level", 0) >= 1:
            ref = comp.get("referencedFileName", "")
            if ref and ref not in subassy_types:
                subassy_types[ref] = ref.rsplit(".", 1)[0]

    # Build parent -> children adjacency list
    children_of = {}
    for comp in components:
        parent = comp.get("parentName", "")
        if parent:
            children_of.setdefault(parent, []).append(comp)

    def _collect_leaf_parts(comp_name):
        leaf_pdks = set()
        for child in children_of.get(comp_name, []):
            if child.get("type") == "Part":
                pdk = child.get("partDataKey", "")
                if pdk:
                    leaf_pdks.add(pdk.lower())
            elif child.get("type") == "Assembly":
                leaf_pdks |= _collect_leaf_parts(child["name"])
        return leaf_pdks

    for ref, display_name in sorted(subassy_types.items(), key=lambda x: x[1]):
        instance_names = [c["name"] for c in components if c.get("referencedFileName") == ref]
        all_leaf_pdks = set()
        for inst in instance_names:
            all_leaf_pdks |= _collect_leaf_parts(inst)
        parts = sorted({key_to_pn[pdk] for pdk in all_leaf_pdks if pdk in key_to_pn})
        if parts:
            configs.append({"name": display_name, "icon": "layers", "parts": parts})

    # --- 2. Fasteners (strict keywords, no "pin") ---
    fastener_keywords = ["screw", "bolt", "nut", "washer", "rivet", "stud"]
    fastener_pns = set()
    for old_key, pn in key_to_pn.items():
        desc = (pdc.get(old_key, {}).get("identity") or {}).get("description", "").lower()
        desc_tokens = re.split(r'[\s_\-\.,;]+', desc)
        if any(kw in desc_tokens for kw in fastener_keywords):
            fastener_pns.add(pn)
        elif any(kw in re.split(r'[\s_\-\.]+', old_key.lower()) for kw in fastener_keywords):
            fastener_pns.add(pn)

    if fastener_pns and len(fastener_pns) < len(all_pns):
        configs.append({"name": "Fasteners", "icon": "wrench", "parts": sorted(fastener_pns)})

    # --- 3. Internals / Housing (confidence gate, subtract fasteners) ---
    housing_keywords = ["block", "housing", "case", "cover", "enclosure", "shell", "body", "frame"]
    housing_pns = set()
    for comp in components:
        if comp.get("type") != "Part" or comp.get("level", 0) != 1:
            continue
        pdk = comp.get("partDataKey", "")
        pn = key_to_pn.get((pdk or "").lower(), "")
        if not pn:
            continue
        desc = (pdc.get(pdk, {}).get("identity") or {}).get("description", "").lower()
        desc_tokens = re.split(r'[\s_\-\.,;]+', desc)
        if any(kw in desc_tokens for kw in housing_keywords):
            housing_pns.add(pn)

    if housing_pns and len(housing_pns) <= len(all_pns) * 0.5:
        internal_pns = all_pns - housing_pns - fastener_pns
        if internal_pns:
            configs.append({"name": "Internals", "icon": "eye", "parts": sorted(internal_pns)})
        configs.append({"name": "Housing", "icon": "box", "parts": sorted(housing_pns)})

    return configs


# ---------- Kinematic Chain Detection ----------

def _vec3_dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]

def _vec3_cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]

def _vec3_sub(a, b):
    return [a[0]-b[0], a[1]-b[1], a[2]-b[2]]

def _vec3_add(a, b):
    return [a[0]+b[0], a[1]+b[1], a[2]+b[2]]

def _vec3_scale(v, s):
    return [v[0]*s, v[1]*s, v[2]*s]

def _vec3_norm(v):
    return math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)

def _vec3_normalize(v):
    n = _vec3_norm(v)
    return [v[0]/n, v[1]/n, v[2]/n] if n > 1e-12 else [0.0, 0.0, 0.0]

def _mat3_row_vec_mul(R_flat, v):
    """Row-vector multiplication: result = v @ R.  R_flat is row-major [r00,r01,r02,r10,r11,r12,r20,r21,r22]."""
    return [
        v[0]*R_flat[0] + v[1]*R_flat[3] + v[2]*R_flat[6],
        v[0]*R_flat[1] + v[1]*R_flat[4] + v[2]*R_flat[7],
        v[0]*R_flat[2] + v[1]*R_flat[5] + v[2]*R_flat[8],
    ]

def _transform_point(point, R_flat, T):
    """P_world = P_local @ R + T (row-vector convention)."""
    rotated = _mat3_row_vec_mul(R_flat, point)
    return _vec3_add(rotated, T)

def _transform_dir(direction, R_flat):
    """d_world = d_local @ R (row-vector convention, no translation)."""
    return _mat3_row_vec_mul(R_flat, direction)

def _point_to_line_dist(point, line_origin, line_dir):
    """Distance from a point to an infinite line defined by origin + direction."""
    v = _vec3_sub(point, line_origin)
    along = _vec3_dot(v, line_dir)
    perp = _vec3_sub(v, _vec3_scale(line_dir, along))
    return _vec3_norm(perp)


def _build_kinematic_chain(assy_data: dict) -> Optional[dict]:
    """Detect slider-crank mechanism from assembly Concentric mate data.

    Returns kinematic_chain dict if a valid slider-crank topology is found,
    or None if the assembly doesn't contain one.
    """
    components = assy_data.get("components", [])
    mates = assy_data.get("mates", [])

    if not components or not mates:
        return None

    # Build component lookup: name -> component data
    comp_lookup = {c["name"]: c for c in components}

    # Find all Concentric mates
    concentric = [m for m in mates if m.get("type") == "Concentric" and not m.get("isSuppressed")]

    # Step 1: Find crankshaft component (name contains "crank")
    crank_comp = None
    for c in components:
        if c.get("type") == "Part" and "crank" in c.get("name", "").lower():
            crank_comp = c
            break
    if not crank_comp:
        return None

    crank_name = crank_comp["name"]
    ct = crank_comp.get("transform", {})
    crank_R = ct.get("rotation", [1, 0, 0, 0, 1, 0, 0, 0, 1])
    crank_T = ct.get("translation", [0, 0, 0])

    # Step 2: Classify crankshaft Concentric mates into bearing vs crank-pin
    housing_kw = ["block", "housing", "case", "frame", "body"]
    bearing_mates = []   # crankshaft-to-housing (small radius ~0.016)
    pin_mates = []       # crankshaft-to-rod (large radius ~0.027)

    for mate in concentric:
        e1, e2 = mate.get("entity1", {}), mate.get("entity2", {})
        e1n, e2n = e1.get("componentName", ""), e2.get("componentName", "")

        if crank_name not in (e1n, e2n):
            continue

        crank_e = e1 if e1n == crank_name else e2
        other_e = e2 if e1n == crank_name else e1
        other_n = other_e.get("componentName", "").lower()

        if any(kw in other_n for kw in housing_kw) or \
           other_e.get("componentFileName", "").lower().endswith(".sldasm"):
            bearing_mates.append(crank_e)
        elif "rod" in other_n or "connecting" in other_n:
            if crank_e.get("radius", 0) > 0.02:  # crank pin, not bearing
                pin_mates.append({"crank_e": crank_e, "rod_e": other_e, "rod_name": other_e["componentName"]})

    if not bearing_mates or not pin_mates:
        return None

    # Step 3: Crank axis in world coords (from first bearing mate)
    axis_local = bearing_mates[0].get("direction", [1, 0, 0])
    center_local = bearing_mates[0].get("point", [0, 0, 0])
    axis_world = _vec3_normalize(_transform_dir(axis_local, crank_R))
    center_world = _transform_point(center_local, crank_R, crank_T)

    # Step 4: Build each cylinder's data
    cylinders = []

    for pm in pin_mates:
        rod_name = pm["rod_name"]
        rod_comp = comp_lookup.get(rod_name)
        if not rod_comp:
            continue
        rt = rod_comp.get("transform", {})
        rod_R = rt.get("rotation", [1, 0, 0, 0, 1, 0, 0, 0, 1])
        rod_T = rt.get("translation", [0, 0, 0])

        # Crank pin world position
        pin_local = pm["crank_e"].get("point", [0, 0, 0])
        pin_world = _transform_point(pin_local, crank_R, crank_T)

        # Throw radius = perpendicular distance from pin to crank axis line
        throw_radius = _point_to_line_dist(pin_world, center_world, axis_world)

        # Find rod-to-piston Concentric mate (rod small end, radius ~0.015)
        rod_big_end_local = pm["rod_e"].get("point", [0, 0, 0])
        rod_small_end_local = None
        piston_entity_name = None

        for mate in concentric:
            e1, e2 = mate.get("entity1", {}), mate.get("entity2", {})
            e1n, e2n = e1.get("componentName", ""), e2.get("componentName", "")
            if rod_name == e1n and "piston" in e2n.lower() and e1.get("radius", 0) < 0.02:
                rod_small_end_local = e1.get("point", [0, 0, 0])
                piston_entity_name = e2n
                break
            elif rod_name == e2n and "piston" in e1n.lower() and e2.get("radius", 0) < 0.02:
                rod_small_end_local = e2.get("point", [0, 0, 0])
                piston_entity_name = e1n
                break

        if rod_small_end_local is None or piston_entity_name is None:
            continue

        # Rod length
        rod_length = _vec3_norm(_vec3_sub(rod_big_end_local, rod_small_end_local))

        # Wrist pin world position
        wrist_pin_world = _transform_point(rod_small_end_local, rod_R, rod_T)

        # Cylinder axis: direction from crank axis to wrist pin (perpendicular to crank axis)
        wp_vec = _vec3_sub(wrist_pin_world, center_world)
        wp_along = _vec3_dot(wp_vec, axis_world)
        cyl_axis = _vec3_sub(wp_vec, _vec3_scale(axis_world, wp_along))
        cyl_axis = _vec3_normalize(cyl_axis)

        # Find rod cap
        rod_cap_name = None
        for mate in concentric:
            e1, e2 = mate.get("entity1", {}), mate.get("entity2", {})
            e1n, e2n = e1.get("componentName", ""), e2.get("componentName", "")
            if e1n == rod_name and "cap" in e2n.lower() and e1.get("radius", 0) > 0.02:
                rod_cap_name = e2n
                break
            elif e2n == rod_name and "cap" in e1n.lower() and e2.get("radius", 0) > 0.02:
                rod_cap_name = e1n
                break

        # Collect piston assembly parts (all children of piston sub-assembly)
        piston_instances = [piston_entity_name]
        piston_parent_match = re.match(r'^(.+?-\d+)/', piston_entity_name)
        if piston_parent_match:
            piston_assy_name = piston_parent_match.group(1)
            for c in components:
                if c["name"].startswith(piston_assy_name + "/") and c["name"] != piston_entity_name:
                    piston_instances.append(c["name"])

        # Find piston pin (piston-to-pin Concentric mate)
        # Match "piston pin-N" by checking componentFileName contains "pin"
        piston_pin_name = None
        for mate in concentric:
            e1, e2 = mate.get("entity1", {}), mate.get("entity2", {})
            e1n, e2n = e1.get("componentName", ""), e2.get("componentName", "")
            if piston_entity_name in (e1n, e2n):
                other = e2 if e1n == piston_entity_name else e1
                other_name = other.get("componentName", "")
                other_file = other.get("componentFileName", "").lower()
                if "pin" in other_file and other_name != rod_name:
                    piston_pin_name = other_name
                    break

        if piston_pin_name:
            piston_instances.append(piston_pin_name)

        # Find rod fasteners (screws/bolts mated to the rod or rod cap)
        rod_fastener_instances = []
        fastener_keywords = ["screw", "bolt", "hex", "socket", "washer", "nut", "fastener"]
        for mate in assy_data.get("mates", []):
            e1, e2 = mate.get("entity1", {}), mate.get("entity2", {})
            e1n, e2n = e1.get("componentName", ""), e2.get("componentName", "")
            for rod_comp in [rod_name, rod_cap_name]:
                if rod_comp and rod_comp in (e1n, e2n):
                    other_name = e2n if e1n == rod_comp else e1n
                    if any(kw in other_name.lower() for kw in fastener_keywords):
                        if other_name not in rod_fastener_instances:
                            rod_fastener_instances.append(other_name)

        cylinders.append({
            "crank_pin_world_at_load": [round(v, 6) for v in pin_world],
            "throw_radius": round(throw_radius, 6),
            "rod_instance": rod_name,
            "rod_length": round(rod_length, 6),
            "rod_cap_instance": rod_cap_name,
            "rod_fastener_instances": rod_fastener_instances,
            "piston_instances": piston_instances,
            "piston_pin_instance": piston_pin_name,
            "cylinder_axis_world": [round(v, 6) for v in cyl_axis],
            "wrist_pin_world_at_load": [round(v, 6) for v in wrist_pin_world],
        })

    if not cylinders:
        return None

    # Compute phase angles relative to first cylinder
    ref_cyl_axis = cylinders[0]["cylinder_axis_world"]
    for cyl in cylinders:
        pin_vec = _vec3_sub(cyl["crank_pin_world_at_load"], center_world)
        pin_perp = _vec3_sub(pin_vec, _vec3_scale(axis_world, _vec3_dot(pin_vec, axis_world)))
        cross = _vec3_cross(ref_cyl_axis, pin_perp)
        dot = _vec3_dot(ref_cyl_axis, pin_perp)
        angle_deg = math.degrees(math.atan2(_vec3_dot(cross, axis_world), dot))
        cyl["phase_deg"] = round(angle_deg, 1)

    # Sort by X position of crank pin (front to back along crank axis)
    cylinders.sort(key=lambda c: _vec3_dot(c["crank_pin_world_at_load"], axis_world))

    logger.info(f"Kinematic chain detected: {len(cylinders)} cylinders, "
                f"throw_radius={cylinders[0]['throw_radius']}, rod_length={cylinders[0]['rod_length']}")

    return {
        "type": "slider_crank",
        "crank": {
            "instance": crank_name,
            "axis_world": [round(v, 6) for v in axis_world],
            "center_world": [round(v, 6) for v in center_world],
            "journal_radius": bearing_mates[0].get("radius", 0),
        },
        "cylinders": cylinders,
        "rpm_default": 60,
        "rpm_max": 300,
    }


# ---------- Assembly Context ----------


def _build_part_properties(part_color_legend: list) -> list:
    """Build physical property summaries for assembly parts from individual profile files.

    Loads each part's profile JSON for richer data (holes, features) than partDataCache.
    Returns a compact list for agent semantic search (e.g. "find parts with 30mm holes").
    """
    library_dir = Path("400S_Sorted_Library")
    result = []

    for item in part_color_legend:
        pn = item.get("part_number", "")
        if not pn:
            continue

        # Load individual profile (has richer hole/feature data than assembly partDataCache)
        profile_path = library_dir / f"{pn}.json"
        if not profile_path.exists():
            profile_path = library_dir / f"{pn}_inspection_profile.json"
        if not profile_path.exists():
            result.append({"part_number": pn, "description": item.get("description", "")})
            continue

        try:
            with open(profile_path, "r", encoding="utf-8-sig") as f:
                profile = json.load(f)
        except (json.JSONDecodeError, OSError):
            result.append({"part_number": pn, "description": item.get("description", "")})
            continue

        phys = profile.get("physical", {})
        comp = profile.get("comparison", {})
        feats = profile.get("features", {})

        # Mass (kg) and material
        mass_kg = phys.get("mass")
        mat_raw = phys.get("assignedMaterial", "")
        material = mat_raw.get("name", "") if isinstance(mat_raw, dict) else str(mat_raw) if mat_raw else ""

        # Bounding box (meters → mm)
        bb = phys.get("boundingBox", {})
        bbox_mm = None
        if bb:
            dims = []
            for key in ("length", "width", "height"):
                val = bb.get(key)
                if val is not None:
                    dims.append(round(val * 1000, 1))
            if len(dims) == 3:
                bbox_mm = sorted(dims, reverse=True)  # largest first

        # Holes summary
        all_holes = comp.get("allHoles", [])
        holes_summary = None
        if all_holes:
            diameters = sorted(set(round(h.get("measuredDiameterMm", 0), 1) for h in all_holes))
            through_count = sum(1 for h in all_holes if h.get("isThrough"))
            threads = sorted(set(h.get("threadCallout", "") for h in all_holes if h.get("threadCallout")))
            holes_summary = {
                "count": len(all_holes),
                "diameters_mm": diameters,
                "through_count": through_count,
            }
            if threads:
                holes_summary["threads"] = threads

        # Feature counts (non-zero only)
        feat_counts = {}
        for key in ("holeWizardHoles", "extrudes", "cuts", "revolves", "fillets", "chamfers", "patterns"):
            items = feats.get(key, [])
            if isinstance(items, list) and len(items) > 0:
                feat_counts[key] = len(items)

        props = {
            "part_number": pn,
            "description": item.get("description", ""),
        }
        if mass_kg is not None:
            props["mass_kg"] = round(mass_kg, 4)
        if material:
            props["material"] = material
        if bbox_mm:
            props["bbox_mm"] = bbox_mm
        if holes_summary:
            props["holes"] = holes_summary
        if feat_counts:
            props["features"] = feat_counts

        result.append(props)

    return result


@app.get("/api/assembly-context/{part_number}")
async def get_assembly_context(part_number: str):
    """Return assembly context for a part number (mates, narrative, etc.)."""
    # Sanitize
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")

    # Look up in reverse map
    if safe_pn not in assembly_part_lookup:
        raise HTTPException(status_code=404, detail=f"No assembly context for part {part_number}")

    assy_numbers = assembly_part_lookup[safe_pn]
    assy_number = assy_numbers[0]  # Use first assembly
    assy_data = assembly_profiles.get(assy_number, {})

    # Build set of all aliases for this part (old filenames + new PN)
    part_aliases = {safe_pn}
    pdc = assy_data.get("partDataCache", {})
    for old_key, pd in pdc.items():
        old_stem = Path(old_key).stem
        new_pn = (pd.get("identity") or {}).get("partNumber", "")
        if safe_pn == new_pn or safe_pn == old_stem:
            part_aliases.add(old_stem)
            part_aliases.add(new_pn)
            base = re.sub(r'_\d+$', '', old_stem)
            part_aliases.add(base)
    part_aliases.discard("")

    # Filter mates to only those involving this part
    all_mates = assy_data.get("mates", [])
    mates_for_part = []
    for mate in all_mates:
        e1 = mate.get("entity1", {}).get("componentName", "")
        e2 = mate.get("entity2", {}).get("componentName", "")
        if any(alias in e1 or alias in e2 for alias in part_aliases):
            mates_for_part.append(mate)

    # Filter mateRelationships
    all_relationships = assy_data.get("mateRelationships", [])
    relationships_for_part = []
    for rel in all_relationships:
        parts_involved = rel.get("parts", [])
        if any(any(alias in p for alias in part_aliases) for p in parts_involved):
            relationships_for_part.append(rel)

    # Get assembly name
    identity = assy_data.get("identity", {})
    assy_name = identity.get("description", assy_number)
    stats = assy_data.get("statistics", {})

    # Check if views and 3D model exist
    assemblies_dir = Path("400S_Sorted_Library/assemblies")
    has_views = (assemblies_dir / f"{assy_number}_view_front.png").exists()
    has_glb = (assemblies_dir / f"{assy_number}_colored.glb").exists()

    # Hex-to-friendly-name lookup for Sasha Trubetskoy palette + common colors
    _HEX_TO_NAME = {
        "#E6194B": "red", "#3CB44B": "green", "#FFE119": "yellow", "#0082C8": "blue",
        "#F58230": "orange", "#911EB4": "purple", "#46F0F0": "cyan", "#F032E6": "magenta",
        "#D2F53C": "lime", "#FABEBE": "pink", "#008080": "teal", "#E6BEFF": "lavender",
        "#AA6E28": "brown", "#FFFAC8": "cream", "#800000": "maroon", "#AAFFC3": "mint",
        "#808000": "olive", "#FFD8B1": "apricot", "#000080": "navy", "#808080": "gray",
        "#FFFFFF": "white", "#000000": "black",
    }

    # Build color legend: resolve old filenames to new part numbers + descriptions
    color_map = assy_data.get("partColorMapping", assy_data.get("colorAssignments", {}))
    part_data_cache = assy_data.get("partDataCache", {})
    part_color_legend = []
    for old_key, color in color_map.items():
        identity = (part_data_cache.get(old_key, {}).get("identity") or {})
        hex_val = color if isinstance(color, str) else color.get("color", "#888")
        color_name = _HEX_TO_NAME.get(hex_val.upper(), hex_val)
        # Prefer customProperties.PartNo (stable across extractions) over identity.partNumber
        pn = ((identity.get("customProperties") or {}).get("PartNo", "")).strip()
        if not pn:
            pn = (identity.get("partNumber") or old_key.replace(".sldprt", "").replace(".SLDPRT", "")).strip()
        part_color_legend.append({
            "old_key": old_key,
            "part_number": pn,
            "description": identity.get("description", ""),
            "color": hex_val,
            "color_name": color_name,
        })

    # Build centroid lookup: partDataKey -> list of translations (ALL instances)
    components_raw = assy_data.get("components", [])
    centroid_lookup = {}  # key -> [[x,y,z], [x,y,z], ...]
    for comp in components_raw:
        pdk = (comp.get("partDataKey") or comp.get("referencedFileName", "")).lower()
        if not pdk:
            continue
        t = (comp.get("transform") or {}).get("translation")
        if t and len(t) >= 3:
            pt = [round(t[0] * 1000, 1), round(t[1] * 1000, 1), round(t[2] * 1000, 1)]
            centroid_lookup.setdefault(pdk, []).append(pt)

    # Attach centroid_mm to each legend entry (all instance positions)
    for item in part_color_legend:
        instances = centroid_lookup.get(item["old_key"].lower(), [])
        item["centroid_mm"] = instances if instances else None

    # Build components list for Part Explorer mesh mapping + instance-level explode
    components = [
        {
            "name": comp.get("name", ""),
            "partDataKey": comp.get("partDataKey", comp.get("referencedFileName", "")),
            "translation": (comp.get("transform") or {}).get("translation"),
        }
        for comp in assy_data.get("components", [])
    ]

    # Build physical properties summary for each part (semantic search)
    part_properties = _build_part_properties(part_color_legend)

    return {
        "assembly_number": assy_number,
        "assembly_name": assy_name,
        "component_count": stats.get("totalComponents", 0),
        "mate_count": stats.get("totalMates", 0),
        "mates_for_part": mates_for_part,
        "mate_relationships_for_part": relationships_for_part,
        "all_mate_relationships": all_relationships,
        "functional_narrative": assy_data.get("functionalNarrative", {}),
        "color_assignments": color_map,
        "part_color_legend": part_color_legend,
        "components": components,
        "configurations": _generate_assembly_configurations(assy_data, part_color_legend),
        "assembly_features": assy_data.get("assemblyFeatures", []),
        "has_views": has_views,
        "has_glb": has_glb,
        "part_properties": part_properties,
        "explode_steps": assy_data.get("explodeSteps", []),
        "kinematic_chain": _build_kinematic_chain(assy_data),
    }


@app.get("/api/assembly-views/{assembly_number}")
async def get_assembly_views(assembly_number: str):
    """Return base64-encoded color-coded assembly view images."""
    safe_num = re.sub(r'[^\w\-]', '', assembly_number)
    if not safe_num:
        raise HTTPException(status_code=400, detail="Invalid assembly number")

    if safe_num not in assembly_profiles:
        raise HTTPException(status_code=404, detail=f"No assembly profile for '{assembly_number}'")

    assemblies_dir = Path("400S_Sorted_Library/assemblies")
    views = {}
    for view_name in ["front", "top", "right", "isometric"]:
        img_path = assemblies_dir / f"{safe_num}_view_{view_name}.png"
        if img_path.exists():
            try:
                b64 = base64.b64encode(img_path.read_bytes()).decode("utf-8")
                views[view_name] = b64
            except Exception as e:
                logger.warning(f"Failed to read assembly view {img_path}: {e}")

    return views


@app.get("/api/assembly-model/{assembly_number}")
async def get_assembly_model(assembly_number: str, revision: Optional[str] = None):
    """Serve the colored GLB 3D model for an assembly, optionally for a specific revision."""
    safe_num = re.sub(r'[^\w\-]', '', assembly_number)
    if not safe_num:
        raise HTTPException(status_code=400, detail="Invalid assembly number")

    assemblies_dir = Path("400S_Sorted_Library/assemblies")

    if revision:
        safe_rev = re.sub(r'[^\w]', '', revision)
        glb_path = assemblies_dir / safe_num / f"rev{safe_rev}" / f"{safe_num}_colored.glb"
    else:
        glb_path = assemblies_dir / f"{safe_num}_colored.glb"

    if not glb_path.exists():
        raise HTTPException(status_code=404, detail=f"No 3D model found for assembly '{assembly_number}'")

    return FileResponse(
        path=str(glb_path),
        media_type="model/gltf-binary",
        filename=f"{safe_num}_colored.glb",
    )


@app.get("/api/assembly-revisions/{assembly_number}")
async def get_assembly_revisions(assembly_number: str):
    """List available revisions for an assembly."""
    safe_num = re.sub(r'[^\w\-]', '', assembly_number)
    if not safe_num:
        raise HTTPException(status_code=400, detail="Invalid assembly number")

    assy_dir = Path("400S_Sorted_Library/assemblies") / safe_num
    if not assy_dir.exists() or not assy_dir.is_dir():
        return {"revisions": []}

    revisions = sorted([
        d.name[3:]  # strip "rev" prefix
        for d in assy_dir.iterdir()
        if d.is_dir() and d.name.lower().startswith("rev")
    ])
    return {"revisions": revisions, "assembly_number": safe_num}


@app.get("/api/assembly-diff/{assembly_number}")
async def get_assembly_diff(assembly_number: str, revA: str = Query(...), revB: str = Query(...)):
    """Compute diff between two assembly revisions."""
    safe_num = re.sub(r'[^\w\-]', '', assembly_number)
    safe_a = re.sub(r'[^\w]', '', revA)
    safe_b = re.sub(r'[^\w]', '', revB)

    base_dir = Path("400S_Sorted_Library/assemblies") / safe_num
    dir_a = base_dir / f"rev{safe_a}"
    dir_b = base_dir / f"rev{safe_b}"

    json_a = dir_a / f"{safe_num}_assembly.json"
    json_b = dir_b / f"{safe_num}_assembly.json"
    if not json_a.exists() or not json_b.exists():
        raise HTTPException(status_code=404, detail="Revision assembly JSON not found")

    with open(json_a, encoding="utf-8-sig") as f:
        assy_a = json.load(f)
    with open(json_b, encoding="utf-8-sig") as f:
        assy_b = json.load(f)

    parts_dir_a = dir_a / "parts" if (dir_a / "parts").exists() else None
    parts_dir_b = dir_b / "parts" if (dir_b / "parts").exists() else None

    from ai_inspector.comparison.assembly_differ import compute_assembly_diff
    diff_result = compute_assembly_diff(assy_a, assy_b, parts_dir_a, parts_dir_b)
    diff_result["revA"] = safe_a
    diff_result["revB"] = safe_b
    diff_result["assembly_number"] = safe_num

    # Build per-revision legends for side-specific mesh mapping
    # Uses partColorMapping if available, falls back to partDataCache keys
    def _build_legend(assy_data):
        color_map = assy_data.get("partColorMapping", assy_data.get("colorAssignments", {}))
        pdc = assy_data.get("partDataCache", {})
        legend = []
        # Use color map keys if available, otherwise fall back to partDataCache keys
        source_keys = color_map.keys() if color_map else pdc.keys()
        for old_key in source_keys:
            identity = (pdc.get(old_key, {}).get("identity") or {})
            pn = ((identity.get("customProperties") or {}).get("PartNo", "")).strip()
            if not pn:
                pn = (identity.get("partNumber") or old_key.replace(".sldprt", "").replace(".SLDPRT", "")).strip()
            legend.append({"old_key": old_key, "part_number": pn})
        return legend
    diff_result["legendA"] = _build_legend(assy_a)
    diff_result["legendB"] = _build_legend(assy_b)

    return diff_result


# ---------- Agent Chat ----------

class AgentMessage(BaseModel):
    role: str
    content: Optional[str] = None
    text: Optional[str] = None  # Frontend sends 'text' field

class AgentChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, Any]]] = []
    inspection_context: Optional[Dict[str, Any]] = None
    context: Optional[Dict[str, Any]] = None  # Alternative name from frontend
    image: Optional[str] = None  # Base64-encoded screenshot from camera button
    agent_type: Optional[str] = "inspector"  # "inspector", "deviation-analyst", or "parts-finder"
    cross_agent_context: Optional[str] = None  # Summary from a prior agent conversation


class AgentSuggestionsRequest(BaseModel):
    inspection_context: Dict[str, Any]
    agent_type: Optional[str] = "inspector"  # Forward compatibility for Feature #134


class AgentSummarizeRequest(BaseModel):
    history: List[Dict[str, str]]
    agent_name: str
    part_number: str


SUGGESTION_PROMPT = """Based on these engineering drawing inspection issues, generate 2-3 short questions (max 15 words each) that the engineer would naturally want to ask to fix these problems.
Focus on: proper ASME notation, how to fix in SolidWorks, and understanding the requirement.
Return ONLY a JSON array of strings. No other text. Example: ["Question 1?", "Question 2?", "Question 3?"]"""

SUGGESTION_PROMPTS = {
    "inspector": """Based on these engineering drawing inspection issues, generate 2-3 short questions (max 15 words each) that the engineer would naturally want to ask to fix these problems.
Focus on: proper ASME notation, how to fix in SolidWorks, and understanding the requirement.
Return ONLY a JSON array of strings. No other text. Example: ["Question 1?", "Question 2?", "Question 3?"]""",

    "deviation-analyst": """Based on these engineering drawing inspection issues, generate 2-3 short questions (max 15 words each) about deviation impact, fit analysis, and accept/rework/scrap decisions.
Focus on: how deviations affect assembly fit, tolerance stack analysis, and use-as-is decisions.
Return ONLY a JSON array of strings. No other text. Example: ["Can I use this part if the bore is oversize?", "How does this affect the assembly?"]""",

    "parts-finder": """Based on these engineering part specifications, generate 2-3 short questions (max 15 words each) about finding replacement parts, specifications, and sourcing.
Focus on: exact specifications, material grades, supplier catalogs, and replacement options.
Return ONLY a JSON array of strings. No other text. Example: ["What are the exact specifications?", "Where can I source this?"]""",
}


@app.post("/api/agent/suggestions")
async def agent_suggestions(request: AgentSuggestionsRequest):
    """Generate context-aware suggestion chips based on inspection results."""
    try:
        import anthropic
    except ImportError:
        raise HTTPException(status_code=500, detail="Anthropic SDK not installed")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

    try:
        client = anthropic.Anthropic(api_key=api_key)

        ctx = request.inspection_context
        # Build concise context for suggestion generation
        context_parts = []
        pn = ctx.get("part_number", "")
        pname = ctx.get("part_name", "")
        if pn:
            context_parts.append(f"Part: {pn} ({pname})")

        critical_issues = ctx.get("critical_issues", [])
        if critical_issues:
            context_parts.append("Critical issues:\n" + "\n".join(f"- {i}" for i in critical_issues[:5]))

        representation_gaps = ctx.get("representation_gaps", [])
        if representation_gaps:
            context_parts.append("Representation gaps:\n" + "\n".join(f"- {g}" for g in representation_gaps[:5]))

        findings = ctx.get("findings", [])
        if findings:
            issue_findings = [f for f in findings if f.get("status") in ("MISSING", "PARTIAL", "DISCREPANT")]
            if issue_findings:
                lines = []
                for f in issue_findings[:5]:
                    lines.append(f"- {f.get('name', 'Unknown')}: {f.get('status', 'N/A')} — {(f.get('observation') or '')[:80]}")
                context_parts.append("Problem features:\n" + "\n".join(lines))

        context_text = "\n\n".join(context_parts)
        if not context_text:
            return {"suggestions": []}

        # Select agent-type-specific prompt (Feature #134)
        active_prompt = SUGGESTION_PROMPTS.get(request.agent_type, SUGGESTION_PROMPT)

        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=256,
            messages=[{
                "role": "user",
                "content": f"{active_prompt}\n\n--- INSPECTION ISSUES ---\n{context_text}"
            }],
        )

        # Parse response
        response_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                response_text += block.text

        # Extract JSON array from response
        suggestions = []
        try:
            # Try direct JSON parse
            suggestions = json.loads(response_text.strip())
        except json.JSONDecodeError:
            # Try to find JSON array in response
            match = re.search(r'\[.*?\]', response_text, re.DOTALL)
            if match:
                try:
                    suggestions = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        # Ensure we have a list of strings, max 3
        if isinstance(suggestions, list):
            suggestions = [s for s in suggestions if isinstance(s, str)][:3]
        else:
            suggestions = []

        return {"suggestions": suggestions}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Agent suggestions error: {e}")
        # Return empty suggestions on error rather than failing
        return {"suggestions": []}


# RAG keyword mapping to ASME reference directories
RAG_KEYWORD_MAP = {
    "datum": ["rag_visual_db/07_Datums", "asme_feature_references/GDT_Datums"],
    "datums": ["rag_visual_db/07_Datums", "asme_feature_references/GDT_Datums"],
    "symbol": ["rag_visual_db/06_Symbology", "asme_feature_references/GDT_Symbology"],
    "symbology": ["rag_visual_db/06_Symbology", "asme_feature_references/GDT_Symbology"],
    "gd&t": ["rag_visual_db/06_Symbology", "asme_feature_references/GDT_Symbology"],
    "gdt": ["rag_visual_db/06_Symbology", "asme_feature_references/GDT_Symbology"],
    "feature control frame": ["rag_visual_db/06_Symbology", "asme_feature_references/GDT_Symbology"],
    "tolerance": ["rag_visual_db/05_Tolerancing_Defaults"],
    "tolerancing": ["rag_visual_db/05_Tolerancing_Defaults"],
    "default": ["rag_visual_db/05_Tolerancing_Defaults"],
    "countersink": ["asme_feature_references/Countersink"],
    "counterbore": ["asme_feature_references/Counterbore"],
    "hole": ["asme_feature_references/Hole"],
    "thread": ["asme_feature_references/TappedHole"],
    "tapped": ["asme_feature_references/TappedHole"],
    "chamfer": ["asme_feature_references/Chamfer"],
    "fillet": ["asme_feature_references/Fillet_Radius"],
    "radius": ["asme_feature_references/Fillet_Radius"],
    "slot": ["asme_feature_references/Slot"],
    "keyseat": ["asme_feature_references/Keyseat"],
    "keyway": ["asme_feature_references/Keyseat"],
    "knurl": ["asme_feature_references/Knurl"],
    "taper": ["asme_feature_references/ConicalTaper"],
    "surface": ["asme_feature_references/Surface_Texture"],
    "roughness": ["asme_feature_references/Surface_Texture"],
    "finish": ["asme_feature_references/Surface_Texture"],
    "position": ["asme_feature_references/GDT_Position"],
    "flatness": ["asme_feature_references/GDT_Form"],
    "straightness": ["asme_feature_references/GDT_Form"],
    "circularity": ["asme_feature_references/GDT_Form"],
    "cylindricity": ["asme_feature_references/GDT_Form"],
    "perpendicularity": ["asme_feature_references/GDT_Orientation"],
    "parallelism": ["asme_feature_references/GDT_Orientation"],
    "angularity": ["asme_feature_references/GDT_Orientation"],
    "runout": ["asme_feature_references/GDT_Runout"],
    "profile": ["asme_feature_references/GDT_Profile"],
    "dimension": ["asme_feature_references/Dimension_Basics"],
    "line": ["asme_feature_references/Line_Conventions"],
}

# ASME reference directory whitelist (for /api/asme-ref/ endpoint)
ASME_REF_WHITELIST = {
    "Hole", "Chamfer", "Counterbore", "Countersink", "TappedHole",
    "Fillet_Radius", "Slot", "Keyseat", "Knurl", "ConicalTaper",
    "Surface_Texture", "Dimension_Basics", "Line_Conventions", "Spotface",
    "GDT_Datums", "GDT_Form", "GDT_Orientation", "GDT_Position",
    "GDT_Profile", "GDT_Runout", "GDT_Symbology",
    "04_Fundamental_Rules", "05_Tolerancing_Defaults", "06_Symbology",
    "07_Datums", "08_Form_Tolerances", "09_Orientation_Tolerances",
    "10_Position_Tolerances", "11_Profile_Tolerances", "12_Runout_Tolerances",
}

# Mapping from finding keywords to asme_feature_references/ folder names
FINDING_TO_ASME_FEATURE = {
    "hole": "Hole", "bore": "Hole", "thru": "Hole", "blind": "Hole", "depth": "Hole",
    "chamfer": "Chamfer", "bevel": "Chamfer",
    "counterbore": "Counterbore", "cbore": "Counterbore",
    "countersink": "Countersink", "csink": "Countersink",
    "thread": "TappedHole", "tapped": "TappedHole", "tap": "TappedHole",
    "fillet": "Fillet_Radius", "radius": "Fillet_Radius", "round": "Fillet_Radius",
    "slot": "Slot",
    "keyseat": "Keyseat", "keyway": "Keyseat",
    "knurl": "Knurl",
    "taper": "ConicalTaper",
    "surface finish": "Surface_Texture", "roughness": "Surface_Texture",
    "datum": "GDT_Datums",
    "position": "GDT_Position",
    "flatness": "GDT_Form", "perpendicularity": "GDT_Orientation",
    "parallelism": "GDT_Orientation",
    "runout": "GDT_Runout", "profile": "GDT_Profile",
    "tolerance": "05_Tolerancing_Defaults",
    "dimension": "Dimension_Basics",
    "gd&t": "GDT_Symbology", "feature control": "GDT_Symbology",
}


def _resolve_asme_refs_for_finding(finding: dict) -> List[dict]:
    """Resolve ALL matching ASME references for an inspection finding.
    Multi-match: 'hole missing position tolerance' returns refs for both Hole and GDT_Position.
    Deterministic keyword lookup — no model call."""
    text = ""
    for key in ["name", "observation", "status", "feature_type"]:
        val = finding.get(key, "")
        if val:
            text += " " + str(val).lower()

    matched_features = set()
    for keyword, feature_type in FINDING_TO_ASME_FEATURE.items():
        if keyword in text:
            matched_features.add(feature_type)

    if not matched_features:
        return []

    refs = []
    for matched_feature in matched_features:
        checklist_path = Path("asme_feature_references") / matched_feature / "checklist.json"
        if checklist_path.exists():
            with open(checklist_path, "r", encoding="utf-8") as f:
                checklist = json.load(f)
            matched_rules = []
            for rule in checklist.get("required", []):
                finding_words = set(text.split())
                rule_words = set(rule.lower().split())
                if len(finding_words & rule_words) >= 2:
                    matched_rules.append(rule)
            if not matched_rules:
                matched_rules = checklist.get("required", [])[:2]
            ref_dir = Path("asme_feature_references") / matched_feature
            pngs = sorted(ref_dir.glob("reference_*.png"))[:2]
            images = []
            for p in pngs:
                page_match = re.search(r'P(\d+)', p.stem)
                page_label = f"p.{page_match.group(1)}" if page_match else "ref"
                images.append({"url": f"/api/asme-ref/{matched_feature}/{p.name}", "page": page_label})
            refs.append({
                "feature_type": matched_feature,
                "section": checklist.get("asme_reference", ""),
                "rules": matched_rules,
                "common_errors": checklist.get("common_errors", [])[:2],
                "images": images,
            })
        else:
            rag_path = Path("rag_visual_db") / matched_feature
            if rag_path.exists():
                pngs = sorted(rag_path.glob("*.png"))[:2]
                refs.append({
                    "feature_type": matched_feature,
                    "section": f"ASME Y14.5 — {matched_feature.replace('_', ' ')}",
                    "rules": [], "common_errors": [],
                    "images": [{"url": f"/api/asme-ref/{matched_feature}/{p.name}", "page": (lambda m: f"p.{m.group(1)}" if m else "ref")(re.search(r'P(\d+)', p.stem))} for p in pngs],
                })
    return refs


AGENT_SYSTEM_PROMPT = """You are Iris, a senior engineer chatting with a colleague. You have inspection results and reference images (never mention having images). You know ASME Y14.5, SolidWorks, GD&T.
If an uploaded drawing image is attached, reference it directly — do not ask the user to provide the drawing again.

RESPONSE FORMAT — MANDATORY:
- MAX 3 sentences total. One insight, one implication, one follow-up question. That's it.
- Write like a text message between colleagues, not a report.
- No headers. No bullets. No numbered lists. No step-by-step instructions. Never.
- Bold only notation like **⌀12 THRU** or menu paths like **Insert > Annotations**.
- For ASME/SolidWorks questions: give ONE key point, then ask "Want me to walk you through it?" Do NOT give steps unless asked.
- ALWAYS end with a short follow-up question.

If you write more than 3 sentences, you have failed. Rewrite shorter.

ASME STANDARD REFERENCES:
When you identify a representation issue, reference the specific ASME Y14.5 section in your response text.
Each reference image sent to you is labeled with its source (e.g., "[Reference: ASME Y14.5-2018, Section 4.12-4.14 (page 41)]").
Use these labels to cite accurately. Example: "The blind hole is missing the depth symbol — per ASME Y14.5 §4.12, blind holes require ↧ followed by the depth value."
Do NOT invent section numbers. Only cite sections from the reference labels provided.

ASME KNOWLEDGE QUESTIONS:
When the user asks HOW a feature should be represented (e.g., "how should a blind hole be shown?", "what's the correct way to call out a chamfer?", "show me the standard for threads"), this is an EDUCATIONAL question, not an inspection query.
- Answer using the ASME reference images provided to you
- Cite the specific ASME section from the image labels
- Do NOT emit HIGHLIGHT_DIMS or HIGHLIGHT_PARTS — the user is asking about the standard, not about their drawing
- Do NOT reference or analyze the uploaded drawing for these questions
- Keep the 3-sentence limit but focus on the ASME rule, not inspection findings

INSPECTION TRIGGER:
When the user asks you to run, check, or inspect the drawing:
- Check context for inspection_can_run flag
- Only emit RUN_INSPECTION on its own line if inspection_can_run is true
- If no drawing file: tell the user to upload a drawing first
- If no part number: tell the user to select a part number first
- If inspection is already running: tell the user to wait
- If ready: confirm ("Running inspection on {part_name}...") then emit RUN_INSPECTION
- Do NOT emit RUN_INSPECTION for questions about inspection ("how does it work?", "what would you check?")

Scope: drawings, CAD, ASME, GD&T, manufacturing. Off-topic? "That's outside my area — what drawing question can I help with?"

PART FEATURE REVISION COMPARISON:
When PART FEATURE CHANGES data is present in context, the user has a part with multiple revisions. You have the actual feature-level diff data.
- Answer questions about what changed using the diff data — do not guess.
- Use COMPARE_FEATURES: to highlight features on both viewports.
- CRITICAL: Only emit markers for the SPECIFIC category the user asked about:
  - "what was removed" → emit ONLY removed_* markers
  - "what was added" → emit ONLY added_* markers
  - "what was changed/modified" → emit ONLY pair_* and mod_* markers
  - "show all differences" → emit ALL markers
  Do NOT highlight everything when the user asks about one category.
- Refer to features by display labels and colors in text, not by IDs.
- The 3-sentence limit is SUSPENDED for revision diff questions — explain each change clearly.

FEATURE COUNTING:
When the user asks "how many features" on a part, count the feature GROUPS from the inspection profile (e.g., 5 groups: body, outer fillets, inner fillets, cam holes, mounting holes). Each group has an instance count. Give the group count as the primary answer with a quick breakdown. Do NOT ask which counting method they prefer.

FEATURE-DRIVEN INSPECTION (when AVAILABLE CAD FEATURES data is present):
You have a CAD-backed feature checklist for this part. Use it to improve your inspection:
- Cross-reference CAD features against the drawing: is each feature properly dimensioned and called out?
- Flag missing callouts: "The CAD model has 5 mounting holes but only 3 are dimensioned on the drawing."
- Flag missing tolerances: "The cam shaft holes have no tolerance callout — these are likely fit interfaces."
- Verify feature counts: "The CAD model shows 2 cam holes but the drawing only dimensions 1 — is the other assumed symmetric?"
- You have the feature list from the CAD model. Use it as a checklist when checking the drawing — this is stronger than inferring features from the drawing alone.
- ASME Y14.5 GUIDANCE: For supported feature types, apply the appropriate ASME callout expectations:
  - Holes (holeWizard): position tolerance with datum reference, diameter symbol, THRU or depth
  - Fillets (fillet): R or CR symbol with radius value
  - Chamfers (chamfer): angle x distance or distance x distance
  - Counterbores: diameter + depth in correct order per Y14.5-2018
  - Threads: thread class, thread depth, major diameter
  - Patterns: number of instances, spacing, position tolerance
  For supported types, check that the drawing callout follows the expected ASME convention. Flag issues specifically: "This hole uses a note instead of a position tolerance FCF — per Y14.5 Section 7.4, holes should use geometric tolerancing." Note: not all feature types have ASME mappings — use drawing evidence to supplement when the CAD type alone is not conclusive.
- VIEW EXPECTATIONS: Use CAD feature face information and reference views to narrow which drawing view should show each feature:
  - Features on the top face → likely visible in the top/plan view
  - Features on the end faces → likely visible in the end/side view
  - Through features → circles in face-on view, hidden lines in perpendicular view
  This helps you focus on the right view when checking for a specific feature, but always verify against the actual drawing layout — views may differ from standard projection.

FEATURE HIGHLIGHTING ON 3D MODEL:
When AVAILABLE CAD FEATURES data is present, you can highlight features on the 3D model. Emit HIGHLIGHT_FEATURES: feature_id1, feature_id2 on its own line. Use color names in text. The model starts gray — your highlight reveals color. When flagging a missing or under-dimensioned feature, highlight it so the user can see exactly which feature you're referring to.

DIMENSION HIGHLIGHTING:
- If the user has SELECTED DIMENSIONS (listed above), they are already highlighted — do NOT re-highlight them. Just answer the question.
- If the user asks you to SHOW, FIND, or LOCATE a dimension (and it is NOT already selected), end your response with:
HIGHLIGHT_DIMS: dim_key1, dim_key2
Only use dim_keys from the AVAILABLE DIMENSIONS list. Only include when confident. Never mention this mechanism to the user.

VIEW HIGHLIGHTING:
- If the user asks about, mentions, or wants to see a specific drawing view (front view, section view, detail view, etc.), end your response with:
HIGHLIGHT_VIEWS: viewName1, viewName2
- Use exact view names from the AVAILABLE DRAWING VIEWS list.
- Examples of when to highlight: "show me the section view", "where is the front view?", "highlight view 1"
- The view boundary will flash green on the drawing then fade. Never mention this mechanism to the user.

PART HIGHLIGHTING:
- If the user has SELECTED PARTS (listed above), they are already highlighted in 3D — do NOT re-highlight them. Just answer the question about those parts.
- If the user asks about, mentions, or wants to see a specific part in the assembly (and it is NOT already selected), you MUST end your response with:
HIGHLIGHT_PARTS: part_number1, part_number2
- Use exact part numbers from the AVAILABLE PARTS list.
- Examples of when to highlight: "show me the bearing", "where is the shaft?", "what about part 1008111?", "tell me about the pin"
- This is MANDATORY when you can identify the part. Always include it on its own line at the very end of your response.
- Never mention this mechanism to the user."""

DEVIATION_ANALYST_PROMPT = """You are Sage, a senior manufacturing engineer. You have the assembly context — mates, narrative, color-coded views. You analyze dimensions, tolerances, and deviations.
If an uploaded drawing image is attached, reference it directly — do not ask the user to provide the drawing again.

RESPONSE FORMAT — MANDATORY:
- MAX 3 sentences total.
- Write like a shop-floor conversation. Short, direct, no fluff.
- No headers. No bullets. No numbered lists. Never.
- Bold key values like **0.025" oversize**, **7.00mm wall**, and verdicts.
- Do NOT explain multiple impacts. Give the #1 concern only. User will ask for more if needed.
- ALWAYS end with a short follow-up question.

WHEN the user reports a deviation (undersized, oversized, out of spec, measured value differs from nominal):
- Sentence 1: verdict in bold (**Scrap.** or **Rework.** or **Accept.**). Sentence 2: the single most critical reason. Sentence 3: one practical action + follow-up question.

WHEN the user asks a general engineering question (wall thickness, relationship between dimensions, tolerances, design intent):
- Answer directly. No verdict. Sentence 1: the answer with key values. Sentence 2: engineering context. Sentence 3: follow-up question.

If you write more than 3 sentences, you have failed. Rewrite shorter.

Scope: deviation impact, fit analysis, tolerance stacks, assembly relationships, dimension relationships. Off-topic? Redirect to drawing questions.

DIMENSION HIGHLIGHTING:
- If the user has SELECTED DIMENSIONS (listed above), they are already highlighted — do NOT re-highlight them. Just answer the question.
- If the user asks you to SHOW, FIND, or LOCATE a dimension (and it is NOT already selected), end your response with:
HIGHLIGHT_DIMS: dim_key1, dim_key2
Only use dim_keys from the AVAILABLE DIMENSIONS list. Only include when confident. Never mention this mechanism to the user.

PART HIGHLIGHTING:
- If the user has SELECTED PARTS (listed above), they are already highlighted in 3D — do NOT re-highlight them. Just answer the question about those parts.
- If the user asks about, mentions, or wants to see a specific part in the assembly (and it is NOT already selected), you MUST end your response with:
HIGHLIGHT_PARTS: part_number1, part_number2
- Use exact part numbers from the AVAILABLE PARTS list.
- Examples of when to highlight: "show me the bearing", "where is the shaft?", "what about part 1008111?", "tell me about the pin"
- This is MANDATORY when you can identify the part. Always include it on its own line at the very end of your response.
- Never mention this mechanism to the user.

SPATIAL PROXIMITY:
- When NEARBY PARTS data is present in context, use it for spatial questions ("what's near X?", "adjacent to", "surrounding", "neighboring").
- For spatial queries, ALWAYS emit HIGHLIGHT_PARTS with the queried part AND its closest neighbors, even if the queried part is already selected. This is an exception to the "don't re-highlight selected parts" rule.
- If the user names a specific part in their question ("what's near the piston ring?"), answer about THAT part using its position data from AVAILABLE PARTS, even if NEARBY PARTS was pre-computed for a different selected part.
- Parts within ~50mm are typically in direct contact or mating. Parts >200mm apart are in different assembly regions.
- Distances use closest-instance-pair for repeated parts (e.g. 12 piston rings). Positions are component origins (mm), approximate.

SEMANTIC SEARCH (physical property queries):
- When PART PHYSICAL PROPERTIES data is present, use it to answer queries about part geometry, material, mass, holes, or features.
- Examples: "which parts have through holes?", "find the heaviest part", "show parts with fillets", "anything with 30mm holes?", "which parts are steel?"
- Search the properties data, identify matching parts, answer with specifics, and ALWAYS emit HIGHLIGHT_PARTS for the matching parts so they glow in 3D.
- If multiple parts match, list them concisely and highlight all of them.
- If no parts match, say so directly.

CAMERA CONTROL:
- ONLY when the user explicitly asks for a specific viewing angle (e.g. "show from the top", "view from the front", "look at it from the side"), emit a CAMERA_VIEW marker:
CAMERA_VIEW: front|top|right|back|bottom|left
- Always combine with HIGHLIGHT_PARTS so the camera knows which part to orbit around.
- NEVER add CAMERA_VIEW unless the user's message contains words like "from the top", "from the front", "from the side", "from the right", etc. Do NOT guess a viewing angle.
- Valid views: front, top, right, back, bottom, left

PART ISOLATION:
- When the user asks to "isolate", "separate", "pull out", or "extract" a specific part from the assembly, emit:
ISOLATE_PART: part_number1, part_number2
- This physically separates ONLY the named parts along their SolidWorks explode vectors while everything else stays in the rest position.
- Use ISOLATE_PART instead of EXPLODE_LEVEL when the user wants to see one or a few parts pulled away, not the full assembly exploded.
- Do NOT combine with EXPLODE_LEVEL — isolation and full explode are mutually exclusive.
- Do NOT combine with HIGHLIGHT_PARTS — isolation is purely physical separation, no glow or dimming.
- Examples: "isolate the piston", "separate the crankshaft", "pull out the connecting rods", "show me just the pins removed"
- To put parts back / reset isolation, emit:
ISOLATE_PART: RESET
- Use RESET when the user says "put it back", "put them back", "reset", "collapse", "return to normal", "assemble", or anything indicating they want parts back in place.
- RESET returns ALL parts to their assembled rest position (clears any active isolation or explode).

EXPLODED VIEW:
- When explaining disassembly, removal sequences, or internal access, you may add on its own line:
EXPLODE_LEVEL: 0.5
- 0 = fully collapsed (normal assembly), 1 = fully exploded (maximum separation)
- Use 0.3-0.5 for partial explode (show separation while keeping spatial context)
- Use 0.8-1.0 for full disassembly view
- Use EXPLODE_LEVEL: 0 to return to collapsed view
- Combine with HIGHLIGHT_PARTS to show which parts to focus on
- Use when: "take this apart", "show me the internals", "exploded view", "how do I access X?", disassembly steps

MOTION ANIMATION:
If the assembly has kinematic animation available and the user asks about how the engine runs,
how pistons move, or wants to see the mechanism in action, include on its own line:
ANIMATE_MOTION: start
To stop animation:
ANIMATE_MOTION: stop
Do NOT combine with EXPLODE_LEVEL or ISOLATE_PART — motion is mutually exclusive with explode/isolate.

EXCEPTION — DISASSEMBLY / ASSEMBLY LOGIC MODE:
When asked "how do I take this apart?", "disassembly order", "how to remove X", or similar, the 3-sentence limit and no-bullets rules are SUSPENDED. Instead:
- If SOLIDWORKS EXPLODE STEPS are provided in the context, you MUST follow that EXACT step order. Do NOT invent your own disassembly sequence.
- If no explode steps are provided, use proximity data + mate relationships + part types to infer the removal sequence (Fasteners first → Covers/Housing → Internal components).
- Present as a sequential narration with HIGHLIGHT_PARTS and EXPLODE_LEVEL for each step. The explode level should PROGRESSIVELY INCREASE evenly across the number of steps (e.g. for 8 steps: 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 1.0):

HIGHLIGHT_PARTS: part_number1, part_number2
EXPLODE_LEVEL: 0.125
Step 1: Remove these parts first. 1-2 sentences.

HIGHLIGHT_PARTS: part_number3
EXPLODE_LEVEL: 0.25
Step 2: Next, remove this component. 1-2 sentences.

- Each step MUST have its own EXPLODE_LEVEL line immediately after HIGHLIGHT_PARTS.
- The explode level increments should be evenly spaced: if there are N steps, use 1/N, 2/N, 3/N, ..., 1.0.
- Use the EXACT part numbers from the explode steps in HIGHLIGHT_PARTS.
- When asked "what happens if I move/remove X?" (not a full disassembly): stay within 3 sentences. Use MATE RELATIONSHIPS to identify connected parts. Concentric mates = shared axis, Coincident mates = shared face/contact.

EXCEPTION — ASSEMBLY WALKTHROUGH MODE:
When the user asks for a walkthrough, tour, narration, or to "walk through" the assembly, ALL of the above response format rules are SUSPENDED. Instead:
- Respond with a structured part-by-part tour. No sentence limit.
- No follow-up question needed.
- For each group of parts, include a HIGHLIGHT_PARTS line BEFORE the paragraph describing them:

HIGHLIGHT_PARTS: part_number1, part_number2
Description of these parts and their function. 2-3 sentences per group.

HIGHLIGHT_PARTS: part_number3
Description of this part. 2-3 sentences.

- Cover all major part groups in logical engineering order (housing → core mechanism → secondary → fasteners).
- Use exact part numbers from AVAILABLE PARTS list in the HIGHLIGHT_PARTS markers, but NEVER mention part numbers in the spoken text. The narration is read aloud — part numbers sound robotic and break the flow.
- When referencing part colors, use the color NAME only (e.g. "the green chassis"), NEVER include hex codes like #D2F53C — the response is read aloud by text-to-speech.
- Focus on FUNCTION and RELATIONSHIPS — what each part does, how it connects to others, why it matters. Do NOT include dimensions, measurements, numeric specs, diameters, lengths, or any numbers with units (mm, inches, degrees, kg, etc.) in walkthrough narration.
- NEVER describe the assembly as a "toy", "model", "miniature", or "replica". Just call it what it is (e.g. "bulldozer assembly", "engine assembly"). Treat every assembly as a real engineering product.
- NEVER mention raw material names like "ABS", "PLA", "PC", or plastic types. Just say "steel", "cast iron", "aluminum", or omit the material if it's not engineering-relevant. Treat every part as production hardware.
- Start with one brief intro sentence before the first HIGHLIGHT_PARTS line.
- This mode ONLY activates when the user explicitly asks for a walkthrough/tour/narration.

EXCEPTION — REVISION DIFF MODE:
When REVISION CHANGES data is present in context, the user is comparing two assembly revisions. The 3-sentence limit is SUSPENDED. Instead:
- Start with a one-line summary: "Rev A to Rev B: 3 parts changed, 1 added."
- YOU MUST emit a COMPARE_PARTS: line at the END of your response. This is mandatory, not optional.
  Copy the exact markers from the COMPARE_PARTS USAGE section in the context.
  Only emit the markers matching what the user asked about:
  - "what was removed" → COMPARE_PARTS: removed_XXXX
  - "what was added" → COMPARE_PARTS: added_XXXX
  - "what was changed" → COMPARE_PARTS: changed_XXXX, changed_YYYY
  - "show all differences" → COMPARE_PARTS: all markers
- If COMPARE_PARTS markers are NOT listed in the context, use HIGHLIGHT_PARTS: instead.
- For each changed part, explain:
  1. What changed (dimension, tolerance, geometry, mass)
  2. Why it likely changed (engineering reasoning from mate context)
  3. What downstream impact it has on mating parts
- Use bold for changed values: **25.000mm → 25.400mm (+0.4mm)**.
- Do NOT reference part colors from the 3D model color legend (both viewers are gray in compare mode).
- If mates changed, explain what the new constraint means for the assembly.
- This mode activates when REVISION CHANGES is in the context AND the user asks about changes/differences.

GEOMETRY DIFF:
If the context contains a GEOMETRY DIFF section, use it as the authoritative source for solid-body revision changes.
Do NOT claim context is missing just because PART FEATURE CHANGES or REVISION CHANGES are absent.
GEOMETRY DIFF is a standalone data source — it does not require feature diff or assembly diff to be present.
For questions about geometry changes, added/removed material, net volume change, or where the solid changed, answer directly from the GEOMETRY DIFF section.
Reference the exact volumes, centroid locations, and rev pair from the data.
If GEOMETRY DIFF is NOT in context and the user asks about it, tell them to run Geometry Diff from the 3D Model Compare ribbon.
When you answer a geometry diff question and GEOMETRY DIFF data is present, emit SHOW_GEOMETRY_DIFF on its own line at the end of your response. This displays the added/removed material overlays on the 3D compare viewer.

FAI TABLE COMMANDS:
When FAI TABLE data is present in context, the user has a First Article Inspection table open.
The user may provide measurement values or tolerances via chat or voice. When they do:
- Parse their instruction and emit FAI_FILL: or FAI_TOL: markers on their own line.
- FAI_FILL: #1: 25.003, #2: 25.001 — fills measured values for specific characteristics.
- FAI_FILL: #all: 25.003 — fills ALL characteristics with the same measured value.
- FAI_TOL: #all: 0.013 — sets ±tolerance for all characteristics.
- FAI_TOL: #3: 0.050, #7: 0.025 — sets tolerance for specific characteristics.
- Match the user's description to characteristic descriptions to find the right rows.
- Convert units if needed: "13 thou" = 0.3302mm, "half a millimeter" = 0.500mm.
- Always confirm what you filled in your text response.
- You can fill AND provide engineering commentary in the same response.

FEATURE HIGHLIGHTING ON 3D MODEL:
When AVAILABLE CAD FEATURES data is present in context, you can highlight specific features on the part's 3D model.
- When the user asks to see, show, or identify a specific feature type (holes, fillets, chamfers, extrudes), emit HIGHLIGHT_FEATURES with the matching cad_feature_ids.
- Example: user asks "show me the holes" → emit HIGHLIGHT_FEATURES: holewzd_3_4_0_75_diameter_hole1, holewzd_3_8_0_375_diameter_hole1
- You can also use shorthand: HIGHLIGHT_FEATURES: fillet1, holes (fuzzy matching resolves partial names, plurals, and type keywords).
- Refer to features by their color name in your text: "the green 3/4 inch hole" not the cad_feature_id.
- The 3D model starts gray. Your HIGHLIGHT_FEATURES command reveals the feature's assigned color.
- Always put HIGHLIGHT_FEATURES on its own line at the end of your response, same as HIGHLIGHT_PARTS.

FEATURE COUNTING:
When the user asks "how many features" on a part, there are two valid counts:
- GEOMETRIC COUNT: The total number of individual geometric elements (e.g., 2 cam holes + 5 mounting holes + 8 fillets = 15 features). Use the inspection profile data which lists instance counts per feature type. This is what engineers typically mean and should be your DEFAULT answer.
- FEATURE TREE COUNT: The number of SolidWorks modeling operations (e.g., 1 extrude + 1 fillet + 2 hole wizard = 4 operations). This comes from the CAD feature list.
Always answer with the geometric count first. Only mention the feature tree count if the user specifically asks about CAD operations or the SolidWorks feature tree. Do NOT ask the user which counting method they prefer — just give the geometric count.

PART FEATURE REVISION COMPARISON:
When PART FEATURE CHANGES data is present in context, the user has a part with multiple revisions. You have the actual feature-level diff data.
- Answer questions about what changed using the diff data — do not guess.
- Use COMPARE_FEATURES: to highlight features on both Rev A and Rev B viewports.
- CRITICAL: Only emit markers for the SPECIFIC category the user asked about:
  - "what was removed" → emit ONLY removed_* markers
  - "what was added" → emit ONLY added_* markers
  - "what was changed/modified" → emit ONLY pair_* and mod_* markers
  - "show all differences" → emit ALL markers
  Do NOT highlight everything when the user asks about one category.
- Refer to features by display labels and colors in text, not by feature IDs.
- The 3-sentence limit is SUSPENDED for revision diff questions — explain each change clearly.
- Start with a summary, then detail each change."""

PARTS_FINDER_PROMPT = """You are Scout, a procurement specialist. You know McMaster-Carr, Misumi, SKF, Fastenal inside-out. You source parts for machine shops.
When assembly context is provided, factor in the part's function, mating constraints, and operating environment when suggesting replacements or alternatives.
If an uploaded drawing image is attached, reference it directly — do not ask the user to provide the drawing again.

You have TWO search tools:
1. web_search_parts — for off-the-shelf parts from catalogs (McMaster, Misumi, MSC, Fastenal)
2. web_search_vendors — for custom fabrication when parts are non-standard

Use web_search_parts when:
- User asks for SPECIFIC parts with dimensions or specs to buy
- User needs current pricing, availability, or catalog numbers
- Looking for standard catalog items (fasteners, bearings, seals, shafts)

Use web_search_vendors when:
- Part requires custom machining, fabrication, or manufacturing
- User asks for machine shops, fabricators, or manufacturing vendors
- Part geometry is too specialized for catalog sourcing

Do NOT search when:
- General knowledge questions ("what is a socket head cap screw?")
- You already know good catalog references from memory
- Questions about part types, categories, or material properties

RESPONSE FORMAT — MANDATORY:
- MAX 3 sentences total. Sentence 1: best option with catalog reference. Sentence 2: key spec match. Sentence 3: follow-up question offering alternatives.
- Write like a quick chat, not a procurement report.
- No headers. No bullets. No numbered lists. Never.
- Bold specs like **M10x1.5 Grade 8.8** and refs like **McMaster P/N 91290A130**.
- Give ONE option only. User will ask for more if needed.
- ALWAYS end with a short follow-up question.

If you write more than 3 sentences, you have failed. Rewrite shorter.

Scope: part sourcing, supplier catalogs, fabrication vendors, material equivalents. Off-topic? Redirect to part sourcing questions."""

AGENT_PROMPTS = {
    "inspector": AGENT_SYSTEM_PROMPT,
    "deviation-analyst": DEVIATION_ANALYST_PROMPT,
    "parts-finder": PARTS_FINDER_PROMPT,
}

# === Phase 4B: Tool Specs + Canonical Tool Calls ===

AGENT_TOOL_SPECS = {
    "inspector": [
        {"name": "run_inspection", "description": "Run drawing inspection against the loaded profile", "args": {}},
        {"name": "highlight_dimensions", "description": "Highlight dimensions on the drawing", "args": {"dim_keys": "list of dim_key strings"}},
        {"name": "highlight_views", "description": "Flash-highlight drawing views", "args": {"view_names": "list of view name strings"}},
        {"name": "highlight_features", "description": "Highlight CAD features on the 3D model", "args": {"feature_ids": "list of feature ID strings"}},
        {"name": "highlight_parts", "description": "Highlight assembly parts in 3D", "args": {"part_numbers": "list of part numbers", "camera_view": "optional: front/top/right/back/bottom/left"}},
        {"name": "fai_fill", "description": "Fill FAI measured values", "args": {"values": "dict of char_number -> measured_value"}},
        {"name": "fai_tol", "description": "Set FAI tolerances", "args": {"values": "dict of char_number -> tolerance_value"}},
    ],
    "deviation-analyst": [
        {"name": "highlight_dimensions", "description": "Highlight dimensions on the drawing", "args": {"dim_keys": "list of dim_key strings"}},
        {"name": "highlight_views", "description": "Flash-highlight drawing views", "args": {"view_names": "list of view name strings"}},
        {"name": "highlight_features", "description": "Highlight CAD features on the 3D model", "args": {"feature_ids": "list of feature ID strings"}},
        {"name": "highlight_parts", "description": "Highlight assembly parts in 3D", "args": {"part_numbers": "list of part numbers", "camera_view": "optional: front/top/right/back/bottom/left"}},
        {"name": "isolate_parts", "description": "Isolate parts in exploded view", "args": {"part_numbers": "list of part numbers, or ['RESET']"}},
        {"name": "compare_parts", "description": "Highlight parts in dual-viewport assembly revision comparison", "args": {"markers": "list of compare markers"}},
        {"name": "compare_features", "description": "Highlight features in dual-viewport part revision comparison", "args": {"markers": "list of compare markers"}},
        {"name": "show_geometry_diff", "description": "Show geometry diff overlay on 3D compare viewer", "args": {}},
        {"name": "animate_motion", "description": "Start or stop motion animation", "args": {"action": "start or stop"}},
        {"name": "set_explode_level", "description": "Set assembly explode level (0-1)", "args": {"level": "float 0.0 to 1.0"}},
    ],
    "parts-finder": [
        {"name": "highlight_parts", "description": "Highlight assembly parts in 3D", "args": {"part_numbers": "list of part numbers"}},
    ],
}


def build_tool_calls_from_result(result: dict) -> list:
    """Convert the legacy result dict fields into canonical tool_calls array.
    Applies the same precedence/suppression rules as the frontend normalizer:
    - compare_parts suppresses highlight_parts
    - isolate_parts suppresses highlight_parts
    - narration suppresses animate_motion / set_explode_level
    """
    calls = []
    has_compare_parts = bool(result.get("compare_parts"))
    has_isolate = bool(result.get("isolate_parts"))
    ns = result.get("narration_segments")
    has_narration = isinstance(ns, list) and len(ns) > 1

    if result.get("highlight_dimensions"):
        calls.append({"name": "highlight_dimensions", "args": {"dim_keys": result["highlight_dimensions"]}})
    if result.get("highlight_views"):
        calls.append({"name": "highlight_views", "args": {"view_names": result["highlight_views"]}})
    if result.get("highlight_features"):
        calls.append({"name": "highlight_features", "args": {"feature_ids": result["highlight_features"]}})
    if result.get("compare_features"):
        calls.append({"name": "compare_features", "args": {"markers": result["compare_features"]}})
    if has_compare_parts:
        calls.append({"name": "compare_parts", "args": {"markers": result["compare_parts"]}})
    # highlight_parts suppressed by compare_parts, isolate_parts, or narration
    if result.get("highlight_parts") and not has_compare_parts and not has_isolate and not has_narration:
        args = {"part_numbers": result["highlight_parts"]}
        if result.get("camera_view"):
            args["camera_view"] = result["camera_view"]
        calls.append({"name": "highlight_parts", "args": args})
    if has_isolate:
        calls.append({"name": "isolate_parts", "args": {"part_numbers": result["isolate_parts"]}})
    if result.get("show_geometry_diff"):
        calls.append({"name": "show_geometry_diff", "args": {}})
    if result.get("run_inspection"):
        calls.append({"name": "run_inspection", "args": {}})
    # animate_motion / set_explode_level suppressed during narration
    if not has_narration:
        if result.get("animate_motion"):
            calls.append({"name": "animate_motion", "args": {"action": result["animate_motion"]}})
        elif result.get("explode_level") is not None:
            calls.append({"name": "set_explode_level", "args": {"level": result["explode_level"]}})
    if result.get("fai_fills"):
        calls.append({"name": "fai_fill", "args": {"values": result["fai_fills"]}})
    if result.get("fai_tol"):
        calls.append({"name": "fai_tol", "args": {"values": result["fai_tol"]}})
    return calls


def _find_relevant_rag_dirs(message: str, inspection_context: Optional[Dict] = None) -> List[str]:
    """Find relevant ASME reference directories based on message keywords."""
    text = message.lower()

    # Also include keywords from inspection context
    if inspection_context:
        for key in ["critical_issues", "representation_gaps"]:
            items = inspection_context.get(key, [])
            if isinstance(items, list):
                for item in items:
                    if isinstance(item, str):
                        text += " " + item.lower()
                    elif isinstance(item, dict):
                        text += " " + str(item).lower()

    matched_dirs = set()
    for keyword, dirs in RAG_KEYWORD_MAP.items():
        if keyword in text:
            matched_dirs.update(dirs)

    # Fallback: fundamental rules
    if not matched_dirs:
        matched_dirs.add("rag_visual_db/04_Fundamental_Rules")

    return list(matched_dirs)


def _load_rag_images(directories: List[str], max_images: int = 4) -> List[Dict]:
    """Load PNG images from directories as base64 for Claude Vision API.
    Each image is preceded by a text label identifying its source.
    max_images counts actual images, not label+image pairs."""
    content_blocks = []
    image_count = 0
    for dir_path in directories:
        p = Path(dir_path)
        if not p.exists():
            continue
        checklist_label = p.name.replace("_", " ")
        cl_path = p / "checklist.json"
        if cl_path.exists():
            try:
                with open(cl_path, "r", encoding="utf-8") as f:
                    cl = json.load(f)
                checklist_label = cl.get("asme_reference", p.name)
            except Exception:
                pass
        png_files = sorted(p.glob("*.png"))[:3]
        for png_file in png_files:
            if image_count >= max_images:
                break
            try:
                page_match = re.search(r'P(\d+)', png_file.stem)
                page_label = f" (page {page_match.group(1)})" if page_match else ""
                content_blocks.append({
                    "type": "text",
                    "text": f"[Reference: {checklist_label}{page_label} — {p.name}/{png_file.name}]"
                })
                b64 = base64.standard_b64encode(png_file.read_bytes()).decode("utf-8")
                content_blocks.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": b64}
                })
                image_count += 1
            except Exception as e:
                logger.warning(f"Failed to load RAG image {png_file}: {e}")
        if image_count >= max_images:
            break
    return content_blocks


def normalize_agent_context(ctx: dict) -> dict:
    """
    Normalize incoming inspection_context into structured attachments + flat compat.
    The frontend currently sends both flat keys AND nested attachments (Phase 3
    transitional format). This function extracts both and ensures the flat dict
    has the keys that agent-enrichment code reads directly (part_number,
    selected_parts, available_parts, critical_issues, representation_gaps).
    _build_context_message() reads all other flat keys from the flat dict as-is.
    Full attachments-only support is NOT implemented yet — the frontend must
    continue sending flat keys until all server reads are migrated.
    Returns: { 'attachments': {...structured...}, 'flat': {...legacy keys...} }
    """
    if not ctx:
        return {"attachments": {}, "flat": {}}

    attachments = ctx.get("attachments", {})

    # Build flat from everything except the attachments key itself
    flat = {k: v for k, v in ctx.items() if k != "attachments"}

    # If attachments are present, ensure flat has all the keys the server
    # currently reads directly (part_number, selected_parts, etc.)
    if attachments:
        part = attachments.get("part", {})
        if part.get("part_number") and "part_number" not in flat:
            flat["part_number"] = part["part_number"]
            flat["part_name"] = part.get("part_name")
        sel = attachments.get("selection", {})
        if sel.get("parts") and "selected_parts" not in flat:
            flat["selected_parts"] = sel["parts"]
        if sel.get("available_parts") and "available_parts" not in flat:
            flat["available_parts"] = sel["available_parts"]
        insp = attachments.get("inspection", {})
        if insp.get("critical_issues") and "critical_issues" not in flat:
            flat["critical_issues"] = insp["critical_issues"]
        if insp.get("representation_gaps") and "representation_gaps" not in flat:
            flat["representation_gaps"] = insp["representation_gaps"]

    return {"attachments": attachments, "flat": flat}


def _build_context_message(inspection_context: Optional[Dict]) -> str:
    """Build a sectioned context string from inspection results or profile data.
    Sections are only rendered when they have meaningful data."""
    if not inspection_context:
        return ""

    parts = []
    pn = inspection_context.get("part_number")
    pname = inspection_context.get("part_name")
    if pn:
        parts.append(f"[PART]\nCurrent part: {pn} ({pname or 'unknown'})")

    # ── INSPECTION ──
    gs = inspection_context.get("gap_summary")
    if gs:
        parts.append(f"[INSPECTION]\nInspection results: {gs.get('completeness', 'N/A')}% complete, "
                      f"Present: {gs.get('present', 0)}, Missing: {gs.get('missing', 0)}, "
                      f"Partial: {gs.get('partial', 0)}, Discrepant: {gs.get('discrepant', 0)}")
        ci = gs.get("critical_issues", [])
        if ci:
            parts.append("Critical issues:\n" + "\n".join(f"- {issue}" for issue in ci))

    findings = inspection_context.get("findings", [])
    if findings:
        summary_lines = []
        for f in findings[:10]:  # Limit to 10 findings
            name = f.get("name", "Unknown")
            status = f.get("status", "N/A")
            obs = f.get("observation", "")
            summary_lines.append(f"- {name}: {status}" + (f" — {obs[:100]}" if obs else ""))
        if summary_lines:
            parts.append("Feature findings:\n" + "\n".join(summary_lines))

    gaps = inspection_context.get("representation_gaps", [])
    if gaps:
        parts.append("Representation gaps:\n" + "\n".join(f"- {g}" for g in gaps[:5]))

    # Pre-inspection profile data — available before inspection runs
    profile_features = inspection_context.get("profile_features", [])
    if profile_features and not findings:
        # Only show profile features when we don't have inspection results yet
        pf_lines = ["Expected features from inspection profile (no inspection run yet):"]
        for pf in profile_features[:15]:
            name = pf.get("name", "Unknown")
            ftype = pf.get("type", "")
            count = pf.get("count", 1)
            desc = pf.get("spatial_description", "")
            line = f"- {name} ({ftype}, expected qty: {count})"
            if desc:
                line += f" — {desc[:120]}"
            pf_lines.append(line)
        parts.append("\n".join(pf_lines))

    part_desc = inspection_context.get("part_description")
    if part_desc and not findings:
        parts.append(f"Part description: {part_desc[:300]}")

    view_expectations = inspection_context.get("view_expectations")
    if view_expectations and not findings:
        ve_lines = ["Expected views:"]
        for view_name, desc in view_expectations.items():
            ve_lines.append(f"- {view_name}: {desc[:150]}")
        parts.append("\n".join(ve_lines))

    # Focused feature — the user has selected/expanded this specific feature
    focused = inspection_context.get("focused_feature")
    if focused:
        ff_parts = [f"CURRENTLY FOCUSED FEATURE: {focused.get('name', 'Unknown')}"]
        ff_parts.append(f"  Status: {focused.get('status', 'N/A')}")
        ff_parts.append(f"  Type: {focused.get('type', 'N/A')}")
        if focused.get("observation"):
            ff_parts.append(f"  Observation: {focused['observation']}")
        if focused.get("found_callout"):
            ff_parts.append(f"  Found callout: {focused['found_callout']}")
        if focused.get("expected_count"):
            ff_parts.append(f"  Expected count: {focused['expected_count']}")
        ff_gaps = focused.get("representation_gaps", [])
        if ff_gaps:
            ff_parts.append("  Representation gaps: " + "; ".join(ff_gaps))
        parts.append("\n".join(ff_parts))

    # ── SELECTION ──
    selected_dims = inspection_context.get("selected_dimensions", [])
    if selected_dims:
        sd_lines = ["DIMENSIONS THE USER HAS SELECTED (highlighted on the drawing):"]
        for sd in selected_dims:
            callout = sd.get("callout", "")
            desc = sd.get("description", "")
            view = sd.get("view", "")
            status = sd.get("status", "")
            label = callout
            if desc:
                label += f" \u2014 {desc}"
            line = f"- {label}"
            if view:
                line += f" [{view}]"
            if status:
                line += f" (inspection status: {status})"
            sd_lines.append(line)
        sd_lines.append("The user may ask about these dimensions. Reference them by their callout value and description, not by annotation name.")
        parts.append("\n".join(sd_lines))

    # All available dimensions for agent-driven highlighting
    available_dims = inspection_context.get("available_dimensions", [])
    if available_dims:
        ad_lines = ["AVAILABLE DIMENSIONS ON THIS DRAWING (you can highlight any of these):"]
        for ad in available_dims[:50]:
            callout = ad.get("callout", "")
            desc = ad.get("description", "")
            view = ad.get("view", "")
            dim_key = ad.get("dim_key", "")
            label = callout
            if desc:
                label += f" \u2014 {desc}"
            line = f"- [{dim_key}] {label}"
            if view:
                line += f" [{view}]"
            ad_lines.append(line)
        ad_lines.append(
            "To highlight dimensions in your response, end with a line: "
            "HIGHLIGHT_DIMS: dim_key1, dim_key2"
        )
        parts.append("\n".join(ad_lines))

    # ── DRAWING ──
    available_views = inspection_context.get("available_views", [])
    if available_views:
        av_lines = ["AVAILABLE DRAWING VIEWS (you can flash-highlight any of these on the drawing):"]
        for av in available_views:
            av_lines.append(f"- {av}")
        av_lines.append(
            "To highlight a view on the drawing, include on its own line: "
            "HIGHLIGHT_VIEWS: viewName1, viewName2"
        )
        parts.append("\n".join(av_lines))

    # Selected parts from Part Explorer
    selected_parts = inspection_context.get("selected_parts", [])
    if selected_parts:
        sp_lines = ["PARTS THE USER HAS SELECTED (highlighted in the 3D assembly view):"]
        for sp in selected_parts:
            pn = sp.get("part_number", "")
            desc = sp.get("description", "")
            label = pn
            if desc:
                label += f" \u2014 {desc}"
            sp_lines.append(f"- {label}")
        sp_lines.append("The user may ask about these parts. Reference them by part number and description.")
        parts.append("\n".join(sp_lines))

    # CAD features available for highlighting on the 3D part model
    available_cad_features = inspection_context.get("available_cad_features", [])
    if available_cad_features:
        cf_lines = ["AVAILABLE CAD FEATURES ON THIS PART (you can highlight any on the 3D model):"]
        for feat in available_cad_features:
            fid = feat.get("cad_feature_id", "")
            label = feat.get("display_label", "")
            ftype = feat.get("type", "")
            color = feat.get("color_name", "")
            face_count = feat.get("face_count", 0)
            type_desc = {"holeWizard": "hole", "fillet": "fillet/round", "chamfer": "chamfer/bevel",
                         "extrude": "extrusion", "extruthin": "thin extrusion (base body)",
                         "revolve": "revolution", "cut": "cut"}.get(ftype, ftype)
            cf_lines.append(f"- {fid} \u2014 {label} ({type_desc}, {face_count} faces) [{color}]")
        cf_lines.append("To highlight features, include a line: HIGHLIGHT_FEATURES: feature_id1, feature_id2")
        cf_lines.append("You can also use the feature type as shorthand: HIGHLIGHT_FEATURES: fillet1 (fuzzy matching is supported).")
        cf_lines.append("Use color names in text (e.g. \"the green holes\"), not feature IDs.")
        cf_lines.append("The 3D model starts gray \u2014 your highlight reveals the feature's color.")
        parts.append("\n".join(cf_lines))

    # ── ASSEMBLY ──
    available_parts = inspection_context.get("available_parts", [])
    if available_parts:
        ap_lines = ["AVAILABLE PARTS IN THIS ASSEMBLY (you can highlight any of these in 3D):"]
        for ap in available_parts:
            pn = ap.get("part_number", "")
            desc = ap.get("description", "")
            color_name = ap.get("color_name", "")
            label = pn
            if desc:
                label += f" \u2014 {desc}"
            if color_name:
                label += f" [{color_name}]"
            c = ap.get("centroid_mm")
            if c and len(c) > 0:
                if len(c) == 1:
                    p = c[0]
                    label += f" [pos: {p[0]}, {p[1]}, {p[2]} mm]"
                else:
                    label += f" [{len(c)} instances, distributed]"
            ap_lines.append(f"- {label}")
        ap_lines.append(
            "To highlight parts in your response, end with a line: "
            "HIGHLIGHT_PARTS: part_number1, part_number2"
        )
        parts.append("\n".join(ap_lines))

    # Part physical properties for semantic search
    part_properties = inspection_context.get("part_properties", [])
    if part_properties:
        pp_lines = ["PART PHYSICAL PROPERTIES (use for semantic search queries like \"find parts with 30mm holes\"):"]
        for pp in part_properties:
            pn = pp.get("part_number", "")
            desc = pp.get("description", "")
            label = f"  {pn}"
            if desc:
                label += f" ({desc})"
            label += ":"
            attrs = []
            if "mass_kg" in pp:
                m = pp["mass_kg"]
                if m < 0.1:
                    attrs.append(f"{round(m * 1000, 1)}g")
                else:
                    attrs.append(f"{m}kg")
            if "material" in pp:
                attrs.append(pp["material"])
            if "bbox_mm" in pp:
                b = pp["bbox_mm"]
                attrs.append(f"bbox {b[0]}x{b[1]}x{b[2]}mm")
            holes = pp.get("holes")
            if holes:
                h_str = f"{holes['count']} hole(s) d={holes['diameters_mm']}mm"
                if holes.get("through_count"):
                    h_str += f", {holes['through_count']} through"
                if holes.get("threads"):
                    h_str += f", threads: {holes['threads']}"
                attrs.append(h_str)
            feat = pp.get("features")
            if feat:
                feat_strs = [f"{v} {k}" for k, v in feat.items()]
                attrs.append("features: " + ", ".join(feat_strs))
            label += " " + " | ".join(attrs)
            pp_lines.append(label)
        parts.append("\n".join(pp_lines))

    # Nearby parts (pre-computed proximity for selected parts)
    nearby_parts = inspection_context.get("nearby_parts", {})
    if nearby_parts:
        np_lines = ["NEARBY PARTS (pre-computed min distances from selected):"]
        for sel_pn, neighbors in nearby_parts.items():
            np_lines.append(f"  Near {sel_pn}:")
            for nb in neighbors:
                inst = f" ({nb['instances']} instances)" if nb.get('instances', 1) > 1 else ""
                np_lines.append(f"    - {nb['part_number']} ({nb.get('description', '')}){inst}: {nb['distance_mm']} mm away")
        parts.append("\n".join(np_lines))

    # Mate relationships (how parts are connected)
    mate_rels = inspection_context.get("mate_relationships", [])
    if mate_rels:
        mr_lines = ["MATE RELATIONSHIPS (how parts are mechanically connected):"]
        for rel in mate_rels[:MAX_MATE_LINES]:
            c1 = rel.get("component1", "")
            c1f = rel.get("component1FileName", "")
            c2 = rel.get("component2", "")
            c2f = rel.get("component2FileName", "")
            count = rel.get("mateCount", 0)
            reqs = rel.get("inspectionRequirements", [])
            line = f"  - {c1} ({c1f}) ↔ {c2} ({c2f}): {count} mate(s)"
            if reqs:
                line += f" — {'; '.join(reqs[:2])}"
            mr_lines.append(line)
        mr_lines.append("Use mate relationships to understand what moves together, what constrains what, and disassembly order.")
        parts.append("\n".join(mr_lines))

    # SolidWorks explode steps (for disassembly ordering)
    explode_steps = inspection_context.get("explode_steps", [])
    if explode_steps:
        es_lines = ["SOLIDWORKS EXPLODE STEPS (use this EXACT order for disassembly — do NOT invent your own order):"]
        # Build partDataKey → part_number lookup from legend
        _legend = inspection_context.get("part_color_legend", [])
        _file_to_pn = {}
        for item in _legend:
            stem = Path(item["old_key"]).stem.lower()
            _file_to_pn[stem] = item.get("part_number", stem)
        for step in explode_steps:
            fns = step.get("componentFileNames", [])
            unique_files = list(dict.fromkeys(fns))  # dedupe preserving order
            part_names = []
            for fn in unique_files:
                stem = Path(fn).stem.lower()
                pn = _file_to_pn.get(stem, stem)
                desc = next((i.get("description", "") for i in _legend if i.get("part_number") == pn), "")
                part_names.append(f"{pn} ({desc})" if desc else pn)
            es_lines.append(f"  Step {step.get('stepIndex', 0) + 1}: {', '.join(part_names)}")
        es_lines.append("When asked for disassembly, follow this exact step order. Use the part numbers above in HIGHLIGHT_PARTS.")
        parts.append("\n".join(es_lines))

    # Paused walkthrough context (barge-in interruption)
    paused = inspection_context.get("paused_walkthrough")
    if paused:
        pw_lines = ["PAUSED WALKTHROUGH (the user interrupted a guided assembly tour to ask a question):"]
        pw_lines.append(f"  Paused at segment {paused.get('paused_at_segment', 0) + 1} of {paused.get('total_segments', 0)}")
        seg_text = paused.get("current_segment_text", "")
        if seg_text:
            pw_lines.append(f"  Currently discussing: {seg_text[:200]}")
        hl_parts = paused.get("current_highlight_parts", [])
        if hl_parts:
            pw_lines.append(f"  Currently highlighted parts: {', '.join(hl_parts)}")
        pw_lines.append("Answer the user's question concisely (max 3 sentences). They may say 'continue' to resume the tour.")
        parts.append("\n".join(pw_lines))

    # ── COMPARE ──
    part_feature_diff = inspection_context.get("part_feature_diff")
    if part_feature_diff:
        pfd_lines = [f"PART FEATURE CHANGES (Rev {part_feature_diff.get('revA', '?')} \u2192 Rev {part_feature_diff.get('revB', '?')}):"]
        pfd_lines.append(f"Summary: {part_feature_diff.get('summary', 'No changes')}")

        changed = part_feature_diff.get("changed_features", {})
        if changed:
            pfd_lines.append("COMPARE PAIRS (use pair_id in COMPARE_FEATURES marker):")
            for i, (fid, info) in enumerate(changed.items()):
                pair_id = f"pair_{i}"
                label_a = info.get("display_label_a", fid)
                label_b = info.get("display_label_b", fid)
                color = info.get("color_name", "")
                # Omit color label when compare mode is active (viewers are gray)
                color_suffix = "" if (inspection_context.get("compare_mode_available") or inspection_context.get("part_compare_active")) else f" [{color}]"
                pfd_lines.append(f"  {pair_id}: MODIFIED \u2014 {info.get('changes', {}).get('display_label', {}).get('old', label_a)} \u2192 {info.get('changes', {}).get('display_label', {}).get('new', label_b)}{color_suffix}")
                for field, change in info.get("changes", {}).items():
                    if field == "parameters":
                        for param_name, param_change in change.items():
                            pfd_lines.append(f"    param {param_name}: {param_change.get('old', '?')} \u2192 {param_change.get('new', '?')}")
                    elif field != "display_label":
                        pfd_lines.append(f"    {field}: {change.get('old')} \u2192 {change.get('new')}")

        modified = part_feature_diff.get("modified_features", {})
        if modified:
            pfd_lines.append("MODIFIED FEATURES (same feature, changed between revisions):")
            for mod_id, info in modified.items():
                label_a = info.get("display_label_a", "")
                label_b = info.get("display_label_b", "")
                ftype = info.get("type", "")
                color_a = info.get("color_name_a", "")
                color_b = info.get("color_name_b", "")
                if inspection_context.get("compare_mode_available") or inspection_context.get("part_compare_active"):
                    pfd_lines.append(f"  {mod_id}: {ftype} — {label_a} → {label_b}")
                else:
                    pfd_lines.append(f"  {mod_id}: {ftype} — {label_a} [{color_a}] → {label_b} [{color_b}]")
                for field, change in info.get("changes", {}).items():
                    if field == "parameters":
                        for param_name, param_change in change.items():
                            pfd_lines.append(f"    param {param_name}: {param_change.get('old', '?')} → {param_change.get('new', '?')}")
                    else:
                        pfd_lines.append(f"    {field}: {change.get('old')} → {change.get('new')}")

        added = part_feature_diff.get("added_features", [])
        if added:
            pfd_lines.append("ADDED FEATURES (new in Rev B):")
            for feat in added:
                fid = feat.get("cad_feature_id", feat) if isinstance(feat, dict) else feat
                label = feat.get("display_label", fid) if isinstance(feat, dict) else fid
                ftype = feat.get("type", "") if isinstance(feat, dict) else ""
                color = feat.get("color_name", "") if isinstance(feat, dict) else ""
                color_suffix = "" if (inspection_context.get("compare_mode_available") or inspection_context.get("part_compare_active")) else f" [{color}]"
                pfd_lines.append(f"  added_{fid}: {label} ({ftype}){color_suffix}")

        removed = part_feature_diff.get("removed_features", [])
        if removed:
            pfd_lines.append("REMOVED FEATURES (was in Rev A, gone in Rev B):")
            for feat in removed:
                fid = feat.get("cad_feature_id", feat) if isinstance(feat, dict) else feat
                label = feat.get("display_label", fid) if isinstance(feat, dict) else fid
                ftype = feat.get("type", "") if isinstance(feat, dict) else ""
                color = feat.get("color_name", "") if isinstance(feat, dict) else ""
                color_suffix = "" if (inspection_context.get("compare_mode_available") or inspection_context.get("part_compare_active")) else f" [{color}]"
                pfd_lines.append(f"  removed_{fid}: {label} ({ftype}){color_suffix}")

        # Build category-specific marker lists so the agent can select the right ones
        removed_markers = []
        if removed:
            for feat in removed:
                fid = feat.get("cad_feature_id", feat) if isinstance(feat, dict) else feat
                removed_markers.append(f"removed_{fid}")
        added_markers = []
        if added:
            for feat in added:
                fid = feat.get("cad_feature_id", feat) if isinstance(feat, dict) else feat
                added_markers.append(f"added_{fid}")
        modified_markers = []
        if changed:
            for i in range(len(changed)):
                modified_markers.append(f"pair_{i}")
        if modified:
            for mod_id in modified:
                modified_markers.append(mod_id)
        all_markers = removed_markers + added_markers + modified_markers

        pfd_lines.append("COMPARE_FEATURES USAGE — emit ONLY the markers relevant to the user's question:")
        if removed_markers:
            pfd_lines.append(f"  For REMOVED features only: COMPARE_FEATURES: {', '.join(removed_markers)}")
        if added_markers:
            pfd_lines.append(f"  For ADDED features only: COMPARE_FEATURES: {', '.join(added_markers)}")
        if modified_markers:
            pfd_lines.append(f"  For MODIFIED/CHANGED features only: COMPARE_FEATURES: {', '.join(modified_markers)}")
        if all_markers:
            pfd_lines.append(f"  For ALL changes at once: COMPARE_FEATURES: {', '.join(all_markers)}")
        pfd_lines.append("IMPORTANT: Only highlight what the user asked about. If they ask 'what was removed', emit ONLY the removed markers. If they ask 'what was added', emit ONLY the added markers. If they ask 'show all differences', emit ALL markers.")
        if not all_markers:
            pfd_lines.append("  No changes to highlight.")
        if inspection_context.get("part_compare_active"):
            pfd_lines.append("Refer to features by display labels only, not IDs. Do NOT reference feature colors (blue, red, green, etc.) — both viewers are gray in compare mode.")
        else:
            pfd_lines.append("Refer to features by display labels and colors in text, not IDs.")
        parts.append("\n".join(pfd_lines))

    # Revision diff context (assembly compare mode)
    revision_diff = inspection_context.get("revision_diff")
    if revision_diff:
        rd_lines = [f"REVISION CHANGES (Rev {revision_diff.get('revA', '?')} \u2192 Rev {revision_diff.get('revB', '?')}):"]
        rd_lines.append(f"Summary: {revision_diff.get('summary', 'No changes')}")

        changed = revision_diff.get("changed_parts", {})
        if changed:
            rd_lines.append("CHANGED PARTS:")
            for pn, changes in list(changed.items())[:10]:
                desc = changes.get("description", "")
                line_parts = [f"  {pn} ({desc}):"]
                dims = changes.get("dimensions_changed", [])
                for d in dims[:5]:
                    old_f = d.get("old", {})
                    new_f = d.get("new", {})
                    if old_f and new_f:
                        old_val = round(old_f.get("value", 0) * 1000, 3)
                        new_val = round(new_f.get("value", 0) * 1000, 3)
                        delta = round(d.get("delta_value", 0) * 1000, 3)
                        line_parts.append(f"dim {old_val}mm \u2192 {new_val}mm (\u0394{delta}mm)")
                phys = changes.get("physical_changed") or {}
                if "mass" in phys:
                    m = phys["mass"]
                    old_g = round(m["old"] * 1000, 1)
                    new_g = round(m["new"] * 1000, 1)
                    line_parts.append(f"mass {old_g}g \u2192 {new_g}g ({m['delta_pct']}%)")
                feats = changes.get("features_changed", [])
                for fc in feats[:3]:
                    line_parts.append(fc.get("details", ""))
                rd_lines.append(" ".join(line_parts))

        added = revision_diff.get("added_parts", [])
        if added:
            rd_lines.append("ADDED PARTS: " + ", ".join(added))

        removed = revision_diff.get("removed_parts", [])
        if removed:
            rd_lines.append("REMOVED PARTS: " + ", ".join(removed))

        mate_changes = revision_diff.get("mates_changed", [])
        mate_added = revision_diff.get("mates_added", [])
        mate_removed = revision_diff.get("mates_removed", [])
        if mate_changes or mate_added or mate_removed:
            rd_lines.append("MATE CHANGES:")
            for mc in mate_changes[:5]:
                rd_lines.append(f"  Modified: {mc.get('description', '')}")
            for ma in mate_added[:5]:
                rd_lines.append(f"  Added: {ma.get('description', '')}")
            for mr in mate_removed[:5]:
                rd_lines.append(f"  Removed: {mr.get('description', '')}")

        # COMPARE_PARTS markers for dual-viewport assembly revision comparison
        compare_available = inspection_context.get("compare_mode_available", False)
        compare_active = inspection_context.get("compare_mode_active", False)

        if compare_available:
            # Build category-specific COMPARE_PARTS marker lists
            cp_removed = [f"removed_{pn}" for pn in removed] if removed else []
            cp_added = [f"added_{pn}" for pn in added] if added else []
            cp_changed = [f"changed_{pn}" for pn in changed.keys()] if changed else []
            cp_all = cp_removed + cp_added + cp_changed

            rd_lines.append("")
            rd_lines.append("COMPARE_PARTS USAGE (dual viewport revision comparison):")
            rd_lines.append("YOU MUST emit a COMPARE_PARTS: line at the end of EVERY revision-related response. This is NOT optional.")
            rd_lines.append("The COMPARE_PARTS line highlights parts on the dual Rev A / Rev B viewports.")
            if not compare_active:
                rd_lines.append("The compare view will auto-open automatically.")
            if cp_removed:
                rd_lines.append(f"  For REMOVED parts only: COMPARE_PARTS: {', '.join(cp_removed)}")
            if cp_added:
                rd_lines.append(f"  For ADDED parts only: COMPARE_PARTS: {', '.join(cp_added)}")
            if cp_changed:
                rd_lines.append(f"  For MODIFIED/CHANGED parts only: COMPARE_PARTS: {', '.join(cp_changed)}")
            if cp_all:
                rd_lines.append(f"  For ALL changes at once: COMPARE_PARTS: {', '.join(cp_all)}")
            rd_lines.append("CRITICAL: Only emit markers for the SPECIFIC category the user asked about.")
            rd_lines.append("  'what was removed' → ONLY removed_* markers. 'what was added' → ONLY added_* markers.")
            rd_lines.append("  'what changed' → ONLY changed_* markers. 'show all differences' → ALL markers.")
            rd_lines.append("IMPORTANT: In compare mode, do NOT reference part colors (red, green, blue, etc.) from the 3D model color legend.")
            rd_lines.append("Both viewers are gray. Only the compare highlighting colors matter: red=removed, green=added, amber=changed.")

        if not compare_available:
            # Single-view: keep existing HIGHLIGHT_PARTS behavior
            rd_lines.append("Use HIGHLIGHT_PARTS: part_number to highlight individual parts on the single viewer when discussing them.")

        parts.append("\n".join(rd_lines))

    # ── GEOMETRY DIFF ──
    geo_diff = inspection_context.get("geometry_diff")
    if geo_diff and not geo_diff.get("identical", True):
        gd_lines = ["GEOMETRY DIFF (solid-body comparison between part revisions):"]
        gd_lines.append(f"  Part: {geo_diff.get('part_number', '?')} Rev {geo_diff.get('revA', '?')} vs Rev {geo_diff.get('revB', '?')}")
        gd_lines.append(f"  Rev A volume: {geo_diff.get('volume_a_mm3', 0):.1f} mm³")
        gd_lines.append(f"  Rev B volume: {geo_diff.get('volume_b_mm3', 0):.1f} mm³")
        removed = geo_diff.get("removed_volume_mm3", 0)
        added = geo_diff.get("added_volume_mm3", 0)
        net = geo_diff.get("net_change_mm3", 0)
        if removed > 0.001:
            gd_lines.append(f"  Material REMOVED: {removed:.1f} mm³")
        if added > 0.001:
            gd_lines.append(f"  Material ADDED: {added:.1f} mm³")
        gd_lines.append(f"  Net change: {'+' if net >= 0 else ''}{net:.1f} mm³")
        centroids = geo_diff.get("changed_centroids", [])
        for c in centroids:
            ctype = c.get("type", "?")
            pos = c.get("centroid", [0, 0, 0])
            vol = c.get("volume_mm3", 0)
            gd_lines.append(f"  {ctype.upper()} region: {vol:.1f} mm³ at ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}) mm")
        warnings = geo_diff.get("import_warnings", [])
        if warnings:
            gd_lines.append(f"  Import warnings: {'; '.join(warnings)}")
        gd_lines.append("")
        gd_lines.append("Use this data to explain the engineering impact of the geometry changes.")
        gd_lines.append("Reference the volume, location, and type (added/removed) in your answer.")
        gd_lines.append("If the user asks about the diff, you have the exact data — do not guess.")
        gd_lines.append("Answer geometry diff questions from this section even if no part feature diff or assembly revision diff is present.")
        gd_lines.append("To show the overlays on the 3D model, emit SHOW_GEOMETRY_DIFF on its own line at the end of your response.")
        parts.append("\n".join(gd_lines))

    # FAI characteristics table state (for chat-driven fill commands)
    fai_chars = inspection_context.get("fai_characteristics", [])
    if fai_chars:
        fai_lines = ["FAI TABLE (First Article Inspection characteristics currently loaded):"]
        for c in fai_chars[:30]:
            cn = c.get("char_number", "?")
            desc = c.get("description", "")
            nom = c.get("nominal")
            tp = c.get("tol_plus")
            tm = c.get("tol_minus")
            meas = c.get("measured")
            status = c.get("status", "PENDING")
            line = f"  #{cn}: {desc} — nominal={nom}"
            if tp is not None and tm is not None:
                line += f" tol=+{tp}/-{tm}"
            if meas:
                line += f" measured={meas} [{status}]"
            else:
                line += " [PENDING]"
            fai_lines.append(line)
        fai_lines.append("")
        fai_lines.append("FAI CHAT COMMANDS:")
        fai_lines.append("When the user provides measurement values or tolerances via chat or voice, you MUST emit FAI_FILL or FAI_TOL markers.")
        fai_lines.append("To fill measured values: FAI_FILL: #1: 25.003, #2: 25.001, #5: 12.450")
        fai_lines.append("To fill ALL rows with the same value: FAI_FILL: #all: 25.003")
        fai_lines.append("To set tolerances: FAI_TOL: #1: 0.013, #2: 0.050")
        fai_lines.append("To set ALL tolerances: FAI_TOL: #all: 0.013")
        fai_lines.append("Match the user's description to the characteristic descriptions above to determine which rows to fill.")
        fai_lines.append("Example: 'all bores measured 25.003' → find chars with 'bore' or '⌀' in description, fill those.")
        fai_lines.append("Example: 'set tolerance to plus minus 13 thou' → 13 thou = 0.3302mm → FAI_TOL: #all: 0.3302")
        fai_lines.append("Example: 'characteristic 5 is 12.45' → FAI_FILL: #5: 12.450")
        fai_lines.append("Always confirm what you filled in your text response (e.g. 'Filled 4 bore measurements with 25.003mm').")
        parts.append("\n".join(fai_lines))

    # ── STATUS ──
    has_drawing = bool(inspection_context.get("has_drawing_file"))
    has_part = bool(inspection_context.get("has_part_number"))
    in_progress = bool(inspection_context.get("inspection_in_progress"))
    can_run = bool(inspection_context.get("inspection_can_run"))

    status_lines = []
    if can_run:
        status_lines.append("INSPECTION READY: Drawing and part number are set. You can emit RUN_INSPECTION if the user asks.")
    else:
        if not has_drawing:
            status_lines.append("NO DRAWING: Tell user to upload a drawing file first.")
        if not has_part:
            status_lines.append("NO PART: Tell user to select a part number first.")
        if in_progress:
            status_lines.append("INSPECTION RUNNING: Tell user to wait for current inspection to finish.")
    if status_lines:
        parts.append("\n".join(status_lines))

    return "\n\n".join(parts)


def _clean_agent_response(text: str) -> str:
    """Strip markdown report formatting to keep agent responses conversational."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.lstrip()
        # Remove markdown headers — turn "## Foo" into "Foo"
        if stripped.startswith("#"):
            line = re.sub(r'^#{1,4}\s*', '', stripped)
            if not line:
                continue
        # Remove leading bullet dashes — turn "- Foo" into "Foo"
        if stripped.startswith("- ") or stripped.startswith("* "):
            line = stripped[2:]
        # Remove numbered list prefix — turn "1. Foo" into "Foo"
        if re.match(r'^\d+\.\s', stripped):
            line = re.sub(r'^\d+\.\s', '', stripped)
        cleaned.append(line)
    # Collapse triple+ newlines into double
    result = "\n".join(cleaned)
    result = re.sub(r'\n{3,}', '\n\n', result)
    return result.strip()


@app.post("/api/agent/chat")
async def agent_chat(request: AgentChatRequest):
    """Chat with the InspectorPro Agent (ASME expert powered by Claude)."""
    try:
        import anthropic
    except ImportError:
        raise HTTPException(status_code=500, detail="Anthropic SDK not installed")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured. Set it in your .env file.")

    # Validate agent_type
    if request.agent_type not in AGENT_PROMPTS:
        raise HTTPException(status_code=400, detail=f"Invalid agent_type: '{request.agent_type}'. Must be one of: inspector, deviation-analyst, parts-finder")

    # Select system prompt based on agent_type
    system_prompt = AGENT_PROMPTS[request.agent_type]

    try:
        client = anthropic.Anthropic(api_key=api_key)

        # Merge inspection_context from either field name, then normalize
        raw_ctx = request.inspection_context or request.context or {}
        normalized = normalize_agent_context(raw_ctx)
        ctx = normalized["flat"]  # flat dict with all legacy keys

        # Enrich with proximity — Sage only, first 2 selected parts
        if request.agent_type == 'deviation-analyst':
            selected = ctx.get("selected_parts", [])
            available = ctx.get("available_parts", [])
            if selected and available and any(ap.get("centroid_mm") for ap in available):
                focus_pns = []
                for sp in selected:
                    pn = sp.get("part_number", "")
                    if pn and pn not in focus_pns:
                        focus_pns.append(pn)
                    if len(focus_pns) >= 2:
                        break
                if focus_pns:
                    nearby = _compute_nearby_parts(available, set(focus_pns))
                    if nearby:
                        ctx["nearby_parts"] = nearby

        # Build context message
        context_text = _build_context_message(ctx)

        # Prepend cross-agent context if provided (summary from a prior agent conversation)
        if request.cross_agent_context:
            context_text = f"=== CONTEXT FROM PRIOR AGENT CONVERSATION ===\n{request.cross_agent_context}\n\n{context_text}"

        # Extra vision images populated by agent-specific context builders
        extra_vision_images = []

        # Agent-type-specific context enrichment (Feature #132)
        if request.agent_type == "parts-finder":
            # Add part specification context for sourcing
            pn = ctx.get("part_number", "")
            if pn:
                safe_pn = re.sub(r'[^\w\-]', '', pn)
                profile_path = Path("400S_Sorted_Library") / f"{safe_pn}.json"
                if not profile_path.exists():
                    profile_path = Path("400S_Sorted_Library") / f"{safe_pn}_inspection_profile.json"
                if profile_path.exists():
                    try:
                        with open(profile_path, "r", encoding="utf-8-sig") as f:
                            profile = json.load(f)
                        spec_parts = ["=== PART SPECIFICATIONS FOR SOURCING ==="]
                        spec_parts.append(f"Part: {profile.get('part_number', pn)}")
                        spec_parts.append(f"Name: {profile.get('part_name', '')}")
                        spec_parts.append(f"Description: {profile.get('part_description', '')}")
                        for feat in profile.get("features", []):
                            spec_parts.append(f"- {feat.get('name', '')}: {feat.get('type', '')} (qty: {feat.get('count', 1)})")
                            if feat.get("spatial_description"):
                                spec_parts.append(f"  {feat['spatial_description'][:150]}")
                        context_text += "\n\n" + "\n".join(spec_parts)
                    except Exception as e:
                        logger.warning(f"Failed to load profile for parts-finder context: {e}")

                # Add assembly context for procurement (Feature #154)
                if pn in assembly_part_lookup:
                    assy_num = assembly_part_lookup[pn][0]
                    assy_data = assembly_profiles.get(assy_num, {})
                    sc_parts = ["=== ASSEMBLY CONTEXT FOR PROCUREMENT ==="]

                    # Assembly identity and scale
                    assy_identity = assy_data.get("identity", {})
                    sc_parts.append(f"Assembly: {assy_identity.get('description', assy_num)} ({assy_num})")
                    stats = assy_data.get("statistics", {})
                    sc_parts.append(f"Components: {stats.get('totalComponents', 0)}, Mates: {stats.get('totalMates', 0)}")

                    # Resolve part aliases (same pattern as Sage, lines 1000-1013)
                    part_aliases = {pn}
                    pdc = assy_data.get("partDataCache", {})
                    for old_key, pd in pdc.items():
                        old_stem = Path(old_key).stem
                        new_pn = (pd.get("identity") or {}).get("partNumber", "")
                        if pn == new_pn or pn == old_stem:
                            part_aliases.add(old_stem)
                            part_aliases.add(new_pn)
                            base = re.sub(r'_\d+$', '', old_stem)
                            part_aliases.add(base)
                    part_aliases.discard("")

                    # Part description from partDataCache
                    for old_key, pd in pdc.items():
                        pd_id = pd.get("identity") or {}
                        if pd_id.get("partNumber", "") in part_aliases or Path(old_key).stem in part_aliases:
                            desc = pd_id.get("description", "")
                            if desc:
                                sc_parts.append(f"Part role: {desc}")
                            break

                    # Filtered mates — show what this part connects to
                    all_mates = assy_data.get("mates", [])
                    mate_lines = []
                    for mate in all_mates:
                        e1 = mate.get("entity1", {}).get("componentName", "")
                        e2 = mate.get("entity2", {}).get("componentName", "")
                        if _component_matches_aliases(e1, part_aliases) or _component_matches_aliases(e2, part_aliases):
                            mate_lines.append(f"- {mate.get('type', 'unknown')}: {e1} ↔ {e2}")
                            if len(mate_lines) >= MAX_MATE_LINES:
                                break
                    if mate_lines:
                        sc_parts.append("\nMATING CONSTRAINTS (replacement must satisfy these fits):")
                        sc_parts.extend(mate_lines)

                    # Functional narrative — procurement-relevant sections only
                    narrative = assy_data.get("functionalNarrative", {})
                    if narrative:
                        sc_parts.append("\nFUNCTIONAL CONTEXT:")
                        for section_key in ["assemblyOverview", "criticalInterfaces"]:
                            section_data = narrative.get(section_key)
                            if section_data:
                                sc_parts.append(f"[{section_key}]")
                                if isinstance(section_data, str):
                                    sc_parts.append(section_data[:500])
                                elif isinstance(section_data, dict):
                                    for k, v in section_data.items():
                                        sc_parts.append(f"  {k}: {str(v)[:300]}")
                                elif isinstance(section_data, list):
                                    for item in section_data[:10]:
                                        sc_parts.append(f"  - {str(item)[:200]}")

                    sc_parts.append("\nWhen sourcing replacements, ensure compatibility with the above mating constraints and assembly function.")
                    context_text += "\n\n" + "\n".join(sc_parts)

        # Agent-type-specific context enrichment (Feature #131)
        elif request.agent_type == "deviation-analyst":
            # Add assembly context for deviation analysis
            pn = ctx.get("part_number", "")
            if pn and pn in assembly_part_lookup:
                assy_num = assembly_part_lookup[pn][0]
                assy_data = assembly_profiles.get(assy_num, {})

                da_parts = ["=== ASSEMBLY CONTEXT FOR DEVIATION ANALYSIS ==="]
                assy_identity = assy_data.get("identity", {})
                da_parts.append(f"Assembly: {assy_identity.get('description', assy_num)} ({assy_num})")
                stats = assy_data.get("statistics", {})
                da_parts.append(f"Components: {stats.get('totalComponents', 0)}, Mates: {stats.get('totalMates', 0)}")

                # Build set of all aliases for this part (old filenames + new PN)
                # so mate filtering works regardless of naming convention
                part_aliases = {pn}
                pdc = assy_data.get("partDataCache", {})
                for old_key, pd in pdc.items():
                    old_stem = Path(old_key).stem  # "022-807" from "022-807.sldprt"
                    new_pn = (pd.get("identity") or {}).get("partNumber", "")
                    if pn == new_pn or pn == old_stem:
                        part_aliases.add(old_stem)
                        part_aliases.add(new_pn)
                        # Also add without config suffix: "022-807_2" -> "022-807"
                        base = re.sub(r'_\d+$', '', old_stem)
                        part_aliases.add(base)
                part_aliases.discard("")
                da_parts.append(f"Part aliases: {', '.join(sorted(part_aliases))}")

                # Filter mates involving this part
                all_mates = assy_data.get("mates", [])
                da_parts.append("\nMATES involving this part:")
                mate_count = 0
                for mate in all_mates:
                    e1 = mate.get("entity1", {}).get("componentName", "")
                    e2 = mate.get("entity2", {}).get("componentName", "")
                    if _component_matches_aliases(e1, part_aliases) or _component_matches_aliases(e2, part_aliases):
                        mate_type = mate.get("type", "unknown")
                        da_parts.append(f"- {mate_type}: {e1} \u2194 {e2}")
                        mate_count += 1
                        if mate_count >= MAX_MATE_LINES:
                            break
                if mate_count == 0:
                    da_parts.append("- (no direct mates found)")

                # Color assignments — resolve old filenames to new part numbers
                colors = assy_data.get("partColorMapping", assy_data.get("colorAssignments", {}))
                if colors:
                    da_parts.append("\nCOLOR ASSIGNMENTS (reference views):")
                    for old_key, color_val in colors.items():
                        color_hex = color_val if isinstance(color_val, str) else color_val.get("color", "unknown")
                        # Resolve to new part number + description
                        pd_identity = (pdc.get(old_key, {}).get("identity") or {})
                        new_pn = pd_identity.get("partNumber", "")
                        desc = pd_identity.get("description", "")
                        label = f"{new_pn} ({desc})" if new_pn else old_key
                        is_current = " ← THIS PART" if any(a in old_key or a == new_pn for a in part_aliases) else ""
                        da_parts.append(f"- {label}: {color_hex}{is_current}")

                # Select functional narrative sections based on question keywords
                narrative = assy_data.get("functionalNarrative", {})
                if narrative:
                    msg_lower = request.message.lower()
                    sections_to_include = []

                    if any(kw in msg_lower for kw in ["can i use", "accept", "reject", "rework", "scrap", "use-as-is"]):
                        sections_to_include = ["criticalInterfaces", "inspectionPriorities"]
                    elif any(kw in msg_lower for kw in ["what does", "function", "role", "purpose"]):
                        sections_to_include = ["assemblyOverview", "structuralRelationships"]
                    elif any(kw in msg_lower for kw in ["critical", "important", "priority"]):
                        sections_to_include = ["inspectionPriorities", "assemblyLevelMachining"]
                    elif any(kw in msg_lower for kw in ["mate", "connect", "attach", "join"]):
                        sections_to_include = ["structuralRelationships", "colorToPartReference"]
                    else:
                        # Default: include all available sections
                        sections_to_include = list(narrative.keys())

                    da_parts.append("\nFUNCTIONAL NARRATIVE:")
                    for section_key in sections_to_include:
                        section_data = narrative.get(section_key)
                        if section_data:
                            da_parts.append(f"\n[{section_key}]")
                            if isinstance(section_data, str):
                                da_parts.append(section_data[:500])
                            elif isinstance(section_data, dict):
                                for k, v in section_data.items():
                                    da_parts.append(f"  {k}: {str(v)[:300]}")
                            elif isinstance(section_data, list):
                                for item in section_data[:10]:
                                    da_parts.append(f"  - {str(item)[:200]}")

                context_text += "\n\n" + "\n".join(da_parts)

                # Load assembly view images for vision context
                assemblies_dir = Path("400S_Sorted_Library/assemblies")
                assy_views = []
                for view_name in ["front", "top", "right", "isometric"]:
                    img_path = assemblies_dir / f"{assy_num}_view_{view_name}.png"
                    if img_path.exists():
                        try:
                            b64 = base64.standard_b64encode(img_path.read_bytes()).decode("utf-8")
                            assy_views.append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": b64,
                                }
                            })
                        except Exception as e:
                            logger.warning(f"Failed to load assembly view {img_path}: {e}")

                extra_vision_images = assy_views

        # RAG images: only for inspector and deviation-analyst, not parts-finder (Feature #132)
        if request.agent_type != "parts-finder":
            rag_dirs = _find_relevant_rag_dirs(request.message, ctx)
            rag_images = _load_rag_images(rag_dirs, max_images=4)
            logger.info(f"Agent chat: loaded {len(rag_images)} RAG images from {rag_dirs}")
        else:
            rag_images = []
            logger.info("Agent chat: parts-finder agent — skipping RAG images")

        # Build message history for Claude
        messages = []

        # Add conversation history
        for msg in (request.history or []):
            role = msg.get("role", "user")
            content = msg.get("content") or msg.get("text", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

        # Build current user message with context + RAG images
        user_content = []

        # Add RAG reference images first (sent as context, not returned to frontend)
        if rag_images:
            user_content.append({
                "type": "text",
                "text": "=== ASME Y14.5 REFERENCE MATERIAL (use to ground your answer) ==="
            })
            user_content.extend(rag_images)

        # Add assembly view images for deviation-analyst (Feature #131)
        if extra_vision_images:
            user_content.append({
                "type": "text",
                "text": "=== COLOR-CODED ASSEMBLY REFERENCE VIEWS (showing how this part fits) ==="
            })
            user_content.extend(extra_vision_images)

        # Add inspection context
        if context_text:
            user_content.append({
                "type": "text",
                "text": f"=== CURRENT INSPECTION CONTEXT ===\n{context_text}"
            })

        # Add user-attached screenshot (from camera button)
        if request.image:
            # Strip data URL prefix if present (e.g., "data:image/png;base64,...")
            img_data = request.image
            media_type = "image/png"
            if img_data.startswith("data:"):
                # Parse data URL: data:image/png;base64,AAAA...
                header, img_data = img_data.split(",", 1)
                if "image/jpeg" in header:
                    media_type = "image/jpeg"
                elif "image/webp" in header:
                    media_type = "image/webp"
            user_content.append({
                "type": "text",
                "text": "=== UPLOADED DRAWING (attached automatically) ==="
            })
            user_content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": img_data,
                }
            })

        # Add the actual user message
        user_content.append({
            "type": "text",
            "text": request.message
        })

        messages.append({"role": "user", "content": user_content})

        # Call Claude
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=2048,
            system=system_prompt,
            messages=messages,
        )

        # Extract text response
        response_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                response_text += block.text

        # Log raw response for debugging marker extraction
        logger.info(f"[Sage raw response] first 500 chars: {response_text[:500]}")
        logger.info(f"[Sage raw response] HIGHLIGHT_PARTS present: {'HIGHLIGHT_PARTS:' in response_text}, ISOLATE_PART present: {'ISOLATE_PART:' in response_text}")

        # Extract dimension highlight commands before cleaning
        highlight_dims = []
        hl_match = re.search(r'^HIGHLIGHT_DIMS:\s*(.+)$', response_text, re.MULTILINE)
        if hl_match:
            highlight_dims = [k.strip() for k in hl_match.group(1).split(",") if k.strip()]
            response_text = re.sub(r'^HIGHLIGHT_DIMS:\s*(.+)$', '', response_text, flags=re.MULTILINE).strip()

        # Extract view highlight commands before cleaning
        highlight_views = []
        hv_match = re.search(r'^HIGHLIGHT_VIEWS:\s*(.+)$', response_text, re.MULTILINE)
        if hv_match:
            highlight_views = [v.strip() for v in hv_match.group(1).split(",") if v.strip()]
            response_text = re.sub(r'^HIGHLIGHT_VIEWS:\s*(.+)$', '', response_text, flags=re.MULTILINE).strip()

        # Extract feature highlight commands (per-feature on single part 3D model)
        highlight_features = []
        hf_match = re.search(r'^HIGHLIGHT_FEATURES?:\s*(.+)$', response_text, re.MULTILINE)
        if hf_match:
            available_feature_ids = set()
            if ctx:
                for feat in ctx.get("available_cad_features", []):
                    available_feature_ids.add(feat.get("cad_feature_id", ""))
            raw_features = [f.strip() for f in hf_match.group(1).split(",") if f.strip()]
            if available_feature_ids:
                # Exact match first
                highlight_features = [f for f in raw_features if f in available_feature_ids]
                # Fuzzy fallback: match by substring or type keyword for any unmatched
                if len(highlight_features) < len(raw_features):
                    unmatched = [f for f in raw_features if f not in available_feature_ids]
                    def _slug(s):
                        """Normalize a string for fuzzy matching: lowercase, strip all non-alphanumeric."""
                        return re.sub(r'[^a-z0-9]', '', s.lower())
                    for um in unmatched:
                        um_slug = _slug(um)
                        for avail_id in available_feature_ids:
                            if avail_id in highlight_features:
                                continue
                            avail_slug = _slug(avail_id)
                            # Substring match in either direction
                            if um_slug in avail_slug or avail_slug in um_slug:
                                highlight_features.append(avail_id)
                            # Type keyword match: "fillet" matches any ID starting with "fillet"
                            elif avail_slug.startswith(um_slug):
                                highlight_features.append(avail_id)
                            # Plural stripping: "fillets" -> "fillet", "holes" -> "hole"
                            elif um_slug.endswith('s') and avail_slug.startswith(um_slug[:-1]):
                                highlight_features.append(avail_id)
                    highlight_features = list(dict.fromkeys(highlight_features))  # dedupe preserving order
            else:
                highlight_features = raw_features
            response_text = re.sub(r'^HIGHLIGHT_FEATURES?:\s*(.+)$', '', response_text, flags=re.MULTILINE).strip()

        # Extract compare features marker (dual-view part revision comparison)
        compare_features = []
        cf_match = re.search(r'^COMPARE_FEATURES:\s*(.+)$', response_text, re.MULTILINE)
        if cf_match:
            raw_pairs = [p.strip() for p in cf_match.group(1).split(',') if p.strip()]
            # Validate against the actual diff context
            part_diff = ctx.get("part_feature_diff", {}) if ctx else {}
            changed_keys = list(part_diff.get("changed_features", {}).keys())
            added_ids = set()
            removed_ids = set()
            for f in part_diff.get("added_features", []):
                fid = f.get("cad_feature_id", f) if isinstance(f, dict) else f
                added_ids.add(fid)
            for f in part_diff.get("removed_features", []):
                fid = f.get("cad_feature_id", f) if isinstance(f, dict) else f
                removed_ids.add(fid)
            modified_keys = set(part_diff.get("modified_features", {}).keys())
            for pid in raw_pairs:
                if pid.startswith("pair_"):
                    idx = int(pid.replace("pair_", "")) if pid.replace("pair_", "").isdigit() else -1
                    if 0 <= idx < len(changed_keys):
                        compare_features.append(pid)
                elif pid.startswith("mod_"):
                    if pid in modified_keys:
                        compare_features.append(pid)
                elif pid.startswith("added_"):
                    fid = pid.replace("added_", "", 1)
                    if fid in added_ids:
                        compare_features.append(pid)
                elif pid.startswith("removed_"):
                    fid = pid.replace("removed_", "", 1)
                    if fid in removed_ids:
                        compare_features.append(pid)
            dropped = [p for p in raw_pairs if p not in compare_features]
            if dropped:
                logger.warning(f"[Compare] Invalid COMPARE_FEATURES markers dropped: {dropped}")
            response_text = re.sub(r'^COMPARE_FEATURES:\s*(.+)$', '', response_text, flags=re.MULTILINE).strip()

        # Extract compare parts marker (dual-view assembly revision comparison)
        compare_parts = []
        cp_match = re.search(r'^COMPARE_PARTS:\s*(.+)$', response_text, re.MULTILINE)
        if cp_match:
            raw_parts = [p.strip() for p in cp_match.group(1).split(',') if p.strip()]
            rev_diff = ctx.get("revision_diff", {}) if ctx else {}
            valid_changed = set(rev_diff.get("changed_parts", {}).keys())
            valid_added = set(rev_diff.get("added_parts", []))
            valid_removed = set(rev_diff.get("removed_parts", []))
            for pid in raw_parts:
                if pid.startswith("changed_"):
                    pn = pid.replace("changed_", "", 1)
                    if pn in valid_changed:
                        compare_parts.append(pid)
                elif pid.startswith("added_"):
                    pn = pid.replace("added_", "", 1)
                    if pn in valid_added:
                        compare_parts.append(pid)
                elif pid.startswith("removed_"):
                    pn = pid.replace("removed_", "", 1)
                    if pn in valid_removed:
                        compare_parts.append(pid)
            dropped = [p for p in raw_parts if p not in compare_parts]
            if dropped:
                logger.warning(f"[Compare] Invalid COMPARE_PARTS markers dropped: {dropped}")
            if compare_parts:
                logger.info(f"[Compare] COMPARE_PARTS parsed OK: {compare_parts}")
            response_text = re.sub(r'^COMPARE_PARTS:\s*(.+)$', '', response_text, flags=re.MULTILINE).strip()

        # Log when agent omitted COMPARE_PARTS in revision-diff mode
        if not compare_parts and ctx and ctx.get("compare_mode_available") and ctx.get("revision_diff"):
            hp_check = re.search(r'^HIGHLIGHT_PARTS:', response_text, re.MULTILINE)
            if hp_check:
                logger.warning("[Compare] Agent emitted HIGHLIGHT_PARTS instead of COMPARE_PARTS in revision mode")
            else:
                logger.warning("[Compare] Agent did NOT emit COMPARE_PARTS despite revision_diff in context")

        # Extract part highlight commands before cleaning
        highlight_parts = []
        narration_segments = []

        # Hoist available_pns before multi/single split
        available_pns = set()
        if ctx:
            for ap in ctx.get("available_parts", []):
                available_pns.add(ap.get("part_number", ""))

        # Parse and strip CAMERA_VIEW before HIGHLIGHT_PARTS (so it doesn't leak into segment text)
        camera_view = None
        camera_pattern = re.compile(r'^CAMERA_VIEW:\s*(\w+)\s*$', re.MULTILINE)
        cam_match = camera_pattern.search(response_text)
        if cam_match:
            view = cam_match.group(1).lower()
            if view in ("front", "top", "right", "back", "bottom", "left"):
                camera_view = view
            response_text = camera_pattern.sub('', response_text).strip()

        # Parse EXPLODE_LEVEL markers (may be global or per-segment)
        explode_level = None
        explode_pattern = re.compile(r'^EXPLODE_LEVEL:\s*([\d.]+)\s*$', re.MULTILINE)

        parts_pattern = re.compile(r'^HIGHLIGHT_PARTS:\s*(.+)$', re.MULTILINE)
        matches = list(parts_pattern.finditer(response_text))

        if len(matches) > 1:
            # Multi-segment narration mode — extract per-segment EXPLODE_LEVEL
            segments = []
            intro = response_text[:matches[0].start()].strip()
            # Strip any EXPLODE_LEVEL from intro
            intro = explode_pattern.sub('', intro).strip()
            if intro:
                segments.append({"text": intro, "highlight_parts": []})
            for i, match in enumerate(matches):
                text_start = match.end()
                text_end = matches[i + 1].start() if i + 1 < len(matches) else len(response_text)
                seg_text = response_text[text_start:text_end].strip()
                raw_parts = [p.strip() for p in match.group(1).split(",") if p.strip()]
                valid_parts = [p for p in raw_parts if p in available_pns] if available_pns else raw_parts
                # Extract per-segment explode level
                seg_explode = None
                seg_explode_match = explode_pattern.search(seg_text)
                if seg_explode_match:
                    seg_explode = max(0.0, min(1.0, float(seg_explode_match.group(1))))
                    seg_text = explode_pattern.sub('', seg_text).strip()
                seg_data = {"text": seg_text, "highlight_parts": valid_parts}
                if seg_explode is not None:
                    seg_data["explode_level"] = seg_explode
                if seg_text or valid_parts:
                    segments.append(seg_data)
            narration_segments = segments
            response_text = parts_pattern.sub('', response_text).strip()
            response_text = explode_pattern.sub('', response_text).strip()
        elif len(matches) == 1:
            # Single-marker behavior (existing)
            raw_parts = [p.strip() for p in matches[0].group(1).split(",") if p.strip()]
            highlight_parts = [p for p in raw_parts if p in available_pns] if available_pns else raw_parts
            response_text = parts_pattern.sub('', response_text).strip()

        # Extract global EXPLODE_LEVEL (for non-narration single-marker or no-marker cases)
        if not narration_segments:
            explode_match = explode_pattern.search(response_text)
            if explode_match:
                explode_level = max(0.0, min(1.0, float(explode_match.group(1))))
                response_text = explode_pattern.sub('', response_text).strip()

        # Extract ISOLATE_PART marker
        isolate_parts = []
        isolate_pattern = re.compile(r'^ISOLATE_PART:\s*(.+)$', re.MULTILINE)
        isolate_match = isolate_pattern.search(response_text)
        if isolate_match:
            raw_value = isolate_match.group(1).strip()
            if raw_value.upper() == "RESET":
                isolate_parts = ["RESET"]
            else:
                raw_isolate = [p.strip() for p in raw_value.split(",") if p.strip()]
                isolate_parts = [p for p in raw_isolate if p in available_pns] if available_pns else raw_isolate
            response_text = isolate_pattern.sub('', response_text).strip()

        logger.info(f"[Sage parsed] highlight_parts={highlight_parts}, isolate_parts={isolate_parts}, "
                    f"narration_segments={len(narration_segments)}, camera_view={camera_view}, explode_level={explode_level}, "
                    f"available_pns sample={list(available_pns)[:5]}")

        # Post-process: strip markdown headers and convert to conversational prose
        response_text = _clean_agent_response(response_text)

        result = {"response": response_text}
        if highlight_dims:
            result["highlight_dimensions"] = highlight_dims
        if highlight_views:
            result["highlight_views"] = highlight_views
        if highlight_features:
            result["highlight_features"] = highlight_features
        if compare_features:
            result["compare_features"] = compare_features
        if compare_parts:
            result["compare_parts"] = compare_parts
        if highlight_parts:
            result["highlight_parts"] = highlight_parts
        if isolate_parts:
            result["isolate_parts"] = isolate_parts
        if narration_segments:
            result["narration_segments"] = narration_segments
        if camera_view:
            result["camera_view"] = camera_view
        if explode_level is not None:
            result["explode_level"] = explode_level

        # Parse FAI_FILL markers (chat-driven measurement fills)
        fai_fills = {}
        fai_fill_match = re.search(r'^FAI_FILL:\s*(.+)$', response_text, re.MULTILINE)
        if fai_fill_match:
            raw = fai_fill_match.group(1).strip()
            # Parse #N: value or #all: value
            all_match = re.match(r'#all:\s*([\d.+-]+)', raw, re.I)
            if all_match:
                val = all_match.group(1)
                fai_chars = ctx.get("fai_characteristics", []) if ctx else []
                for c in fai_chars:
                    fai_fills[str(c.get("char_number", 0))] = val
            else:
                for m in re.finditer(r'#(\d+):\s*([\d.+-]+)', raw):
                    fai_fills[m.group(1)] = m.group(2)
            if fai_fills:
                logger.info(f"[FAI] Chat fill parsed: {len(fai_fills)} values")
            response_text = re.sub(r'^FAI_FILL:\s*(.+)$', '', response_text, flags=re.MULTILINE).strip()

        # Parse FAI_TOL markers (chat-driven tolerance overrides)
        fai_tol = {}
        fai_tol_match = re.search(r'^FAI_TOL:\s*(.+)$', response_text, re.MULTILINE)
        if fai_tol_match:
            raw = fai_tol_match.group(1).strip()
            all_match = re.match(r'#all:\s*([\d.+-]+)', raw, re.I)
            if all_match:
                val = all_match.group(1)
                fai_chars = ctx.get("fai_characteristics", []) if ctx else []
                for c in fai_chars:
                    fai_tol[str(c.get("char_number", 0))] = val
            else:
                for m in re.finditer(r'#(\d+):\s*([\d.+-]+)', raw):
                    fai_tol[m.group(1)] = m.group(2)
            if fai_tol:
                logger.info(f"[FAI] Chat tolerance parsed: {len(fai_tol)} values")
            response_text = re.sub(r'^FAI_TOL:\s*(.+)$', '', response_text, flags=re.MULTILINE).strip()

        if fai_fills:
            result["fai_fills"] = fai_fills
        if fai_tol:
            result["fai_tol"] = fai_tol

        # Resolve ASME references for chat responses (deterministic, no model call)
        # Message-keyword matching must work even when no inspection context is loaded.
        asme_refs = []
        if request.agent_type != "parts-finder":
            seen_ft = set()
            # Priority 1: focused_feature
            focused = ctx.get("focused_feature") if isinstance(ctx, dict) else None
            if focused and isinstance(focused, dict):
                for ref in _resolve_asme_refs_for_finding(focused):
                    if ref["feature_type"] not in seen_ft:
                        seen_ft.add(ref["feature_type"])
                        asme_refs.append(ref)
            # Priority 2: user message keywords
            if len(asme_refs) < 3:
                for ref in _resolve_asme_refs_for_finding({"observation": request.message}):
                    if ref["feature_type"] not in seen_ft:
                        seen_ft.add(ref["feature_type"])
                        asme_refs.append(ref)
            # Priority 3: only MISSING/PARTIAL/DISCREPANT findings
            if len(asme_refs) < 3 and isinstance(ctx, dict):
                ctx_findings = ctx.get("findings", [])
                if isinstance(ctx_findings, list):
                    for finding in ctx_findings:
                        if len(asme_refs) >= 3:
                            break
                        status = finding.get("status", "").upper() if isinstance(finding, dict) else ""
                        if status in ("MISSING", "PARTIAL", "DISCREPANT"):
                            for ref in _resolve_asme_refs_for_finding(finding):
                                if ref["feature_type"] not in seen_ft:
                                    seen_ft.add(ref["feature_type"])
                                    asme_refs.append(ref)
            asme_refs = asme_refs[:3]
        if asme_refs:
            result["asme_refs"] = asme_refs

        # Parse SHOW_GEOMETRY_DIFF marker
        show_geo_diff = re.search(r'^SHOW_GEOMETRY_DIFF\s*$', response_text, re.MULTILINE)
        if show_geo_diff:
            result["show_geometry_diff"] = True
            response_text = re.sub(r'^SHOW_GEOMETRY_DIFF\s*$', '', response_text, flags=re.MULTILINE).strip()

        # Parse RUN_INSPECTION marker
        run_insp_match = re.search(r'^RUN_INSPECTION\s*$', response_text, re.MULTILINE)
        if run_insp_match:
            result["run_inspection"] = True
            response_text = re.sub(r'^RUN_INSPECTION\s*$', '', response_text, flags=re.MULTILINE).strip()

        # Parse ANIMATE_MOTION marker
        animate_match = re.search(r'ANIMATE_MOTION:\s*(start|stop)', response_text, re.I)
        if animate_match:
            result["animate_motion"] = animate_match.group(1).lower()
            response_text = re.sub(r'ANIMATE_MOTION:\s*(start|stop)\s*', '', response_text, flags=re.I).strip()

        # Always update response with final cleaned text
        result["response"] = response_text

        # Phase 4B: Attach canonical tool_calls alongside legacy fields
        tool_calls = build_tool_calls_from_result(result)
        if tool_calls:
            result["tool_calls"] = tool_calls

        return result

    except anthropic.AuthenticationError:
        logger.error("Agent chat: invalid Anthropic API key")
        raise HTTPException(status_code=500, detail="Invalid API key. Please check your ANTHROPIC_API_KEY.")
    except anthropic.RateLimitError:
        logger.warning("Agent chat: rate limited")
        raise HTTPException(status_code=429, detail="Rate limited. Please try again in a moment.")
    except anthropic.APITimeoutError:
        logger.warning("Agent chat: API timeout")
        raise HTTPException(status_code=504, detail="Request timed out. Please try again.")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Agent chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")


# ---------- Scout Browser Search (SSE Streaming) ----------

SCOUT_SEARCH_TOOL = {
    "name": "web_search_parts",
    "description": (
        "Search supplier websites for industrial parts. Use this when the user "
        "asks to find, buy, or source a specific part and you need current pricing, "
        "availability, or catalog numbers that you don't know from memory."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query, e.g. 'M10x1.5 Grade 8.8 hex head cap screw'"
            },
            "target_suppliers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Preferred suppliers: 'misumi', 'msc', 'fastenal'. Defaults to all."
            },
            "category": {
                "type": "string",
                "description": "Product category: 'fasteners', 'bearings', 'shafts', 'seals', etc."
            }
        },
        "required": ["query"]
    }
}

SCOUT_VENDOR_TOOL = {
    "name": "web_search_vendors",
    "description": (
        "Search for fabrication vendors and manufacturing service providers. "
        "Use this when the part is custom-made (not off-the-shelf) and the user "
        "needs to find machine shops, CNC services, or fabrication vendors."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to search for, e.g. 'custom aluminum enclosure CNC machining'"
            },
            "service_type": {
                "type": "string",
                "description": "Manufacturing process: 'CNC machining', 'sheet metal', '3D printing', 'welding', 'casting'"
            }
        },
        "required": ["query"]
    }
}


@app.post("/api/agent/chat/stream")
async def agent_chat_stream(request: AgentChatRequest):
    """Streaming agent chat for Scout with live web search via SSE."""
    import json as json_module

    try:
        import anthropic
    except ImportError:
        raise HTTPException(status_code=500, detail="Anthropic SDK not installed")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

    system_prompt = AGENT_PROMPTS.get(request.agent_type, PARTS_FINDER_PROMPT)

    async def event_generator():
        try:
            client = anthropic.Anthropic(api_key=api_key)

            # Build context (same as agent_chat)
            raw_ctx = request.inspection_context or request.context or {}
            normalized = normalize_agent_context(raw_ctx)
            ctx = normalized["flat"]
            context_text = _build_context_message(ctx)

            if request.cross_agent_context:
                context_text = f"=== CONTEXT FROM PRIOR AGENT CONVERSATION ===\n{request.cross_agent_context}\n\n{context_text}"

            # Parts-finder context enrichment (same as agent_chat)
            pn = ctx.get("part_number", "")
            if pn:
                safe_pn = re.sub(r'[^\w\-]', '', pn)
                profile_path = Path("400S_Sorted_Library") / f"{safe_pn}.json"
                if not profile_path.exists():
                    profile_path = Path("400S_Sorted_Library") / f"{safe_pn}_inspection_profile.json"
                if profile_path.exists():
                    try:
                        with open(profile_path, "r", encoding="utf-8-sig") as f:
                            profile = json.load(f)
                        spec_parts = ["=== PART SPECIFICATIONS FOR SOURCING ==="]
                        spec_parts.append(f"Part: {profile.get('part_number', pn)}")
                        spec_parts.append(f"Name: {profile.get('part_name', '')}")
                        spec_parts.append(f"Description: {profile.get('part_description', '')}")
                        for feat in profile.get("features", []):
                            spec_parts.append(f"- {feat.get('name', '')}: {feat.get('type', '')} (qty: {feat.get('count', 1)})")
                        context_text += "\n\n" + "\n".join(spec_parts)
                    except Exception as e:
                        logger.warning(f"Stream: Failed to load profile: {e}")

                # Add assembly context for procurement (Feature #154)
                if pn in assembly_part_lookup:
                    assy_num = assembly_part_lookup[pn][0]
                    assy_data = assembly_profiles.get(assy_num, {})
                    sc_parts = ["=== ASSEMBLY CONTEXT FOR PROCUREMENT ==="]

                    # Assembly identity and scale
                    assy_identity = assy_data.get("identity", {})
                    sc_parts.append(f"Assembly: {assy_identity.get('description', assy_num)} ({assy_num})")
                    stats = assy_data.get("statistics", {})
                    sc_parts.append(f"Components: {stats.get('totalComponents', 0)}, Mates: {stats.get('totalMates', 0)}")

                    # Resolve part aliases (same pattern as non-streaming endpoint)
                    part_aliases = {pn}
                    pdc = assy_data.get("partDataCache", {})
                    for old_key, pd in pdc.items():
                        old_stem = Path(old_key).stem
                        new_pn = (pd.get("identity") or {}).get("partNumber", "")
                        if pn == new_pn or pn == old_stem:
                            part_aliases.add(old_stem)
                            part_aliases.add(new_pn)
                            base = re.sub(r'_\d+$', '', old_stem)
                            part_aliases.add(base)
                    part_aliases.discard("")

                    # Part description from partDataCache
                    for old_key, pd in pdc.items():
                        pd_id = pd.get("identity") or {}
                        if pd_id.get("partNumber", "") in part_aliases or Path(old_key).stem in part_aliases:
                            desc = pd_id.get("description", "")
                            if desc:
                                sc_parts.append(f"Part role: {desc}")
                            break

                    # Filtered mates — show what this part connects to
                    all_mates = assy_data.get("mates", [])
                    mate_lines = []
                    for mate in all_mates:
                        e1 = mate.get("entity1", {}).get("componentName", "")
                        e2 = mate.get("entity2", {}).get("componentName", "")
                        if _component_matches_aliases(e1, part_aliases) or _component_matches_aliases(e2, part_aliases):
                            mate_lines.append(f"- {mate.get('type', 'unknown')}: {e1} ↔ {e2}")
                            if len(mate_lines) >= MAX_MATE_LINES:
                                break
                    if mate_lines:
                        sc_parts.append("\nMATING CONSTRAINTS (replacement must satisfy these fits):")
                        sc_parts.extend(mate_lines)

                    # Functional narrative — procurement-relevant sections only
                    narrative = assy_data.get("functionalNarrative", {})
                    if narrative:
                        sc_parts.append("\nFUNCTIONAL CONTEXT:")
                        for section_key in ["assemblyOverview", "criticalInterfaces"]:
                            section_data = narrative.get(section_key)
                            if section_data:
                                sc_parts.append(f"[{section_key}]")
                                if isinstance(section_data, str):
                                    sc_parts.append(section_data[:500])
                                elif isinstance(section_data, dict):
                                    for k, v in section_data.items():
                                        sc_parts.append(f"  {k}: {str(v)[:300]}")
                                elif isinstance(section_data, list):
                                    for item in section_data[:10]:
                                        sc_parts.append(f"  - {str(item)[:200]}")

                    sc_parts.append("\nWhen sourcing replacements, ensure compatibility with the above mating constraints and assembly function.")
                    context_text += "\n\n" + "\n".join(sc_parts)

            # Build messages
            messages = []
            for msg in (request.history or []):
                role = msg.get("role", "user")
                content = msg.get("content") or msg.get("text", "")
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

            user_content = []
            if context_text:
                user_content.append({"type": "text", "text": f"=== CURRENT INSPECTION CONTEXT ===\n{context_text}"})
            if request.image:
                img_data = request.image
                media_type = "image/png"
                if img_data.startswith("data:"):
                    header, img_data = img_data.split(",", 1)
                    if "image/jpeg" in header:
                        media_type = "image/jpeg"
                user_content.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_data}})
            user_content.append({"type": "text", "text": request.message})
            messages.append({"role": "user", "content": user_content})

            # Determine if search engine is available
            tools = [SCOUT_SEARCH_TOOL, SCOUT_VENDOR_TOOL] if search_engine and search_engine.ready else []
            tool_choice = {"type": "auto"} if tools else None

            # Call Claude (with tools if available)
            create_kwargs = {
                "model": "claude-sonnet-4-5-20250929",
                "max_tokens": 2048,
                "system": system_prompt,
                "messages": messages,
            }
            if tools:
                create_kwargs["tools"] = tools
                create_kwargs["tool_choice"] = tool_choice

            response = client.messages.create(**create_kwargs)

            # Check for tool_use
            tool_use_block = None
            text_blocks = []
            for block in response.content:
                if block.type == "tool_use" and block.name in ("web_search_parts", "web_search_vendors"):
                    tool_use_block = block
                elif hasattr(block, "text"):
                    text_blocks.append(block.text)

            if tool_use_block is None:
                # No search needed — send text response
                text = _clean_agent_response("".join(text_blocks))
                yield f"data: {json_module.dumps({'type': 'response', 'text': text})}\n\n"
                yield f"data: {json_module.dumps({'type': 'done'})}\n\n"
                return

            # Execute browser search, streaming events
            search_input = tool_use_block.input
            results = []

            if tool_use_block.name == "web_search_vendors":
                search_gen = search_engine.search_vendors(
                    query=search_input.get("query", request.message),
                    service_type=search_input.get("service_type", "CNC machining"),
                )
            else:
                search_gen = search_engine.search_parts(
                    query=search_input.get("query", request.message),
                    sites=search_input.get("target_suppliers"),
                )

            async for event in search_gen:
                yield f"data: {json_module.dumps(event.to_dict())}\n\n"
                if event.type == "result":
                    results.append(event.data)

            # Filter out junk results (error pages, blocked pages, empty results)
            _junk_names = [
                "sorry", "error", "not found", "404", "403", "500",
                "blocked", "captcha", "denied", "unable to complete",
                "something went wrong", "server error", "http status",
                "search results", "access denied", "forbidden",
                "just a moment", "checking your browser",
            ]
            _junk_domains = ["amazon.com", "ebay.com", "walmart.com", "aliexpress.com", "alibaba.com"]
            def _is_junk(r):
                name = (r.get("name") or "").lower().strip()
                url = (r.get("url") or "").lower()
                if not name or len(name) < 4:
                    return True
                if any(junk in name for junk in _junk_names):
                    return True
                if any(d in url for d in _junk_domains):
                    return True
                # Names that are just the domain/supplier name (no real product info)
                supplier = (r.get("supplier") or "").lower().strip()
                domain_base = name.replace(".com", "").replace(".org", "").replace("www.", "")
                if domain_base == supplier or name == supplier:
                    return True
                # "Part" alone is MSC's error page title
                if name in ("part", "parts", "product", "products", "home", "search"):
                    return True
                return False

            results = [r for r in results if not _is_junk(r)]

            # Call Claude again with search results for summary
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_use_block.id,
                    "content": json_module.dumps(results),
                }]
            })

            summary_response = client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=2048,
                system=system_prompt,
                messages=messages,
            )

            summary_text = ""
            for block in summary_response.content:
                if hasattr(block, "text"):
                    summary_text += block.text
            summary_text = _clean_agent_response(summary_text)

            yield f"data: {json_module.dumps({'type': 'response', 'text': summary_text, 'results': results})}\n\n"
            yield f"data: {json_module.dumps({'type': 'done'})}\n\n"

        except Exception as e:
            logger.error(f"Scout stream error: {e}")
            yield f"data: {json_module.dumps({'type': 'error', 'message': str(e)})}\n\n"
            yield f"data: {json_module.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/agent/summarize")
async def agent_summarize(request: AgentSummarizeRequest):
    """Summarize a conversation for cross-agent context injection."""
    if not request.history:
        return {"summary": ""}

    try:
        import anthropic
    except ImportError:
        raise HTTPException(status_code=500, detail="Anthropic SDK not installed")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

    try:
        client = anthropic.Anthropic(api_key=api_key)

        # Build conversation text
        conv_text = "\n".join(
            f"{m.get('role', 'user').upper()}: {m.get('text', m.get('content', ''))}"
            for m in request.history if m.get('text') or m.get('content')
        )

        summarize_prompt = f"Summarize this conversation between a user and the {request.agent_name} agent about part {request.part_number}. Extract: key findings, measurements mentioned, deviations discussed, questions asked, and any decisions made. Output max 150 words as a concise bulleted summary."

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{
                "role": "user",
                "content": f"{summarize_prompt}\n\n--- CONVERSATION ---\n{conv_text}"
            }],
        )

        summary_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                summary_text += block.text

        formatted = f"PRIOR AGENT CONTEXT (for reference):\n---\nAgent: {request.agent_name} | Part: {request.part_number}\n{summary_text.strip()}\n---"

        return {"summary": formatted}

    except Exception as e:
        logger.error(f"Agent summarize error: {e}")
        return {"summary": ""}


# ---------- FAI Verdicts ----------


@app.post("/api/fai-verdicts")
async def fai_verdicts(request: Request):
    """Batch Sage verdicts for failing FAI characteristics."""
    try:
        body = await request.json()
        part_number = body.get("part_number", "")
        characteristics = body.get("characteristics", [])
        inspection_context = body.get("inspection_context", {})

        if not characteristics:
            return {"verdicts": {}}

        # Build prompt with all measured characteristics
        char_lines = []
        for c in characteristics:
            char_lines.append(
                f"#{c['char_number']}: {c.get('description', 'N/A')} — "
                f"Nominal: {c.get('nominal_mm', 0):.3f}mm, "
                f"Tol: +{c.get('tolerance_plus_mm', 0):.3f}/-{c.get('tolerance_minus_mm', 0):.3f}mm, "
                f"Measured: {c.get('measured_mm', 0):.3f}mm, "
                f"Status: {c.get('status', 'UNKNOWN')}"
            )
        chars_text = "\n".join(char_lines)

        prompt = f"""FAI VERDICT MODE — Part: {part_number}

The following controlled characteristics were measured during First Article Inspection.
For each, provide a disposition verdict with engineering reasoning.
- PASS characteristics: confirm acceptance with brief reasoning
- FAIL/WARN characteristics: recommend Scrap, Rework, or Accept with engineering justification

{chars_text}

For each characteristic, respond in exactly this format:
VERDICT #N: Scrap|Rework|Accept
Reasoning in 1-2 sentences with assembly/functional context.
"""
        # Use the same Anthropic client setup as the agent chat routes
        try:
            import anthropic
        except ImportError:
            return JSONResponse(status_code=500, content={"error": "Anthropic SDK not installed"})

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return JSONResponse(status_code=500, content={"error": "ANTHROPIC_API_KEY not configured"})

        client = anthropic.Anthropic(api_key=api_key)

        messages = [{"role": "user", "content": prompt}]
        system_prompt = DEVIATION_ANALYST_PROMPT + "\n\nEXCEPTION — FAI VERDICT MODE:\nWhen receiving FAI characteristics for batch evaluation, the 3-sentence rule is SUSPENDED.\nFor each failing characteristic, provide:\nVERDICT #N: Scrap|Rework|Accept\nReasoning in 1-2 sentences with assembly context."

        # Add inspection context if available
        context_parts = []
        if inspection_context:
            context_parts.append(f"Assembly context: {json.dumps(inspection_context, default=str)[:2000]}")
        if context_parts:
            system_prompt += "\n\n" + "\n".join(context_parts)

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=system_prompt,
            messages=messages,
        )

        response_text = response.content[0].text if response.content else ""

        # Parse verdicts from response
        verdicts = {}
        verdict_pattern = re.compile(r'VERDICT\s*#(\d+):\s*(Scrap|Rework|Accept)', re.IGNORECASE)
        lines = response_text.split('\n')
        for i, line in enumerate(lines):
            match = verdict_pattern.search(line)
            if match:
                num = match.group(1)
                disposition = match.group(2).capitalize()
                # Reasoning is the next line(s) until next VERDICT or end
                reasoning_lines = []
                for j in range(i + 1, min(i + 3, len(lines))):
                    if verdict_pattern.search(lines[j]):
                        break
                    if lines[j].strip():
                        reasoning_lines.append(lines[j].strip())
                verdicts[num] = {
                    "disposition": disposition,
                    "reasoning": " ".join(reasoning_lines),
                }

        return {"verdicts": verdicts}

    except Exception as e:
        logger.error(f"FAI verdicts error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/fai-agent-fill")
async def fai_agent_fill(request: Request):
    """Agent-assisted measurement fill for FAI table."""
    try:
        body = await request.json()
        instruction = body.get("instruction", "")
        characteristics = body.get("characteristics", [])
        part_number = body.get("part_number", "")

        if not instruction or not characteristics:
            return JSONResponse(status_code=400, content={"error": "Instruction and characteristics required"})

        # Build table context for the agent
        table_lines = []
        for c in characteristics:
            status = "FILLED" if c.get("current_measured") else "EMPTY"
            table_lines.append(
                f"#{c['char_number']}: Ref={c.get('ref','')}, View={c.get('view','')}, "
                f"Desc=\"{c.get('description','')}\", Nominal={c.get('nominal_mm', 0):.3f}mm, "
                f"Current={c.get('current_measured') or 'EMPTY'} [{status}]"
            )
        table_text = "\n".join(table_lines)

        prompt = f"""FAI MEASUREMENT FILL — Part: {part_number}

You are helping an inspector fill in the "Measured" column of a First Article Inspection table.
Below is the current state of the table. Each row shows its char number, reference, view, description, nominal value, and current measured value (EMPTY or a number).

{table_text}

INSPECTOR'S INSTRUCTION:
{instruction}

RULES:
- "Nominal" means the measured value equals the nominal value exactly.
- "All nominal" means set every EMPTY cell to its nominal value.
- If the inspector specifies specific rows differently (e.g. "#9=4.5"), use that value for those rows.
- Only fill cells the instruction refers to. If the instruction says "all nominal except #9 and #10", fill all EMPTY cells with nominal and set #9 and #10 to the specified values.
- If a cell already has a value (FILLED), do NOT overwrite it unless the instructor explicitly mentions that row.
- Respond ONLY with FILL lines in this exact format, one per row to fill:

FILL #1: 92.000
FILL #2: 9.300

Do not include any other text, explanation, or commentary. Only FILL lines."""

        try:
            import anthropic
        except ImportError:
            return JSONResponse(status_code=500, content={"error": "Anthropic SDK not installed"})

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return JSONResponse(status_code=500, content={"error": "ANTHROPIC_API_KEY not configured"})

        client = anthropic.Anthropic(api_key=api_key)

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = response.content[0].text if response.content else ""
        logger.info(f"FAI agent fill response: {response_text[:500]}")

        # Parse FILL lines
        fills = {}
        fill_pattern = re.compile(r'FILL\s*#(\d+):\s*([\d.+-]+)')
        for line in response_text.split('\n'):
            match = fill_pattern.search(line)
            if match:
                num = match.group(1)
                value = match.group(2)
                fills[num] = value

        return {"fills": fills}

    except Exception as e:
        logger.error(f"FAI agent fill error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ---------- PDF Rendering ----------


@app.post("/api/render-pdf-page")
async def render_pdf_page(
    file: UploadFile = File(...),
    page: int = Form(1),
):
    """Render a PDF page to a PNG image and return it as base64.

    Used by the frontend camera capture when the uploaded drawing is a PDF,
    since browser embed elements cannot be captured via JavaScript canvas.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise HTTPException(status_code=500, detail="PyMuPDF (fitz) is not installed")

    try:
        pdf_bytes = await file.read()
        if len(pdf_bytes) == 0:
            raise HTTPException(status_code=422, detail="Uploaded PDF file is empty")

        # Open the PDF from bytes
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_count = len(doc)

        # Validate page number (1-based)
        if page < 1 or page > page_count:
            doc.close()
            raise HTTPException(
                status_code=400,
                detail=f"Invalid page number {page}. PDF has {page_count} page(s)."
            )

        # Render the page at 2x resolution for clarity
        pdf_page = doc.load_page(page - 1)  # 0-indexed
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = pdf_page.get_pixmap(matrix=mat)
        png_bytes = pix.tobytes("png")
        doc.close()

        # Encode as base64 data URL
        b64 = base64.b64encode(png_bytes).decode("utf-8")
        data_url = f"data:image/png;base64,{b64}"

        logger.info(f"Rendered PDF page {page}/{page_count} to PNG ({len(png_bytes)} bytes)")
        return {"image": data_url, "page": page, "total_pages": page_count}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rendering PDF page: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to render PDF page: {str(e)}")


# ---------- Voice (STT + TTS) ----------

# ── Geometry Diff endpoints (proxy to worker on :8001) ──

def _sanitize_revision(rev: str) -> str:
    """Strip revision strings to alphanumeric only."""
    sanitized = re.sub(r'[^a-zA-Z0-9]', '', rev)
    if not sanitized:
        raise HTTPException(status_code=400, detail=f"Invalid revision: '{rev}'")
    return sanitized


@app.get("/api/geometry-diff/{part_number}")
async def geometry_diff(part_number: str, revA: str = Query(...), revB: str = Query(...)):
    """Compute or retrieve solid-body geometry diff between two part revisions.
    Proxies to the geometry worker on :8001 if not cached."""
    safe_pn = sanitize_part_number(part_number)
    safe_revA = _sanitize_revision(revA)
    safe_revB = _sanitize_revision(revB)

    step_a = Path(f"400S_Sorted_Library/parts/{safe_pn}/rev{safe_revA}/{safe_pn}.stp")
    step_b = Path(f"400S_Sorted_Library/parts/{safe_pn}/rev{safe_revB}/{safe_pn}.stp")
    if not step_a.exists() or not step_b.exists():
        raise HTTPException(status_code=404, detail="STEP file(s) not found for requested revisions")

    cache_dir = Path(f"400S_Sorted_Library/parts/{safe_pn}/geometry_diff/{safe_revA}_vs_{safe_revB}")
    result_path = cache_dir / "diff_result.json"

    # Cache check with freshness validation (STEPs + sidecars)
    if result_path.exists():
        cache_mtime = result_path.stat().st_mtime
        source_mtimes = [step_a.stat().st_mtime, step_b.stat().st_mtime]
        for sc in [step_a.parent / f"{safe_pn}_step_meta.json", step_b.parent / f"{safe_pn}_step_meta.json"]:
            if sc.exists():
                source_mtimes.append(sc.stat().st_mtime)
        if cache_mtime > max(source_mtimes):
            with open(result_path, "r") as f:
                return json.load(f)
        else:
            import shutil
            shutil.rmtree(cache_dir, ignore_errors=True)

    # Proxy to geometry worker
    try:
        import httpx
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post("http://localhost:8001/diff", json={
                "step_a": str(step_a.resolve()),
                "step_b": str(step_b.resolve()),
                "output_dir": str(cache_dir.resolve()),
                "part_number": safe_pn,
                "revA": safe_revA, "revB": safe_revB,
            })
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Geometry worker error: {resp.text}")
        return resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Geometry worker not running. Start it with: conda run -n geo-env python geometry_worker.py")


@app.get("/api/geometry-diff/{part_number}/{rev_pair}/{filename}")
async def serve_geometry_diff_artifact(part_number: str, rev_pair: str, filename: str):
    """Serve cached geometry diff artifacts (STL/GLB files)."""
    safe_pn = sanitize_part_number(part_number)
    if not re.match(r'^\w+_vs_\w+$', rev_pair):
        raise HTTPException(status_code=400, detail="Invalid revision pair format")
    if filename not in ("removed.stl", "added.stl", "removed.glb", "added.glb", "diff_result.json"):
        raise HTTPException(status_code=400, detail="Invalid artifact name")
    artifact = Path(f"400S_Sorted_Library/parts/{safe_pn}/geometry_diff/{rev_pair}/{filename}")
    if not artifact.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    media_types = {".stl": "model/stl", ".glb": "model/gltf-binary", ".json": "application/json"}
    media = media_types.get(artifact.suffix, "application/octet-stream")
    return FileResponse(artifact, media_type=media)


# Per-agent voice mapping (ElevenLabs voice IDs)
AGENT_VOICE_MAP = {
    "inspector":         os.getenv("ELEVENLABS_VOICE_IRIS",  "21m00Tcm4TlvDq8ikWAM"),  # Rachel
    "deviation-analyst": os.getenv("ELEVENLABS_VOICE_SAGE",  "gs0tAILXbY5DNrJrsM6F"),
    "parts-finder":      os.getenv("ELEVENLABS_VOICE_SCOUT", "AZnzlk1XvdvUeBnXmlld"),  # Domi
}


class VoiceSynthesizeRequest(BaseModel):
    text: str
    agent_type: str = "inspector"


@app.get("/api/asme-ref/{folder}/{image_name}")
async def get_asme_reference(folder: str, image_name: str):
    """Serve an ASME reference page image. Whitelist-protected."""
    if folder not in ASME_REF_WHITELIST:
        raise HTTPException(status_code=404, detail="Unknown reference folder")
    if not re.match(r'^[\w\-]+\.png$', image_name):
        raise HTTPException(status_code=400, detail="Invalid image name")
    for base in [Path("asme_feature_references"), Path("rag_visual_db")]:
        img_path = base / folder / image_name
        if img_path.exists() and img_path.is_file():
            return FileResponse(img_path, media_type="image/png")
    raise HTTPException(status_code=404, detail="Image not found")


@app.post("/api/voice/transcribe")
async def voice_transcribe(audio: UploadFile = File(...)):
    """Transcribe audio using local faster-whisper (CPU/CUDA), with OpenAI API fallback."""
    audio_bytes = await audio.read()
    if len(audio_bytes) == 0:
        raise HTTPException(status_code=422, detail="Audio file is empty")
    if len(audio_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file exceeds 25MB limit")

    # Force API mode if configured
    if os.getenv("STT_BACKEND") == "api":
        return await _fallback_openai_transcribe(audio_bytes, audio.filename)

    desired_device = _resolve_whisper_device()
    used_device = desired_device  # default before model load; updated on success

    try:
        model, used_device = _get_whisper_model(desired_device)
        audio_file = io.BytesIO(audio_bytes)

        def _transcribe():
            segments, info = model.transcribe(
                audio_file,
                beam_size=1,
                language="en",
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
            )
            text = " ".join(segment.text.strip() for segment in segments)
            if not text.strip():
                audio_file.seek(0)
                segments2, _ = model.transcribe(audio_file, beam_size=1, language="en", vad_filter=False)
                text = " ".join(s.text.strip() for s in segments2)
            return text

        text = await asyncio.to_thread(_transcribe)
        text = text.strip()

        if not text:
            raise HTTPException(status_code=422, detail="No speech detected in audio")

        logger.info(f"Whisper transcription (local/{used_device}): {len(audio_bytes)} bytes -> {len(text)} chars")
        return {"text": text}

    except HTTPException:
        raise
    except Exception as e:
        configured = os.getenv("WHISPER_DEVICE", "auto").lower()

        # WHISPER_DEVICE=cuda: fail hard, no retry
        if configured == "cuda":
            logger.error(f"CUDA transcription failed (WHISPER_DEVICE=cuda, no fallback): {e}")
            raise HTTPException(status_code=500, detail=f"CUDA transcription failed: {str(e)}")

        # auto mode with CUDA failure: mark CUDA as bad, evict, retry CPU
        if used_device == "cuda":
            logger.warning(f"CUDA transcription failed ({e}), marking cuda as bad, retrying on CPU...")
            _whisper_bad_devices.add("cuda")
            _whisper_models.pop("cuda", None)
            try:
                model_cpu, _ = _get_whisper_model("cpu")
                audio_file_retry = io.BytesIO(audio_bytes)

                def _transcribe_cpu():
                    segments, info = model_cpu.transcribe(
                        audio_file_retry, beam_size=1, language="en",
                        vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500),
                    )
                    text = " ".join(s.text.strip() for s in segments)
                    if not text.strip():
                        audio_file_retry.seek(0)
                        segments2, _ = model_cpu.transcribe(audio_file_retry, beam_size=1, language="en", vad_filter=False)
                        text = " ".join(s.text.strip() for s in segments2)
                    return text

                text = await asyncio.to_thread(_transcribe_cpu)
                text = text.strip()
                if not text:
                    raise HTTPException(status_code=422, detail="No speech detected in audio")
                logger.info(f"Whisper transcription (local/cpu after cuda fail): {len(audio_bytes)} bytes -> {len(text)} chars")
                return {"text": text}
            except HTTPException:
                raise
            except Exception as cpu_err:
                logger.error(f"Local CPU transcription also failed: {cpu_err}")
                return await _fallback_openai_transcribe(audio_bytes, audio.filename)
        else:
            logger.error(f"Local transcription error: {e}")
            return await _fallback_openai_transcribe(audio_bytes, audio.filename)


@app.post("/api/voice/synthesize")
async def voice_synthesize(request: VoiceSynthesizeRequest):
    """Synthesize text to speech using ElevenLabs with agent-specific voice."""
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ELEVENLABS_API_KEY not configured")

    if not request.text.strip():
        raise HTTPException(status_code=422, detail="Text is empty")

    voice_id = AGENT_VOICE_MAP.get(request.agent_type)
    if not voice_id:
        raise HTTPException(status_code=400, detail=f"Unknown agent_type: {request.agent_type}")

    # Strip markdown formatting for cleaner speech
    clean_text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', request.text)

    try:
        import asyncio
        from elevenlabs import ElevenLabs
        client = ElevenLabs(api_key=api_key)

        # Run sync ElevenLabs call off the event loop, collect full audio
        def _synthesize():
            chunks = []
            for chunk in client.text_to_speech.convert(
                voice_id=voice_id,
                text=clean_text,
                model_id="eleven_turbo_v2_5",
                output_format="mp3_44100_128",
            ):
                if chunk:
                    chunks.append(chunk)
            return b"".join(chunks)

        audio_bytes_out = await asyncio.to_thread(_synthesize)

        return StreamingResponse(
            iter([audio_bytes_out]),
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-cache"},
        )

    except Exception as e:
        logger.error(f"ElevenLabs synthesis error: {e}")
        raise HTTPException(status_code=502, detail=f"Voice synthesis failed: {str(e)}")


# ---------- Static Files ----------

# Serve the frontend
@app.get("/")
async def serve_index():
    """Serve the main frontend HTML page."""
    return FileResponse("static/index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


# Mount static files directory (must be after specific routes)
app.mount("/static", StaticFiles(directory="static"), name="static")
