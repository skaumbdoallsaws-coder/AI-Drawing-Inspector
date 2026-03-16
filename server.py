"""
InspectorPro - FastAPI Web Server
Thin wrapper around the SpatialInspector engine for engineering drawing QC inspection.
"""
# Updated: proper HTTP error codes for malformed requests
# Reloaded: ASME prompt improvements (feature #109) - reinstalled package
# Reloaded: Feature #125 - auto-annotation bounding box locations in inspection prompt

import os
import re
import base64
import json
import logging
import math
import shutil
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

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
        part_data_cache = assy_data.get("partDataCache", {})
        for old_key, part_data in part_data_cache.items():
            new_pn = (part_data.get("identity") or {}).get("partNumber", "")
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


@app.get("/api/3d-model/{part_number}")
async def get_3d_model(part_number: str):
    """Serve the raw STL file for a part number, or 404 if not found."""
    # Sanitize part_number to prevent path traversal
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")

    stl_path = Path("400S_Sorted_Library") / f"{safe_pn}.stl"
    if not stl_path.exists():
        raise HTTPException(status_code=404, detail=f"No 3D model found for part number '{part_number}'")

    return FileResponse(
        path=str(stl_path),
        media_type="application/octet-stream",
        filename=f"{safe_pn}.stl",
    )


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

    # Build color legend: resolve old filenames to new part numbers + descriptions
    color_map = assy_data.get("partColorMapping", assy_data.get("colorAssignments", {}))
    part_data_cache = assy_data.get("partDataCache", {})
    part_color_legend = []
    for old_key, color in color_map.items():
        identity = (part_data_cache.get(old_key, {}).get("identity") or {})
        part_color_legend.append({
            "old_key": old_key,
            "part_number": identity.get("partNumber", old_key.replace(".sldprt", "").replace(".SLDPRT", "")),
            "description": identity.get("description", ""),
            "color": color if isinstance(color, str) else color.get("color", "#888"),
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
async def get_assembly_model(assembly_number: str):
    """Serve the colored GLB 3D model for an assembly."""
    safe_num = re.sub(r'[^\w\-]', '', assembly_number)
    if not safe_num:
        raise HTTPException(status_code=400, detail="Invalid assembly number")

    assemblies_dir = Path("400S_Sorted_Library/assemblies")
    glb_path = assemblies_dir / f"{safe_num}_colored.glb"
    if not glb_path.exists():
        raise HTTPException(status_code=404, detail=f"No 3D model found for assembly '{assembly_number}'")

    return FileResponse(
        path=str(glb_path),
        media_type="model/gltf-binary",
        filename=f"{safe_num}_colored.glb",
    )


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

Scope: drawings, CAD, ASME, GD&T, manufacturing. Off-topic? "That's outside my area — what drawing question can I help with?"

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
- Use exact part numbers from AVAILABLE PARTS list.
- Start with one brief intro sentence before the first HIGHLIGHT_PARTS line.
- This mode ONLY activates when the user explicitly asks for a walkthrough/tour/narration."""

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
    """Load PNG images from directories as base64 for Claude Vision API."""
    images = []
    for dir_path in directories:
        p = Path(dir_path)
        if not p.exists():
            continue
        png_files = sorted(p.glob("*.png"))[:3]  # Max 3 per directory
        for png_file in png_files:
            if len(images) >= max_images:
                break
            try:
                b64 = base64.standard_b64encode(png_file.read_bytes()).decode("utf-8")
                images.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": b64,
                    }
                })
            except Exception as e:
                logger.warning(f"Failed to load RAG image {png_file}: {e}")
        if len(images) >= max_images:
            break
    return images


def _build_context_message(inspection_context: Optional[Dict]) -> str:
    """Build a context string from inspection results or profile data."""
    if not inspection_context:
        return ""

    parts = []
    pn = inspection_context.get("part_number")
    pname = inspection_context.get("part_name")
    if pn:
        parts.append(f"Current part: {pn} ({pname or 'unknown'})")

    gs = inspection_context.get("gap_summary")
    if gs:
        parts.append(f"Inspection results: {gs.get('completeness', 'N/A')}% complete, "
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

    # Selected dimensions from Dimension Explorer
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

    # Available drawing views for agent-driven view highlighting
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

    # All available parts for agent-driven highlighting
    available_parts = inspection_context.get("available_parts", [])
    if available_parts:
        ap_lines = ["AVAILABLE PARTS IN THIS ASSEMBLY (you can highlight any of these in 3D):"]
        for ap in available_parts:
            pn = ap.get("part_number", "")
            desc = ap.get("description", "")
            label = pn
            if desc:
                label += f" \u2014 {desc}"
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
            dir_vec = step.get("direction", [0, 0, 0])
            axes = {0: "X", 1: "Y", 2: "Z"}
            dir_desc = ", ".join(f"{'+' if dir_vec[i] > 0 else '-'}{axes[i]}" for i in range(3) if abs(dir_vec[i]) > 0.01)
            es_lines.append(f"  Step {step.get('stepIndex', 0) + 1}: {', '.join(part_names)} → direction {dir_desc}")
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

        # Merge inspection_context from either field name
        ctx = request.inspection_context or request.context or {}

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

        # Parse ANIMATE_MOTION marker
        animate_match = re.search(r'ANIMATE_MOTION:\s*(start|stop)', response_text, re.I)
        if animate_match:
            result["animate_motion"] = animate_match.group(1).lower()
            response_text = re.sub(r'ANIMATE_MOTION:\s*(start|stop)\s*', '', response_text, flags=re.I).strip()
            result["response"] = response_text

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
            ctx = request.inspection_context or request.context or {}
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

# Per-agent voice mapping (ElevenLabs voice IDs)
AGENT_VOICE_MAP = {
    "inspector":         os.getenv("ELEVENLABS_VOICE_IRIS",  "21m00Tcm4TlvDq8ikWAM"),  # Rachel
    "deviation-analyst": os.getenv("ELEVENLABS_VOICE_SAGE",  "gs0tAILXbY5DNrJrsM6F"),
    "parts-finder":      os.getenv("ELEVENLABS_VOICE_SCOUT", "AZnzlk1XvdvUeBnXmlld"),  # Domi
}


class VoiceSynthesizeRequest(BaseModel):
    text: str
    agent_type: str = "inspector"


@app.post("/api/voice/transcribe")
async def voice_transcribe(audio: UploadFile = File(...)):
    """Transcribe audio to text using OpenAI Whisper."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    audio_bytes = await audio.read()
    if len(audio_bytes) == 0:
        raise HTTPException(status_code=422, detail="Audio file is empty")
    if len(audio_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio file exceeds 25MB limit")

    try:
        import io
        import asyncio
        import openai
        client = openai.OpenAI(api_key=api_key)

        audio_file = io.BytesIO(audio_bytes)
        audio_file.name = audio.filename or "recording.webm"

        # Run sync Whisper call off the event loop
        transcript = await asyncio.to_thread(
            client.audio.transcriptions.create,
            model="whisper-1",
            file=audio_file,
            response_format="text",
        )

        text = transcript.strip()
        if not text:
            raise HTTPException(status_code=422, detail="No speech detected in audio")

        logger.info(f"Whisper transcription: {len(audio_bytes)} bytes -> {len(text)} chars")
        return {"text": text}

    except openai.APIError as e:
        logger.error(f"Whisper API error: {e}")
        raise HTTPException(status_code=502, detail=f"Whisper transcription failed: {str(e)}")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")


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
