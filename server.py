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
import sqlite3
import threading
import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any, Tuple

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent
load_dotenv(dotenv_path=REPO_ROOT / ".env")

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai_inspector.spatial import SpatialInspector
from ai_inspector.spatial.profile_validator import validate_all_profiles, validate_profile
from ai_inspector.utils.drawing_map import (
    apply_drawing_map_to_findings,
    load_drawing_map,
    load_drawing_map_revision,
    list_drawing_map_revisions,
    normalize_drawing_map,
    sanitize_part_number,
)
from ai_inspector.classification import classify_drawing_mode
from ai_inspector.bridge import (
    BridgeClient,
    BridgeUnavailableError,
    BridgeUnauthorizedError,
    BridgeJobConflictError,
    BridgeBadResponseError,
    JOB_STATE_AWAITING_APPROVAL,
    JOB_STATE_DONE,
    JOB_STATE_DENIED,
    JOB_STATE_FAILED,
    JobSnapshot,
    KIND_DRAWING,
    KIND_PART,
    KIND_ASSEMBLY,
)
# Phase 2 + 3 telemetry instrumentation. All helpers are soft-fail
# (telemetry exceptions never affect responses).
from ai_inspector.telemetry import (
    TelemetryStore,
    classify_exception_status,
    default_db_path,
    record_anthropic_call,
    record_endpoint_event,
    record_openai_transcription,
    record_workflow_stage,
    time_block,
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("inspectorpro")

_DEFAULT_LIBRARY_NAME = "400S_Sorted_Library"


def _limited_count(paths, limit: int = 80) -> int:
    """Count path iterator items without walking an entire large library."""
    count = 0
    for _ in paths:
        count += 1
        if count >= limit:
            break
    return count


def _library_score(path: Path) -> int:
    """Rank candidate inspection libraries by useful CAD/profile content."""
    if not path.exists() or not path.is_dir():
        return -1
    profile_count = _limited_count(path.rglob("*_inspection_profile.json"))
    assembly_dir = path / "assemblies"
    assembly_count = _limited_count(assembly_dir.glob("*_assembly.json")) if assembly_dir.is_dir() else 0
    parts_dir = path / "parts"
    part_dir_count = _limited_count((p for p in parts_dir.iterdir() if p.is_dir())) if parts_dir.is_dir() else 0
    return profile_count * 10 + assembly_count * 5 + part_dir_count


def _primary_workspace_library_from_worktree(repo_root: Path) -> Optional[Path]:
    """Return the primary workspace library when running from a feature worktree."""
    for parent in [repo_root, *repo_root.parents]:
        if parent.name == ".claude":
            return parent.parent / _DEFAULT_LIBRARY_NAME
        if parent.name == "tmp":
            primary = parent.parent / _DEFAULT_LIBRARY_NAME
            if primary.exists() and primary.is_dir():
                return primary
    return None


def _resolve_library_dir() -> Path:
    """Resolve the real inspection library.

    Feature worktrees usually contain only a sparse tracked library stub.
    When that happens, prefer the fuller primary workspace library so
    profiles, assembly membership, GLBs, and revision sidecars still load.
    """
    env_dir = os.getenv("INSPECTORPRO_LIBRARY_DIR", "").strip()
    if env_dir:
        candidate = Path(env_dir).expanduser()
        if candidate.exists() and candidate.is_dir():
            resolved = candidate.resolve()
            logger.info("Using inspection library from INSPECTORPRO_LIBRARY_DIR=%s", resolved)
            return resolved
        logger.warning("INSPECTORPRO_LIBRARY_DIR does not exist or is not a directory: %s", env_dir)

    candidates: List[Path] = [
        REPO_ROOT / _DEFAULT_LIBRARY_NAME,
        Path.cwd() / _DEFAULT_LIBRARY_NAME,
    ]
    primary_library = _primary_workspace_library_from_worktree(REPO_ROOT)
    if primary_library is not None:
        candidates.append(primary_library)

    unique_candidates = []
    seen = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate.absolute())
        if key not in seen:
            seen.add(key)
            unique_candidates.append(candidate)

    scored = [(candidate, _library_score(candidate)) for candidate in unique_candidates]
    best, best_score = max(scored, key=lambda item: item[1])
    resolved = best.resolve() if best.exists() else best.absolute()
    logger.info(
        "Resolved inspection library: %s (score=%s; candidates=%s)",
        resolved,
        best_score,
        ", ".join(f"{c}={s}" for c, s in scored),
    )
    return resolved


LIBRARY_DIR = _resolve_library_dir()


def library_path(*parts: str) -> Path:
    return LIBRARY_DIR.joinpath(*parts)


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

    # Phase 2 telemetry: Whisper transcription. Per pricing.py whisper-1
    # is confidence="unknown" (per-audio-minute, not per-token), so cost
    # is recorded as 0; latency + status are still useful.
    with time_block() as _elapsed_ms:
        try:
            import openai
            client = openai.OpenAI(api_key=api_key)
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = filename or "recording.webm"
            transcript = await asyncio.to_thread(
                client.audio.transcriptions.create,
                model="whisper-1", file=audio_file, response_format="text",
            )
            record_openai_transcription(
                model="whisper-1", latency_ms=_elapsed_ms(),
                route="/api/voice/transcribe", workflow="voice_transcribe", agentType="none",
            )
            return {"text": transcript.strip()}
        except Exception as e:
            _status, _err = classify_exception_status(e)
            record_openai_transcription(
                model="whisper-1", latency_ms=_elapsed_ms(),
                status=_status, errorType=_err,
                route="/api/voice/transcribe", workflow="voice_transcribe", agentType="none",
            )
            raise HTTPException(status_code=502, detail=f"Transcription failed: {str(e)}")


# Assembly reverse-lookup data (populated at startup)
assembly_part_lookup: Dict[str, List[str]] = {}   # part_number -> [assembly_number, ...]
assembly_profiles: Dict[str, dict] = {}            # assembly_number -> loaded JSON dict


def _part_root_dir(safe_pn: str) -> Path:
    """Return the part asset root, accepting standard and doubled layouts."""
    base = library_path("parts", safe_pn)
    doubled = base / safe_pn
    if doubled.exists() and doubled.is_dir():
        return doubled
    return base


def _part_rev_dir(safe_pn: str, safe_rev: str) -> Path:
    return _part_root_dir(safe_pn) / f"rev{safe_rev}"


def _part_asset_candidates(safe_pn: str, *relative_parts: str) -> List[Path]:
    """Candidate part asset paths, doubled layout first then standard layout."""
    base = library_path("parts", safe_pn)
    roots = []
    doubled = base / safe_pn
    if doubled.exists() and doubled.is_dir():
        roots.append(doubled)
    roots.append(base)
    return [root.joinpath(*relative_parts) for root in roots]


def _resolve_part_asset(safe_pn: str, *relative_parts: str) -> Optional[Path]:
    for candidate in _part_asset_candidates(safe_pn, *relative_parts):
        if candidate.exists():
            return candidate
    return None


# ── Library Intake Wizard — stub-profile awareness (Step 1) ───────────
#
# Per docs/library-intake-wizard-plan.md §5.7, a profile written by the
# wizard's intake flow is marked with `source: "library_intake_stub"`.
# Downstream consumers (get_profile_details, run_inspection, the
# /api/profiles picker via SpatialInspector.list_profiles) must detect
# this and gate inspection actions so the operator never sees an
# incomplete-profile part presented as inspection-ready.
#
# This file owns the canonical detection rule + path-resolution helpers
# so the gates in /api/profile-details (§9.5) and /api/inspect (§9.6)
# stay consistent. Both gates use the same predicate so the UI and
# backend never disagree about which parts are stubs.

INTAKE_STUB_SOURCE = "library_intake_stub"
INTAKE_STUB_INSPECT_MESSAGE = (
    "This part has been added to the library, but no inspection profile "
    "has been authored yet."
)


def _is_intake_stub_profile(profile_data: Any) -> bool:
    """Single source of truth for the intake-stub detection rule (§5.7).

    Returns True iff the parsed profile JSON has top-level
    `source == "library_intake_stub"`. Defensive: non-dict input returns
    False so a malformed/unreadable file does NOT silently get treated
    as a stub.
    """
    return isinstance(profile_data, dict) and profile_data.get("source") == INTAKE_STUB_SOURCE


def _resolve_profile_path(safe_pn: str) -> Optional[Path]:
    """Resolve the root-level profile JSON path for a part. Same candidate
    order get_profile_details uses, factored out so the run_inspection
    fail-fast gate can do the same lookup without re-reading the file."""
    library_dir = library_path()
    candidates = [
        library_dir / f"{safe_pn}_inspection_profile.json",
        library_dir / f"{safe_pn}.json",
        *_part_asset_candidates(safe_pn, "revA", f"{safe_pn}_inspection_profile.json"),
        *_part_asset_candidates(safe_pn, "revA", f"{safe_pn}.json"),
    ]
    return next((p for p in candidates if p.exists()), None)


def _load_profile_if_present(part_number: str) -> Optional[dict]:
    """Read the raw profile JSON for a part, or None if missing or
    unreadable. Used by the stub-awareness gates -- never raises
    (callers fall through to existing handler behaviour on None)."""
    safe_pn = re.sub(r"[^\w\-]", "", part_number or "")
    if not safe_pn:
        return None
    path = _resolve_profile_path(safe_pn)
    if path is None:
        return None
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


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
    assemblies_dir = library_path("assemblies")
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

    assembly_part_lookup = {}
    assembly_profiles = {}

    assemblies_dir = library_path("assemblies")
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
    logger.info("Initializing SpatialInspector with library_dir=%r...", str(LIBRARY_DIR))
    inspector = SpatialInspector(library_dir=str(LIBRARY_DIR))
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


# Phase 3 telemetry: endpoint timing middleware. Records one telemetry
# event per /api/* request (route, method, http status, latency). Skips
# static assets and the root index so we don't bury the dashboard in
# noise. The helper is soft-fail; an exception inside it never affects
# the response — that contract is enforced inside record_endpoint_event.
@app.middleware("http")
async def _telemetry_endpoint_timing(request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or path.startswith("/api/metrics/"):
        # Skip /, /static/*, /favicon.ico, and the dashboard's own
        # metrics API so usage tracking does not count itself.
        return await call_next(request)
    import time as _time
    _start = _time.perf_counter()
    response = None
    raised: Optional[BaseException] = None
    try:
        response = await call_next(request)
        return response
    except BaseException as ex:
        raised = ex
        raise
    finally:
        try:
            elapsed_ms = (_time.perf_counter() - _start) * 1000.0
            if response is not None:
                http_status = int(response.status_code)
            elif isinstance(raised, HTTPException):
                http_status = int(getattr(raised, "status_code", 500))
            else:
                http_status = 500
            record_endpoint_event(
                route=path,
                method=request.method,
                httpStatus=http_status,
                latency_ms=elapsed_ms,
                errorType=(type(raised).__name__ if raised is not None and not isinstance(raised, HTTPException) else None),
            )
        except Exception:  # noqa: BLE001 — last-ditch belt-and-suspenders
            # record_endpoint_event itself is soft-fail; this outer
            # except is the FastAPI-middleware contract — we MUST NOT
            # raise out of the finally clause.
            pass


# ---------- API Endpoints ----------


_METRICS_RANGE_LABELS = {
    "24h": ("Last 24 hours", timedelta(hours=24)),
    "7d": ("Last 7 days", timedelta(days=7)),
    "30d": ("Last 30 days", timedelta(days=30)),
}
_PROVIDER_NAMES = {"anthropic", "openai"}


def _metrics_float(value, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        num = float(value)
        if math.isfinite(num):
            return num
    except (TypeError, ValueError):
        pass
    return default


def _metrics_int(value, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _metrics_percentile(values: List[float], pct: float) -> float:
    clean = sorted(v for v in values if isinstance(v, (int, float)) and math.isfinite(float(v)))
    if not clean:
        return 0.0
    idx = int(math.ceil((pct / 100.0) * len(clean))) - 1
    return float(clean[max(0, min(idx, len(clean) - 1))])


def _metrics_confidence(rows: List[Dict[str, Any]]) -> str:
    confidences = {str(r.get("pricingConfidence") or "unknown") for r in rows if r.get("provider") in _PROVIDER_NAMES}
    if not confidences:
        return "unknown"
    if "unknown" in confidences:
        return "unknown"
    if "estimated" in confidences:
        return "estimated"
    return "verified"


def _metrics_group(rows: List[Dict[str, Any]], key_fields: Tuple[str, ...]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, ...], List[Dict[str, Any]]] = {}
    for row in rows:
        key = tuple(str(row.get(field) or "") for field in key_fields)
        grouped.setdefault(key, []).append(row)

    result = []
    for key, group_rows in grouped.items():
        latencies = [_metrics_float(r.get("latencyMs")) for r in group_rows]
        failures = [
            r for r in group_rows
            if str(r.get("status") or "").lower() != "success"
            or (_metrics_int(r.get("httpStatus")) >= 400 if r.get("httpStatus") is not None else False)
        ]
        item = {field: key[i] for i, field in enumerate(key_fields)}
        item.update({
            "events": len(group_rows),
            "errors": len(failures),
            "errorRate": (len(failures) / len(group_rows)) if group_rows else 0.0,
            "inputTokens": sum(_metrics_int(r.get("inputTokens")) for r in group_rows),
            "outputTokens": sum(_metrics_int(r.get("outputTokens")) for r in group_rows),
            "totalTokens": sum(_metrics_int(r.get("totalTokens")) for r in group_rows),
            "estimatedCostUsd": sum(_metrics_float(r.get("estimatedCostUsd")) for r in group_rows),
            "pricingConfidence": _metrics_confidence(group_rows),
            "avgLatencyMs": (sum(latencies) / len(latencies)) if latencies else 0.0,
            "p95LatencyMs": _metrics_percentile(latencies, 95),
        })
        result.append(item)
    result.sort(key=lambda x: (x.get("estimatedCostUsd", 0.0), x.get("events", 0)), reverse=True)
    return result


def _load_telemetry_rows(range_key: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Path]:
    label, delta = _METRICS_RANGE_LABELS.get(range_key, _METRICS_RANGE_LABELS["24h"])
    now = datetime.now(timezone.utc)
    cutoff = now - delta
    db_path = default_db_path()

    # Initialize/migrate the store before direct dashboard reads. This keeps
    # the dashboard compatible with a v1 database from before Phase 3.
    store = TelemetryStore(db_path)
    store.query_recent(1)
    store.close()

    if not db_path.exists():
        return (
            {
                "key": range_key if range_key in _METRICS_RANGE_LABELS else "24h",
                "label": label,
                "cutoffUtc": cutoff.isoformat(),
                "generatedAtUtc": now.isoformat(),
            },
            [],
            db_path,
        )

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT * FROM telemetry_events WHERE timestampUtc >= ? ORDER BY timestampUtc DESC",
            (cutoff.isoformat(),),
        )
        rows = [dict(row) for row in cursor.fetchall()]

    return (
        {
            "key": range_key if range_key in _METRICS_RANGE_LABELS else "24h",
            "label": label,
            "cutoffUtc": cutoff.isoformat(),
            "generatedAtUtc": now.isoformat(),
        },
        rows,
        db_path,
    )


def _build_usage_metrics(range_key: str, limit: int) -> Dict[str, Any]:
    range_info, rows, db_path = _load_telemetry_rows(range_key)
    provider_rows = [r for r in rows if str(r.get("provider") or "").lower() in _PROVIDER_NAMES]
    endpoint_rows = [r for r in rows if r.get("httpStatus") is not None]
    workflow_stage_rows = [r for r in rows if r.get("stage")]
    bridge_rows = [r for r in workflow_stage_rows if r.get("workflow") == "bridge_extract"]

    provider_latencies = [_metrics_float(r.get("latencyMs")) for r in provider_rows]
    endpoint_latencies = [_metrics_float(r.get("latencyMs")) for r in endpoint_rows]
    failure_rows = [
        r for r in rows
        if str(r.get("status") or "").lower() != "success"
        or (_metrics_int(r.get("httpStatus")) >= 400 if r.get("httpStatus") is not None else False)
    ]
    total_cost = sum(_metrics_float(r.get("estimatedCostUsd")) for r in provider_rows)
    provider_calls = len(provider_rows)

    def public_event(row: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "timestampUtc": row.get("timestampUtc"),
            "route": row.get("route"),
            "workflow": row.get("workflow"),
            "stage": row.get("stage"),
            "agentType": row.get("agentType"),
            "provider": row.get("provider"),
            "model": row.get("model"),
            "status": row.get("status"),
            "errorType": row.get("errorType"),
            "httpStatus": row.get("httpStatus"),
            "latencyMs": _metrics_float(row.get("latencyMs")),
            "totalTokens": _metrics_int(row.get("totalTokens")),
            "estimatedCostUsd": _metrics_float(row.get("estimatedCostUsd")),
            "pricingConfidence": row.get("pricingConfidence"),
            "partNumber": row.get("partNumber"),
            "documentKind": row.get("documentKind"),
        }

    return {
        "range": range_info,
        "dbPath": str(db_path),
        "summary": {
            "totalEvents": len(rows),
            "providerCalls": provider_calls,
            "endpointEvents": len(endpoint_rows),
            "workflowStageEvents": len(workflow_stage_rows),
            "errorCount": len(failure_rows),
            "errorRate": (len(failure_rows) / len(rows)) if rows else 0.0,
            "inputTokens": sum(_metrics_int(r.get("inputTokens")) for r in provider_rows),
            "outputTokens": sum(_metrics_int(r.get("outputTokens")) for r in provider_rows),
            "totalTokens": sum(_metrics_int(r.get("totalTokens")) for r in provider_rows),
            "estimatedCostUsd": total_cost,
            "pricingConfidence": _metrics_confidence(provider_rows),
            "avgCostPerProviderCallUsd": (total_cost / provider_calls) if provider_calls else 0.0,
            "avgProviderLatencyMs": (sum(provider_latencies) / len(provider_latencies)) if provider_latencies else 0.0,
            "p95ProviderLatencyMs": _metrics_percentile(provider_latencies, 95),
            "avgEndpointLatencyMs": (sum(endpoint_latencies) / len(endpoint_latencies)) if endpoint_latencies else 0.0,
            "p95EndpointLatencyMs": _metrics_percentile(endpoint_latencies, 95),
        },
        "byProviderModel": _metrics_group(provider_rows, ("provider", "model"))[:20],
        "byWorkflow": _metrics_group(workflow_stage_rows, ("workflow",))[:20],
        "bridgeStages": _metrics_group(bridge_rows, ("stage",))[:20],
        "endpointRoutes": _metrics_group(endpoint_rows, ("route",))[:20],
        "recentEvents": [public_event(r) for r in rows[:max(1, min(int(limit), 200))]],
    }


@app.get("/api/metrics/usage")
async def get_usage_metrics(
    range_key: str = Query("24h", alias="range", description="Metrics range: 24h, 7d, or 30d"),
    limit: int = Query(25, ge=1, le=200, description="Recent event row limit"),
):
    """Return token, cost, latency, and workflow telemetry for the Usage dashboard.

    The response contains only counters and short identifiers already present in
    TelemetryEvent. Raw prompts, responses, API keys, drawings, and CAD payloads
    are not stored in telemetry and are not exposed here.
    """
    try:
        return _build_usage_metrics(range_key, limit)
    except Exception as e:
        logger.error("Error building usage metrics dashboard payload: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Usage metrics unavailable")


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
        if not result.get("part_number"):
            stem = Path(filename or "").stem
            raw_candidates = [stem]
            raw_candidates.extend(re.split(r"[^A-Za-z0-9_-]+", stem))
            for raw in raw_candidates:
                candidate = re.sub(r"[^\w\-]", "", raw or "")
                if not candidate:
                    continue
                if candidate in assembly_profiles:
                    return {
                        "part_number": candidate,
                        "match_type": "assembly_direct",
                        "candidate": candidate,
                    }
                rev_match = re.match(r"^(.+?)[-_]?REV[-_]?[A-Z0-9]*$", candidate, re.IGNORECASE)
                if rev_match:
                    base = re.sub(r"[^\w\-]", "", rev_match.group(1) or "")
                    if base in assembly_profiles:
                        return {
                            "part_number": base,
                            "match_type": "assembly_direct",
                            "candidate": candidate,
                        }
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
async def get_drawing_map(part_number: str, revision: Optional[str] = Query(None)):
    """Return a normalized drawing map for a part number, optionally revision-specific."""
    safe_pn = sanitize_part_number(part_number)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")

    try:
        safe_rev = re.sub(r"[^\w]", "", revision or "")
        drawing_map = (
            load_drawing_map_revision(safe_pn, safe_rev, LIBRARY_DIR)
            if safe_rev
            else load_drawing_map(safe_pn, LIBRARY_DIR)
        )
        if drawing_map is None:
            rev_msg = f" revision '{safe_rev}'" if safe_rev else ""
            raise HTTPException(
                status_code=404,
                detail=f"No drawing map found for part number '{safe_pn}'{rev_msg}",
            )
        return drawing_map
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting drawing map for '{safe_pn}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Phase 10D: SOLIDWORKS extraction bridge endpoints ──────────────
#
# /api/bridge/status            — discoverability probe; always 200
# /api/request-extraction       — drives the bridge end-to-end and
#                                 imports the package into 400S_Sorted_Library
#
# See ai_inspector/bridge/ for the client + protocol details.
# Audit trail spans both sides: the SW addin writes
# %LOCALAPPDATA%\InspectorPro\Bridge\audit.log; this server logs to
# the standard logger with the prefix "request_extraction.".
#
# One request at a time per the Week 10D scope: an asyncio.Lock
# serializes calls to /api/request-extraction so the SW user does not
# see overlapping approval windows.

_request_extraction_lock = asyncio.Lock()

# Configurable path to the inspectorpkg CLI used for validate-package +
# compat-export. Override via INSPECTORPKG_CLI env var. The default is
# the Release build alongside the Week-9+ SOLIDWORKS extractor repo —
# fragile to dev-machine layout, which is why it is overridable.
_DEFAULT_INSPECTORPKG_CLI = (
    r"C:\Users\skaumb\OneDrive - continentalmachines.com\Desktop\Projects"
    r"\InspectorPro.SolidWorks\src\InspectorPro.PackageCli\bin\Release\net48\inspectorpkg.exe"
)


def _inspectorpkg_cli_path() -> Optional[str]:
    """Return a usable inspectorpkg.exe path or None if not found."""
    candidate = os.environ.get("INSPECTORPKG_CLI") or _DEFAULT_INSPECTORPKG_CLI
    return candidate if (candidate and Path(candidate).exists()) else None


class RequestExtractionBody(BaseModel):
    """POST /api/request-extraction body. Field names mirror the bridge
    JSON exactly so request flows are easy to trace end-to-end."""
    partNumber: str
    expectedDocPath: Optional[str] = None


@app.get("/api/bridge/status")
async def bridge_status():
    """Discoverability probe for the InspectorPro app's UI.

    Always returns 200 so callers can render a clean disabled state
    when the bridge is missing — they should NOT need try/except for
    the common "SOLIDWORKS isn't running" case.

    Week 11 fields:
      - authRequired:  bridge has Week-11 auth enabled
      - authenticated: our request authenticated successfully
    A Week-11 bridge that we can reach but cannot authenticate against
    surfaces available=true, authRequired=true, authenticated=false so
    the UI can render a "Bridge: auth missing / unauthorized" state
    rather than the generic "unavailable".
    """
    client = BridgeClient()
    info = client.discover()
    if info is None:
        return {
            "available": False,
            "authRequired": False,
            "authenticated": False,
            "message": "SOLIDWORKS bridge not available "
                       "(InspectorPro add-in not loaded, or SOLIDWORKS not running).",
        }
    status = await client.status()
    if status is None:
        return {
            "available": False,
            "authRequired": False,
            "authenticated": False,
            "message": "SOLIDWORKS bridge port file present but the bridge is not responding.",
        }

    # Week-11 bridge with auth enforced: when our token is missing or
    # wrong, the bridge replies 200 with the minimal body
    # (authRequired=true, authenticated=false, no activeDoc). Surface
    # that to the UI as a distinct state.
    if status.auth_required and not status.authenticated:
        return {
            "available": True,
            "authRequired": True,
            "authenticated": False,
            "bridgeVersion": status.bridge_version,
            "message": "SOLIDWORKS bridge is running but the app's token does not match. "
                       "Verify %LOCALAPPDATA%/InspectorPro/Bridge/bridge_token.",
        }

    return {
        "available": True,
        "authRequired": status.auth_required,
        "authenticated": status.authenticated,
        "swRunning": status.sw_running,
        "bridgeVersion": status.bridge_version,
        "swProcessId": status.sw_process_id,
        "activeDoc": (
            None if status.active_doc is None else {
                "type":  status.active_doc.type,
                "title": status.active_doc.title,
                "path":  status.active_doc.path,
            }
        ),
    }


@app.post("/api/request-extraction")
async def request_extraction(body: RequestExtractionBody):
    """Drive the SOLIDWORKS bridge end-to-end and import the resulting
    drawing package into 400S_Sorted_Library.

    Phases (each emits a log line under "request_extraction.*"):
      start            → request received
      precheck         → bridge alive, active doc is a drawing
      job.created      → POST /jobs/extract returned awaiting-approval
      bridge.done      → user approved + extraction completed
      bridge.denied    → user denied or approval timed out
      bridge.failed    → extraction threw on the SW side
      package.downloaded
      package.validated
      compat.exported
      imported         → atomic-replace into 400S_Sorted_Library + load verified
      failed.<phase>   → any non-recoverable failure
    """
    safe_pn = sanitize_part_number(body.partNumber)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")
    expected_doc_path = (body.expectedDocPath or "").strip() or None

    if _request_extraction_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Another extraction request is in progress; one at a time.",
        )

    async with _request_extraction_lock:
        return await _drive_extraction(safe_pn, expected_doc_path)


@app.post("/api/request-part-extraction")
async def request_part_extraction(body: RequestExtractionBody):
    """Drive the bridge to extract a Part package and install it as a
    sidecar under 400S_Sorted_Library/_bridge_imports/part/{pn}/.

    Sidecar-only — never touches manual library files (the curated
    {pn}.json / {pn}_inspection_profile.json / view PNGs / etc. under
    400S_Sorted_Library/parts/{pn}/...). See
    docs/bridge-part-assembly-app-integration-plan.md §4.2.

    Same single-flight gate as the drawing endpoint — the SW user
    only ever sees one approval modal at a time.
    """
    safe_pn = sanitize_part_number(body.partNumber)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")
    expected_doc_path = (body.expectedDocPath or "").strip() or None

    if _request_extraction_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Another extraction request is in progress; one at a time.",
        )

    async with _request_extraction_lock:
        return await _drive_part_extraction(safe_pn, expected_doc_path)


@app.post("/api/request-assembly-extraction")
async def request_assembly_extraction(body: RequestExtractionBody):
    """Drive the bridge to extract an Assembly package and install it
    as a sidecar under 400S_Sorted_Library/_bridge_imports/assembly/{pn}/.

    Same sidecar-only / single-flight contract as the part endpoint
    above. See docs/bridge-part-assembly-app-integration-plan.md §4.3.
    """
    safe_pn = sanitize_part_number(body.partNumber)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")
    expected_doc_path = (body.expectedDocPath or "").strip() or None

    if _request_extraction_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Another extraction request is in progress; one at a time.",
        )

    async with _request_extraction_lock:
        return await _drive_assembly_extraction(safe_pn, expected_doc_path)


# ─────────────────────────────────────────────────────────────────────
# Shared bridge pipeline (Phase B refactor)
# ─────────────────────────────────────────────────────────────────────
#
# The full bridge extraction pipeline has two distinct halves:
#
#   Half 1 (kind-agnostic, shared):
#     precheck → POST /jobs/extract → poll → download .zip → validate
#       via inspectorpkg validate-package → unzip into staging
#
#   Half 2 (kind-specific, per-orchestrator):
#     drawing  → compat-export + atomic-replace into library root with
#                .bak rollback + load_drawing_map verify
#     part     → sidecar install into _bridge_imports/part/{pn}/{pkgId}/
#     assembly → sidecar install into _bridge_imports/assembly/{pn}/{pkgId}/
#
# `_bridge_extract_and_unpack` is half 1; the three `_drive_*_extraction`
# orchestrators below own half 2. Drawing's half 2 logic was written
# pre-Phase-A and the orchestrator preserves its byte-equivalent
# behaviour (same .bak rollback, same atomic-replace, same load_verify
# probe, same cleanup ordering).


@dataclass
class _BridgeFetchOk:
    """Successful outcome of the kind-agnostic bridge pipeline.

    The caller is responsible for the per-kind import tail AND for
    cleaning up `zip_path` and `pkg_folder` after a successful import
    (the helper does NOT clean them up on success — different
    orchestrators have slightly different cleanup ordering). The
    helper DOES clean both up on its own failure paths so a partial
    download / unzip cannot leak into a future re-extraction.
    """
    snap: JobSnapshot
    pkg_folder: Path     # unzipped {packageId}.inspectorpkg/ in staging_dir
    zip_path: Path       # downloaded {packageId}.inspectorpkg.zip in staging_dir
    library_root: Path   # 400S_Sorted_Library
    staging_dir: Path    # library_root / _staging


class _BridgeNotDone(Exception):
    """Bridge reached a terminal state OTHER than DONE (denied, failed,
    or anything unexpected). Caller catches and renders its own
    kind-specific failure response shape — denied/failed do NOT raise
    HTTPException because the consumer-visible 200 OK + success=false
    is part of the established contract.

    Transport / timeout / precondition failures are raised as
    HTTPException directly from the helper instead.
    """
    def __init__(self, snap: JobSnapshot):
        super().__init__(f"bridge terminal state {snap.state}")
        self.snap = snap


# Per-kind precheck wording. Drawing strings are byte-equivalent to the
# pre-Phase-B wording; part / assembly use parallel structure with the
# right doctype + file-extension hints.
_PRECHECK_NO_DOC_HINT = {
    KIND_DRAWING:  "Open the drawing first.",
    KIND_PART:     "Open the part first.",
    KIND_ASSEMBLY: "Open the assembly first.",
}
_PRECHECK_EXPECTED_TYPE = {
    KIND_DRAWING:  "Drawing",
    KIND_PART:     "Part",
    KIND_ASSEMBLY: "Assembly",
}
_PRECHECK_OPEN_HINT = {
    KIND_DRAWING:  "Open the drawing for this part and try again.",
    KIND_PART:     "Open the corresponding .SLDPRT file and try again.",
    KIND_ASSEMBLY: "Open the corresponding .SLDASM file and try again.",
}


async def _bridge_extract_and_unpack(
    *,
    kind: str,
    part_number: str,
    expected_doc_path: Optional[str],
    log_prefix: str,
) -> _BridgeFetchOk:
    """Run the kind-agnostic phases of bridge extraction:
        precheck → POST /jobs/extract → poll → download → validate → unzip

    Behavioural contract:
      - HTTPException on transport / timeout / precondition / validate /
        unzip failures (FastAPI propagates to the client directly).
      - _BridgeNotDone(snap) on bridge terminal state DENIED / FAILED.
        Caller catches and renders a 200 OK with success=false + the
        relevant kind/jobState/message fields.
      - _BridgeFetchOk on bridge terminal state DONE.

    `log_prefix` lets each per-kind orchestrator namespace its log
    lines:  "request_extraction" (drawing — preserves byte-equivalent
    grep recipes), "request_part_extraction", "request_assembly_extraction".

    Drawing flow stays byte-equivalent on the wire: when kind=KIND_DRAWING
    the bridge POST omits the `kind` field entirely (same body the
    pre-Phase-A client sent). For non-drawing kinds, the kind field is
    explicitly sent and the bridge dispatches accordingly.
    """
    log = logger
    log.info("%s.start pn=%s expectedDocPath=%s", log_prefix, part_number, expected_doc_path)
    client = BridgeClient()

    # Phase 3 telemetry: workflow="bridge_extract" stage timers. The
    # approval_wait vs extract_wait split is the most-important piece —
    # waiting for the user to click Approve in SOLIDWORKS should never
    # be blamed on software latency.
    import time as _t_bridge
    _wf_route = f"/api/request-{kind}-extraction" if kind != KIND_DRAWING else "/api/request-extraction"
    _stage_start = _t_bridge.perf_counter()

    def _emit_stage(stage_name, *, status="success", errorType=None, latency_ms=None):
        if latency_ms is None:
            latency_ms = (_t_bridge.perf_counter() - _stage_start) * 1000.0
        record_workflow_stage(
            workflow="bridge_extract", stage=stage_name,
            latency_ms=latency_ms, status=status, errorType=errorType,
            route=_wf_route, partNumber=part_number, documentKind=kind,
        )

    # ── Precheck: bridge available + authenticated + active doc matches kind ──
    status = await client.status()
    if status is None:
        log.warning("%s.failed.bridge_unavailable pn=%s", log_prefix, part_number)
        raise HTTPException(
            status_code=503,
            detail="SOLIDWORKS bridge not available. "
                   "Open SOLIDWORKS with the InspectorPro add-in enabled and try again.",
        )
    # Week 11: Bridge running with auth, but our token does not match.
    # Fail FAST with 401 + actionable message, do not even try POSTing.
    if status.auth_required and not status.authenticated:
        log.warning("%s.failed.unauthorized pn=%s", log_prefix, part_number)
        raise HTTPException(
            status_code=401,
            detail="SOLIDWORKS bridge token is missing or invalid. "
                   "Restart SOLIDWORKS so the InspectorPro add-in regenerates "
                   "%LOCALAPPDATA%/InspectorPro/Bridge/bridge_token, then retry.",
        )
    if status.active_doc is None:
        log.warning("%s.failed.no_active_doc pn=%s", log_prefix, part_number)
        raise HTTPException(
            status_code=409,
            detail="No active document in SOLIDWORKS. " + _PRECHECK_NO_DOC_HINT[kind],
        )
    expected_type = _PRECHECK_EXPECTED_TYPE[kind]
    if status.active_doc.type != expected_type:
        # Drawing path uses the existing log key "not_a_drawing" for
        # byte-equivalent grep recipes; other kinds get the new
        # "kind_mismatch" key so callers can distinguish at a glance.
        log_key = "not_a_drawing" if kind == KIND_DRAWING else "kind_mismatch"
        log.warning("%s.failed.%s pn=%s active_type=%s",
                    log_prefix, log_key, part_number, status.active_doc.type)
        raise HTTPException(
            status_code=409,
            detail=f"Active document in SOLIDWORKS is a {status.active_doc.type}, not a {expected_type}. "
                   + _PRECHECK_OPEN_HINT[kind],
        )
    log.info("%s.precheck pn=%s active_doc_path=%s",
             log_prefix, part_number, status.active_doc.path)
    _precheck_done = _t_bridge.perf_counter()
    _emit_stage("precheck", latency_ms=(_precheck_done - _stage_start) * 1000.0)

    # ── Create job (triggers SW approval window) ───────────────────
    _create_start = _t_bridge.perf_counter()
    try:
        # Drawing flow stays byte-equivalent on the wire: omit `kind`
        # entirely. Bridge defaults missing kind to "drawing" via
        # BridgeKindNormaliser.Normalise, so the POST body and the
        # bridge's audit line are unchanged from pre-Phase-A.
        if kind == KIND_DRAWING:
            create = await client.request_extraction(part_number, expected_doc_path)
        else:
            create = await client.request_extraction(part_number, expected_doc_path, kind=kind)
    except BridgeUnauthorizedError as ex:
        log.warning("%s.failed.unauthorized pn=%s msg=%s", log_prefix, part_number, ex)
        raise HTTPException(
            status_code=401,
            detail="SOLIDWORKS bridge rejected the token. "
                   "Restart SOLIDWORKS to refresh the local bridge_token, then retry.",
        )
    except BridgeJobConflictError as ex:
        log.warning("%s.failed.bridge_conflict pn=%s active_job=%s",
                    log_prefix, part_number, ex.active_job_id)
        raise HTTPException(status_code=409, detail=str(ex))
    except BridgeUnavailableError as ex:
        log.warning("%s.failed.bridge_gone pn=%s msg=%s", log_prefix, part_number, ex)
        raise HTTPException(status_code=503, detail=f"SOLIDWORKS bridge unavailable: {ex}")
    except BridgeBadResponseError as ex:
        log.error("%s.failed.bridge_bad pn=%s status=%s body=%s",
                  log_prefix, part_number, ex.status_code, (ex.body or "")[:300])
        # 400 = precondition failure (e.g. doc changed between precheck and POST,
        #       or the bridge surfaces its own kind-mismatch wording from 5a.7).
        if ex.status_code == 400:
            raise HTTPException(status_code=409, detail=ex.body or str(ex))
        raise HTTPException(status_code=502, detail=f"bridge error: {ex}")

    job_id = create.job_id
    log.info("%s.job.created pn=%s jobId=%s state=%s",
             log_prefix, part_number, job_id, create.state)
    _create_done = _t_bridge.perf_counter()
    _emit_stage("job_create", latency_ms=(_create_done - _create_start) * 1000.0)

    # ── Poll until terminal (10-min hard cap) ──────────────────────
    # Track approval-wait split: the moment the bridge job leaves the
    # "awaiting-approval" state is when the SOLIDWORKS user clicked
    # Approve (or Deny). Everything before that is operator wait time;
    # everything after is bridge extraction work. The on_state_change
    # callback fires once per state transition during polling.
    _poll_start = _t_bridge.perf_counter()
    _approval_done_marker = [None]  # mutable holder so the nested cb can write

    def _on_state(old_state, new_state):
        if _approval_done_marker[0] is None and new_state != JOB_STATE_AWAITING_APPROVAL:
            _approval_done_marker[0] = _t_bridge.perf_counter()

    try:
        snap = await client.wait_for_terminal(
            job_id, poll_interval_s=1.0, timeout_s=600.0,
            on_state_change=_on_state,
        )
    except asyncio.TimeoutError:
        log.error("%s.failed.job_timeout pn=%s jobId=%s", log_prefix, part_number, job_id)
        raise HTTPException(
            status_code=504,
            detail="Timed out waiting for SOLIDWORKS extraction (10 minutes). "
                   "The job may still complete in SOLIDWORKS; check the add-in's audit log.",
        )
    except BridgeUnauthorizedError as ex:
        log.error("%s.failed.unauthorized_midpoll pn=%s jobId=%s msg=%s",
                  log_prefix, part_number, job_id, ex)
        raise HTTPException(
            status_code=401,
            detail="SOLIDWORKS bridge revoked the token mid-job. "
                   "Restart SOLIDWORKS to refresh bridge_token and retry.",
        )
    except BridgeUnavailableError as ex:
        log.error("%s.failed.bridge_lost pn=%s jobId=%s msg=%s",
                  log_prefix, part_number, job_id, ex)
        raise HTTPException(status_code=503, detail=f"bridge lost mid-job: {ex}")

    if snap.state in (JOB_STATE_DENIED, JOB_STATE_FAILED):
        # Caller renders its own kind-aware response shape.
        if snap.state == JOB_STATE_DENIED:
            log.info("%s.bridge.denied pn=%s jobId=%s reason=%s",
                     log_prefix, part_number, job_id, snap.error or "")
        else:
            log.error("%s.bridge.failed pn=%s jobId=%s reason=%s",
                      log_prefix, part_number, job_id, snap.error or "")
        raise _BridgeNotDone(snap)
    if snap.state != JOB_STATE_DONE:
        log.error("%s.failed.unexpected_state pn=%s jobId=%s state=%s",
                  log_prefix, part_number, job_id, snap.state)
        raise HTTPException(status_code=500, detail=f"unexpected terminal state {snap.state!r}")

    # Emit approval_wait + extract_wait stage events. If the user denied
    # immediately, _approval_done_marker may still be None — treat the
    # whole polling duration as approval_wait and extract_wait as 0.
    _poll_end = _t_bridge.perf_counter()
    _approval_done = _approval_done_marker[0] if _approval_done_marker[0] is not None else _poll_end
    _emit_stage("approval_wait",
                latency_ms=(_approval_done - _poll_start) * 1000.0)
    _emit_stage("extract_wait",
                latency_ms=(_poll_end - _approval_done) * 1000.0)

    # bridge.done log line — drawing keeps the original sheets/views
    # tail for byte-equivalent grep recipes; part/assembly use a
    # kind-aware line that reports the relevant counts.
    if kind == KIND_DRAWING:
        log.info("%s.bridge.done pn=%s jobId=%s packageId=%s sheets=%s views=%s",
                 log_prefix, part_number, job_id, snap.package_id,
                 snap.sheet_count, snap.view_count)
    elif kind == KIND_PART:
        log.info("%s.bridge.done pn=%s jobId=%s packageId=%s features=%s config=%s",
                 log_prefix, part_number, job_id, snap.package_id,
                 snap.feature_count, snap.active_configuration)
    else:  # KIND_ASSEMBLY
        log.info("%s.bridge.done pn=%s jobId=%s packageId=%s components=%s mates=%s config=%s",
                 log_prefix, part_number, job_id, snap.package_id,
                 snap.component_count, snap.mate_count, snap.active_configuration)

    # ── Stage path + download zip ──────────────────────────────────
    library_root = LIBRARY_DIR
    staging_dir = library_root / "_staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    if not snap.package_id:
        raise HTTPException(status_code=500, detail="bridge returned no packageId on done")
    zip_path = staging_dir / f"{snap.package_id}.inspectorpkg.zip"

    _download_start = _t_bridge.perf_counter()
    try:
        bytes_written = await client.download_package(job_id, zip_path)
    except BridgeUnauthorizedError as ex:
        log.error("%s.failed.unauthorized_download pn=%s jobId=%s msg=%s",
                  log_prefix, part_number, job_id, ex)
        raise HTTPException(
            status_code=401,
            detail="SOLIDWORKS bridge rejected the token on package download. "
                   "Restart SOLIDWORKS to refresh bridge_token and retry.",
        )
    except BridgeBadResponseError as ex:
        log.error("%s.failed.download_http pn=%s jobId=%s status=%s",
                  log_prefix, part_number, job_id, ex.status_code)
        if ex.status_code == 410:
            raise HTTPException(status_code=410,
                                detail="Package expired before download (5-minute TTL elapsed).")
        raise HTTPException(status_code=502, detail=f"package download HTTP {ex.status_code}")
    except BridgeUnavailableError as ex:
        log.error("%s.failed.download_transport pn=%s jobId=%s msg=%s",
                  log_prefix, part_number, job_id, ex)
        raise HTTPException(status_code=503, detail=f"package download failed: {ex}")
    log.info("%s.package.downloaded pn=%s jobId=%s bytes=%d path=%s",
             log_prefix, part_number, job_id, bytes_written, zip_path)
    _download_done = _t_bridge.perf_counter()
    _emit_stage("download", latency_ms=(_download_done - _download_start) * 1000.0)

    # ── Validate via inspectorpkg CLI ──────────────────────────────
    _validate_start = _t_bridge.perf_counter()
    cli = _inspectorpkg_cli_path()
    if cli is None:
        log.error("%s.failed.cli_missing INSPECTORPKG_CLI=%s default=%s",
                  log_prefix, os.environ.get("INSPECTORPKG_CLI"), _DEFAULT_INSPECTORPKG_CLI)
        # On failure, clean up the staged zip so a future re-extraction
        # is not confused by an orphan file.
        try: zip_path.unlink(missing_ok=True)
        except Exception: pass
        raise HTTPException(
            status_code=500,
            detail="inspectorpkg CLI not found. Set INSPECTORPKG_CLI env var or rebuild "
                   "the InspectorPro.SolidWorks Release configuration.",
        )

    try:
        rc = _run_subprocess([cli, "validate-package", str(zip_path)])
        if rc != 0:
            log.error("%s.failed.validate pn=%s rc=%d zip=%s",
                      log_prefix, part_number, rc, zip_path)
            try: zip_path.unlink(missing_ok=True)
            except Exception: pass
            raise HTTPException(status_code=500, detail=f"validate-package failed (rc={rc})")
        log.info("%s.package.validated pn=%s", log_prefix, part_number)
        _emit_stage("validate",
                    latency_ms=(_t_bridge.perf_counter() - _validate_start) * 1000.0)
    except FileNotFoundError as ex:
        log.error("%s.failed.cli_run pn=%s msg=%s", log_prefix, part_number, ex)
        try: zip_path.unlink(missing_ok=True)
        except Exception: pass
        raise HTTPException(status_code=500, detail=f"inspectorpkg CLI invoke failed: {ex}")

    # ── Unzip into staging ─────────────────────────────────────────
    # Zip's top-level entry is the {packageId}.inspectorpkg folder.
    import zipfile
    _unzip_start = _t_bridge.perf_counter()
    pkg_folder = staging_dir / f"{snap.package_id}.inspectorpkg"
    if pkg_folder.exists():
        shutil.rmtree(pkg_folder, ignore_errors=True)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(staging_dir)
    except Exception as ex:
        log.error("%s.failed.unzip pn=%s msg=%s", log_prefix, part_number, ex)
        try: zip_path.unlink(missing_ok=True)
        except Exception: pass
        raise HTTPException(status_code=500, detail=f"unzip failed: {ex}")
    if not pkg_folder.exists():
        log.error("%s.failed.unzip_layout pn=%s expected=%s",
                  log_prefix, part_number, pkg_folder)
        try: zip_path.unlink(missing_ok=True)
        except Exception: pass
        raise HTTPException(status_code=500, detail="zip did not contain expected package folder")

    _emit_stage("unzip",
                latency_ms=(_t_bridge.perf_counter() - _unzip_start) * 1000.0)

    return _BridgeFetchOk(
        snap=snap,
        pkg_folder=pkg_folder,
        zip_path=zip_path,
        library_root=library_root,
        staging_dir=staging_dir,
    )


def _install_sidecar(
    *,
    kind: str,
    part_number: str,
    package_id: str,
    pkg_folder: Path,
    library_root: Path,
    log_prefix: str,
) -> Tuple[Path, Path]:
    """Install pkg_folder contents to:
        library_root / _bridge_imports / {kind} / {part_number} / {package_id} /

    Update the _latest.txt pointer atomically. Idempotent for the same
    package_id (re-extracting identical content is a quick no-op pass).

    Returns (target_dir, latest_pointer_path) on success.
    Raises HTTPException(500) on copy / rename / pointer write failure;
    in failure cases, the .partial dir is removed and _latest.txt is
    NOT updated — per the user directive, failure paths must never
    create a successful sidecar pointer.
    """
    log = logger
    base = library_root / "_bridge_imports" / kind / part_number
    target = base / package_id
    latest = base / "_latest.txt"

    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception as ex:
        log.error("%s.failed.sidecar_mkdir pn=%s msg=%s", log_prefix, part_number, ex)
        raise HTTPException(
            status_code=500,
            detail=f"failed to create sidecar dir {base}: {ex}",
        )

    if target.exists():
        # Idempotent re-extract of identical content. We trust the bridge
        # packageId (sha256 of content) — same id means same bytes. Skip
        # the copy and just refresh the _latest.txt pointer.
        log.info("%s.sidecar.idempotent pn=%s packageId=%s target=%s",
                 log_prefix, part_number, package_id, target)
    else:
        partial = base / f"{package_id}.partial"
        if partial.exists():
            shutil.rmtree(partial, ignore_errors=True)
        try:
            shutil.copytree(pkg_folder, partial)
            os.rename(partial, target)
        except Exception as ex:
            log.error("%s.failed.sidecar_install pn=%s msg=%s", log_prefix, part_number, ex)
            # Tidy the partial so a future re-extraction sees a clean slate.
            try: shutil.rmtree(partial, ignore_errors=True)
            except Exception: pass
            raise HTTPException(
                status_code=500,
                detail=f"failed to install sidecar package: {ex}",
            )

    # Update _latest.txt via tmp + atomic rename. Intentionally LAST so
    # a partial install never produces a stale pointer claim.
    latest_tmp = base / "_latest.txt.tmp"
    try:
        latest_tmp.write_text(package_id, encoding="utf-8")
        os.replace(latest_tmp, latest)
    except Exception as ex:
        log.error("%s.failed.sidecar_pointer pn=%s msg=%s", log_prefix, part_number, ex)
        try: latest_tmp.unlink(missing_ok=True)
        except Exception: pass
        raise HTTPException(
            status_code=500,
            detail=f"failed to update sidecar _latest.txt pointer: {ex}",
        )

    log.info("%s.sidecar.installed pn=%s packageId=%s target=%s",
             log_prefix, part_number, package_id, target)
    return target, latest


def _denial_response(kind: str, snap: JobSnapshot, *, include_kind_field: bool) -> dict:
    """Shape a 200 OK + success=false response for bridge DENIED/FAILED.

    Drawing endpoint (include_kind_field=False) returns the pre-Phase-B
    shape verbatim: {success, jobState, message}. Part/assembly endpoints
    set include_kind_field=True so consumers can dispatch on it.
    """
    if snap.state == JOB_STATE_DENIED:
        message = "Extraction denied in SOLIDWORKS" + (f" ({snap.error})" if snap.error else ".")
    elif snap.state == JOB_STATE_FAILED:
        message = "SOLIDWORKS extraction failed" + (f": {snap.error}" if snap.error else ".")
    else:
        message = f"unexpected terminal state {snap.state!r}"
    body: Dict[str, Any] = {
        "success":  False,
        "jobState": snap.state,
        "message":  message,
    }
    if include_kind_field:
        body["kind"] = kind
    return body


def _bridge_workflow_total_timer(*, kind: str, route: str):
    """Decorator that emits a workflow="bridge_extract" stage="total"
    event in finally for each per-kind bridge orchestrator. Captures
    latency for success, denial, and error paths uniformly without
    requiring the wrapped function body to be re-indented.
    """
    def deco(fn):
        async def wrapper(part_number, expected_doc_path):
            import time as _t
            _start = _t.perf_counter()
            _status = "success"
            _err: Optional[str] = None
            try:
                result = await fn(part_number, expected_doc_path)
                # _BridgeNotDone is converted to a dict response inside
                # the orchestrator — detect denial via the response shape
                # so the total event labels it accurately.
                if isinstance(result, dict) and result.get("success") is False:
                    js = result.get("jobState")
                    _status = "denied" if js == JOB_STATE_DENIED else "error"
                return result
            except HTTPException as ex:
                _status = "error"
                _err = f"HTTP_{int(getattr(ex, 'status_code', 500))}"
                raise
            except Exception as ex:  # noqa: BLE001
                _status = "error"
                _err = type(ex).__name__
                raise
            finally:
                record_workflow_stage(
                    workflow="bridge_extract", stage="total",
                    latency_ms=(_t.perf_counter() - _start) * 1000.0,
                    status=_status, errorType=_err,
                    route=route, partNumber=part_number, documentKind=kind,
                )
        return wrapper
    return deco


@_bridge_workflow_total_timer(kind=KIND_DRAWING, route="/api/request-extraction")
async def _drive_extraction(part_number: str, expected_doc_path: Optional[str]) -> dict:
    """Drawing-specific orchestrator (Phase B refactor).

    Pre-Phase-B this function did everything inline. The kind-agnostic
    half (precheck through unzip) now lives in _bridge_extract_and_unpack;
    the half-2 tail (compat-export + atomic-replace into library root +
    load_drawing_map verify + .bak rollback) stays here because that
    behaviour is drawing-specific and intentionally byte-equivalent
    with the pre-Phase-B implementation.
    """
    log = logger
    try:
        ok = await _bridge_extract_and_unpack(
            kind=KIND_DRAWING,
            part_number=part_number,
            expected_doc_path=expected_doc_path,
            log_prefix="request_extraction",
        )
    except _BridgeNotDone as nd:
        return _denial_response(KIND_DRAWING, nd.snap, include_kind_field=False)

    # Phase 3: import stage timer (compat-export + atomic-replace +
    # load_drawing_map verify + cleanup). Emitted just before the return.
    import time as _t_de_import
    _de_import_start = _t_de_import.perf_counter()

    snap          = ok.snap
    pkg_folder    = ok.pkg_folder
    zip_path      = ok.zip_path
    library_root  = ok.library_root
    staging_dir   = ok.staging_dir
    cli           = _inspectorpkg_cli_path()  # already proven non-None inside the helper

    # Run compat-export → drops {pn}_drawing_map.json + {pn}_drawing.pdf in staging
    try:
        rc = _run_subprocess([
            cli, "compat-export",
            "--in",  str(pkg_folder),
            "--out", str(staging_dir),
            "--pn",  part_number,
        ])
        if rc != 0:
            log.error("request_extraction.failed.compat_export pn=%s rc=%d", part_number, rc)
            raise HTTPException(status_code=500, detail=f"compat-export failed (rc={rc})")
    except FileNotFoundError as ex:
        log.error("request_extraction.failed.cli_run pn=%s msg=%s", part_number, ex)
        raise HTTPException(status_code=500, detail=f"inspectorpkg CLI invoke failed: {ex}")

    new_map = staging_dir / f"{part_number}_drawing_map.json"
    new_pdf = staging_dir / f"{part_number}_drawing.pdf"
    if not new_map.exists():
        log.error("request_extraction.failed.compat_no_map pn=%s expected=%s", part_number, new_map)
        raise HTTPException(status_code=500, detail="compat-export did not produce drawing_map.json")
    log.info("request_extraction.compat.exported pn=%s map=%s pdf=%s",
             part_number, new_map, new_pdf if new_pdf.exists() else "(none)")

    # ── Atomic replace into library root + verify load ─────────────
    dest_map = library_root / f"{part_number}_drawing_map.json"
    dest_pdf = library_root / f"{part_number}_drawing.pdf"

    # Per Week 10D direction: do not delete old map until the new map
    # has loaded successfully through load_drawing_map. Strategy:
    #   1. Move existing dest_map to dest_map.bak  (preserves rollback)
    #   2. Atomically install new file at dest_map (tmp + os.replace)
    #   3. Probe load_drawing_map on the now-installed file
    #   4. On success: delete the .bak file. On failure: restore .bak.
    backup_map = dest_map.with_suffix(dest_map.suffix + ".bak")
    backup_pdf = dest_pdf.with_suffix(dest_pdf.suffix + ".bak")
    if dest_map.exists():
        try:
            if backup_map.exists():
                backup_map.unlink()
            os.replace(dest_map, backup_map)
        except Exception as ex:
            log.error("request_extraction.failed.backup pn=%s msg=%s", part_number, ex)
            raise HTTPException(status_code=500, detail=f"failed to back up old drawing map: {ex}")
    if dest_pdf.exists():
        try:
            if backup_pdf.exists():
                backup_pdf.unlink()
            os.replace(dest_pdf, backup_pdf)
        except Exception:
            pass  # PDF backup failure is non-fatal — map is the source of truth

    # Stage the new files via tmp + rename for atomicity
    def _atomic_install(src: Path, dest: Path) -> None:
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        if tmp.exists():
            tmp.unlink()
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)

    try:
        _atomic_install(new_map, dest_map)
    except Exception as ex:
        log.error("request_extraction.failed.install_map pn=%s msg=%s", part_number, ex)
        # Restore backup if we had moved it aside
        if backup_map.exists():
            try: os.replace(backup_map, dest_map)
            except Exception: pass
        raise HTTPException(status_code=500, detail=f"failed to install drawing map: {ex}")

    if new_pdf.exists():
        try:
            _atomic_install(new_pdf, dest_pdf)
        except Exception as ex:
            log.warning("request_extraction.warn.install_pdf pn=%s msg=%s", part_number, ex)
            # PDF install failure is non-fatal; map already in place.

    # Verify load_drawing_map works on the newly-installed file
    try:
        loaded = load_drawing_map(part_number, str(library_root))
    except Exception as ex:
        loaded = None
        log.error("request_extraction.failed.load_probe pn=%s msg=%s", part_number, ex)

    if loaded is None:
        # Roll back map (and pdf if backed up)
        log.error("request_extraction.failed.load_verify pn=%s — rolling back", part_number)
        if backup_map.exists():
            try: os.replace(backup_map, dest_map)
            except Exception as rollback_ex:
                log.error("request_extraction.failed.rollback pn=%s msg=%s", part_number, rollback_ex)
        else:
            try: dest_map.unlink()
            except Exception: pass
        if backup_pdf.exists():
            try: os.replace(backup_pdf, dest_pdf)
            except Exception: pass
        raise HTTPException(
            status_code=500,
            detail="newly imported drawing map failed to load; restored previous version.",
        )

    # Success — clean up backups + staging artifacts
    for p in (backup_map, backup_pdf):
        try:
            if p.exists(): p.unlink()
        except Exception: pass
    try:
        zip_path.unlink(missing_ok=True)
    except Exception: pass
    try:
        if pkg_folder.exists(): shutil.rmtree(pkg_folder, ignore_errors=True)
    except Exception: pass
    try: new_map.unlink(missing_ok=True)
    except Exception: pass
    try:
        if new_pdf.exists(): new_pdf.unlink()
    except Exception: pass

    log.info("request_extraction.imported pn=%s packageId=%s map=%s pdf=%s",
             part_number, snap.package_id, dest_map, dest_pdf if dest_pdf.exists() else "(none)")

    record_workflow_stage(
        workflow="bridge_extract", stage="import",
        latency_ms=(_t_de_import.perf_counter() - _de_import_start) * 1000.0,
        route="/api/request-extraction", partNumber=part_number, documentKind=KIND_DRAWING,
    )

    return {
        "success": True,
        "packageId": snap.package_id,
        "drawingMapPath": str(dest_map),
        "pdfPath": str(dest_pdf) if dest_pdf.exists() else None,
        "sheetCount": snap.sheet_count,
        "viewCount": snap.view_count,
    }


@_bridge_workflow_total_timer(kind=KIND_PART, route="/api/request-part-extraction")
async def _drive_part_extraction(part_number: str, expected_doc_path: Optional[str]) -> dict:
    """Part-specific orchestrator. After the shared pipeline produces
    an unzipped pkg_folder, install it as a sidecar and return the
    response shape spec'd in plan §3.1 (success / kind / packageId /
    importPath / latestPointerPath / featureCount / activeConfiguration).

    Never touches manual library data. Failure paths leave _latest.txt
    untouched so a downstream consumer can rely on the pointer always
    naming a successfully-installed packageId.
    """
    log = logger
    try:
        ok = await _bridge_extract_and_unpack(
            kind=KIND_PART,
            part_number=part_number,
            expected_doc_path=expected_doc_path,
            log_prefix="request_part_extraction",
        )
    except _BridgeNotDone as nd:
        return _denial_response(KIND_PART, nd.snap, include_kind_field=True)

    import time as _t_dp_import
    _dp_import_start = _t_dp_import.perf_counter()

    snap = ok.snap
    target, latest = _install_sidecar(
        kind=KIND_PART,
        part_number=part_number,
        package_id=snap.package_id or "unknown",
        pkg_folder=ok.pkg_folder,
        library_root=ok.library_root,
        log_prefix="request_part_extraction",
    )

    # Cleanup staging artifacts (the sidecar copy is the durable record)
    try: ok.zip_path.unlink(missing_ok=True)
    except Exception: pass
    try:
        if ok.pkg_folder.exists(): shutil.rmtree(ok.pkg_folder, ignore_errors=True)
    except Exception: pass

    log.info("request_part_extraction.imported pn=%s packageId=%s target=%s",
             part_number, snap.package_id, target)

    record_workflow_stage(
        workflow="bridge_extract", stage="import",
        latency_ms=(_t_dp_import.perf_counter() - _dp_import_start) * 1000.0,
        route="/api/request-part-extraction", partNumber=part_number, documentKind=KIND_PART,
    )

    return {
        "success":             True,
        "kind":                KIND_PART,
        "packageId":           snap.package_id,
        "importPath":          str(target),
        "latestPointerPath":   str(latest),
        "featureCount":        snap.feature_count,
        "activeConfiguration": snap.active_configuration,
    }


@_bridge_workflow_total_timer(kind=KIND_ASSEMBLY, route="/api/request-assembly-extraction")
async def _drive_assembly_extraction(part_number: str, expected_doc_path: Optional[str]) -> dict:
    """Assembly-specific orchestrator. Mirrors _drive_part_extraction
    with assembly-specific response fields (componentCount, mateCount,
    activeConfiguration). See plan §3.1."""
    log = logger
    try:
        ok = await _bridge_extract_and_unpack(
            kind=KIND_ASSEMBLY,
            part_number=part_number,
            expected_doc_path=expected_doc_path,
            log_prefix="request_assembly_extraction",
        )
    except _BridgeNotDone as nd:
        return _denial_response(KIND_ASSEMBLY, nd.snap, include_kind_field=True)

    import time as _t_da_import
    _da_import_start = _t_da_import.perf_counter()

    snap = ok.snap
    target, latest = _install_sidecar(
        kind=KIND_ASSEMBLY,
        part_number=part_number,
        package_id=snap.package_id or "unknown",
        pkg_folder=ok.pkg_folder,
        library_root=ok.library_root,
        log_prefix="request_assembly_extraction",
    )

    try: ok.zip_path.unlink(missing_ok=True)
    except Exception: pass
    try:
        if ok.pkg_folder.exists(): shutil.rmtree(ok.pkg_folder, ignore_errors=True)
    except Exception: pass

    log.info("request_assembly_extraction.imported pn=%s packageId=%s target=%s",
             part_number, snap.package_id, target)

    record_workflow_stage(
        workflow="bridge_extract", stage="import",
        latency_ms=(_t_da_import.perf_counter() - _da_import_start) * 1000.0,
        route="/api/request-assembly-extraction", partNumber=part_number, documentKind=KIND_ASSEMBLY,
    )

    return {
        "success":             True,
        "kind":                KIND_ASSEMBLY,
        "packageId":           snap.package_id,
        "importPath":          str(target),
        "latestPointerPath":   str(latest),
        "componentCount":      snap.component_count,
        "mateCount":           snap.mate_count,
        "activeConfiguration": snap.active_configuration,
    }


def _run_subprocess(argv: list) -> int:
    """Run a subprocess synchronously inside the FastAPI handler.
    inspectorpkg validate-package + compat-export are file-IO bound and
    typically <500ms, so blocking the event loop briefly is acceptable
    for a manual one-at-a-time UX. If this ever becomes hot, lift into
    asyncio.to_thread()."""
    import subprocess
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        logger.error("subprocess failed argv=%s rc=%d stderr=%s",
                     argv, proc.returncode, (proc.stderr or "")[:500])
    return proc.returncode


# ── Library Intake Wizard — preview + promote (Step 2) ─────────────────
#
# Per docs/library-intake-wizard-plan.md §4 (user flow steps 10-11),
# §5 (canonical storage shape), §6 (safety rules), §7 (validation),
# §9.2 (endpoints), §9.4 (single-flight gate), and §10.7 (consumer
# behaviour against stubs — Step 1 of this wizard already ships that
# half).
#
# MVP scope: part + drawing only. Assembly intake is explicitly out
# of scope (§3.2, §10.3) and the endpoints below only ever read/write
# under parts/ — assembly_profiles globals are not touched.
#
# Data sources at promote time:
#   - drawing map  -- library_dir / "{pn}_drawing_map.json"
#                     (already installed by /api/request-extraction's
#                     atomic install pattern in _drive_extraction; the
#                     wizard treats this as the canonical post-extraction
#                     content for the just-extracted revision)
#   - drawing pdf  -- library_dir / "{pn}_drawing.pdf"  (optional)
#   - part data    -- library_dir / "_bridge_imports/part/{pn}/{packageId}/part/part.json"
#                     (sidecar from /api/request-part-extraction; the
#                     wizard reads but never modifies _bridge_imports/
#                     per §6.6)
#
# Targets:
#   - parts/{pn}/rev{X}/{pn}_drawing_map.json            (per-rev archive)
#   - parts/{pn}/rev{X}/{pn}.json                        (per-rev part metadata)
#   - parts/{pn}/rev{X}/{pn}_drawing.pdf                 (per-rev, optional)
#   - parts/{pn}/rev{X}/intake_manifest.json             (per-rev, synthesized)
#   - parts/{pn}/rev{X}/{pn}_inspection_profile.json     (per-rev stub copy, §5.7
#                                                         row 1+2; skipped if a
#                                                         real profile exists at
#                                                         root per §5.7 row 3)
#   - library_dir / "{pn}_drawing_map.json"              (root "current pointer")
#   - library_dir / "{pn}_drawing.pdf"                   (root, optional)
#   - library_dir / "{pn}_inspection_profile.json"       (root stub, same skip rule)

INTAKE_MANIFEST_SCHEMA_VERSION = "1.0.0"
INTAKE_STUB_SCHEMA_VERSION     = "intake-stub-1.0.0"
INTAKE_PROMOTED_BY_AGENT       = "library-intake-wizard@1.0.0"
INTAKE_BRIDGE_BASELINE         = {"addinCommit": "c043fbe", "appCommit": "c2de55d"}
INTAKE_VALID_MODES             = {"new-revision-of-existing-part", "brand-new-part"}
INTAKE_REV_RE                  = re.compile(r"^rev[A-Za-z0-9]+$")

# §9.4 single-flight gate. Separate lock from bridge so an in-flight
# extraction does not block a preview / promote.
_library_intake_lock = asyncio.Lock()


def _intake_sanitize_revision(rev: str) -> str:
    """Project convention: revA, revB, ... — `rev` prefix + alphanumeric.
    Returns the input verbatim if it matches; empty string otherwise.
    Empty return signals 'invalid revision' to callers (handled as a
    400 by the endpoint).

    Distinct from the pre-existing module-level `_sanitize_revision`
    (used by /api/geometry-diff) which has different stripper-style
    semantics. The intake wizard needs a strict validator, not a
    stripper, because the revision name lands in filesystem paths
    and the wizard's overwrite-confirmation contract requires exact
    string equality."""
    if not isinstance(rev, str):
        return ""
    rev = rev.strip()
    return rev if INTAKE_REV_RE.match(rev) else ""


# Filename-stem suffixes the numbering scanner strips before recording a
# token as "used" -- so 1030024_view_front.png contributes 1030024, not
# 1030024_view_front. List is intentionally exhaustive: a new suffix
# leaking through would falsely show a number as available when it is
# already attached to a real library entry.
_INTAKE_NUMBERING_STRIP_SUFFIXES = (
    "_drawing_map", "_drawing", "_highlight_boxes", "_inspection_profile",
    "_feature_colors", "_dimension_descriptions",
    "_view_front", "_view_top", "_view_right", "_view_isometric",
    "_colored", "_assembly",
)

# Canonical JSON keys an assembly file uses to reference one of its
# component part numbers. PartNo observed in the wild
# (6000302_assembly.json: customProperties.PartNo); the alternate
# spellings are listed for defensive coverage of future extractor
# versions / hand-authored exports.
_INTAKE_ASSEMBLY_PART_KEYS = {"PartNo", "part_number", "partNumber", "part_no"}

# Token shape for assembly-internal part-number references. Tighter
# than the root-stem scanner because we MUST NOT treat coordinate or
# count values from a SOLIDWORKS dump as part numbers if they happen
# to be numeric. Matches the project convention (~7-character tokens
# like "1030031") with tolerance for the variant-letter form
# "1030001C" observed at root.
_INTAKE_ASSEMBLY_PART_REF_RE = re.compile(r"^\d{4,7}[A-Za-z0-9]{0,3}$")


def _intake_collect_assembly_part_refs(obj: Any, accumulator: set) -> None:
    """Recursively walk a parsed JSON value, adding any string value
    found under one of the canonical assembly part-number keys
    (_INTAKE_ASSEMBLY_PART_KEYS) when it matches the part-ref token
    shape. Defensive: tolerates dicts, lists, scalars, and non-string
    values; never raises."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _INTAKE_ASSEMBLY_PART_KEYS and isinstance(v, str):
                t = v.strip()
                if _INTAKE_ASSEMBLY_PART_REF_RE.match(t):
                    accumulator.add(t)
            _intake_collect_assembly_part_refs(v, accumulator)
    elif isinstance(obj, list):
        for item in obj:
            _intake_collect_assembly_part_refs(item, accumulator)


def _intake_used_part_numbers(library_dir: Path) -> set:
    """All part / assembly number tokens currently in use anywhere in the
    library. Union of:

      1. Root-level file stems (any extension: .json / .STL / .pdf /
         .glb / .png / etc.), with the known suffix list above stripped
         so visual-asset / map / profile filenames roll up to their
         owning part number.
      2. parts/{pn}/ subdirectory names -- catches parts that have a
         per-revision folder but no root profile yet (the model-only
         intake path leaves it in exactly this state).
      3. assemblies/**/*_assembly.json stems (existing convention) AND
         every PartNo / part_number / partNumber / part_no string value
         found by walking each assembly JSON recursively. This is the
         fix for the smoke bug where 1030031 was suggested as "next
         available" even though it was already in use as a BOM
         component (Straight Rail) inside the 6000302 Straight Roller
         Conveyor assembly. A part number referenced inside an
         assembly's customProperties is just as "taken" as one with a
         root profile file.

    A part number that collides with an assembly is detected in either
    direction because the scan is union-of-all-locations regardless of
    `kind`. The Numbering Wizard uses the result to suggest the next
    available number; `kind` only narrows the candidate prefix range
    the caller supplies."""
    used: set = set()

    if library_dir.exists() and library_dir.is_dir():
        for f in library_dir.iterdir():
            if not f.is_file():
                continue
            stem = f.stem
            for sfx in _INTAKE_NUMBERING_STRIP_SUFFIXES:
                if stem.endswith(sfx):
                    stem = stem[: -len(sfx)]
                    break
            if stem:
                used.add(stem)

    parts_dir = library_dir / "parts"
    if parts_dir.exists() and parts_dir.is_dir():
        for p in parts_dir.iterdir():
            if p.is_dir():
                used.add(p.name)

    assemblies_dir = library_dir / "assemblies"
    if assemblies_dir.exists() and assemblies_dir.is_dir():
        # Assembly identifier from filename stem. rglob picks up both
        # the top-level 6000302_assembly.json and any nested
        # 6000300/revA/6000300_assembly.json variants.
        for f in assemblies_dir.rglob("*_assembly.json"):
            used.add(f.stem.replace("_assembly", ""))
        # Recursive component-PartNo walk. Every .json under
        # assemblies/ is parsed; failures are silently skipped so a
        # malformed file does not break the suggester. Catches BOM
        # rows, customProperties blocks, partDataCache entries,
        # mateRelationships, and any future assembly-shaped JSON the
        # extractor adds.
        for f in assemblies_dir.rglob("*.json"):
            try:
                with open(f, "r", encoding="utf-8-sig") as fh:
                    data = json.load(fh)
            except Exception:
                continue
            _intake_collect_assembly_part_refs(data, used)

    return used


def _intake_next_part_number(library_dir: Path, prefix: str = "1030") -> str:
    """First `<prefix><N>` token not present anywhere in the library.

    Width is derived from prefix length so the project's 7-character
    convention holds and the iteration STOPS at the width boundary --
    i.e. prefix '1030' (4 chars) iterates 1030001..1030999 (999
    candidates), prefix '60003' (5 chars) iterates 6000301..6000399
    (99 candidates), prefix '6000' iterates 6000001..6000999. This
    matters because the candidate scanner must not silently roll past
    the implied width and start emitting 8-character tokens that
    violate the convention. Raises ValueError when the range is
    exhausted; the endpoint converts that to a 409 so the operator
    sees a clean 'this range is full' message instead of a stack
    trace."""
    used = _intake_used_part_numbers(library_dir)
    width = max(1, 7 - len(prefix))
    max_n = 10 ** width  # exclusive upper bound -- enforces width boundary
    for i in range(1, max_n):
        candidate = f"{prefix}{str(i).zfill(width)}"
        if candidate not in used:
            return candidate
    raise ValueError(
        f"No available numbers in {prefix}xxx range "
        f"({max_n - 1} candidates exhausted)"
    )


def _intake_part_sidecar_partjson_path(library_dir: Path, pn: str, package_id: str) -> Path:
    """parts/.../part/part.json INSIDE the bridge sidecar package."""
    return library_dir / "_bridge_imports" / "part" / pn / package_id / "part" / "part.json"


# Visual-asset filenames the wizard promotes from the bridge sidecar
# into parts/{pn}/rev{X}/ when present. Defensive: today's shipped
# bridge does NOT produce these (the InspectorPro.SolidWorks add-in
# planning doc explicitly defers GLB to the app side because SOLIDWORKS
# has no native GLB exporter). This list is forward-compatible -- the
# day the bridge or a sidecar-enhancement tool drops these files into
# the package, the wizard copies them; until then it is a no-op.
def _intake_visual_asset_filenames(pn: str) -> list:
    return [
        f"{pn}_colored.glb",
        f"{pn}_feature_colors.json",
        f"{pn}_view_front.png",
        f"{pn}_view_top.png",
        f"{pn}_view_right.png",
        f"{pn}_view_isometric.png",
        f"{pn}.stl",
        f"{pn}.STL",  # case-insensitive filesystems vary; both spellings observed in the existing library
    ]


def _intake_visual_assets_in_sidecar(library_dir: Path, pn: str, package_id: str) -> list:
    """Return paths of visual-asset files found in the bridge sidecar
    package for this part. Scans both the package root and the package
    `part/` subdirectory because the placement convention for visual
    exports is not yet pinned (planning doc reference: the bridge
    add-in defers GLB export to the app side; until the sidecar layout
    is fixed, defensive scan in both spots)."""
    found: list = []
    pkg_root = library_dir / "_bridge_imports" / "part" / pn / package_id
    if not pkg_root.exists():
        return found
    candidates = _intake_visual_asset_filenames(pn)
    seen_names: set = set()
    for parent in (pkg_root / "part", pkg_root):
        if not parent.exists():
            continue
        for fn in candidates:
            p = parent / fn
            if p.exists() and fn not in seen_names:
                found.append(p)
                seen_names.add(fn)
    return found


def _intake_part_sidecar_manifest_path(library_dir: Path, pn: str, package_id: str) -> Path:
    """manifest.json at the package root inside the sidecar."""
    return library_dir / "_bridge_imports" / "part" / pn / package_id / "manifest.json"


def _intake_real_profile_present(library_dir: Path, pn: str) -> bool:
    """§5.7 row 3 protection: true iff library root has a
    {pn}_inspection_profile.json that is NOT an intake stub. When true,
    the wizard MUST NOT write a stub at root or in the per-rev archive
    (a real profile is authoritative; the wizard never shadows it)."""
    p = library_dir / f"{pn}_inspection_profile.json"
    if not p.exists():
        return False
    try:
        with open(p, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        # Unreadable file -- be conservative and treat as "present"
        # so the wizard does not silently overwrite something we can't
        # parse. Operator can repair manually.
        return True
    return not _is_intake_stub_profile(data)


def _synthesize_intake_manifest(
    *,
    part_number: str,
    revision: str,
    intake_mode: str,
    drawing_package_id: str,
    drawing_source_doc_path: Optional[str],
    drawing_sheet_count: Optional[int],
    drawing_view_count: Optional[int],
    part_package_id: str,
    part_source_doc_path: Optional[str],
    part_feature_count: Optional[int],
    part_active_configuration: Optional[str],
    files: List[Dict[str, Any]],
    promoted_by: str,
) -> dict:
    """§5.4 intake_manifest.json shape. `files` is a list of
    { "path": "<relative>", "bytes": <int> } entries for everything
    the wizard wrote into this revision directory."""
    return {
        "schemaVersion":   INTAKE_MANIFEST_SCHEMA_VERSION,
        "partNumber":      part_number,
        "revision":        revision,
        "promotedAtUtc":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
        "promotedBy":      promoted_by,
        "intakeMode":      intake_mode,
        "sourceDrawing": {
            "packageId":     drawing_package_id or "",
            "sourceDocPath": drawing_source_doc_path or "",
            "sheetCount":    drawing_sheet_count if drawing_sheet_count is not None else None,
            "viewCount":     drawing_view_count if drawing_view_count is not None else None,
        },
        "sourcePart": {
            "packageId":           part_package_id,
            "sourceDocPath":       part_source_doc_path or "",
            "featureCount":        part_feature_count if part_feature_count is not None else None,
            "activeConfiguration": part_active_configuration or "",
        },
        "files":           files,
        "bridgeBaseline":  dict(INTAKE_BRIDGE_BASELINE),
    }


def _synthesize_intake_stub(
    *,
    part_number: str,
    revision: str,
    part_name: str = "",
    part_description: str = "",
) -> dict:
    """§5.7 schema for the intake stub profile JSON."""
    return {
        "$schemaVersion":  INTAKE_STUB_SCHEMA_VERSION,
        "source":          INTAKE_STUB_SOURCE,
        "status":          "incomplete",
        "inspectionReady": False,
        "part_number":     part_number,
        "revision":        revision,
        "name":            part_name or "",
        "description":     part_description or "",
        "createdAtUtc":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
        "createdBy":       INTAKE_PROMOTED_BY_AGENT,
        "links": {
            "intakeManifest": f"parts/{part_number}/{revision}/intake_manifest.json",
            "drawingMap":     f"{part_number}_drawing_map.json",
            "partMetadata":   f"parts/{part_number}/{revision}/{part_number}.json",
        },
        "notes": (
            "Stub profile created automatically by the Library Intake Wizard. "
            "The wizard produced the underlying drawing-map and part-metadata "
            "files but cannot infer inspection criteria (which features matter, "
            "which dimensions to inspect, what tolerance bands trigger findings). "
            f"Author a real {part_number}_inspection_profile.json (or use a future "
            "Profile Builder tool) before relying on this part's inspection workflow."
        ),
    }


def _intake_relpath(library_dir: Path, path: Path) -> str:
    """Library-relative POSIX-style path for display in the preview table."""
    try:
        return path.relative_to(library_dir).as_posix()
    except ValueError:
        return path.as_posix()


def _compute_intake_plan(body: "IntakeRequestBody") -> dict:
    """Returns the §9.2 preview response shape: planValid, actions,
    warnings, errors. Pure computation -- no file writes."""
    library_dir = library_path()
    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    actions: List[Dict[str, Any]] = []

    # ── Pre-flight validation (§6.5 fail-closed: any failure here
    # blocks promotion). ──
    safe_pn = sanitize_part_number(body.partNumber)
    if not safe_pn:
        errors.append({"code": "invalid_part_number", "message": "partNumber is empty or contains invalid characters."})
    safe_rev = _intake_sanitize_revision(body.revision)
    if not safe_rev:
        errors.append({"code": "invalid_revision", "message": "revision must match the pattern 'rev<alnum>' (e.g. revA, revB, revC1)."})
    if body.intakeMode not in INTAKE_VALID_MODES:
        errors.append({"code": "invalid_intake_mode",
                       "message": f"intakeMode must be one of {sorted(INTAKE_VALID_MODES)}."})
    if not (body.partPackageId or "").strip():
        errors.append({"code": "missing_part_package_id",
                       "message": "partPackageId is required (returned by /api/request-part-extraction)."})

    if errors:
        return {"planValid": False, "partNumber": body.partNumber, "revision": body.revision,
                "intakeMode": body.intakeMode, "targetRevisionPath": "",
                "actions": [], "warnings": warnings, "errors": errors}

    rev_dir = library_dir / "parts" / safe_pn / safe_rev
    target_rel = _intake_relpath(library_dir, rev_dir)

    # ── Source artifact checks (§7.5 / §7.3 / §7.4) ──
    drawing_map_src = library_dir / f"{safe_pn}_drawing_map.json"
    drawing_pdf_src = library_dir / f"{safe_pn}_drawing.pdf"
    part_json_src   = _intake_part_sidecar_partjson_path(library_dir, safe_pn, body.partPackageId)

    # Model-only mode: drawing is optional. The wizard MUST still write
    # an intake stub so the part is discoverable + inspection is gated
    # (inspectionReady=false). Drawing-related actions are simply
    # omitted from the plan.
    model_only = bool(getattr(body, "modelOnly", False))

    if not model_only and not drawing_map_src.exists():
        errors.append({
            "code": "missing_drawing_map",
            "message": f"Drawing map not found at {_intake_relpath(library_dir, drawing_map_src)}. "
                       "Run drawing extraction first (Re-extract Drawing from SOLIDWORKS) so the "
                       "root-level drawing map is in place before promoting. Or, if this part has "
                       "no drawing yet, re-post with modelOnly=true to import the SLDPRT only "
                       "(inspection will remain disabled until a drawing is added).",
        })
    if not part_json_src.exists():
        errors.append({
            "code": "missing_part_sidecar",
            "message": f"Part sidecar not found at {_intake_relpath(library_dir, part_json_src)}. "
                       "Re-run part extraction; the bridge sidecar must exist before promote.",
        })

    if errors:
        return {"planValid": False, "partNumber": safe_pn, "revision": safe_rev,
                "intakeMode": body.intakeMode, "targetRevisionPath": target_rel,
                "actions": [], "warnings": warnings, "errors": errors}

    # ── Overwrite gate (§6.1 case 1). The user-confirmed retype string
    # MUST equal the revision name exactly. ──
    rev_dir_exists = rev_dir.exists()
    overwrite_confirmed = (body.overwriteConfirmed or "").strip() == safe_rev
    if rev_dir_exists and not overwrite_confirmed:
        errors.append({
            "code": "revision_exists",
            "message": (
                f"{target_rel} already exists. Re-post with "
                f'overwriteConfirmed: "{safe_rev}" to overwrite, or pick a new revision name.'
            ),
        })
        return {"planValid": False, "partNumber": safe_pn, "revision": safe_rev,
                "intakeMode": body.intakeMode, "targetRevisionPath": target_rel,
                "actions": [], "warnings": warnings, "errors": errors}

    # ── Real-profile-at-root protection (§5.7 row 3). When a real
    # profile exists at root, the wizard does NOT write a stub anywhere
    # (root or per-rev archive). ──
    skip_stub = _intake_real_profile_present(library_dir, safe_pn)
    if skip_stub:
        warnings.append({
            "code": "real_profile_protected",
            "message": (
                f"A real (non-stub) inspection profile exists at "
                f"{safe_pn}_inspection_profile.json. The wizard will NOT write "
                "a stub profile anywhere (root or per-revision archive)."
            ),
        })

    # ── Build the action list. Order matters only for human readability
    # in the preview table; promote executes them in the order most
    # likely to leave a consistent intermediate state on a failure. ──
    overwrite_kind = "OVERWRITE" if rev_dir_exists else "CREATE"

    # Drawing-side bytes only computed when not model-only. The model-
    # only path uses model_only_marker to signal downstream blocks
    # to omit drawing rows + drawing-related root updates.
    drawing_map_bytes = drawing_map_src.stat().st_size if (not model_only and drawing_map_src.exists()) else 0
    part_json_bytes   = part_json_src.stat().st_size

    if not model_only:
        actions.append({
            "kind":   overwrite_kind,
            "path":   _intake_relpath(library_dir, rev_dir / f"{safe_pn}_drawing_map.json"),
            "bytes":  drawing_map_bytes,
            "source": _intake_relpath(library_dir, drawing_map_src),
        })
    actions.append({
        "kind":   overwrite_kind,
        "path":   _intake_relpath(library_dir, rev_dir / f"{safe_pn}.json"),
        "bytes":  part_json_bytes,
        "source": _intake_relpath(library_dir, part_json_src),
    })
    pdf_will_copy = (not model_only) and drawing_pdf_src.exists()
    if pdf_will_copy:
        actions.append({
            "kind":   overwrite_kind,
            "path":   _intake_relpath(library_dir, rev_dir / f"{safe_pn}_drawing.pdf"),
            "bytes":  drawing_pdf_src.stat().st_size,
            "source": _intake_relpath(library_dir, drawing_pdf_src),
        })

    # Visual-asset promotion (task 3 of the extractor-parity pass).
    # Defensive: today's shipped bridge does NOT emit GLB / view PNGs
    # / STL (the InspectorPro.SolidWorks add-in planning doc explicitly
    # defers GLB to the app side). When the sidecar does carry these,
    # the wizard copy-if-not-exists into the per-rev archive so the
    # operator does not have to move them by hand. Curated assets
    # already in the per-rev folder survive: the writer never clobbers
    # an existing target (§6.4 spirit, applied to visual assets).
    visual_src_paths = _intake_visual_assets_in_sidecar(library_dir, safe_pn, body.partPackageId)
    for vp in visual_src_paths:
        tgt = rev_dir / vp.name
        if tgt.exists():
            actions.append({
                "kind":   "SKIP",
                "path":   _intake_relpath(library_dir, tgt),
                "bytes":  0,
                "source": "curated asset preserved (already present in revision target)",
            })
        else:
            actions.append({
                "kind":   "CREATE",
                "path":   _intake_relpath(library_dir, tgt),
                "bytes":  vp.stat().st_size,
                "source": _intake_relpath(library_dir, vp),
            })

    # Synthesized files. Generate the content now so we can report exact
    # bytes (the preview's contract: "exact files that would be written").
    # The promote step regenerates these with fresh timestamps; the byte
    # count in preview will differ by <50 bytes from final and that's
    # acceptable for a UI preview.
    manifest_preview = _synthesize_intake_manifest(
        part_number=safe_pn, revision=safe_rev, intake_mode=body.intakeMode,
        drawing_package_id=body.drawingPackageId or "",
        drawing_source_doc_path=body.drawingSourceDocPath,
        drawing_sheet_count=body.drawingSheetCount,
        drawing_view_count=body.drawingViewCount,
        part_package_id=body.partPackageId,
        part_source_doc_path=body.partSourceDocPath,
        part_feature_count=body.partFeatureCount,
        part_active_configuration=body.partActiveConfiguration,
        files=(
            ([{"path": f"{safe_pn}_drawing_map.json", "bytes": drawing_map_bytes}] if not model_only else [])
            + [{"path": f"{safe_pn}.json", "bytes": part_json_bytes}]
            + ([{"path": f"{safe_pn}_drawing.pdf", "bytes": drawing_pdf_src.stat().st_size}] if pdf_will_copy else [])
        ),
        promoted_by=INTAKE_PROMOTED_BY_AGENT,
    )
    actions.append({
        "kind":   overwrite_kind,
        "path":   _intake_relpath(library_dir, rev_dir / "intake_manifest.json"),
        "bytes":  len(json.dumps(manifest_preview, indent=2).encode("utf-8")),
        "source": "synthesized by wizard",
    })

    if not skip_stub:
        stub_preview = _synthesize_intake_stub(part_number=safe_pn, revision=safe_rev)
        stub_bytes   = len(json.dumps(stub_preview, indent=2).encode("utf-8"))
        actions.append({
            "kind":   overwrite_kind,
            "path":   _intake_relpath(library_dir, rev_dir / f"{safe_pn}_inspection_profile.json"),
            "bytes":  stub_bytes,
            "source": "synthesized stub (§5.7)",
        })
        root_stub_path = library_dir / f"{safe_pn}_inspection_profile.json"
        actions.append({
            "kind":   "UPDATE" if root_stub_path.exists() else "CREATE",
            "path":   _intake_relpath(library_dir, root_stub_path),
            "bytes":  stub_bytes,
            "source": "synthesized stub (§5.7)",
        })
    else:
        actions.append({
            "kind":   "SKIP",
            "path":   _intake_relpath(library_dir, library_dir / f"{safe_pn}_inspection_profile.json"),
            "bytes":  0,
            "source": "real profile protected (§5.7 row 3)",
        })

    # Root drawing map (and pdf). Always UPDATE on subsequent runs; the
    # .bak rollback mirrors the existing drawing-extraction install
    # pattern (§10.1). Skipped entirely in model-only mode: the wizard
    # has no drawing bytes to push to the root pointer, and the prior
    # root pointer (if any) must remain valid for its previously-
    # promoted revision.
    if not model_only:
        root_map_path = library_dir / f"{safe_pn}_drawing_map.json"
        actions.append({
            "kind":   "UPDATE" if root_map_path.exists() else "CREATE",
            "path":   _intake_relpath(library_dir, root_map_path),
            "bytes":  drawing_map_bytes,
            "source": _intake_relpath(library_dir, drawing_map_src),
            "backup": _intake_relpath(library_dir, root_map_path.with_suffix(root_map_path.suffix + ".bak")),
        })
        if pdf_will_copy:
            root_pdf_path = library_dir / f"{safe_pn}_drawing.pdf"
            actions.append({
                "kind":   "UPDATE" if root_pdf_path.exists() else "CREATE",
                "path":   _intake_relpath(library_dir, root_pdf_path),
                "bytes":  drawing_pdf_src.stat().st_size,
                "source": _intake_relpath(library_dir, drawing_pdf_src),
                "backup": _intake_relpath(library_dir, root_pdf_path.with_suffix(root_pdf_path.suffix + ".bak")),
            })

    return {
        "planValid":          True,
        "partNumber":         safe_pn,
        "revision":           safe_rev,
        "intakeMode":         body.intakeMode,
        "modelOnly":          model_only,
        "targetRevisionPath": target_rel,
        "actions":            actions,
        "warnings":           warnings,
        "errors":             [],
    }


def _execute_intake_plan(body: "IntakeRequestBody") -> dict:
    """Performs the §5 install. Mirrors the partial-then-rename safety
    design from §6.2 for NEW targets; per-file tmp+replace for confirmed
    OVERWRITE targets so curated files (.STL, .glb, view PNGs) survive
    per §6.4.

    Returns a dict matching the preview response shape with each action
    additively annotated `committed: true|false` and a final
    `success: true` flag at the top level.

    On any failure: NEW target -> the .partial dir is rmtree'd, no
    library state changes. OVERWRITE target -> any per-file write that
    succeeded before the failure has already replaced its previous
    content; the response reports which actions committed. Root file
    updates use the .bak rollback pattern (mirrors server.py drawing-
    extraction install)."""
    library_dir = library_path()
    plan = _compute_intake_plan(body)
    if not plan["planValid"]:
        return {**plan, "success": False, "executed": []}

    safe_pn  = plan["partNumber"]
    safe_rev = plan["revision"]
    rev_dir  = library_dir / "parts" / safe_pn / safe_rev
    rev_dir_exists = rev_dir.exists()
    skip_stub = _intake_real_profile_present(library_dir, safe_pn)
    model_only = bool(getattr(body, "modelOnly", False))

    drawing_map_src = library_dir / f"{safe_pn}_drawing_map.json"
    drawing_pdf_src = library_dir / f"{safe_pn}_drawing.pdf"
    part_json_src   = _intake_part_sidecar_partjson_path(library_dir, safe_pn, body.partPackageId)

    # Pre-read sources INTO MEMORY before any write -- §6.5 fail-closed.
    # If any source is unreadable, we abort before touching disk.
    # In model-only mode the drawing files are skipped entirely; the
    # part sidecar is still required (the wizard never produces a
    # zero-file revision).
    try:
        if not model_only:
            drawing_map_bytes = drawing_map_src.read_bytes()
            json.loads(drawing_map_bytes.decode("utf-8-sig"))
            drawing_pdf_bytes = drawing_pdf_src.read_bytes() if drawing_pdf_src.exists() else None
        else:
            drawing_map_bytes = b""
            drawing_pdf_bytes = None
        part_json_bytes = part_json_src.read_bytes()
        json.loads(part_json_bytes.decode("utf-8-sig"))
    except Exception as ex:
        return {**plan, "success": False, "executed": [],
                "errors": [{"code": "source_read_failed", "message": f"failed to read source files: {ex}"}]}

    # Read optional package manifest for richer intake_manifest fields.
    sidecar_manifest_path = _intake_part_sidecar_manifest_path(library_dir, safe_pn, body.partPackageId)
    sidecar_manifest = None
    if sidecar_manifest_path.exists():
        try:
            sidecar_manifest = json.loads(sidecar_manifest_path.read_text(encoding="utf-8-sig"))
        except Exception:
            sidecar_manifest = None

    # Try to enrich feature count / config from the sidecar if the wizard
    # did not pass them in the request body.
    part_feature_count = body.partFeatureCount
    part_active_cfg    = body.partActiveConfiguration
    if (part_feature_count is None or not part_active_cfg) and isinstance(sidecar_manifest, dict):
        if part_feature_count is None and isinstance(sidecar_manifest.get("featureCount"), int):
            part_feature_count = sidecar_manifest.get("featureCount")
        if not part_active_cfg and isinstance(sidecar_manifest.get("activeConfiguration"), str):
            part_active_cfg = sidecar_manifest.get("activeConfiguration")
    # Same enrichment for source doc paths
    part_src_doc_path = body.partSourceDocPath
    if not part_src_doc_path and isinstance(sidecar_manifest, dict):
        sdp = sidecar_manifest.get("sourceDocPath")
        if isinstance(sdp, str):
            part_src_doc_path = sdp

    # Build the manifest content using the same files list the plan
    # reported. Doing this AFTER we know the source bytes are real.
    # Model-only mode omits the drawing-map row because no drawing was
    # promoted; the part.json is still required.
    manifest_files: List[Dict[str, Any]] = []
    if not model_only:
        manifest_files.append({"path": f"{safe_pn}_drawing_map.json", "bytes": len(drawing_map_bytes)})
    manifest_files.append({"path": f"{safe_pn}.json", "bytes": len(part_json_bytes)})
    if drawing_pdf_bytes is not None:
        manifest_files.append({"path": f"{safe_pn}_drawing.pdf", "bytes": len(drawing_pdf_bytes)})

    try:
        import getpass
        promoted_by = f"{getpass.getuser()}@{os.environ.get('COMPUTERNAME', 'unknown')}"
    except Exception:
        promoted_by = INTAKE_PROMOTED_BY_AGENT

    manifest = _synthesize_intake_manifest(
        part_number=safe_pn, revision=safe_rev, intake_mode=body.intakeMode,
        drawing_package_id=body.drawingPackageId or "",
        drawing_source_doc_path=body.drawingSourceDocPath,
        drawing_sheet_count=body.drawingSheetCount,
        drawing_view_count=body.drawingViewCount,
        part_package_id=body.partPackageId,
        part_source_doc_path=part_src_doc_path,
        part_feature_count=part_feature_count,
        part_active_configuration=part_active_cfg,
        files=manifest_files,
        promoted_by=promoted_by,
    )
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")

    # Read part name + description from the part.json so the stub picker
    # shows something more useful than the bare number.
    try:
        part_doc = json.loads(part_json_bytes.decode("utf-8-sig"))
        stub_name = (part_doc.get("name") or part_doc.get("title") or "") if isinstance(part_doc, dict) else ""
        stub_desc = (part_doc.get("description") or "") if isinstance(part_doc, dict) else ""
    except Exception:
        stub_name = ""
        stub_desc = ""

    stub = _synthesize_intake_stub(
        part_number=safe_pn, revision=safe_rev,
        part_name=stub_name, part_description=stub_desc,
    )
    stub_bytes = json.dumps(stub, indent=2).encode("utf-8")

    executed: List[Dict[str, Any]] = []
    rollback_paths: List[Path] = []  # for NEW path -- track .partial to rmtree on failure

    def _record(kind: str, path: Path, ok: bool, detail: str = ""):
        executed.append({
            "kind":      kind,
            "path":      _intake_relpath(library_dir, path),
            "committed": ok,
            "detail":    detail,
        })

    # ── Per-revision directory writes. ──
    # NEW path: build under .partial then atomic rename. Mirrors §6.2.
    # OVERWRITE path: write each file via tmp+replace into existing dir,
    # leaves untouched files (.STL, .glb, etc.) alone per §6.4.
    parts_root = library_dir / "parts" / safe_pn
    parts_root.mkdir(parents=True, exist_ok=True)

    if not rev_dir_exists:
        partial = library_dir / "parts" / safe_pn / f"{safe_rev}.partial"
        if partial.exists():
            shutil.rmtree(partial, ignore_errors=True)
        rollback_paths.append(partial)
        try:
            partial.mkdir(parents=True, exist_ok=False)
            if not model_only:
                (partial / f"{safe_pn}_drawing_map.json").write_bytes(drawing_map_bytes)
                if drawing_pdf_bytes is not None:
                    (partial / f"{safe_pn}_drawing.pdf").write_bytes(drawing_pdf_bytes)
            (partial / f"{safe_pn}.json").write_bytes(part_json_bytes)
            (partial / "intake_manifest.json").write_bytes(manifest_bytes)
            if not skip_stub:
                (partial / f"{safe_pn}_inspection_profile.json").write_bytes(stub_bytes)
            # Atomic flip (§6.2 step 4)
            os.rename(partial, rev_dir)
        except Exception as ex:
            for rp in rollback_paths:
                shutil.rmtree(rp, ignore_errors=True)
            return {**plan, "success": False, "executed": executed,
                    "errors": [{"code": "per_rev_write_failed", "message": str(ex)}]}
        rollback_paths.clear()  # rename succeeded -- nothing to clean
        if not model_only:
            _record("CREATE", rev_dir / f"{safe_pn}_drawing_map.json", True)
            if drawing_pdf_bytes is not None:
                _record("CREATE", rev_dir / f"{safe_pn}_drawing.pdf", True)
        _record("CREATE", rev_dir / f"{safe_pn}.json", True)
        _record("CREATE", rev_dir / "intake_manifest.json", True)
        if not skip_stub:
            _record("CREATE", rev_dir / f"{safe_pn}_inspection_profile.json", True)
    else:
        # Confirmed OVERWRITE -- per-file tmp + os.replace. Preserves
        # any curated files in the same dir per §6.4.
        overwrite_pairs: List = []
        if not model_only:
            overwrite_pairs.append((f"{safe_pn}_drawing_map.json", drawing_map_bytes))
            if drawing_pdf_bytes is not None:
                overwrite_pairs.append((f"{safe_pn}_drawing.pdf", drawing_pdf_bytes))
        overwrite_pairs.append((f"{safe_pn}.json", part_json_bytes))
        overwrite_pairs.append(("intake_manifest.json", manifest_bytes))
        if not skip_stub:
            overwrite_pairs.append((f"{safe_pn}_inspection_profile.json", stub_bytes))
        for fname, payload in overwrite_pairs:
            tgt = rev_dir / fname
            tmp = tgt.with_suffix(tgt.suffix + ".tmp")
            try:
                tmp.write_bytes(payload)
                os.replace(tmp, tgt)
                _record("OVERWRITE", tgt, True)
            except Exception as ex:
                try: tmp.unlink(missing_ok=True)
                except Exception: pass
                _record("OVERWRITE", tgt, False, detail=str(ex))
                return {**plan, "success": False, "executed": executed,
                        "errors": [{"code": "per_rev_overwrite_failed", "message": str(ex)}]}

    # ── Visual-asset copy (task 3 of the extractor-parity pass). ──
    # Copy-if-not-exists from the bridge sidecar into the per-rev
    # archive. Runs for BOTH new + overwrite paths and for BOTH
    # standard + model-only intakes. Curated assets already in the
    # target are skipped, not clobbered (§6.4 spirit applied to
    # visual assets). Failures are logged in `executed` but do not
    # fail the promote -- visual assets are presentational; the
    # canonical archive (part.json + manifest) is already committed.
    visual_src_paths = _intake_visual_assets_in_sidecar(library_dir, safe_pn, body.partPackageId)
    for vp in visual_src_paths:
        tgt = rev_dir / vp.name
        if tgt.exists():
            _record("SKIP", tgt, True, detail="curated asset preserved (already present)")
            continue
        try:
            tgt.write_bytes(vp.read_bytes())
            _record("CREATE", tgt, True, detail="copied from bridge sidecar")
        except Exception as ex:
            _record("CREATE", tgt, False, detail=f"visual asset copy failed: {ex}")

    # ── Root file updates (.bak rollback per §10.1 / mirror of
    # _drive_extraction's pattern). The per-rev archive is already
    # committed at this point; root failure is reported as partial
    # success (the canonical archive is intact). ──
    root_failures: List[str] = []

    def _install_root_file(src_bytes: bytes, dest: Path) -> bool:
        bak = dest.with_suffix(dest.suffix + ".bak")
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        try:
            tmp.write_bytes(src_bytes)
            if dest.exists():
                if bak.exists():
                    bak.unlink()
                os.replace(dest, bak)
            os.replace(tmp, dest)
            return True
        except Exception as ex:
            try: tmp.unlink(missing_ok=True)
            except Exception: pass
            root_failures.append(f"{_intake_relpath(library_dir, dest)}: {ex}")
            return False

    # Model-only mode does NOT touch the root drawing_map / drawing.pdf
    # pointers. The previously-promoted revision's pointer must remain
    # valid -- this part has no drawing to push.
    if not model_only:
        root_map = library_dir / f"{safe_pn}_drawing_map.json"
        ok = _install_root_file(drawing_map_bytes, root_map)
        _record("UPDATE" if ok else "FAILED", root_map, ok)

        if drawing_pdf_bytes is not None:
            root_pdf = library_dir / f"{safe_pn}_drawing.pdf"
            ok = _install_root_file(drawing_pdf_bytes, root_pdf)
            _record("UPDATE" if ok else "FAILED", root_pdf, ok)

    if not skip_stub:
        root_stub = library_dir / f"{safe_pn}_inspection_profile.json"
        ok = _install_root_file(stub_bytes, root_stub)
        _record("UPDATE" if ok else "FAILED", root_stub, ok)
    else:
        _record("SKIP", library_dir / f"{safe_pn}_inspection_profile.json",
                True, detail="real profile protected (§5.7 row 3)")

    # ── Refresh inspector profile-index so the new stub appears in
    # /api/profiles within the same session (§9.2 internal step). ──
    if inspector is not None and hasattr(inspector, "refresh_profile_index"):
        try:
            inspector.refresh_profile_index()
        except Exception as ex:
            logger.warning("intake.refresh_profile_index failed pn=%s: %s", safe_pn, ex)

    success = len(root_failures) == 0
    out = {**plan, "success": success, "executed": executed}
    if root_failures:
        out["errors"] = [{"code": "root_install_failed", "message": f}
                         for f in root_failures]
    return out


class IntakeRequestBody(BaseModel):
    """POST body for /api/library/intake/preview and /promote (§9.2)."""
    partNumber:                str
    revision:                  str
    intakeMode:                str = "new-revision-of-existing-part"
    drawingPackageId:          str = ""                       # from /api/request-extraction response
    partPackageId:             str                            # from /api/request-part-extraction response
    drawingSourceDocPath:      Optional[str] = None
    partSourceDocPath:         Optional[str] = None
    drawingSheetCount:         Optional[int] = None
    drawingViewCount:          Optional[int] = None
    partFeatureCount:          Optional[int] = None
    partActiveConfiguration:   Optional[str] = None
    overwriteConfirmed:        Optional[str] = None           # must equal revision to allow overwrite
    # Model-only intake: the operator extracted a SLDPRT but has no
    # accompanying drawing yet. Skips the drawing-required gate in
    # _compute_intake_plan and skips drawing-related writes in
    # _execute_intake_plan. Stub profile is still written because no
    # real inspection profile can be authored without a drawing
    # describing what to inspect.
    modelOnly:                 bool = False


@app.get("/api/library/numbering/next")
async def library_numbering_next(
    kind:   str = Query("part",   description="'part' or 'assembly'."),
    prefix: str = Query("1030",   description="Numeric prefix; e.g. '1030' for parts in the 1030xxx series, '6000' for assemblies in the 6000xxx series."),
):
    """Suggest the next available part/assembly number in a prefix range.

    The scan is union-of-all-locations: root files (any extension, with
    suffix-stripping so 1030024_view_front.png rolls up to 1030024),
    parts/{pn}/ subdirectory names, and assemblies/{id}_assembly.json
    stems. A part number that collides with an assembly is detected in
    either direction. `kind` only narrows the prefix the caller wants
    to suggest from; it does not narrow what counts as 'taken'.

    Returns:
      {
        "kind":         "part" | "assembly",
        "prefix":       "1030",
        "suggestion":   "1030025",
        "scannedCount": <int>,
        "library":      "<path>"
      }
    """
    if kind not in ("part", "assembly"):
        raise HTTPException(status_code=400,
                            detail=f"unknown kind: {kind!r}; must be 'part' or 'assembly'")
    if not prefix or not prefix.isdigit():
        raise HTTPException(status_code=400,
                            detail=f"invalid prefix: {prefix!r}; must be digits only")
    library_dir = library_path()
    used = _intake_used_part_numbers(library_dir)
    try:
        suggestion = _intake_next_part_number(library_dir, prefix=prefix)
    except ValueError as ex:
        raise HTTPException(status_code=409, detail=str(ex))
    return {
        "kind":         kind,
        "prefix":       prefix,
        "suggestion":   suggestion,
        "scannedCount": len(used),
        "library":      str(library_dir),
    }


@app.get("/api/library/revisions/{partNumber}")
async def library_revisions(partNumber: str):
    """Existing-revision listing + wizard auto-fill (§9.2).

    Powers the wizard frontend (Step 3 of the Library Intake Wizard):
      - lists existing parts/{pn}/rev*/ directories with optional
        intake_manifest excerpts so the operator sees prior promotes
      - pre-fills `partPackageId` from the most recently bridge-installed
        sidecar at _bridge_imports/part/{pn}/_latest.txt so the operator
        does not have to paste a 64-char hex hash
      - reports whether the root {pn}_drawing_map.json is present so the
        wizard can render an actionable "extract first" hint when the
        operator opens the wizard before running drawing extraction

    Additive to the plan §9.2 response shape (rootDrawingMapPresent +
    lastBridgePartPackageId are wizard-quality-of-life fields, not part
    of the original spec). Returns the empty-revisions shape (not 404)
    when parts/{pn}/ does not yet exist, so the wizard can treat
    'brand-new-part' as a normal flow without a 404 round-trip."""
    safe_pn = sanitize_part_number(partNumber)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")

    library_dir = library_path()
    revisions: List[Dict[str, Any]] = []

    parts_dir = library_dir / "parts" / safe_pn
    if parts_dir.exists() and parts_dir.is_dir():
        for rev_dir in sorted(parts_dir.iterdir()):
            if not rev_dir.is_dir() or not rev_dir.name.startswith("rev"):
                continue
            try:
                file_count = sum(1 for _ in rev_dir.iterdir())
            except Exception:
                file_count = 0
            manifest_excerpt: Optional[Dict[str, Any]] = None
            mpath = rev_dir / "intake_manifest.json"
            if mpath.exists():
                try:
                    mdata = json.loads(mpath.read_text(encoding="utf-8-sig"))
                    if isinstance(mdata, dict):
                        manifest_excerpt = {
                            "promotedAtUtc":  mdata.get("promotedAtUtc"),
                            "promotedBy":     mdata.get("promotedBy"),
                            "intakeMode":     mdata.get("intakeMode"),
                            "sourceDrawing":  mdata.get("sourceDrawing"),
                            "sourcePart":     mdata.get("sourcePart"),
                        }
                except Exception:
                    pass
            revisions.append({
                "name":           rev_dir.name,
                "path":           _intake_relpath(library_dir, rev_dir),
                "intakeManifest": manifest_excerpt,
                "fileCount":      file_count,
            })

    last_bridge_pkg: Optional[str] = None
    bridge_latest = library_dir / "_bridge_imports" / "part" / safe_pn / "_latest.txt"
    if bridge_latest.exists():
        try:
            txt = bridge_latest.read_text(encoding="utf-8").strip()
            last_bridge_pkg = txt or None
        except Exception:
            last_bridge_pkg = None

    return {
        "partNumber":              safe_pn,
        "revisions":               revisions,
        "lastBridgePartPackageId": last_bridge_pkg,
        "rootDrawingMapPresent":   (library_dir / f"{safe_pn}_drawing_map.json").exists(),
    }


@app.post("/api/library/intake/preview")
async def library_intake_preview(body: IntakeRequestBody):
    """Dry-run: compute the §9.2 preview plan without writing anything.

    Returns 200 with planValid=true + actions list when the plan is
    acceptable, or planValid=false + errors when validation fails or
    the per-rev directory already exists without an overwriteConfirmed
    match. Either way the response shape is the same so the wizard UI
    has a single code path."""
    return _compute_intake_plan(body)


@app.post("/api/library/intake/promote")
async def library_intake_promote(body: IntakeRequestBody):
    """The commit. Same body shape as preview plus overwriteConfirmed
    when overwriting. Single-flight via _library_intake_lock so two
    concurrent promotes cannot race the same revision target."""
    if _library_intake_lock.locked():
        raise HTTPException(
            status_code=409,
            detail="Another library intake promote is in progress; one at a time.",
        )
    async with _library_intake_lock:
        result = _execute_intake_plan(body)
    # Map planValid=false / success=false to a non-200 so the wizard's
    # error path fires; success cases stay 200.
    if not result.get("planValid", False):
        return JSONResponse(status_code=409, content=result)
    if not result.get("success", False):
        return JSONResponse(status_code=500, content=result)
    return result


# ---------------------------------------------------------------------------
# Profile Builder MVP
# ---------------------------------------------------------------------------
#
# The Library Intake Wizard deliberately writes an incomplete stub when no
# real inspection profile exists. Profile Builder is the next step: use the
# promoted part metadata + drawing map to draft a real inspection profile,
# then require an explicit apply action before replacing the stub. This tool
# is intentionally draft/review oriented: it never silently overwrites a real
# hand-authored profile.

PROFILE_BUILDER_MODEL_DEFAULT = "claude-sonnet-4-5-20250929"
PROFILE_BUILDER_AUTHOR        = "profile-builder@1.0.0"
PROFILE_BUILDER_MATERIAL_TERMS = {
    "aluminum", "aluminium", "steel", "stainless", "cast iron", "iron",
    "brass", "bronze", "copper", "plastic", "nylon", "abs", "pla",
    "polycarbonate", "delrin", "acetal", "titanium", "inconel",
    "6061-t6", "7075-t6",
}


class ProfileBuilderGenerateBody(BaseModel):
    partNumber:    str
    revision:      Optional[str] = None
    instructions:  Optional[str] = None
    model:         Optional[str] = None


class ProfileBuilderApplyBody(BaseModel):
    partNumber:            str
    revision:              Optional[str] = None
    profile:               Dict[str, Any]
    overwriteConfirmed:    Optional[str] = None


def _profile_builder_revision_dirs(library_dir: Path, pn: str) -> List[Path]:
    parts_dir = library_dir / "parts" / pn
    if not parts_dir.exists() or not parts_dir.is_dir():
        return []
    return sorted(
        [p for p in parts_dir.iterdir() if p.is_dir() and p.name.startswith("rev")],
        key=lambda p: (p.stat().st_mtime, p.name),
    )


def _profile_builder_resolve_revision(library_dir: Path, pn: str, revision: Optional[str]) -> Tuple[Optional[str], Optional[Path]]:
    if revision:
        safe_rev = _intake_sanitize_revision(revision)
        if not safe_rev:
            raise HTTPException(status_code=400, detail="revision must match rev<alnum> (for example revA).")
        rev_dir = library_dir / "parts" / pn / safe_rev
        return safe_rev, rev_dir

    dirs = _profile_builder_revision_dirs(library_dir, pn)
    if not dirs:
        return None, None
    rev_dir = dirs[-1]
    return rev_dir.name, rev_dir


def _profile_builder_load_json(path: Optional[Path]) -> Optional[dict]:
    if path is None or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _profile_builder_profile_kind(data: Optional[dict]) -> str:
    if data is None:
        return "missing"
    if _is_intake_stub_profile(data):
        return "stub"
    return "real"


def _profile_builder_material_info(part_data: Optional[dict]) -> dict:
    def _material_result(value: str, source: str) -> dict:
        text = (value or "").strip()
        lowered = text.lower()
        specified = bool(text) and not any(marker in lowered for marker in (
            "not specified", "<not specified>", "unspecified", "unknown", "none",
        ))
        return {
            "status": "specified" if specified else "not_specified",
            "value": text if specified else "",
            "raw": text,
            "source": source,
        }

    if not isinstance(part_data, dict):
        return {"status": "unknown", "value": "", "raw": "", "source": ""}

    props = part_data.get("customProperties")
    if isinstance(props, dict):
        global_props = props.get("global")
        if isinstance(global_props, dict):
            for key, value in global_props.items():
                if "material" in str(key).lower() and str(value or "").strip():
                    return _material_result(str(value), f"customProperties.global.{key}")

    for feat in part_data.get("featureTree", []) if isinstance(part_data.get("featureTree"), list) else []:
        if not isinstance(feat, dict):
            continue
        if str(feat.get("type") or "").lower() == "materialfolder":
            name = str(feat.get("name") or "")
            value = re.sub(r"^\s*Material\s*", "", name, flags=re.IGNORECASE).strip()
            return _material_result(value, "featureTree.MaterialFolder")

    return {"status": "unknown", "value": "", "raw": "", "source": ""}


def _profile_builder_part_summary(part_data: Optional[dict]) -> dict:
    if not isinstance(part_data, dict):
        return {"featureCount": 0, "features": [], "featureTypes": {}, "material": _profile_builder_material_info(part_data)}

    raw_features: List[dict] = []
    if isinstance(part_data.get("featureTree"), list):
        skip_types = {
            "commentsfolder", "favoritefolder", "historyfolder", "selectionsetfolder",
            "sensorfolder", "docsfolder", "detailcabinet", "surfacebodyfolder",
            "solidbodyfolder", "envfolder", "inkmarkupfolder", "eqnfolder",
            "materialfolder", "refplane", "originprofilefeature", "refaxis",
        }
        for feat in part_data.get("featureTree", []):
            if not isinstance(feat, dict):
                continue
            ftype = str(feat.get("type") or "")
            if ftype.lower() in skip_types:
                continue
            raw_features.append({
                "name": feat.get("name", ""),
                "type": ftype,
                "suppressed": bool(feat.get("suppressedInActive", False)),
            })
    elif isinstance(part_data.get("features"), list):
        for feat in part_data.get("features", []):
            if isinstance(feat, dict):
                raw_features.append({
                    "name": feat.get("name") or feat.get("id") or "",
                    "type": feat.get("type", ""),
                    "suppressed": bool(feat.get("suppressed", False)),
                })

    type_counts: Dict[str, int] = {}
    for feat in raw_features:
        ftype = str(feat.get("type") or "Unknown")
        type_counts[ftype] = type_counts.get(ftype, 0) + 1

    return {
        "documentType": part_data.get("documentType"),
        "activeConfiguration": part_data.get("activeConfiguration"),
        "units": part_data.get("units"),
        "boundingBox": part_data.get("boundingBox", {}),
        "material": _profile_builder_material_info(part_data),
        "massProperties": {
            "mass_kg": ((part_data.get("massProperties") or {}).get("mass_kg")),
            "volumeMm3": ((part_data.get("massProperties") or {}).get("volumeMm3")),
            "surfaceAreaMm2": ((part_data.get("massProperties") or {}).get("surfaceAreaMm2")),
        },
        "featureCount": len(raw_features),
        "featureTypes": type_counts,
        "features": raw_features[:60],
    }


def _profile_builder_drawing_summary(drawing_map: Optional[dict]) -> dict:
    if not isinstance(drawing_map, dict):
        return {"sheetCount": 0, "viewCount": 0, "dimensions": [], "notes": [], "gtols": []}

    sheets = drawing_map.get("sheets") if isinstance(drawing_map.get("sheets"), list) else []
    dimensions: List[dict] = []
    notes: List[str] = []
    gtols: List[str] = []
    view_count = 0

    for sheet in sheets:
        if not isinstance(sheet, dict):
            continue
        sheet_name = sheet.get("sheetName") or sheet.get("name") or ""
        views = sheet.get("views") if isinstance(sheet.get("views"), list) else []
        view_count += len(views)
        for view in views:
            if not isinstance(view, dict):
                continue
            view_name = view.get("viewName") or view.get("name") or ""
            anns = view.get("annotations") if isinstance(view.get("annotations"), list) else []
            for ann in anns:
                if not isinstance(ann, dict):
                    continue
                dim = ann.get("dimensionText")
                note = ann.get("noteText")
                gtol = ann.get("gtolText")
                if dim and len(dimensions) < 60:
                    dimensions.append({
                        "sheet": sheet_name,
                        "view": view_name,
                        "text": str(dim),
                        "featureName": ann.get("featureName"),
                    })
                if note and len(notes) < 30:
                    notes.append(str(note))
                if gtol and len(gtols) < 30:
                    gtols.append(str(gtol))

    return {
        "fileName": drawing_map.get("fileName"),
        "referencedModelPath": drawing_map.get("referencedModelPath"),
        "sheetCount": len(sheets),
        "viewCount": view_count,
        "projectionType": (sheets[0].get("projectionType") if sheets and isinstance(sheets[0], dict) else None),
        "dimensions": dimensions,
        "notes": notes,
        "gtols": gtols,
    }


def _profile_builder_context(library_dir: Path, pn: str, revision: Optional[str]) -> dict:
    safe_rev, rev_dir = _profile_builder_resolve_revision(library_dir, pn, revision)
    root_profile_path = library_dir / f"{pn}_inspection_profile.json"
    root_profile = _profile_builder_load_json(root_profile_path)

    part_path = (rev_dir / f"{pn}.json") if rev_dir is not None else (library_dir / f"{pn}.json")
    drawing_map_path = (rev_dir / f"{pn}_drawing_map.json") if rev_dir is not None else (library_dir / f"{pn}_drawing_map.json")
    manifest_path = (rev_dir / "intake_manifest.json") if rev_dir is not None else None

    part_data = _profile_builder_load_json(part_path)
    drawing_map = _profile_builder_load_json(drawing_map_path)
    manifest = _profile_builder_load_json(manifest_path)

    missing = []
    if safe_rev and rev_dir is not None and not rev_dir.exists():
        missing.append("revision")
    if part_data is None:
        missing.append("part_metadata")
    if drawing_map is None:
        missing.append("drawing_map")

    return {
        "partNumber": pn,
        "revision": safe_rev,
        "ready": not missing,
        "missing": missing,
        "paths": {
            "revisionDir": _intake_relpath(library_dir, rev_dir) if rev_dir is not None else "",
            "partMetadata": _intake_relpath(library_dir, part_path),
            "drawingMap": _intake_relpath(library_dir, drawing_map_path),
            "intakeManifest": _intake_relpath(library_dir, manifest_path) if manifest_path else "",
            "rootProfile": _intake_relpath(library_dir, root_profile_path),
        },
        "existingProfile": {
            "kind": _profile_builder_profile_kind(root_profile),
            "path": _intake_relpath(library_dir, root_profile_path),
            "partName": (root_profile or {}).get("part_name") or (root_profile or {}).get("name") or "",
        },
        "intakeManifest": manifest or {},
        "partSummary": _profile_builder_part_summary(part_data),
        "drawingSummary": _profile_builder_drawing_summary(drawing_map),
    }


def _profile_builder_prompt(context: dict, instructions: Optional[str]) -> str:
    payload = {
        "partNumber": context.get("partNumber"),
        "revision": context.get("revision"),
        "existingProfile": context.get("existingProfile"),
        "intakeManifest": context.get("intakeManifest"),
        "partSummary": context.get("partSummary"),
        "drawingSummary": context.get("drawingSummary"),
        "operatorInstructions": instructions or "",
    }
    return (
        "You are the InspectorPro Profile Builder. Given promoted part metadata and drawing-map context, "
        "draft an inspection profile for human review.\n\n"
        "Output a single valid JSON object only. Do not include markdown or prose.\n\n"
        "Required JSON shape:\n"
        "{\n"
        '  "part_number": "<part number>",\n'
        '  "part_name": "<short product name>",\n'
        '  "part_description": "<plain-language manufacturing description>",\n'
        '  "features": [\n'
        "    {\n"
        '      "name": "<short physical-feature label>",\n'
        '      "type": "<e.g. revolved | hole_pattern | counterbore | slot_pattern | planar_face | thread | cylindrical_surface>",\n'
        '      "count": <integer; physical instance count>,\n'
        '      "spatial_description": "<where this feature appears in the drawing/views and how a reviewer can recognize it>",\n'
        '      "inspection_reason": "<why this feature warrants inspection>",\n'
        '      "evidence": ["<traceable plain-English source>", "..."],\n'
        '      "uncertainty": "low|medium|high",\n'
        '      "review_notes": "<include when uncertainty is medium or high>"\n'
        "    }\n"
        "  ],\n"
        '  "view_expectations": {\n'
        '    "front_or_plan": "<expected drawing content>",\n'
        '    "side_or_right": "<expected drawing content>",\n'
        '    "top": "<expected drawing content>",\n'
        '    "isometric": "<expected drawing content>",\n'
        '    "section_views": "<expected drawing content>",\n'
        '    "detail_views": "<expected drawing content>"\n'
        "  },\n"
        '  "review_notes": [\n'
        '    "<profile-level items the human reviewer should confirm before applying>"\n'
        "  ]\n"
        "}\n\n"
        "RULES:\n"
        "1. A feature is a physical or functional thing on the part: flange body, hole pattern, "
        "counterbore set, thread, slot pattern, planar mating face, register, shaft journal, etc.\n\n"
        "2. Dimensions, GD&T frames, surface-finish callouts, notes, section views, and detail views "
        "are evidence attached to features. Do not turn every dimension into its own feature row.\n\n"
        "3. count = physical instance count. Six bolt holes means count: 6. One flange body means "
        "count: 1. Do not use count to mean number of dimensions or callouts.\n\n"
        "4. Count must not contradict the supplied context. If you cite Cut-Extrude1 through "
        "Cut-Extrude12, the count is 12; if the drawing does not prove the count, lower "
        "uncertainty and state what needs review.\n\n"
        "5. Do not create feature rows for envelope/thickness/position dimensions by themselves. "
        "Attach overall thickness, axial positions, wall thickness, and similar dimensions as "
        "evidence on the physical feature they control. If the only support is a CAD feature-tree "
        "name with no drawing evidence, prefer a profile-level review_notes item instead of a "
        "new inspectable feature.\n\n"
        "6. evidence[] entries should be plain-English source references a reviewer can find, such as:\n"
        '   "front view: \u00d875 outer diameter dimension"\n'
        '   "section view A-A: 12 mm overall thickness"\n'
        '   "front view: parallelism 0.05 to datum A on mating face"\n'
        '   "general note: BREAK ALL SHARP EDGES, DEBURR"\n'
        '   "part feature tree: HoleWzd counterbore feature"\n\n'
        "7. inspection_reason is mandatory. Explain why the feature warrants inspection, usually "
        "because of fit, mating function, assembly correctness, or drawing control. Avoid generic "
        "language like \"to ensure quality.\"\n\n"
        "8. uncertainty:\n"
        "   low = directly supported by supplied context\n"
        "   medium = inferred from convention or unstated function\n"
        "   high = weakly supported; operator must verify before relying on this entry\n\n"
        "9. review_notes is required when uncertainty is medium or high. State what is ambiguous and "
        "what the reviewer should confirm.\n\n"
        "10. Do not claim criticality, tolerance bands, material, supplier capability, process "
        "capability, or function unless supported by the supplied context. If a function is inferred, "
        "mark uncertainty medium/high and explain the assumption.\n\n"
        "11. If partSummary.material.status is not \"specified\", do not name a material family "
        "(aluminum, steel, plastic, etc.) anywhere in the profile. Say only in profile-level "
        "review_notes that material is not specified in the supplied context.\n\n"
        "12. Whole-part notes such as deburr, break sharp edges, and general finish notes should "
        "attach as evidence to the relevant body/surface feature or profile-level review_notes. "
        "They should not become standalone feature rows.\n\n"
        "13. Do not include source/status/inspectionReady fields; applying the draft makes it a real profile.\n\n"
        "EXAMPLE 1: Revolved mounting flange\n\n"
        "Context: Front view + section view A-A. Front view shows \u00d875 OD, \u00d825 central bore, "
        "six \u00d86.5 holes on a \u00d860 bolt circle with callout \"6X \u00d86.5\". Section A-A shows "
        "12 mm overall thickness and \u00d811 x 4 deep counterbore on each bolt-circle hole. No GD&T "
        "and no functional notes.\n\n"
        "Bad output:\n"
        "{\n"
        '  "features": [\n'
        '    {"name": "Outer Diameter", "type": "dimension"},\n'
        '    {"name": "Inner Diameter", "type": "dimension"},\n'
        '    {"name": "Overall Thickness", "type": "dimension"},\n'
        '    {"name": "Bolt Circle Diameter", "type": "dimension"},\n'
        '    {"name": "Bolt Hole Diameter", "type": "dimension"},\n'
        '    {"name": "Counterbore Diameter", "type": "dimension"},\n'
        '    {"name": "Counterbore Depth", "type": "dimension"}\n'
        "  ]\n"
        "}\n\n"
        "Good output:\n"
        "{\n"
        '  "features": [\n'
        "    {\n"
        '      "name": "Mounting flange body",\n'
        '      "type": "revolved",\n'
        '      "count": 1,\n'
        '      "spatial_description": "Main circular flange body visible in front view and section view A-A.",\n'
        '      "inspection_reason": "Defines the part envelope and central through-bore used for mating/clearance.",\n'
        '      "evidence": [\n'
        '        "front view: \u00d875 outer diameter dimension",\n'
        '        "front view: \u00d825 central bore dimension",\n'
        '        "section view A-A: 12 mm overall thickness"\n'
        "      ],\n"
        '      "uncertainty": "low"\n'
        "    },\n"
        "    {\n"
        '      "name": "Bolt-circle clearance holes",\n'
        '      "type": "hole_pattern",\n'
        '      "count": 6,\n'
        '      "spatial_description": "Six equally spaced holes on the bolt circle in the front view.",\n'
        '      "inspection_reason": "Pattern controls bolted assembly fit. Inspect count, hole diameter, and bolt-circle location.",\n'
        '      "evidence": [\n'
        '        "front view: \u00d860 bolt-circle dimension",\n'
        '        "front view: 6X \u00d86.5 hole callout"\n'
        "      ],\n"
        '      "uncertainty": "low"\n'
        "    },\n"
        "    {\n"
        '      "name": "Bolt-hole counterbores",\n'
        '      "type": "counterbore",\n'
        '      "count": 6,\n'
        '      "spatial_description": "Counterbores shown on bolt-circle holes in section view A-A.",\n'
        '      "inspection_reason": "Controls fastener head seating/recess geometry.",\n'
        '      "evidence": [\n'
        '        "section view A-A: \u00d811 x 4 deep counterbore on bolt-circle hole"\n'
        "      ],\n"
        '      "uncertainty": "medium",\n'
        '      "review_notes": "Drawing does not explicitly state whether the counterbore is critical. Reviewer should confirm inspection priority before treating it as critical."\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "EXAMPLE 2: Machined bracket with slots, holes, and GD&T\n\n"
        "Context: Rectangular bracket, 120 x 80 x 8 mm. Title block material 6061-T6. Two parallel "
        "12 x 30 slots on the top face. Four \u00d84 through-holes in a 40 x 30 rectangular pattern. "
        "1 x 45 chamfer on top edge. R2 fillet under small boss. GD&T frame on mating face: "
        "parallelism 0.05 to datum A. General note: BREAK ALL SHARP EDGES, DEBURR. This example "
        "uses material only because the context explicitly states 6061-T6; do not infer material "
        "when supplied context says material is not specified.\n\n"
        "Bad output:\n"
        "{\n"
        '  "features": [\n'
        '    {"name": "Slot Length", "type": "dimension"},\n'
        '    {"name": "Slot Width", "type": "dimension"},\n'
        '    {"name": "Hole \u00d8", "type": "dimension"},\n'
        '    {"name": "Hole Pitch X", "type": "dimension"},\n'
        '    {"name": "Hole Pitch Y", "type": "dimension"},\n'
        '    {"name": "Top Chamfer 1x45", "type": "chamfer"},\n'
        '    {"name": "Boss Fillet R2", "type": "fillet"},\n'
        '    {"name": "Parallelism 0.05 A", "type": "gdt"},\n'
        '    {"name": "Deburr Note", "type": "note"}\n'
        "  ]\n"
        "}\n\n"
        "Good output:\n"
        "{\n"
        '  "features": [\n'
        "    {\n"
        '      "name": "Mounting slots",\n'
        '      "type": "slot_pattern",\n'
        '      "count": 2,\n'
        '      "spatial_description": "Two parallel slots visible on the top/front view.",\n'
        '      "inspection_reason": "Slot size controls fastener clearance; slot spacing controls mating alignment.",\n'
        '      "evidence": [\n'
        '        "front view: 12 x 30 slot dimension",\n'
        '        "front view: slot-pair centerline pitch dimension"\n'
        "      ],\n"
        '      "uncertainty": "low"\n'
        "    },\n"
        "    {\n"
        '      "name": "Through-hole pattern",\n'
        '      "type": "hole_pattern",\n'
        '      "count": 4,\n'
        '      "spatial_description": "Four through-holes in a rectangular pattern.",\n'
        '      "inspection_reason": "Inspect count, hole diameter, and pattern pitch to confirm drawing conformance.",\n'
        '      "evidence": [\n'
        '        "front view: 4X \u00d84 hole callout",\n'
        '        "front view: 40 x 30 pattern pitch"\n'
        "      ],\n"
        '      "uncertainty": "medium",\n'
        "      \"review_notes\": \"Drawing does not name the holes' function. Do not assume fastener, locating, or strain-relief use until confirmed.\"\n"
        "    },\n"
        "    {\n"
        '      "name": "Bracket body and mating face",\n'
        '      "type": "planar_face",\n'
        '      "count": 1,\n'
        '      "spatial_description": "Main rectangular body and controlled mating face.",\n'
        '      "inspection_reason": "GD&T frame applies to the mating face; parallelism to datum A controls assembly fit.",\n'
        '      "evidence": [\n'
        '        "front view: parallelism 0.05 to datum A on mating face",\n'
        '        "front view: 1 x 45 chamfer on top edge",\n'
        '        "right view: R2 fillet under boss",\n'
        '        "general note: BREAK ALL SHARP EDGES, DEBURR",\n'
        '        "title block: material 6061-T6"\n'
        "      ],\n"
        '      "uncertainty": "low"\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Now generate the inspection profile for the supplied part. Output JSON only.\n\n"
        "--- CONTEXT JSON ---\n"
        f"{json.dumps(payload, indent=2)}"
    )


def _extract_json_object(text: str) -> dict:
    text = (text or "").strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("model did not return a JSON object")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("model JSON was not an object")
    return data


def _normalize_profile_builder_draft(profile: dict, pn: str) -> dict:
    if not isinstance(profile, dict):
        raise ValueError("profile must be a JSON object")

    out: Dict[str, Any] = {
        "part_number": str(profile.get("part_number") or pn),
        "part_name": str(profile.get("part_name") or profile.get("name") or pn),
        "part_description": str(profile.get("part_description") or profile.get("description") or ""),
        "features": [],
        "view_expectations": profile.get("view_expectations") if isinstance(profile.get("view_expectations"), dict) else {},
    }
    if isinstance(profile.get("review_notes"), list):
        out["review_notes"] = [str(v) for v in profile.get("review_notes", []) if v is not None]
    elif isinstance(profile.get("review_notes"), str) and profile.get("review_notes").strip():
        out["review_notes"] = [profile.get("review_notes").strip()]

    raw_features = profile.get("features")
    if isinstance(raw_features, dict):
        raw_features = raw_features.get("items") or raw_features.get("features")
    if not isinstance(raw_features, list):
        raw_features = []

    for idx, feat in enumerate(raw_features):
        if not isinstance(feat, dict):
            continue
        name = str(feat.get("name") or f"Feature {idx + 1}").strip()
        ftype = str(feat.get("type") or "Feature").strip()
        try:
            count = int(feat.get("count", 1))
        except Exception:
            count = 1
        normalized_feature = {
            "name": name,
            "type": ftype,
            "count": max(1, count),
            "spatial_description": str(feat.get("spatial_description") or feat.get("description") or "").strip(),
        }
        if feat.get("inspection_reason"):
            normalized_feature["inspection_reason"] = str(feat.get("inspection_reason")).strip()
        if isinstance(feat.get("evidence"), list):
            normalized_feature["evidence"] = [str(v) for v in feat.get("evidence", []) if v is not None]
        elif isinstance(feat.get("evidence"), str) and feat.get("evidence").strip():
            normalized_feature["evidence"] = [feat.get("evidence").strip()]
        uncertainty = str(feat.get("uncertainty") or "").strip().lower()
        if uncertainty in {"low", "medium", "high"}:
            normalized_feature["uncertainty"] = uncertainty
        if feat.get("review_notes"):
            normalized_feature["review_notes"] = str(feat.get("review_notes")).strip()
        out["features"].append(normalized_feature)

    if not out["features"]:
        raise ValueError("profile must include at least one feature")
    return out


def _profile_builder_text_values(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: List[str] = []
        for item in value:
            out.extend(_profile_builder_text_values(item))
        return out
    if isinstance(value, dict):
        out: List[str] = []
        for item in value.values():
            out.extend(_profile_builder_text_values(item))
        return out
    return []


def _profile_builder_contextual_validation_issues(profile: dict, context: dict) -> List[dict]:
    issues: List[dict] = []
    material = ((context.get("partSummary") or {}).get("material") or {})
    material_status = str(material.get("status") or "unknown")
    if material_status == "specified":
        return issues

    text = "\n".join(_profile_builder_text_values(profile)).lower()
    found = []
    for term in sorted(PROFILE_BUILDER_MATERIAL_TERMS, key=len, reverse=True):
        pattern = r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])"
        if re.search(pattern, text):
            found.append(term)

    if found:
        raw = str(material.get("raw") or material.get("value") or material_status)
        issues.append({
            "feature_name": "<profile>",
            "feature_type": "material_claim",
            "issue": (
                "Profile names unsupported material(s) "
                f"{', '.join(sorted(found))} but source material is {raw!r}. "
                "Remove the material claim or add source evidence before applying."
            ),
            "severity": "error",
        })
    return issues


def _generate_profile_builder_draft(context: dict, instructions: Optional[str], model: Optional[str]) -> Tuple[dict, str]:
    try:
        import anthropic
    except ImportError:
        raise HTTPException(status_code=500, detail="Anthropic SDK not installed")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

    selected_model = (model or os.getenv("INSPECTORPRO_PROFILE_BUILDER_MODEL") or PROFILE_BUILDER_MODEL_DEFAULT).strip()
    client = anthropic.Anthropic(api_key=api_key)
    prompt = _profile_builder_prompt(context, instructions)

    with time_block() as _elapsed_ms:
        try:
            response = client.messages.create(
                model=selected_model,
                max_tokens=3000,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as ex:
            status, error_type = classify_exception_status(ex)
            record_anthropic_call(
                model=selected_model, response=None, latency_ms=_elapsed_ms(),
                status=status, errorType=error_type,
                route="/api/profile-builder/generate",
                workflow="profile_builder",
                agentType="profile_builder",
                partNumber=context.get("partNumber"),
            )
            raise

    record_anthropic_call(
        model=selected_model, response=response, latency_ms=_elapsed_ms(),
        route="/api/profile-builder/generate",
        workflow="profile_builder",
        agentType="profile_builder",
        partNumber=context.get("partNumber"),
    )

    response_text = ""
    for block in getattr(response, "content", []) or []:
        if hasattr(block, "text"):
            response_text += block.text
    return _extract_json_object(response_text), selected_model


def _profile_builder_write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    bak = path.with_suffix(path.suffix + ".bak")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    if path.exists():
        try:
            if bak.exists():
                bak.unlink()
            os.replace(path, bak)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
    os.replace(tmp, path)


@app.get("/api/profile-builder/context/{partNumber}")
async def profile_builder_context(partNumber: str, revision: Optional[str] = Query(default=None)):
    safe_pn = sanitize_part_number(partNumber)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")
    return _profile_builder_context(library_path(), safe_pn, revision)


@app.post("/api/profile-builder/generate")
async def profile_builder_generate(body: ProfileBuilderGenerateBody):
    safe_pn = sanitize_part_number(body.partNumber)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")
    context = _profile_builder_context(library_path(), safe_pn, body.revision)
    if not context.get("ready"):
        return JSONResponse(status_code=409, content={
            "success": False,
            "error": "profile_builder_context_incomplete",
            "message": "Profile Builder needs promoted part metadata and drawing map before it can draft a profile.",
            "missing": context.get("missing", []),
            "context": context,
        })

    try:
        raw_profile, model_used = _generate_profile_builder_draft(context, body.instructions, body.model)
        draft = _normalize_profile_builder_draft(raw_profile, safe_pn)
    except HTTPException:
        raise
    except Exception as ex:
        logger.error("profile_builder.generate failed pn=%s msg=%s", safe_pn, ex)
        raise HTTPException(status_code=500, detail=f"Profile Builder failed: {ex}")

    issues = validate_profile(draft) + _profile_builder_contextual_validation_issues(draft, context)
    return {
        "success": True,
        "partNumber": safe_pn,
        "revision": context.get("revision"),
        "model": model_used,
        "draftProfile": draft,
        "validationIssues": issues,
        "context": {
            "paths": context.get("paths", {}),
            "existingProfile": context.get("existingProfile", {}),
            "partFeatureCount": (context.get("partSummary") or {}).get("featureCount", 0),
            "drawingSheetCount": (context.get("drawingSummary") or {}).get("sheetCount", 0),
            "drawingViewCount": (context.get("drawingSummary") or {}).get("viewCount", 0),
        },
    }


@app.post("/api/profile-builder/apply")
async def profile_builder_apply(body: ProfileBuilderApplyBody):
    safe_pn = sanitize_part_number(body.partNumber)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")
    safe_rev, rev_dir = _profile_builder_resolve_revision(library_path(), safe_pn, body.revision)
    if safe_rev and (rev_dir is None or not rev_dir.exists()):
        raise HTTPException(status_code=404, detail=f"Revision {safe_rev} does not exist for part {safe_pn}")

    library_dir = library_path()
    context = _profile_builder_context(library_dir, safe_pn, safe_rev)

    try:
        profile = _normalize_profile_builder_draft(body.profile, safe_pn)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=f"Invalid profile draft: {ex}")
    issues = validate_profile(profile) + _profile_builder_contextual_validation_issues(profile, context)
    hard_errors = [i for i in issues if i.get("severity") == "error"]
    if hard_errors:
        return JSONResponse(status_code=422, content={
            "success": False,
            "error": "profile_validation_failed",
            "message": "Profile has validation errors. Fix the draft before applying.",
            "validationIssues": issues,
        })

    root_profile = library_dir / f"{safe_pn}_inspection_profile.json"
    existing = _profile_builder_load_json(root_profile)
    existing_kind = _profile_builder_profile_kind(existing)
    if existing_kind == "real" and (body.overwriteConfirmed or "").strip() != safe_pn:
        return JSONResponse(status_code=409, content={
            "success": False,
            "error": "real_profile_overwrite_requires_confirmation",
            "message": f"A real profile already exists. Type {safe_pn} to confirm overwrite.",
            "requiresOverwriteConfirmation": True,
            "confirmationText": safe_pn,
            "existingProfile": {"kind": existing_kind, "path": _intake_relpath(library_dir, root_profile)},
        })

    written: List[str] = []
    try:
        _profile_builder_write_json_atomic(root_profile, profile)
        written.append(_intake_relpath(library_dir, root_profile))
        if rev_dir is not None and rev_dir.exists():
            rev_profile = rev_dir / f"{safe_pn}_inspection_profile.json"
            _profile_builder_write_json_atomic(rev_profile, profile)
            written.append(_intake_relpath(library_dir, rev_profile))
    except Exception as ex:
        logger.error("profile_builder.apply failed pn=%s msg=%s", safe_pn, ex)
        raise HTTPException(status_code=500, detail=f"failed to write profile: {ex}")

    if inspector is not None and hasattr(inspector, "refresh_profile_index"):
        try:
            inspector.refresh_profile_index()
        except Exception as ex:
            logger.warning("profile_builder.refresh_profile_index failed pn=%s: %s", safe_pn, ex)

    return {
        "success": True,
        "partNumber": safe_pn,
        "revision": safe_rev,
        "written": written,
        "validationIssues": issues,
        "replacedProfileKind": existing_kind,
    }


@app.post("/api/inspect")
async def run_inspection(
    file: UploadFile = File(...),
    part_number: str = Form(...),
    send_reference_views: bool = Form(True),
    drawing_map_revision: Optional[str] = Form(None),
):
    """Run a full inspection on an uploaded drawing."""
    # Phase 3 telemetry: workflow="inspection" with per-stage events.
    # The four stages mirror the spec at usage-cost-dashboard-plan.md
    # plus a "total" event emitted in finally so latency is always
    # recorded — even on HTTP-error paths.
    import time as _t_inspect
    _wf_start = _t_inspect.perf_counter()
    _wf_status = "success"
    _wf_error: Optional[str] = None

    # Validate part_number is not empty or whitespace
    if not part_number or not part_number.strip():
        # Total event covers even the early-validation reject.
        _val_ms = (_t_inspect.perf_counter() - _wf_start) * 1000.0
        record_workflow_stage(
            workflow="inspection", stage="validate_input",
            latency_ms=_val_ms, status="error", errorType="HTTPException_422",
            route="/api/inspect",
        )
        record_workflow_stage(
            workflow="inspection", stage="total",
            latency_ms=_val_ms, status="error", errorType="HTTPException_422",
            route="/api/inspect",
        )
        raise HTTPException(status_code=422, detail="part_number is required and cannot be empty")

    # Library Intake Wizard Step 1: stub-profile fail-fast gate (§9.6).
    # Resolve the profile file the same way get_profile_details does and
    # refuse the request with HTTP 422 BEFORE any file read, LLM call,
    # or temp write. Telemetry total event still fires so the dashboard
    # can chart these gated requests as a distinct error class.
    _stub_check_data = _load_profile_if_present(part_number)
    if _is_intake_stub_profile(_stub_check_data):
        _val_ms = (_t_inspect.perf_counter() - _wf_start) * 1000.0
        record_workflow_stage(
            workflow="inspection", stage="validate_input",
            latency_ms=_val_ms, status="error", errorType="profile_incomplete",
            route="/api/inspect", partNumber=part_number,
        )
        record_workflow_stage(
            workflow="inspection", stage="total",
            latency_ms=_val_ms, status="error", errorType="profile_incomplete",
            route="/api/inspect", partNumber=part_number,
        )
        logger.info("inspect.fail_fast.profile_incomplete pn=%s", part_number)
        return JSONResponse(
            status_code=422,
            content={
                "error":       "profile_incomplete",
                "message":     INTAKE_STUB_INSPECT_MESSAGE,
                "part_number": part_number,
            },
        )

    try:
        drawing_bytes = await file.read()
        filename = file.filename or "unknown"

        # Validate file is not empty
        if len(drawing_bytes) == 0:
            raise HTTPException(status_code=422, detail="Uploaded file is empty")

        _validate_done = _t_inspect.perf_counter()
        record_workflow_stage(
            workflow="inspection", stage="validate_input",
            latency_ms=(_validate_done - _wf_start) * 1000.0,
            route="/api/inspect", partNumber=part_number,
        )

        logger.info(f"Running inspection: part={part_number}, file={filename}, ref_views={send_reference_views}")

        _inspect_start = _t_inspect.perf_counter()
        result = inspector.inspect(
            drawing_bytes=drawing_bytes,
            filename=filename,
            part_number=part_number,
            send_reference_views=send_reference_views,
        )
        _inspect_done = _t_inspect.perf_counter()
        record_workflow_stage(
            workflow="inspection", stage="inspect",
            latency_ms=(_inspect_done - _inspect_start) * 1000.0,
            route="/api/inspect", partNumber=part_number,
        )

        logger.info(f"Inspection complete for {part_number}: {result.get('gap_summary', {}).get('completeness', 'N/A')}")

        resolved_part_number = result.get("part_number") or part_number
        safe_map_rev = re.sub(r"[^\w]", "", drawing_map_revision or "")
        drawing_map = (
            load_drawing_map_revision(resolved_part_number, safe_map_rev, LIBRARY_DIR)
            if safe_map_rev
            else load_drawing_map(resolved_part_number, LIBRARY_DIR)
        )

        # Load inspection profile for profile-aware annotation matching
        profile_data = None
        safe_rpn = sanitize_part_number(resolved_part_number)
        for _prof_candidate in [
            library_path() / f"{safe_rpn}_inspection_profile.json",
            library_path() / f"{safe_rpn}.json",
        ]:
            if _prof_candidate.exists():
                try:
                    with open(_prof_candidate, "r", encoding="utf-8-sig") as _pf:
                        profile_data = json.load(_pf)
                except Exception:
                    pass
                break

        enriched_features, drawing_map_metadata = apply_drawing_map_to_findings(
            result.get("features", []),
            drawing_map,
            profile=profile_data,
        )

        result["features"] = enriched_features
        if isinstance(result.get("findings"), dict):
            result["findings"]["features"] = enriched_features

        total_features = len(enriched_features)
        status_counts = {
            "present": sum(1 for f in enriched_features if str(f.get("status") or "").upper() == "PRESENT"),
            "missing": sum(1 for f in enriched_features if str(f.get("status") or "").upper() == "MISSING"),
            "partial": sum(1 for f in enriched_features if str(f.get("status") or "").upper() == "PARTIAL"),
            "discrepant": sum(1 for f in enriched_features if str(f.get("status") or "").upper() == "DISCREPANT"),
        }
        completeness_pct = int(round((status_counts["present"] / total_features) * 100)) if total_features else 0
        issue_statuses = {"MISSING", "PARTIAL", "DISCREPANT"}
        critical_issues = []
        for feat in enriched_features:
            if str(feat.get("status") or "").upper() not in issue_statuses:
                continue
            critical_issues.append(feat.get("observation") or feat.get("name") or "Unnamed issue")
        critical_issues = critical_issues[:10]

        result["gap_summary"] = {
            "total_features": total_features,
            "present": status_counts["present"],
            "missing": status_counts["missing"],
            "partial": status_counts["partial"],
            "discrepant": status_counts["discrepant"],
            "completeness": f"{completeness_pct}%",
            "critical_issues": critical_issues,
        }
        if isinstance(result.get("findings"), dict):
            result["findings"]["gap_summary"] = {
                "total_features": total_features,
                "present": status_counts["present"],
                "missing": status_counts["missing"],
                "partial": status_counts["partial"],
                "discrepant": status_counts["discrepant"],
                "overall_completeness": f"{completeness_pct}%",
                "critical_issues": critical_issues,
            }
        try:
            rep_summary = inspector._compute_representation_summary(enriched_features)
        except Exception:
            rep_summary = result.get("representation_summary")
        result["representation_summary"] = rep_summary
        if isinstance(result.get("findings"), dict) and rep_summary is not None:
            result["findings"]["representation_summary"] = rep_summary
        result["drawing_map"] = drawing_map
        result["drawing_map_metadata"] = drawing_map_metadata

        # Load VLM highlight boxes if cached
        hl_path = _find_highlight_boxes_path(resolved_part_number, LIBRARY_DIR)
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
        dd_path = _find_dimension_descriptions_path(resolved_part_number, LIBRARY_DIR)
        if dd_path is not None:
            try:
                with open(dd_path, "r", encoding="utf-8-sig") as df:
                    result["dimension_descriptions"] = json.load(df)
                logger.info(f"Loaded dimension descriptions for {resolved_part_number}")
            except Exception as e:
                logger.warning(f"Failed to load dimension descriptions: {e}")

        # ── Load part JSON once (shared by sketch + hybrid comparison) ──
        part_json = None
        part_json_path = library_path() / f"{sanitize_part_number(resolved_part_number)}.json"
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

        # Stage events: everything between inspect-done and now is
        # enrichment. response_assembly is a near-zero step (build the
        # dict + return); we record it for symmetry with the spec but
        # expect it to be in the sub-millisecond range.
        _enrichment_done = _t_inspect.perf_counter()
        record_workflow_stage(
            workflow="inspection", stage="enrichment",
            latency_ms=(_enrichment_done - _inspect_done) * 1000.0,
            route="/api/inspect", partNumber=part_number,
        )
        record_workflow_stage(
            workflow="inspection", stage="response_assembly",
            latency_ms=0.0,  # negligible; placeholder for shape consistency
            route="/api/inspect", partNumber=part_number,
        )
        return result
    except HTTPException as _http_ex:
        _wf_status = "error"
        _wf_error = f"HTTPException_{int(getattr(_http_ex, 'status_code', 500))}"
        raise  # Re-raise HTTPExceptions as-is
    except FileNotFoundError as e:
        _wf_status = "error"
        _wf_error = "FileNotFoundError"
        logger.warning(f"Profile not found for part '{part_number}': {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        _wf_status = "error"
        _wf_error = "ValueError"
        logger.warning(f"Invalid input for inspection: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        _wf_status = "error"
        _wf_error = type(e).__name__
        logger.error(f"Error during inspection: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        # Total event always fires — success or failure. Lets the
        # dashboard compute "total /api/inspect latency p95" without
        # discriminating against error paths.
        record_workflow_stage(
            workflow="inspection", stage="total",
            latency_ms=(_t_inspect.perf_counter() - _wf_start) * 1000.0,
            status=_wf_status, errorType=_wf_error,
            route="/api/inspect", partNumber=part_number,
        )


@app.get("/api/validate-profiles")
async def validate_profiles():
    """Run the profile validator and return results as JSON."""
    try:
        results = validate_all_profiles(str(LIBRARY_DIR))
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
    profile_path = _resolve_profile_path(safe_pn)
    if profile_path is None:
        assy_data = assembly_profiles.get(safe_pn)
        if assy_data:
            ident = assy_data.get("identity", {}) or {}
            stats = assy_data.get("statistics", {}) or {}
            assy_name = ident.get("description", safe_pn)
            return {
                "part_number": safe_pn,
                "part_name": assy_name,
                "part_description": assy_name,
                "features": [],
                "view_expectations": {},
                "context_kind": "assembly",
                "component_count": stats.get("totalComponents", 0),
                "mate_count": stats.get("totalMates", 0),
            }
        raise HTTPException(status_code=404, detail=f"No profile found for part number '{part_number}'")

    try:
        with open(profile_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)

        # Library Intake Wizard Step 1: stub-aware response per §9.5.
        # When the underlying file is an intake stub, expose
        # source/status/inspectionReady/links verbatim so the frontend
        # can gate Inspect actions. Real profiles fall through to the
        # existing composition unchanged (backward compat — no `source`
        # field added when not in the file, see §9.5 paragraph
        # "Backward compat for real profiles").
        if _is_intake_stub_profile(data):
            return {
                "part_number":      data.get("part_number", safe_pn),
                "part_name":        data.get("name") or data.get("part_name", ""),
                "part_description": data.get("description") or data.get("part_description", ""),
                "features":         [],
                "source":           data.get("source"),
                "status":           data.get("status"),
                "inspectionReady":  data.get("inspectionReady"),
                "links":            data.get("links", {}),
            }

        # Real profile -- return a curated subset focused on what the agent needs
        features = []
        raw_features = data.get("features", [])
        if isinstance(raw_features, dict):
            raw_features = raw_features.get("items") or raw_features.get("features") or []
        if isinstance(raw_features, list):
            for feat in raw_features:
                if not isinstance(feat, dict):
                    continue
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

    library_dir = library_path()
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

    stl_path = library_path() / f"{safe_pn}.stl"
    # Fallback: check parts/{pn}/revA/ for revision-stored STL
    if not stl_path.exists():
        rev_stl = _resolve_part_asset(safe_pn, "revA", f"{safe_pn}.stl")
        logger.info(f"[3D Model] Root STL not found, checking revision path: {rev_stl} exists={rev_stl is not None}")
        if rev_stl is not None:
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
    rev_path = _resolve_part_asset(safe_pn, "revA", f"{safe_pn}_colored.glb")
    root_path = library_path() / f"{safe_pn}_colored.glb"
    glb_path = rev_path if rev_path is not None else root_path
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
    rev_json = _resolve_part_asset(safe_pn, "revA", f"{safe_pn}_feature_colors.json")
    root_json = library_path() / f"{safe_pn}_feature_colors.json"
    json_path = rev_json if rev_json is not None else root_json
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

    parts_dir = _part_root_dir(safe_pn)
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

    glb_path = _resolve_part_asset(safe_pn, f"rev{safe_rev}", f"{safe_pn}_colored.glb")
    if glb_path is None:
        # Fallback: serve STL if GLB not available
        stl_path = _resolve_part_asset(safe_pn, f"rev{safe_rev}", f"{safe_pn}.stl")
        if stl_path is not None:
            return FileResponse(stl_path, media_type="model/stl")
        raise HTTPException(status_code=404, detail=f"No GLB or STL for part '{part_number}' revision '{revision}'")

    return FileResponse(path=str(glb_path), media_type="model/gltf-binary", filename=f"{safe_pn}_colored.glb")


@app.get("/api/part-feature-diff/{part_number}")
async def get_part_feature_diff(part_number: str, revA: str = Query(...), revB: str = Query(...)):
    """Compare features between two part revisions."""
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    safe_a = re.sub(r'[^\w]', '', revA)
    safe_b = re.sub(r'[^\w]', '', revB)

    base_dir = _part_root_dir(safe_pn)
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
    library_dir = library_path()
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


def _read_glb_material_color_map(glb_path: Path) -> Dict[str, str]:
    """Return a best-effort material/mesh-name -> hex color map from a GLB.

    Assembly sidecars can carry stale partColorMapping data after a colored
    GLB is regenerated. The GLB is the visual source of truth for Part
    Explorer swatches and narration color labels.
    """
    if not glb_path.exists():
        return {}
    try:
        raw = glb_path.read_bytes()
        if len(raw) < 20 or raw[:4] != b"glTF":
            return {}
        offset = 12
        gltf_json = None
        while offset + 8 <= len(raw):
            chunk_len = int.from_bytes(raw[offset:offset + 4], "little")
            chunk_type = int.from_bytes(raw[offset + 4:offset + 8], "little")
            offset += 8
            chunk = raw[offset:offset + chunk_len]
            offset += chunk_len
            if chunk_type == 0x4E4F534A:  # JSON
                gltf_json = json.loads(chunk.decode("utf-8").rstrip("\x00 \t\r\n"))
                break
        if not gltf_json:
            return {}
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return {}

    def norm(value: Any) -> str:
        return str(value or "").strip().lower().replace("\\", "/").rsplit("/", 1)[-1]

    def factor_to_hex(factor: Any) -> Optional[str]:
        if not isinstance(factor, list) or len(factor) < 3:
            return None
        try:
            rgb = [max(0, min(255, int(round(float(v) * 255)))) for v in factor[:3]]
        except (TypeError, ValueError):
            return None
        return "#{:02X}{:02X}{:02X}".format(*rgb)

    material_colors: Dict[int, str] = {}
    result: Dict[str, str] = {}
    for idx, material in enumerate(gltf_json.get("materials", []) or []):
        pbr = material.get("pbrMetallicRoughness") or {}
        hex_val = factor_to_hex(pbr.get("baseColorFactor"))
        if not hex_val:
            continue
        material_colors[idx] = hex_val
        name = norm(material.get("name"))
        if name:
            result[name] = hex_val

    meshes = gltf_json.get("meshes", []) or []
    for mesh in meshes:
        mesh_name = norm(mesh.get("name"))
        if not mesh_name:
            continue
        prim_colors = []
        for prim in mesh.get("primitives", []) or []:
            mat_idx = prim.get("material")
            if isinstance(mat_idx, int) and mat_idx in material_colors:
                prim_colors.append(material_colors[mat_idx])
        unique = sorted(set(prim_colors))
        if len(unique) == 1:
            result[mesh_name] = unique[0]

    for node in gltf_json.get("nodes", []) or []:
        node_name = norm(node.get("name"))
        mesh_idx = node.get("mesh")
        if not node_name or not isinstance(mesh_idx, int) or mesh_idx >= len(meshes):
            continue
        mesh_name = norm((meshes[mesh_idx] or {}).get("name"))
        if mesh_name in result:
            result[node_name] = result[mesh_name]
            result[node_name.rsplit("/", 1)[-1]] = result[mesh_name]

    return result


def _correct_assembly_color_map_from_glb(assy_number: str, assy_data: dict, color_map: dict) -> dict:
    """Overlay assembly color metadata with the actual colored-GLB materials."""
    corrected = dict(color_map or {})
    part_data_cache = assy_data.get("partDataCache", {})
    glb_color_map = _read_glb_material_color_map(
        library_path("assemblies") / f"{assy_number}_colored.glb"
    )
    if not glb_color_map:
        return corrected

    for old_key in list(corrected.keys() or part_data_cache.keys()):
        identity = (part_data_cache.get(old_key, {}).get("identity") or {})
        pn = ((identity.get("customProperties") or {}).get("PartNo", "")).strip()
        if not pn:
            pn = (identity.get("partNumber") or "").strip()
        candidates = [
            old_key,
            Path(old_key).name,
            Path(old_key).stem,
            f"{pn}.sldprt" if pn else "",
            pn,
        ]
        for candidate in candidates:
            normalized = str(candidate or "").strip().lower().replace("\\", "/").rsplit("/", 1)[-1]
            if normalized in glb_color_map:
                corrected[old_key] = glb_color_map[normalized]
                break

    return corrected


_ASSEMBLY_HEX_TO_NAME = {
    "#E6194B": "red", "#3CB44B": "green", "#FFE119": "yellow", "#0082C8": "blue",
    "#F58230": "orange", "#911EB4": "purple", "#46F0F0": "cyan", "#F032E6": "magenta",
    "#D2F53C": "lime", "#FABEBE": "pink", "#FABED4": "pink", "#008080": "teal",
    "#E6BEFF": "lavender", "#DCBEFF": "lavender", "#AA6E28": "brown",
    "#FFFAC8": "cream", "#800000": "maroon", "#AAFFC3": "mint", "#808000": "olive",
    "#FFD8B1": "apricot", "#000080": "navy", "#808080": "gray", "#FFFFFF": "white",
    "#000000": "black",
}


def _assembly_hex_to_name(hex_val: Any) -> str:
    if not isinstance(hex_val, str):
        return ""
    return _ASSEMBLY_HEX_TO_NAME.get(hex_val.upper(), hex_val)


def _rewrite_narrative_color_references(value: Any, color_by_pn: Dict[str, str]) -> Any:
    """Replace stale color words that appear directly next to part numbers."""
    color_words = (
        "red|green|yellow|blue|orange|purple|cyan|magenta|lime|pink|teal|"
        "lavender|brown|cream|maroon|mint|olive|apricot|navy|gray|grey|white|black"
    )

    def rewrite_text(text: str) -> str:
        fixed = text
        for pn, color_name in color_by_pn.items():
            if not pn or not color_name:
                continue
            escaped_pn = re.escape(str(pn))
            # Robot Base (1030018, green)
            fixed = re.sub(
                rf"(\(\s*{escaped_pn}\s*,\s*)({color_words})(\s*\))",
                lambda m, c=color_name: f"{m.group(1)}{c}{m.group(3)}",
                fixed,
                flags=re.IGNORECASE,
            )
            # 1030018 ROBOT BASE (green) or 1030018 (green)
            fixed = re.sub(
                rf"({escaped_pn}[^()\n]{{0,80}}\(\s*)({color_words})(\s*\))",
                lambda m, c=color_name: f"{m.group(1)}{c}{m.group(3)}",
                fixed,
                flags=re.IGNORECASE,
            )
        return fixed

    if isinstance(value, str):
        return rewrite_text(value)
    if isinstance(value, list):
        return [_rewrite_narrative_color_references(v, color_by_pn) for v in value]
    if isinstance(value, dict):
        return {k: _rewrite_narrative_color_references(v, color_by_pn) for k, v in value.items()}
    return value


@app.get("/api/assembly-context/{part_number}")
async def get_assembly_context(part_number: str):
    """Return assembly context for a part number or direct assembly number."""
    # Sanitize
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")

    # Accept either:
    # 1. a member part number that maps back to an assembly, or
    # 2. the assembly number itself (used by full-assembly drawings like 6000302).
    if safe_pn in assembly_part_lookup:
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
        context_kind = "part"
    elif safe_pn in assembly_profiles:
        assy_number = safe_pn
        assy_data = assembly_profiles.get(assy_number, {})
        part_aliases = None
        context_kind = "assembly"
    else:
        raise HTTPException(status_code=404, detail=f"No assembly context for part {part_number}")

    # Filter mates to only those involving this part
    all_mates = assy_data.get("mates", [])
    if part_aliases is None:
        mates_for_part = all_mates
    else:
        mates_for_part = []
        for mate in all_mates:
            e1 = mate.get("entity1", {}).get("componentName", "")
            e2 = mate.get("entity2", {}).get("componentName", "")
            if any(alias in e1 or alias in e2 for alias in part_aliases):
                mates_for_part.append(mate)

    # Filter mateRelationships
    all_relationships = assy_data.get("mateRelationships", [])
    if part_aliases is None:
        relationships_for_part = all_relationships
    else:
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
    assemblies_dir = library_path("assemblies")
    has_views = (assemblies_dir / f"{assy_number}_view_front.png").exists()
    has_glb = (assemblies_dir / f"{assy_number}_colored.glb").exists()

    # Hex-to-friendly-name lookup for Sasha Trubetskoy palette + common colors
    _HEX_TO_NAME = {
        "#E6194B": "red", "#3CB44B": "green", "#FFE119": "yellow", "#0082C8": "blue",
        "#F58230": "orange", "#911EB4": "purple", "#46F0F0": "cyan", "#F032E6": "magenta",
        "#D2F53C": "lime", "#FABEBE": "pink", "#008080": "teal", "#E6BEFF": "lavender",
        "#FABED4": "pink", "#DCBEFF": "lavender",
        "#AA6E28": "brown", "#FFFAC8": "cream", "#800000": "maroon", "#AAFFC3": "mint",
        "#808000": "olive", "#FFD8B1": "apricot", "#000080": "navy", "#808080": "gray",
        "#FFFFFF": "white", "#000000": "black",
    }

    # Build color legend: resolve old filenames to new part numbers +
    # descriptions. Some extracted assembly JSONs do not carry an explicit
    # partColorMapping even though the assembly is otherwise valid. In that
    # case we still need a stable legend / Part Explorer dataset, so fall
    # back to deterministic palette assignment from partDataCache keys.
    color_map = assy_data.get("partColorMapping", assy_data.get("colorAssignments", {}))
    part_data_cache = assy_data.get("partDataCache", {})
    if not color_map and part_data_cache:
        palette = [
            "#E6194B", "#3CB44B", "#FFE119", "#0082C8", "#F58230",
            "#911EB4", "#46F0F0", "#F032E6", "#D2F53C", "#FABEBE",
            "#008080", "#E6BEFF", "#AA6E28", "#FFFAC8", "#800000",
            "#AAFFC3", "#808000", "#FFD8B1", "#000080", "#808080",
        ]
        color_map = {
            old_key: palette[idx % len(palette)]
            for idx, old_key in enumerate(sorted(part_data_cache.keys()))
        }
    color_map = _correct_assembly_color_map_from_glb(assy_number, assy_data, color_map)
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

    color_by_pn = {
        item["part_number"]: item.get("color_name", "")
        for item in part_color_legend
        if item.get("part_number")
    }
    functional_narrative = _rewrite_narrative_color_references(
        assy_data.get("functionalNarrative", {}),
        color_by_pn,
    )

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
        "context_kind": context_kind,
        "assembly_number": assy_number,
        "assembly_name": assy_name,
        "component_count": stats.get("totalComponents", 0),
        "mate_count": stats.get("totalMates", 0),
        "mates_for_part": mates_for_part,
        "mate_relationships_for_part": relationships_for_part,
        "all_mate_relationships": all_relationships,
        "functional_narrative": functional_narrative,
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

    assemblies_dir = library_path("assemblies")
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

    assemblies_dir = library_path("assemblies")

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

    assy_dir = library_path("assemblies") / safe_num
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

    base_dir = library_path("assemblies") / safe_num
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


# ---------- Assembly BOM-aware Revision Package (Phase 1) ----------
#
# These routes back the BOM-aware compare workspace. They are intentionally
# narrow: they list revisions, expose per-revision asset URLs, and serve the
# raw JSON/PDF for each revision. No procurement classification, no diff
# normalisation, no substitution detection. Those land in Phase 2.

def _normalize_revision_letter(revision: str) -> str:
    """Strip an optional leading 'rev' (case-insensitive) and uppercase the rest.

    Accepts 'A', 'a', 'revA', 'Rev_a' and returns 'A'. Empty string if the
    input contains no usable suffix. Canonicalising to uppercase keeps the
    contract consistent with the revisions listing, which always returns
    uppercase letters.
    """
    if revision is None:
        return ""
    cleaned = re.sub(r'[^A-Za-z0-9]', '', revision)
    if cleaned[:3].lower() == "rev":
        cleaned = cleaned[3:]
    return cleaned.upper()


def _assembly_revision_dir(safe_num: str, safe_rev: str) -> Path:
    return library_path("assemblies") / safe_num / f"rev{safe_rev}"


def _resolve_assembly_pdf_path(safe_num: str, safe_rev: str) -> Optional[Path]:
    """Return the assembly drawing PDF path for a revision, or None if missing.

    Both '.PDF' and '.pdf' on disk are accepted. Used by the package presence
    map and the direct PDF route so they cannot disagree.
    """
    rev_dir = _assembly_revision_dir(safe_num, safe_rev)
    for candidate in (rev_dir / f"{safe_num}.PDF", rev_dir / f"{safe_num}.pdf"):
        if candidate.exists():
            return candidate
    return None


def _resolve_assembly_compare_assets(safe_num: str, safe_rev: str) -> Dict[str, dict]:
    """Return {asset_kind: {path: Path, exists: bool, url: Optional[str]}} for one revision.

    URLs are returned only for assets that exist; missing assets get url=None so
    the frontend can render an explicit gap rather than guess.
    """
    rev_dir = _assembly_revision_dir(safe_num, safe_rev)
    base_url = f"/api/assembly-compare/{safe_num}/{safe_rev}"
    assets = {
        "assembly_json": {
            "path": rev_dir / f"{safe_num}_assembly.json",
            "url": f"{base_url}/assembly-json",
        },
        "glb": {
            "path": rev_dir / f"{safe_num}_colored.glb",
            "url": f"/api/assembly-model/{safe_num}?revision={safe_rev}",
        },
        "drawing_map": {
            "path": rev_dir / f"{safe_num}_drawing_map.json",
            "url": f"{base_url}/drawing-map",
        },
        "bom_highlights": {
            "path": rev_dir / f"{safe_num}_bom_row_highlights.json",
            "url": f"{base_url}/bom-highlights",
        },
        "pdf": {
            "path": _resolve_assembly_pdf_path(safe_num, safe_rev),
            "url": f"{base_url}/pdf",
        },
    }
    for kind, info in assets.items():
        path = info["path"]
        info["exists"] = path is not None and path.exists()
        if not info["exists"]:
            info["url"] = None
    return assets


def _list_assembly_revisions(safe_num: str) -> List[str]:
    """Return sorted list of revision letters available on disk for an assembly."""
    assy_dir = library_path("assemblies") / safe_num
    if not assy_dir.exists() or not assy_dir.is_dir():
        return []
    return sorted([
        d.name[3:]
        for d in assy_dir.iterdir()
        if d.is_dir() and d.name.lower().startswith("rev")
    ])


@app.get("/api/assembly-compare/{assembly_number}/revisions")
async def get_assembly_compare_revisions(assembly_number: str):
    """List revisions for an assembly with per-revision asset presence + URLs."""
    safe_num = re.sub(r'[^\w\-]', '', assembly_number)
    if not safe_num:
        raise HTTPException(status_code=400, detail="Invalid assembly number")

    revisions = _list_assembly_revisions(safe_num)
    revision_packages = []
    for rev in revisions:
        assets = _resolve_assembly_compare_assets(safe_num, rev)
        presence = {kind: info["exists"] for kind, info in assets.items()}
        urls = {kind: info["url"] for kind, info in assets.items()}
        revision_packages.append({
            "revision": rev,
            "presence": presence,
            "asset_urls": urls,
        })

    return {
        "assembly_number": safe_num,
        "revisions": [r["revision"] for r in revision_packages],
        "revision_packages": revision_packages,
    }


@app.get("/api/assembly-compare/{assembly_number}/{revision}/drawing-map")
async def get_assembly_compare_drawing_map(assembly_number: str, revision: str):
    """Serve the drawing map JSON for one revision of an assembly."""
    safe_num = re.sub(r'[^\w\-]', '', assembly_number)
    safe_rev = _normalize_revision_letter(revision)
    if not safe_num or not safe_rev:
        raise HTTPException(status_code=400, detail="Invalid assembly number or revision")

    path = _assembly_revision_dir(safe_num, safe_rev) / f"{safe_num}_drawing_map.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No drawing map for {safe_num} rev {safe_rev}")

    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to read drawing map: {e}")


@app.get("/api/assembly-compare/{assembly_number}/{revision}/bom-highlights")
async def get_assembly_compare_bom_highlights(assembly_number: str, revision: str):
    """Serve the BOM row highlight JSON for one revision of an assembly."""
    safe_num = re.sub(r'[^\w\-]', '', assembly_number)
    safe_rev = _normalize_revision_letter(revision)
    if not safe_num or not safe_rev:
        raise HTTPException(status_code=400, detail="Invalid assembly number or revision")

    path = _assembly_revision_dir(safe_num, safe_rev) / f"{safe_num}_bom_row_highlights.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No BOM highlights for {safe_num} rev {safe_rev}")

    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to read BOM highlights: {e}")


@app.get("/api/assembly-compare/{assembly_number}/{revision}/assembly-json")
async def get_assembly_compare_assembly_json(assembly_number: str, revision: str):
    """Serve the assembly JSON for one revision of an assembly."""
    safe_num = re.sub(r'[^\w\-]', '', assembly_number)
    safe_rev = _normalize_revision_letter(revision)
    if not safe_num or not safe_rev:
        raise HTTPException(status_code=400, detail="Invalid assembly number or revision")

    path = _assembly_revision_dir(safe_num, safe_rev) / f"{safe_num}_assembly.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"No assembly JSON for {safe_num} rev {safe_rev}")

    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to read assembly JSON: {e}")


@app.get("/api/assembly-compare/{assembly_number}/{revision}/pdf")
async def get_assembly_compare_pdf(assembly_number: str, revision: str):
    """Serve the assembly drawing PDF for one revision."""
    safe_num = re.sub(r'[^\w\-]', '', assembly_number)
    safe_rev = _normalize_revision_letter(revision)
    if not safe_num or not safe_rev:
        raise HTTPException(status_code=400, detail="Invalid assembly number or revision")

    pdf_path = _resolve_assembly_pdf_path(safe_num, safe_rev)
    if pdf_path is None:
        raise HTTPException(status_code=404, detail=f"No PDF for {safe_num} rev {safe_rev}")

    return FileResponse(
        path=str(pdf_path),
        media_type="application/pdf",
        filename=f"{safe_num}_rev{safe_rev}.pdf",
    )


@app.get("/api/assembly-compare/{assembly_number}/{revision}/drawing-png")
async def get_assembly_compare_drawing_png(assembly_number: str, revision: str, page: int = 1, dpi: int = 150):
    """Render page 1 of the assembly drawing PDF to PNG.

    The default DPI matches the value recorded in *_bom_row_highlights.json's
    'render' block so the row rectangles overlay at the same coordinate space
    the BOM extractor used. The frontend can resample by passing ?dpi=...
    but should expect to scale row bounds proportionally if it does.
    """
    safe_num = re.sub(r'[^\w\-]', '', assembly_number)
    safe_rev = _normalize_revision_letter(revision)
    if not safe_num or not safe_rev:
        raise HTTPException(status_code=400, detail="Invalid assembly number or revision")
    if dpi < 50 or dpi > 600:
        raise HTTPException(status_code=400, detail="dpi must be in [50, 600]")

    pdf_path = _resolve_assembly_pdf_path(safe_num, safe_rev)
    if pdf_path is None:
        raise HTTPException(status_code=404, detail=f"No PDF for {safe_num} rev {safe_rev}")

    try:
        import fitz  # PyMuPDF
    except ImportError:
        raise HTTPException(status_code=500, detail="PyMuPDF (fitz) is not installed")

    try:
        doc = fitz.open(str(pdf_path))
        if page < 1 or page > len(doc):
            doc.close()
            raise HTTPException(status_code=400, detail=f"Invalid page {page}; PDF has {len(doc)} page(s)")
        pdf_page = doc.load_page(page - 1)
        zoom = dpi / 72.0
        pix = pdf_page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        png_bytes = pix.tobytes("png")
        width, height = pix.width, pix.height
        doc.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to render PDF: {e}")

    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "X-Image-Width": str(width),
            "X-Image-Height": str(height),
            "X-Render-DPI": str(dpi),
            "Cache-Control": "public, max-age=3600",
        },
    )


def _supplier_spec_present(part_number: str, safe_rev: str) -> bool:
    """Return True if a supplier_spec.json sidecar exists for a part at a revision.

    Path convention is parts/{pn}/rev{rev}/{pn}_supplier_spec.json. This is
    the only signal the BOM compare uses to flag substitution_unverified.
    """
    if not part_number or not safe_rev:
        return False
    sidecar = (
        library_path("parts")
        / part_number
        / f"rev{safe_rev}"
        / f"{part_number}_supplier_spec.json"
    )
    return sidecar.exists()


@app.get("/api/assembly-compare/{assembly_number}/normalized")
async def get_assembly_compare_normalized(
    assembly_number: str,
    revA: str = Query(...),
    revB: str = Query(...),
):
    """Return the normalized BOM compare payload for two revisions.

    Composes the per-revision BOM row highlight JSONs into a single row-keyed
    response with diff status (added / removed / qty_changed / unchanged /
    substitution_unverified) and procurement classification (purchased /
    custom / unknown). substitution_unverified is a soft signal driven by
    supplier-spec sidecar asymmetry; it is intentionally NOT a member of
    'proven_changed' so the frontend filter can keep it out of 'Changed only'.
    """
    safe_num = re.sub(r'[^\w\-]', '', assembly_number)
    safe_a = _normalize_revision_letter(revA)
    safe_b = _normalize_revision_letter(revB)
    if not safe_num or not safe_a or not safe_b:
        raise HTTPException(status_code=400, detail="Invalid assembly number or revision")

    bom_a_path = _assembly_revision_dir(safe_num, safe_a) / f"{safe_num}_bom_row_highlights.json"
    bom_b_path = _assembly_revision_dir(safe_num, safe_b) / f"{safe_num}_bom_row_highlights.json"
    if not bom_a_path.exists() or not bom_b_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"BOM highlights missing for one or both revisions ({safe_a}/{safe_b}) of {safe_num}",
        )

    try:
        with open(bom_a_path, encoding="utf-8-sig") as f:
            bom_a = json.load(f)
        with open(bom_b_path, encoding="utf-8-sig") as f:
            bom_b = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to read BOM highlights: {e}")

    from ai_inspector.comparison.bom_compare import compute_bom_compare
    result = compute_bom_compare(
        bom_a,
        bom_b,
        supplier_evidence_a=lambda pn: _supplier_spec_present(pn, safe_a),
        supplier_evidence_b=lambda pn: _supplier_spec_present(pn, safe_b),
    )
    result["assembly_number"] = safe_num
    result["revA"] = safe_a
    result["revB"] = safe_b
    return result


@app.get("/api/assembly-compare/{assembly_number}/{revision}")
async def get_assembly_compare_revision_package(assembly_number: str, revision: str):
    """Return the single-revision package: asset URLs + presence flags.

    No data is inlined here; the frontend fetches each asset via the URLs in
    the response. This keeps the package response small and lets the frontend
    decide which sidecars it actually needs for a given view.
    """
    safe_num = re.sub(r'[^\w\-]', '', assembly_number)
    safe_rev = _normalize_revision_letter(revision)
    if not safe_num or not safe_rev:
        raise HTTPException(status_code=400, detail="Invalid assembly number or revision")

    rev_dir = _assembly_revision_dir(safe_num, safe_rev)
    if not rev_dir.exists() or not rev_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"No revision {safe_rev} for assembly {safe_num}")

    assets = _resolve_assembly_compare_assets(safe_num, safe_rev)
    presence = {kind: info["exists"] for kind, info in assets.items()}
    urls = {kind: info["url"] for kind, info in assets.items()}

    return {
        "assembly_number": safe_num,
        "revision": safe_rev,
        "presence": presence,
        "asset_urls": urls,
    }


# ---------- Supplier Spec Compare ----------
# Three honest contracts:
#   1. /api/part-supplier-spec/{pn}?revision=X       — single rev sidecar
#   2. /api/part-supplier-spec-compare/{pn}?revA&revB — split-compare payload
#   3. /api/part-supplier-spec-file/{pn}?revision=X  — raw underlying doc
#
# Honesty rules:
# - Missing sidecars return exists=false. We do not fabricate fields.
# - Field differences are surfaced as "review items", not as proven design
#   changes. The honesty_note on the compare payload says so explicitly so
#   the frontend cannot accidentally present them as proven changes.

_SUPPLIER_SPEC_FIELDS = (
    "supplier",
    "manufacturer_part_number",
    "description",
    "finish",
    "grade",
    "standard",
    "material",
)


def _supplier_spec_path(part_number: str, safe_rev: str) -> Path:
    return (
        library_path("parts")
        / part_number
        / f"rev{safe_rev}"
        / f"{part_number}_supplier_spec.json"
    )


def _normalise_supplier_summary(raw: dict) -> dict:
    """Project a raw supplier-spec sidecar onto the canonical summary
    fields. Absent fields are explicitly null so the compare diff can
    distinguish 'missing on this side' from 'same on both sides'.
    """
    if not isinstance(raw, dict):
        return {f: None for f in _SUPPLIER_SPEC_FIELDS}
    summary = raw.get("summary_fields") if isinstance(raw.get("summary_fields"), dict) else raw
    return {f: (summary.get(f) if summary.get(f) not in (None, "") else None) for f in _SUPPLIER_SPEC_FIELDS}


def _resolve_supplier_doc_path(raw: dict) -> Path | None:
    """Locate the underlying supplier doc file referenced by a sidecar.
    The sidecar's `document` block carries `filename` + `located_in`
    relative to 400S_Sorted_Library. Returns None if missing.
    """
    if not isinstance(raw, dict):
        return None
    doc = raw.get("document") or {}
    filename = doc.get("filename")
    located_in = doc.get("located_in")
    if not filename or not located_in:
        return None
    candidate = library_path() / located_in / filename
    return candidate if candidate.exists() else None


def _read_supplier_spec(part_number: str, safe_rev: str) -> dict:
    """Return a structured sidecar payload for one revision.
    {
      part_number, revision, exists,
      summary_fields: { ... canonical projection (may contain nulls) },
      raw_spec_json: { ... or None },
      document_url: '/api/part-supplier-spec-file/...' or None
    }
    """
    path = _supplier_spec_path(part_number, safe_rev)
    if not path.exists():
        return {
            "part_number": part_number,
            "revision": safe_rev,
            "exists": False,
            "summary_fields": {f: None for f in _SUPPLIER_SPEC_FIELDS},
            "raw_spec_json": None,
            "document_url": None,
        }
    try:
        with open(path, encoding="utf-8-sig") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {
            "part_number": part_number,
            "revision": safe_rev,
            "exists": True,
            "summary_fields": {f: None for f in _SUPPLIER_SPEC_FIELDS},
            "raw_spec_json": None,
            "document_url": None,
            "honesty_note": "Sidecar present but unreadable.",
        }
    doc_path = _resolve_supplier_doc_path(raw)
    document_url = (
        f"/api/part-supplier-spec-file/{part_number}?revision={safe_rev}"
        if doc_path is not None else None
    )
    # image_url normalises both PDF and image documents to a single image
    # endpoint the frontend can render with <img> + zoom controls. PDFs
    # are rendered server-side to a stacked PNG by /api/part-supplier-
    # spec-image; images are streamed through the same endpoint as-is.
    # That eliminates the browser PDF-plugin dependency that left
    # iframe-embedded PDFs as blank white panes.
    image_url = (
        f"/api/part-supplier-spec-image/{part_number}?revision={safe_rev}"
        if doc_path is not None else None
    )
    return {
        "part_number": part_number,
        "revision": safe_rev,
        "exists": True,
        "summary_fields": _normalise_supplier_summary(raw),
        "raw_spec_json": raw,
        "document_url": document_url,
        "image_url": image_url,
    }


@app.get("/api/part-supplier-spec/{part_number}")
async def get_part_supplier_spec(part_number: str, revision: str = Query(...)):
    safe_pn = re.sub(r"[^\w\-]", "", part_number)
    safe_rev = _normalize_revision_letter(revision)
    if not safe_pn or not safe_rev:
        raise HTTPException(status_code=400, detail="Invalid part number or revision")
    return _read_supplier_spec(safe_pn, safe_rev)


@app.get("/api/part-supplier-spec-compare/{part_number}")
async def get_part_supplier_spec_compare(
    part_number: str,
    revA: str = Query(...),
    revB: str = Query(...),
):
    safe_pn = re.sub(r"[^\w\-]", "", part_number)
    safe_a = _normalize_revision_letter(revA)
    safe_b = _normalize_revision_letter(revB)
    if not safe_pn or not safe_a or not safe_b:
        raise HTTPException(status_code=400, detail="Invalid part number or revision")
    spec_a = _read_supplier_spec(safe_pn, safe_a)
    spec_b = _read_supplier_spec(safe_pn, safe_b)

    diff_fields = []
    sa = spec_a["summary_fields"] or {}
    sb = spec_b["summary_fields"] or {}
    for field in _SUPPLIER_SPEC_FIELDS:
        a_val = sa.get(field)
        b_val = sb.get(field)
        if a_val is None and b_val is None:
            status = "missing"
        elif a_val is None or b_val is None:
            status = "missing"
        elif str(a_val).strip().lower() == str(b_val).strip().lower():
            status = "same"
        else:
            status = "changed"
        diff_fields.append({
            "field": field,
            "revA": a_val,
            "revB": b_val,
            "status": status,
        })

    honesty_note = (
        "Supplier-side differences are review items and do not by themselves "
        "prove a design change. A 'changed' field here means the captured "
        "supplier evidence differs across revisions; a 'missing' field means "
        "one or both sides have no supplier-spec sidecar for this part."
    )

    return {
        "part_number": safe_pn,
        "revA": safe_a,
        "revB": safe_b,
        "revA_spec": spec_a,
        "revB_spec": spec_b,
        "diff_fields": diff_fields,
        "honesty_note": honesty_note,
    }


@app.get("/api/part-supplier-spec-file/{part_number}")
async def get_part_supplier_spec_file(part_number: str, revision: str = Query(...)):
    safe_pn = re.sub(r"[^\w\-]", "", part_number)
    safe_rev = _normalize_revision_letter(revision)
    if not safe_pn or not safe_rev:
        raise HTTPException(status_code=400, detail="Invalid part number or revision")
    sidecar_path = _supplier_spec_path(safe_pn, safe_rev)
    if not sidecar_path.exists():
        raise HTTPException(status_code=404, detail=f"No supplier spec sidecar for {safe_pn} rev {safe_rev}")
    try:
        with open(sidecar_path, encoding="utf-8-sig") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        raise HTTPException(status_code=500, detail="Sidecar unreadable")
    doc_path = _resolve_supplier_doc_path(raw)
    if doc_path is None:
        raise HTTPException(status_code=404, detail=f"No supplier document on disk for {safe_pn} rev {safe_rev}")
    # Pick a sensible content-type from the suffix.
    suffix = doc_path.suffix.lower()
    media_type = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
    return FileResponse(str(doc_path), media_type=media_type, filename=doc_path.name)


_SUPPLIER_PDF_RENDER_MAX_OUTPUT_PIXELS = 28_000_000  # ~84 MB RGB canvas
_SUPPLIER_PDF_RENDER_CACHE_MAX_ITEMS = 12
_SUPPLIER_PDF_RENDER_CACHE_MAX_BYTES = 24 * 1024 * 1024


def _render_supplier_pdf_pages_to_png_bytes(pdf_path: Path, dpi: int = 150) -> bytes:
    """Render every page of a supplier PDF stacked vertically into a single
    PNG. Returns raw PNG bytes. Caller is responsible for caching / serving.

    150 dpi is the same default used by the assembly-drawing PNG renderer
    elsewhere in this module — readable on screen, ~200-500 KB per page,
    scales naturally under client-side zoom on the canvas.
    """
    import fitz  # PyMuPDF
    from PIL import Image
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    with fitz.open(str(pdf_path)) as doc:
        if doc.page_count <= 0:
            raise HTTPException(status_code=500, detail="PDF rendered zero pages")

        # Pre-compute the final canvas size from page boxes so we can render
        # one page at a time rather than holding every full-size page image in
        # memory simultaneously.
        sep_height = 4
        sep_color = (40, 40, 40)
        page_sizes = []
        width = 0
        total_h = 0
        for page in doc:
            page_w = int(round(page.rect.width * zoom))
            page_h = int(round(page.rect.height * zoom))
            page_sizes.append((page_w, page_h))
            width = max(width, page_w)
            total_h += page_h
        total_h += sep_height * (len(page_sizes) - 1)

        total_pixels = width * total_h
        if total_pixels > _SUPPLIER_PDF_RENDER_MAX_OUTPUT_PIXELS:
            raise HTTPException(
                status_code=413,
                detail=(
                    "Supplier PDF too large to render in-app at this zoom. "
                    "Use the original document link instead."
                ),
            )

        canvas = Image.new("RGB", (width, total_h), (255, 255, 255))
        y = 0
        for page_index, page in enumerate(doc):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            # Center horizontally if this page is narrower than the widest.
            x = (width - img.width) // 2
            canvas.paste(img, (x, y))
            y += img.height
            if page_index + 1 < len(page_sizes):
                sep = Image.new("RGB", (width, sep_height), sep_color)
                canvas.paste(sep, (0, y))
                y += sep_height
            img.close()

    buf = io.BytesIO()
    canvas.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# Small byte-bounded in-process cache for rendered supplier PDFs. This keeps
# repeat modal opens fast without letting one unexpectedly large document stay
# resident forever.
_SUPPLIER_PDF_RENDER_CACHE: "OrderedDict[tuple, bytes]" = OrderedDict()
_SUPPLIER_PDF_RENDER_CACHE_BYTES = 0


def _supplier_pdf_cache_get(cache_key: tuple):
    cached = _SUPPLIER_PDF_RENDER_CACHE.get(cache_key)
    if cached is None:
        return None
    _SUPPLIER_PDF_RENDER_CACHE.move_to_end(cache_key)
    return cached


def _supplier_pdf_cache_put(cache_key: tuple, payload: bytes):
    global _SUPPLIER_PDF_RENDER_CACHE_BYTES
    if cache_key in _SUPPLIER_PDF_RENDER_CACHE:
        old = _SUPPLIER_PDF_RENDER_CACHE.pop(cache_key)
        _SUPPLIER_PDF_RENDER_CACHE_BYTES -= len(old)
    _SUPPLIER_PDF_RENDER_CACHE[cache_key] = payload
    _SUPPLIER_PDF_RENDER_CACHE_BYTES += len(payload)
    while (
        len(_SUPPLIER_PDF_RENDER_CACHE) > _SUPPLIER_PDF_RENDER_CACHE_MAX_ITEMS
        or _SUPPLIER_PDF_RENDER_CACHE_BYTES > _SUPPLIER_PDF_RENDER_CACHE_MAX_BYTES
    ):
        _, evicted = _SUPPLIER_PDF_RENDER_CACHE.popitem(last=False)
        _SUPPLIER_PDF_RENDER_CACHE_BYTES -= len(evicted)


@app.get("/api/part-supplier-spec-image/{part_number}")
async def get_part_supplier_spec_image(
    part_number: str,
    revision: str = Query(...),
    dpi: int = Query(150),
):
    """Serve the supplier document as a PNG image regardless of source kind.

    Why: embedded PDF iframes show as blank white panes in some browser
    configurations (no PDF plugin, headless contexts, custom security
    profiles). Rendering server-side via PyMuPDF makes the modal work
    everywhere AND lets the frontend drive a real zoom control with
    plain CSS scaling on the resulting <img>.

    Image documents (.png, .jpg, etc.) are streamed through unchanged.
    """
    safe_pn = re.sub(r"[^\w\-]", "", part_number)
    safe_rev = _normalize_revision_letter(revision)
    if not safe_pn or not safe_rev:
        raise HTTPException(status_code=400, detail="Invalid part number or revision")
    # Clamp dpi: too low is unreadable; too high blows up memory.
    dpi = max(72, min(int(dpi), 300))

    sidecar_path = _supplier_spec_path(safe_pn, safe_rev)
    if not sidecar_path.exists():
        raise HTTPException(status_code=404, detail=f"No supplier spec sidecar for {safe_pn} rev {safe_rev}")
    try:
        with open(sidecar_path, encoding="utf-8-sig") as f:
            raw = json.load(f)
    except (json.JSONDecodeError, OSError):
        raise HTTPException(status_code=500, detail="Sidecar unreadable")
    doc_path = _resolve_supplier_doc_path(raw)
    if doc_path is None:
        raise HTTPException(status_code=404, detail=f"No supplier document on disk for {safe_pn} rev {safe_rev}")

    suffix = doc_path.suffix.lower()
    if suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        media_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }[suffix]
        return FileResponse(str(doc_path), media_type=media_type, filename=doc_path.name)

    if suffix != ".pdf":
        raise HTTPException(status_code=415, detail=f"Unsupported supplier document type: {suffix}")

    cache_key = (safe_pn, safe_rev, dpi)
    cached = _supplier_pdf_cache_get(cache_key)
    if cached is None:
        try:
            cached = _render_supplier_pdf_pages_to_png_bytes(doc_path, dpi=dpi)
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"[supplier-spec-image] render failed for {safe_pn} rev {safe_rev}: {exc}")
            raise HTTPException(status_code=500, detail=f"PDF render failed: {exc}")
        _supplier_pdf_cache_put(cache_key, cached)
    return Response(content=cached, media_type="image/png")


# ---------- Drawing Revision Diff ----------

@app.get("/api/drawing-revisions/{part_number}")
async def get_drawing_revisions(part_number: str):
    """List revisions that have drawing maps available for comparison."""
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")

    revisions = _list_drawing_compare_revisions(safe_pn)
    return {"revisions": revisions, "part_number": safe_pn}


@app.get("/api/drawing-diff/{part_number}")
async def get_drawing_diff(
    part_number: str,
    revA: str = Query(...),
    revB: str = Query(...),
):
    """Compare two drawing map revisions and return structured diff.

    Returns the full compare artifact (contract v1.0) with view matching,
    annotation diff, sheet metadata diff, projected model delta, and verdicts.
    """
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    safe_a = re.sub(r'[^\w]', '', revA)
    safe_b = re.sub(r'[^\w]', '', revB)
    if not safe_pn or not safe_a or not safe_b:
        raise HTTPException(status_code=400, detail="Invalid part number or revision")

    map_a = _load_drawing_compare_map_revision(safe_pn, safe_a)
    map_b = _load_drawing_compare_map_revision(safe_pn, safe_b)

    if map_a is None:
        raise HTTPException(status_code=404, detail=f"Drawing map not found for rev {safe_a}")
    if map_b is None:
        raise HTTPException(status_code=404, detail=f"Drawing map not found for rev {safe_b}")

    # Load geometry diff if available (for projected model delta)
    geometry_diff = None
    geom_cache = _part_root_dir(safe_pn) / "geometry_diff" / f"{safe_a}_vs_{safe_b}" / "diff_result.json"
    if geom_cache.exists():
        try:
            with open(geom_cache, encoding="utf-8-sig") as f:
                geometry_diff = json.load(f)
        except Exception:
            logger.warning("Failed to load geometry diff cache: %s", geom_cache)

    # Load part JSONs for bbox center (optional)
    part_json_a = _load_part_json(safe_pn, safe_a)
    part_json_b = _load_part_json(safe_pn, safe_b)

    from ai_inspector.comparison.drawing_differ import compute_drawing_diff
    result = compute_drawing_diff(
        drawing_map_a=map_a,
        drawing_map_b=map_b,
        geometry_diff=geometry_diff,
        part_json_a=part_json_a,
        part_json_b=part_json_b,
    )
    result["partNumber"] = safe_pn
    result["revA"] = safe_a
    result["revB"] = safe_b

    # Load per-revision highlight boxes for overlay geometry
    result["highlightBoxesA"] = _load_highlight_boxes(safe_pn, safe_a)
    result["highlightBoxesB"] = _load_highlight_boxes(safe_pn, safe_b)

    # Strip internal fields before sending to frontend
    vi = result.get("viewIdentity", {})
    vi.pop("_viewsA", None)
    vi.pop("_viewsB", None)

    return result


def _load_part_json(part_number: str, revision: str) -> Optional[dict]:
    """Load part JSON for a specific revision, with root fallback."""
    safe_pn = part_number
    safe_rev = revision

    # Revision-specific
    rev_path = _resolve_part_asset(safe_pn, f"rev{safe_rev}", f"{safe_pn}.json")
    if rev_path is not None:
        try:
            with open(rev_path, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            pass

    # Root fallback
    root_path = library_path() / f"{safe_pn}.json"
    if root_path.exists():
        try:
            with open(root_path, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            pass

    return None


def _load_highlight_boxes(part_number: str, revision: str) -> Optional[dict]:
    """Load highlight boxes for a specific revision, with root fallback."""
    safe_pn = part_number
    safe_rev = revision
    filename = f"{safe_pn}_highlight_boxes.json"

    # Revision-specific
    rev_path = _resolve_part_asset(safe_pn, f"rev{safe_rev}", filename)
    if rev_path is not None:
        try:
            with open(rev_path, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            pass

    # Root fallback
    root_path = library_path() / filename
    if root_path.exists():
        try:
            with open(root_path, encoding="utf-8-sig") as f:
                return json.load(f)
        except Exception:
            pass

    return None


def _is_assembly_drawing_number(part_number: str) -> bool:
    """True when the drawing number corresponds to a loaded assembly."""
    return part_number in assembly_profiles


def _assembly_drawing_revision_dir(part_number: str, revision: str) -> Path:
    return library_path("assemblies") / part_number / f"rev{revision}"


def _load_drawing_compare_map_revision(part_number: str, revision: str) -> Optional[dict]:
    """Load a revisioned drawing map from parts or assembly revision folders."""
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    safe_rev = re.sub(r'[^\w]', '', revision)
    if not safe_pn or not safe_rev:
        return None

    if _is_assembly_drawing_number(safe_pn):
        map_path = _assembly_drawing_revision_dir(safe_pn, safe_rev) / f"{safe_pn}_drawing_map.json"
        if map_path.exists():
            with open(map_path, "r", encoding="utf-8-sig") as handle:
                raw_data = json.load(handle)
            normalized = normalize_drawing_map(raw_data, part_number=safe_pn)
            normalized["sourcePath"] = str(map_path)
            normalized["revision"] = safe_rev
            return normalized

    filename = f"{safe_pn}_drawing_map.json"
    part_map = _resolve_part_asset(safe_pn, f"rev{safe_rev}", filename)
    if part_map is not None:
        with open(part_map, "r", encoding="utf-8-sig") as handle:
            raw_data = json.load(handle)
        normalized = normalize_drawing_map(raw_data, part_number=safe_pn)
        normalized["sourcePath"] = str(part_map)
        normalized["revision"] = safe_rev
        return normalized

    return load_drawing_map_revision(safe_pn, safe_rev, LIBRARY_DIR)


def _list_drawing_compare_revisions(part_number: str) -> List[str]:
    """List drawing compare revisions from parts or assembly revision folders."""
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    if not safe_pn:
        return []

    revisions = list_drawing_map_revisions(safe_pn, LIBRARY_DIR)
    filename = f"{safe_pn}_drawing_map.json"
    part_root = _part_root_dir(safe_pn)
    nested_found = []
    if part_root.exists() and part_root.is_dir():
        for d in sorted(part_root.iterdir()):
            if d.is_dir() and d.name.lower().startswith("rev") and (d / filename).exists():
                nested_found.append(d.name[3:])
    if len(nested_found) >= 2:
        return nested_found
    if len(revisions) >= 2:
        return revisions

    if _is_assembly_drawing_number(safe_pn):
        assy_dir = library_path("assemblies") / safe_pn
        found = []
        if assy_dir.exists() and assy_dir.is_dir():
            for d in sorted(assy_dir.iterdir()):
                if not d.is_dir() or not d.name.lower().startswith("rev"):
                    continue
                rev_label = d.name[3:]
                has_map = (d / f"{safe_pn}_drawing_map.json").exists()
                has_pdf = (d / f"{safe_pn}.PDF").exists() or (d / f"{safe_pn}.pdf").exists()
                if has_map or has_pdf:
                    found.append(rev_label)
        if found:
            return found

    return revisions


@app.get("/api/drawing-render/{part_number}")
async def get_drawing_render(part_number: str, revision: str = Query(...)):
    """Serve a revision-specific rendered drawing image (raster only).

    Looks for PNG/JPG renders at parts/{pn}/rev{X}/{pn}_drawing.{ext}.
    PDF is excluded because the compare UI renders into <img> tags.
    Returns 404 if no raster render exists (frontend falls back to the
    uploaded drawing).
    """
    safe_pn = re.sub(r'[^\w\-]', '', part_number)
    safe_rev = re.sub(r'[^\w]', '', revision)
    if not safe_pn or not safe_rev:
        raise HTTPException(status_code=400, detail="Invalid part number or revision")

    if _is_assembly_drawing_number(safe_pn):
        base_dir = _assembly_drawing_revision_dir(safe_pn, safe_rev)
        for candidate in (base_dir / f"{safe_pn}.PDF", base_dir / f"{safe_pn}.pdf"):
            if candidate.exists():
                import fitz

                with fitz.open(candidate) as doc:
                    if doc.page_count < 1:
                        raise HTTPException(status_code=404, detail=f"Empty assembly drawing for {part_number} rev {revision}")
                    pix = doc.load_page(0).get_pixmap(dpi=150, alpha=False)
                    return Response(content=pix.tobytes("png"), media_type="image/png")

    base_dir = _part_rev_dir(safe_pn, safe_rev)
    # Raster only — PDF excluded (can't render in <img>)
    for ext, media in [("png", "image/png"), ("jpg", "image/jpeg")]:
        render_path = base_dir / f"{safe_pn}_drawing.{ext}"
        if render_path.exists():
            return FileResponse(path=str(render_path), media_type=media)

    raise HTTPException(status_code=404, detail=f"No drawing render for {part_number} rev {revision}")


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

        raw_ctx = request.inspection_context or {}
        ctx = normalize_agent_context(raw_ctx)["flat"]
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

        # Phase 2 telemetry: time + record. Re-raise so the outer
        # try/except keeps its HTTP-error shape.
        _model = "claude-sonnet-4-5-20250929"
        _agent_type = getattr(request, "agent_type", None) or "none"
        with time_block() as _elapsed_ms:
            try:
                response = client.messages.create(
                    model=_model,
                    max_tokens=256,
                    messages=[{
                        "role": "user",
                        "content": f"{active_prompt}\n\n--- INSPECTION ISSUES ---\n{context_text}"
                    }],
                )
            except Exception as _ex:
                _s, _e = classify_exception_status(_ex)
                record_anthropic_call(
                    model=_model, response=None, latency_ms=_elapsed_ms(),
                    status=_s, errorType=_e,
                    route="/api/agent/suggestions", workflow="agent_suggestions",
                    agentType=_agent_type,
                )
                raise

        record_anthropic_call(
            model=_model, response=response, latency_ms=_elapsed_ms(),
            route="/api/agent/suggestions", workflow="agent_suggestions",
            agentType=_agent_type,
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
    "hidden line": "Line_Conventions", "centerline": "Line_Conventions",
    "center line": "Line_Conventions", "line type": "Line_Conventions",
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

ASSEMBLY_COMPARE_CHAT_PROMPT_APPENDIX = """

================================================================
ASSEMBLY COMPARE — CHAT-FIRST ACTION REGISTRY
================================================================
When assembly revision compare is available for the current assembly
(compare_mode_available = true), you SHOULD answer in plain prose AND
additionally emit a [UI_ACTIONS] block immediately after the prose for
any concrete viewer/UI action the user is asking for. If Assembly >
Compare is not open yet, the action block should open it first. When
the user is already on Assembly > Compare, keep using the same
[UI_ACTIONS] path. The prose stays human-readable; the action block is
a deterministic contract for the frontend.

Format (strict JSON inside the block, no comments, no trailing commas):
[UI_ACTIONS]
{"workspace":"assembly_compare","actions":[ {action_obj_1}, ... ]}
[/UI_ACTIONS]

Supported action types (use only these names):
- open_workspace        : { "type":"open_workspace", "tab":"assembly", "subtab":"compare" }
- set_compare_revisions : { "type":"set_compare_revisions", "revA":"A", "revB":"B", "run_compare": true }
- explode               : { "type":"explode", "side":"A|B|both", "enabled": true|false }
- focus                 : { "type":"focus", "side":"A|B|both", "scope":{...} }   (dim non-targets, no spatial move)
- highlight             : { "type":"highlight", "side":"A|B|both", "scope":{...} } (color/emissive only)
- extract               : { "type":"extract", "side":"A|B|both", "scope":{...}, "camera":"keep" } (spatial pull-out)
- select_bom_rows       : { "type":"select_bom_rows", "mode":"replace|add|remove|clear", "keys":[...], "primary":"...", "open_drawer": true|false }
- open_supplier_spec    : { "type":"open_supplier_spec", "part_number":"1040017", "revision":"A" }
- compare_supplier_specs: { "type":"compare_supplier_specs", "part_number":"1040017", "revA":"A", "revB":"B" }
- clear_compare_overlays: { "type":"clear_compare_overlays" }

Scope object for focus/highlight/extract:
  { "procurement":"purchased|custom",
    "diff_status":"changed",
    "part_numbers":["1030031"],
    "bom_keys":["6000302"] }
At least one field must be set. Multiple fields union together.

Vocabulary semantics (specifically for Assembly > Compare):
- "highlight" — color/emissive glow only. Does NOT isolate or move geometry.
- "focus"    — dim non-targets so the user can read the targets clearly.
               No spatial movement.
- "explode"  — per-side. Use SolidWorks explode steps for that revision.
- "extract"  — pull a target subset spatially out of the assembly. Dims
               non-targets. Pairs well with row selection.
- "show me the changed parts" — only proven changed parts (added /
  removed / qty_changed). substitution_unverified is NEVER counted as
  changed. If 6000302 has no proven changes, say so honestly and
  optionally redirect the user to the supplier review items.
- "show me the purchased parts" / "custom parts" — that procurement
  classification only.
- "compare the supplier specs for X" — emit compare_supplier_specs
  against the current revA/revB. Sage MUST present supplier-side
  differences as REVIEW ITEMS, not as proven design changes.
- When compare_mode_available = true, prefer ui_actions over legacy
  highlight_parts / isolate_parts for Assembly Compare requests.

Honesty contract you MUST keep in prose:
- substitution_unverified is a supplier-side review item, not a proven
  design change.
- Use phrases like "supplier-side review item",
  "vendor-sensitive purchased hardware", or
  "possible sourced-component substitution".
- Do NOT say "proven changed part" unless the BOM compare actually has
  a row with diff_status in {added, removed, qty_changed}.
- Missing-side honesty: if a side has no spec, say "missing on this
  side" — do not invent fields.

Examples:

User: "Show me the custom parts"
Sage prose: short answer about the custom rows on this assembly.
[UI_ACTIONS]
{"workspace":"assembly_compare","actions":[
  {"type":"open_workspace","tab":"assembly","subtab":"compare"},
  {"type":"select_bom_rows","mode":"replace","keys":["1030031","6000302"],"primary":"1030031","open_drawer":true},
  {"type":"focus","side":"both","scope":{"procurement":"custom"}}
]}
[/UI_ACTIONS]

User: "Explode Rev A and Rev B"
[UI_ACTIONS]
{"workspace":"assembly_compare","actions":[
  {"type":"explode","side":"both","enabled":true}
]}
[/UI_ACTIONS]

User: "Extract the purchased parts"
[UI_ACTIONS]
{"workspace":"assembly_compare","actions":[
  {"type":"extract","side":"both","scope":{"procurement":"purchased"},"camera":"keep"}
]}
[/UI_ACTIONS]

User: "Compare the screw supplier specs for Rev A and Rev B"
Prose: "These are vendor-sensitive review items, not proven design changes — see the side-by-side compare for the captured supplier evidence."
[UI_ACTIONS]
{"workspace":"assembly_compare","actions":[
  {"type":"compare_supplier_specs","part_number":"1040017","revA":"A","revB":"B"}
]}
[/UI_ACTIONS]

The block is ADDITIVE. You may also emit the legacy markers (HIGHLIGHT_PARTS,
EXPLODE_LEVEL, etc.) when they are more natural — both pipelines run.
But for chat commands that have a direct action mapping above, prefer
[UI_ACTIONS] because it is explicit and deterministic.
"""

AGENT_PROMPTS = {
    "inspector": AGENT_SYSTEM_PROMPT,
    "deviation-analyst": DEVIATION_ANALYST_PROMPT + ASSEMBLY_COMPARE_CHAT_PROMPT_APPENDIX,
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
        {"name": "ui_actions", "description": "Assembly Compare chat-first action registry — workspace + ordered list of declarative UI actions (open_workspace, set_compare_revisions, explode, focus, highlight, extract, select_bom_rows, open_supplier_spec, compare_supplier_specs, clear_compare_overlays).", "args": {"workspace": "string", "actions": "list of action objects"}},
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
    # Assembly Compare chat-first action registry. Sage emits an additive
    # [UI_ACTIONS] JSON block that the frontend dispatcher unpacks into the
    # per-action handlers. Independent of the legacy markers above so the
    # chat layer can be deterministic without rewriting the existing
    # tool-call surface.
    if result.get("ui_actions"):
        calls.append({"name": "ui_actions", "args": result["ui_actions"]})
    return calls


# === Phase 7: Guardrail Policy Maps ===
MAX_TOOL_CALLS_PER_TURN = {
    "inspector": 4,
    # ui_actions counts as a single tool call regardless of how many actions
    # it bundles, so deviation-analyst keeps room for the legacy markers
    # AND the chat-first action block in the same turn.
    "deviation-analyst": 5,
    "parts-finder": 1,
}

MAX_TOOL_ARG_ITEMS = {
    "dim_keys": 25,
    "view_names": 12,
    "feature_ids": 30,
    "part_numbers": 30,
    "markers": 30,
    # Cap the number of actions per ui_actions block. A natural-chat
    # response should never need more than this and the cap protects
    # against runaway model output.
    "actions": 25,
}

VALID_ENUM_VALUES = {
    "animate_motion": {"action": {"start", "stop"}},
}

# Tools that require non-empty list args to be meaningful
REQUIRED_LIST_ARGS = {
    "highlight_dimensions": "dim_keys",
    "highlight_views": "view_names",
    "highlight_features": "feature_ids",
    "highlight_parts": "part_numbers",
    "isolate_parts": "part_numbers",
    "compare_parts": "markers",
    "compare_features": "markers",
}


def get_allowed_tool_names(agent_type: str) -> set:
    """Return the set of tool names allowed for this agent type."""
    specs = AGENT_TOOL_SPECS.get(agent_type, [])
    return {s["name"] for s in specs}


def _tool_signature(tc: dict) -> str:
    """Stable JSON signature for deduplication."""
    return json.dumps({"name": tc["name"], "args": tc.get("args", {})}, sort_keys=True)


def sanitize_tool_calls(tool_calls: list, agent_type: str) -> list:
    """Validate, type-check, and clamp tool calls against agent specs."""
    allowed = get_allowed_tool_names(agent_type)
    sanitized = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            logger.warning(f"[ToolGuard] Dropped non-dict tool call: {tc}")
            continue
        name = tc.get("name")
        if not name or name not in allowed:
            logger.warning(f"[ToolGuard] Dropped disallowed tool '{name}' for {agent_type}")
            continue
        args = tc.get("args")
        if not isinstance(args, dict):
            args = {}

        # List field coercion + capping
        for list_field in ("dim_keys", "view_names", "feature_ids", "part_numbers", "markers"):
            if list_field in args:
                if not isinstance(args[list_field], list):
                    args[list_field] = [args[list_field]] if args[list_field] else []
                cap = MAX_TOOL_ARG_ITEMS.get(list_field, 50)
                if len(args[list_field]) > cap:
                    logger.warning(f"[ToolGuard] Capped {list_field} from {len(args[list_field])} to {cap} in {name}")
                    args[list_field] = args[list_field][:cap]

        # Object field check
        if "values" in args and not isinstance(args["values"], dict):
            logger.warning(f"[ToolGuard] Dropped non-dict 'values' in {name}")
            args["values"] = {}

        # Numeric clamping
        if name == "set_explode_level" and "level" in args:
            try:
                args["level"] = max(0.0, min(1.0, float(args["level"])))
            except (TypeError, ValueError):
                logger.warning(f"[ToolGuard] Invalid level in set_explode_level, defaulting to 0")
                args["level"] = 0.0

        # Enum validation — drop entire tool call if invalid
        enum_invalid = False
        if name in VALID_ENUM_VALUES:
            for field, valid in VALID_ENUM_VALUES[name].items():
                if field in args and args[field] not in valid:
                    logger.warning(f"[ToolGuard] Invalid {field}='{args.get(field)}' in {name}, dropping tool call")
                    enum_invalid = True
                    break
        if enum_invalid:
            continue

        # Drop tools with empty required list args
        req_field = REQUIRED_LIST_ARGS.get(name)
        if req_field and not args.get(req_field):
            logger.warning(f"[ToolGuard] Dropped {name} with empty {req_field}")
            continue

        sanitized.append({"name": name, "args": args})
    return sanitized


def apply_tool_guardrails(tool_calls: list, agent_type: str, source: str = "unknown") -> tuple:
    """Canonical guardrail: dedupe, resolve conflicts, enforce budget.
    Returns (guarded_calls, warnings). Applied to both native and legacy paths."""
    warnings = []

    # 1. Sanitize shapes/types
    calls = sanitize_tool_calls(tool_calls, agent_type)

    # 2. Dedupe exact duplicates
    seen_sigs = set()
    deduped = []
    for tc in calls:
        sig = _tool_signature(tc)
        if sig in seen_sigs:
            warnings.append(f"deduped:{tc['name']}")
            continue
        seen_sigs.add(sig)
        deduped.append(tc)
    calls = deduped

    # 3. Resolve conflicts
    names = {tc["name"] for tc in calls}
    if "compare_parts" in names and "highlight_parts" in names:
        calls = [tc for tc in calls if tc["name"] != "highlight_parts"]
        warnings.append("conflict:highlight_parts_suppressed_by_compare_parts")
    if "isolate_parts" in names and "highlight_parts" in names:
        calls = [tc for tc in calls if tc["name"] != "highlight_parts"]
        warnings.append("conflict:highlight_parts_suppressed_by_isolate_parts")

    # 4. Truncate to budget
    max_calls = MAX_TOOL_CALLS_PER_TURN.get(agent_type, 4)
    if len(calls) > max_calls:
        warnings.append(f"truncated:{len(calls)}_to_{max_calls}")
        calls = calls[:max_calls]

    if warnings:
        logger.info(f"[ToolGuard] {source} for {agent_type}: {warnings}")

    return calls, warnings


def extract_tool_calls_from_response(text: str, agent_type: str) -> tuple:
    """Extract a <tool_calls> JSON block from the model's response text.
    Returns (cleaned_text, tool_calls_list). If no valid block found, returns (text, [])."""
    pattern = re.compile(r'<tool_calls>\s*(.*?)\s*</tool_calls>', re.DOTALL)
    match = pattern.search(text)
    if not match:
        return text, []
    json_str = match.group(1).strip()
    # Strip the block from the text
    cleaned = pattern.sub('', text).strip()
    try:
        raw = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"[ToolParse] Malformed <tool_calls> JSON for {agent_type}: {e}")
        return cleaned, []
    if not isinstance(raw, list):
        logger.warning(f"[ToolParse] <tool_calls> is not a list for {agent_type}")
        return cleaned, []
    sanitized = sanitize_tool_calls(raw, agent_type)
    if sanitized:
        logger.info(f"[ToolParse] Native tool_calls parsed for {agent_type}: {[tc['name'] for tc in sanitized]}")
    return cleaned, sanitized


def apply_tool_calls_to_legacy_result(result: dict, tool_calls: list) -> None:
    """Mirror canonical tool_calls back into legacy response fields for compatibility.
    Only sets fields that are explicitly present in tool_calls."""
    for tc in tool_calls:
        name = tc["name"]
        args = tc.get("args", {})
        if name == "run_inspection":
            result["run_inspection"] = True
        elif name == "highlight_dimensions":
            result["highlight_dimensions"] = args.get("dim_keys", [])
        elif name == "highlight_views":
            result["highlight_views"] = args.get("view_names", [])
        elif name == "highlight_features":
            result["highlight_features"] = args.get("feature_ids", [])
        elif name == "highlight_parts":
            result["highlight_parts"] = args.get("part_numbers", [])
            if args.get("camera_view"):
                result["camera_view"] = args["camera_view"]
        elif name == "isolate_parts":
            result["isolate_parts"] = args.get("part_numbers", [])
        elif name == "compare_parts":
            result["compare_parts"] = args.get("markers", [])
        elif name == "compare_features":
            result["compare_features"] = args.get("markers", [])
        elif name == "show_geometry_diff":
            result["show_geometry_diff"] = True
        elif name == "animate_motion":
            result["animate_motion"] = args.get("action", "start")
        elif name == "set_explode_level":
            result["explode_level"] = args.get("level", 0)
        elif name == "fai_fill":
            result["fai_fills"] = args.get("values", {})
        elif name == "fai_tol":
            result["fai_tol"] = args.get("values", {})


def build_tool_appendix(agent_type: str) -> str:
    """Build a compact tool appendix for the agent's system prompt."""
    specs = AGENT_TOOL_SPECS.get(agent_type, [])
    if not specs:
        return ""
    lines = [
        "",
        "",
        "TOOL CALLS",
        "When an action is needed, emit a <tool_calls> JSON block at the end of your response.",
        "",
        "Rules:",
        "- Use only the tools listed below.",
        "- Emit valid JSON only, no markdown fences.",
        "- Your normal text answer must stand on its own.",
        "- Only emit tool calls when they directly help answer the user's request.",
        "- Keep arguments minimal and specific.",
        "- Do not emit duplicate or conflicting tool calls.",
        "- Emit at most 3 tool calls unless truly necessary.",
        "- Prefer one precise tool call over several broad ones.",
        "- If no action is needed, emit no tool calls.",
        "- Do not emit highlight_parts if compare_parts or isolate_parts is the better fit.",
        "- Use <tool_calls> instead of legacy markers (HIGHLIGHT_DIMS:, RUN_INSPECTION, etc.).",
        "",
        "Format:",
        "<tool_calls>",
        '[{"name":"tool_name","args":{"key":"value"}}]',
        "</tool_calls>",
        "",
        "Available tools:",
    ]
    for spec in specs:
        args_desc = ", ".join(f'{k}: {v}' for k, v in spec["args"].items()) if spec["args"] else "none"
        lines.append(f"- {spec['name']}: {spec['description']} (args: {args_desc})")
    return "\n".join(lines)


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


# ---------- Drawing classification (Phase 1) ----------

def _compute_drawing_classification(
    part_number: Optional[str],
    drawing_map: Optional[dict] = None,
) -> dict:
    """Gather server-side signals for ``part_number`` and run the classifier.

    All signal lookups are best-effort: missing files / empty profiles fall
    through cleanly to the classifier's lower-confidence branches. The
    function never raises — a missing or invalid ``part_number`` returns a
    valid ``unknown`` classification.
    """
    safe_pn = re.sub(r'[^\w\-]', '', (part_number or '')).strip()
    if not safe_pn:
        return classify_drawing_mode(None, drawing_map=drawing_map)

    # ── has_assembly_context ──
    # True only when the part number IS itself an assembly's number (i.e.
    # registered as an assembly_profiles key). Being a *component* of some
    # assembly does NOT qualify; a component drawing is still a part drawing.
    has_assembly_context = safe_pn in assembly_profiles

    # ── has_drawing_revisions ──
    # ≥2 rev{X} subdirectories exist. For assemblies we look in assemblies/<n>/;
    # for parts in parts/<n>/. Single-revision parts don't qualify.
    if has_assembly_context:
        rev_root = library_path("assemblies") / safe_pn
    else:
        rev_root = _part_root_dir(safe_pn)
    has_drawing_revisions = False
    if rev_root.exists() and rev_root.is_dir():
        rev_dirs = [d for d in rev_root.iterdir() if d.is_dir() and d.name.lower().startswith("rev")]
        has_drawing_revisions = len(rev_dirs) >= 2

    # ── has_inspection_profile ──
    # Standard naming: 400S_Sorted_Library/<pn>.json. We check the file system
    # rather than asking the SpatialInspector so this stays cheap and
    # side-effect-free.
    has_inspection_profile = (library_path() / f"{safe_pn}.json").exists()

    # ── drawing_map ──
    # If the caller didn't pass one, try to load it from disk for richer
    # signal extraction (BOM-table detection, dimension annotations). We
    # enumerate all rev{X} subdirectories sorted alphabetically rather than
    # hardcoding revA, so a part with only revB / revC populated still
    # produces a usable drawing map. The flat-layout fallback is searched
    # last because revisioned files are the source of truth when present.
    if drawing_map is None:
        if has_assembly_context:
            rev_root_dir = library_path("assemblies") / safe_pn
            flat_fallback = library_path("assemblies") / f"{safe_pn}_drawing_map.json"
        else:
            rev_root_dir = _part_root_dir(safe_pn)
            flat_fallback = library_path() / f"{safe_pn}_drawing_map.json"

        candidates: List[Path] = []
        if rev_root_dir.exists() and rev_root_dir.is_dir():
            rev_subdirs = sorted(
                (d for d in rev_root_dir.iterdir()
                 if d.is_dir() and d.name.lower().startswith("rev")),
                key=lambda d: d.name.lower(),
            )
            for rd in rev_subdirs:
                candidates.append(rd / f"{safe_pn}_drawing_map.json")
        candidates.append(flat_fallback)

        for p in candidates:
            if p.exists():
                try:
                    with open(p, encoding='utf-8-sig') as f:
                        drawing_map = json.load(f)
                    break
                except (json.JSONDecodeError, OSError):
                    pass

    return classify_drawing_mode(
        safe_pn,
        drawing_map=drawing_map,
        has_assembly_context=has_assembly_context,
        has_drawing_revisions=has_drawing_revisions,
        has_inspection_profile=has_inspection_profile,
    )


@app.get("/api/drawing-classification/{part_number}")
async def get_drawing_classification(part_number: str):
    """Return the classification contract for ``part_number``.

    Public version of :func:`_compute_drawing_classification`. The frontend
    can call this directly when it needs the contract without going through
    the agent context flow.
    """
    safe_pn = re.sub(r'[^\w\-]', '', part_number or '').strip()
    if not safe_pn:
        raise HTTPException(status_code=400, detail="Invalid part number")
    classification = _compute_drawing_classification(safe_pn)
    return {"part_number": safe_pn, **classification}


def normalize_agent_context(ctx: dict) -> dict:
    """
    Normalize incoming inspection_context into structured attachments + flat compat.
    Phase 6: the frontend now sends attachments-only. This function fully
    reconstructs all flat keys from attachments so all server code works unchanged.
    Also accepts legacy flat payloads for backward compat.
    Returns: { 'attachments': {...structured...}, 'flat': {...all legacy keys...} }
    """
    if not ctx:
        return {"attachments": {}, "flat": {}}

    attachments = ctx.get("attachments", {})

    # Start with any non-attachments flat keys already present (legacy compat)
    flat = {k: v for k, v in ctx.items() if k != "attachments"}

    # Reconstruct ALL flat keys from structured attachments
    if attachments:
        part = attachments.get("part", {})
        drawing = attachments.get("drawing", {})
        insp = attachments.get("inspection", {})
        sel = attachments.get("selection", {})
        compare = attachments.get("compare", {})
        assembly = attachments.get("assembly", {})
        session = attachments.get("session", {})
        user = attachments.get("user", {}) or {}

        # User display name. Sales-coaching mode reads this to address the
        # user by name in the opener. Empty string when not provided —
        # the override prompt has a "if user_name is available" branch.
        if user.get("display_name"):
            flat.setdefault("user_display_name", str(user["display_name"]).strip())

        # Part
        flat.setdefault("part_number", part.get("part_number"))
        flat.setdefault("part_name", part.get("part_name"))
        if part.get("profile_features"):
            flat.setdefault("profile_features", part["profile_features"])
        if part.get("description"):
            flat.setdefault("part_description", part["description"])
        if part.get("view_expectations"):
            flat.setdefault("view_expectations", part["view_expectations"])
        if part.get("focused_feature"):
            flat.setdefault("focused_feature", part["focused_feature"])
        if part.get("available_cad_features"):
            flat.setdefault("available_cad_features", part["available_cad_features"])

        # Drawing
        flat.setdefault("has_drawing_file", drawing.get("has_drawing_file", False))
        if drawing.get("available_views"):
            flat.setdefault("available_views", drawing["available_views"])

        # Inspection
        flat.setdefault("has_part_number", bool(part.get("part_number")))
        flat.setdefault("inspection_in_progress", insp.get("in_progress", False))
        flat.setdefault("inspection_can_run", insp.get("can_run", False))
        if insp.get("gap_summary"):
            flat.setdefault("gap_summary", insp["gap_summary"])
            flat.setdefault("completeness_score", insp.get("completeness_score"))
        if insp.get("findings"):
            flat.setdefault("findings", insp["findings"])
        if insp.get("representation_gaps"):
            flat.setdefault("representation_gaps", insp["representation_gaps"])
        if insp.get("critical_issues"):
            flat.setdefault("critical_issues", insp["critical_issues"])
        if insp.get("fai_characteristics"):
            flat.setdefault("fai_characteristics", insp["fai_characteristics"])

        # Selection
        if sel.get("dimensions"):
            flat.setdefault("selected_dimensions", sel["dimensions"])
        if sel.get("available_dimensions"):
            flat.setdefault("available_dimensions", sel["available_dimensions"])
        if sel.get("parts"):
            flat.setdefault("selected_parts", sel["parts"])
        if sel.get("available_parts"):
            flat.setdefault("available_parts", sel["available_parts"])

        # Compare
        if compare.get("geometry_diff"):
            flat.setdefault("geometry_diff", compare["geometry_diff"])
        if compare.get("assembly_compare_available"):
            flat.setdefault("compare_mode_available", True)
            flat.setdefault("compare_mode_active", compare.get("assembly_compare_active", False))
        if compare.get("revision_diff"):
            flat.setdefault("revision_diff", compare["revision_diff"])
        if compare.get("part_feature_diff"):
            flat.setdefault("part_feature_diff", compare["part_feature_diff"])
            flat.setdefault("part_compare_active", compare.get("part_compare_active", False))
        if compare.get("part_revisions"):
            flat.setdefault("part_revisions", compare["part_revisions"])

        # Assembly
        if assembly.get("mate_relationships"):
            flat.setdefault("mate_relationships", assembly["mate_relationships"])
        if assembly.get("configurations"):
            flat.setdefault("assembly_configurations", assembly["configurations"])
        if assembly.get("active_config"):
            flat.setdefault("active_assembly_config", assembly["active_config"])
        if assembly.get("part_properties"):
            flat.setdefault("part_properties", assembly["part_properties"])
        if assembly.get("explode_steps"):
            flat.setdefault("explode_steps", assembly["explode_steps"])
            flat.setdefault("part_color_legend", assembly.get("part_color_legend"))

        # Session
        if session.get("paused_walkthrough"):
            flat.setdefault("paused_walkthrough", session["paused_walkthrough"])

    # ── Drawing classification injection (Phase 2) ──
    # If the frontend already populated the classification fields directly on
    # attachments.drawing (Phase 3 cache hit), reuse them as-is. Otherwise
    # compute server-side from the part number. Either way the contract ends
    # up under both attachments.drawing AND flat keys so legacy code paths
    # that read flat fields work without touching the structured tree.
    pn_for_class = flat.get("part_number")
    drawing_attach = (attachments.get("drawing") if attachments else None) or {}
    frontend_supplied = drawing_attach.get("drawing_type") is not None

    classification = None
    if frontend_supplied:
        # Trust what the frontend sent — don't recompute and don't second-guess.
        classification = {
            "drawing_type": drawing_attach.get("drawing_type"),
            "workflow_mode": drawing_attach.get("workflow_mode"),
            "drawing_capabilities": drawing_attach.get("drawing_capabilities") or {},
            "classification_reasons": drawing_attach.get("classification_reasons") or [],
        }
    elif pn_for_class:
        try:
            classification = _compute_drawing_classification(pn_for_class)
        except Exception:
            classification = None

    if classification:
        # Mutate the structured tree so downstream code that reads attachments
        # gets the contract too. We attach under "drawing" because the contract
        # is about the drawing being viewed, not the part itself.
        if attachments is None:
            attachments = {}
        d = attachments.get("drawing")
        if d is None:
            d = {}
            attachments["drawing"] = d
        d["drawing_type"] = classification.get("drawing_type")
        d["workflow_mode"] = classification.get("workflow_mode")
        d["drawing_capabilities"] = classification.get("drawing_capabilities")
        d["classification_reasons"] = classification.get("classification_reasons")
        # Flat compat fields. setdefault so legacy callers that already set
        # them upstream win.
        flat.setdefault("drawing_type", classification.get("drawing_type"))
        flat.setdefault("drawing_workflow_mode", classification.get("workflow_mode"))
        flat.setdefault("drawing_capabilities", classification.get("drawing_capabilities"))
        flat.setdefault("drawing_classification_reasons", classification.get("classification_reasons"))

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

    # ── DRAWING MODE (Phase 2) ──
    # Render the classification near the top so the agent sees the workflow
    # contract before any downstream fields. Preferred / deprioritized actions
    # are derived directly from drawing_capabilities so the agent doesn't have
    # to infer them from raw booleans.
    dt = inspection_context.get("drawing_type")
    wm = inspection_context.get("drawing_workflow_mode")
    caps = inspection_context.get("drawing_capabilities") or {}
    reasons = inspection_context.get("drawing_classification_reasons") or []
    if dt and dt != "unknown":
        # Capability-to-action mapping, kept here so the prompt text stays
        # in sync with the capability matrix in classification/drawing_mode.py.
        _CAP_TO_ACTION = {
            "bom_compare":        "highlight_bom_rows / switch_drawing_revision",
            "part_isolation":     "highlight_parts / isolate_parts",
            "assembly_compare":   "assembly_revision_compare",
            "dimension_overlay":  "dimension_overlay / dimension_highlighting",
            "feature_overlay":    "feature_overlay",
            "fai_mode":           "fai_table / fai_balloons",
        }
        preferred = [_CAP_TO_ACTION[k] for k, v in caps.items() if v and k in _CAP_TO_ACTION]
        deprioritized = [_CAP_TO_ACTION[k] for k, v in caps.items() if (not v) and k in _CAP_TO_ACTION]
        dm_lines = ["[DRAWING MODE]"]
        dm_lines.append(f"Type: {dt}")
        if wm:
            dm_lines.append(f"Workflow: {wm}")
        if preferred:
            dm_lines.append("Preferred actions: " + ", ".join(preferred))
        if deprioritized:
            dm_lines.append("Deprioritize: " + ", ".join(deprioritized))
        if reasons:
            dm_lines.append("Reasons: " + "; ".join(reasons))
        parts.append("\n".join(dm_lines))

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
            color_name = sp.get("color_name", "")
            label = pn
            if desc:
                label += f" \u2014 {desc}"
            if color_name:
                label += f" [{color_name}]"
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


def _is_walkthrough_message(message: str) -> bool:
    """Detect guided assembly walkthrough requests that need legacy narration markers."""
    msg_lower = (message or "").lower()
    return any(kw in msg_lower for kw in ["walk", "tour", "narrat", "walkthrough"])


# ───────────────────────── Sales-coaching mode ─────────────────────────
# Engineering-grounded sales coaching is a SEPARATE narration mode from the
# part-by-part walkthrough. The intent detector and application extractor
# below feed a dedicated SALES_COACHING_OUTPUT_OVERRIDE in the chat
# endpoint. Walkthrough detection runs FIRST so the existing prompt
# "Walk me through this assembly part by part" keeps using the legacy
# walkthrough override unchanged.

_SALES_COACHING_PATTERNS = (
    "coach me to sell",
    "how do i sell",
    "sales walkthrough",
    "sales coach",
    "pitch this",
    "pitch the",
    "help me explain this machine",
    "help me explain this robot",
    "sell this robot",
    "sell this machine",
)

_SALES_APPLICATIONS = {
    "machine tending":     ["machine tending", "cnc tending", "load cnc", "unload cnc"],
    "welding":             ["welding", "spot welding", "weld cell", "large frames"],
    "press tending":       ["press tending", "press loading", "press unloading", "press automation"],
    "material handling":   ["material handling", "heavy parts", "part transfer", "transfer parts"],
    "palletizing":         ["palletizing", "end of line", "stacking"],
    "deburring/grinding":  ["deburring", "grinding", "polishing", "finishing"],
}


def _is_sales_coaching_message(message: str) -> bool:
    """True when the user is asking Sage to coach them on selling the
    machine. Phrasing patterns from the spec; case-insensitive substring
    match keeps the detector forgiving of natural-chat variations."""
    msg = (message or "").lower()
    return any(p in msg for p in _SALES_COACHING_PATTERNS)


def _extract_sales_application(message: str) -> str:
    """Return the canonical sales application name when the message
    contains an alias for one. Returns '' when no application phrase
    is present — caller uses that to trigger the clarification path
    instead of generating a generic pitch."""
    msg = (message or "").lower()
    for app_name, aliases in _SALES_APPLICATIONS.items():
        if any(alias in msg for alias in aliases):
            return app_name
    return ""


_SALES_COACHING_CLARIFICATION = (
    "What application are you selling it into: machine tending, welding, "
    "press tending, material handling, palletizing, or deburring/grinding?"
)


def _sales_coaching_override(application: str, user_name: str = "") -> str:
    """System-prompt override appended for sales-coaching responses.

    Tone refinement (2026-05-06): rewrites the previous spec-heavy
    monologue into a "warm technical coach speaking to the user"
    style. Strict anti-overclaim list keeps the model from inventing
    payload, reach, ROI, cycle-time, tolerance, duty-cycle, material,
    or compatibility values that are not present in the assembly /
    inspection context. Segment-length cap (45 words / 1-2 sentences /
    one engineering point) prevents the brochure-monologue feel.
    """
    user_name = (user_name or "").strip()
    if user_name:
        name_tone_line = (
            f"- The user's name is '{user_name}'. Use it ONCE naturally in the "
            "opening segment, and OPTIONALLY ONCE near the close. Do NOT "
            "repeat the name in every segment.\n"
            f"  Example opener: \"{user_name}, here is how I would position this for {application}.\"\n"
        )
    else:
        name_tone_line = (
            "- The user's display name is not available. Open with \"Here is how I would "
            "position this for...\" — never invent a name.\n"
        )

    return (
        "\n\n"
        "SALES_COACHING OUTPUT OVERRIDE\n\n"
        "You are Sage, an engineering-grounded sales coach speaking directly to the user.\n"
        "You are coaching the user, not delivering a generic marketing script.\n\n"
        f"Target application: {application}\n"
        f"User name (may be empty): \"{user_name}\"\n\n"
        "Tone:\n"
        "- Speak like a senior application engineer coaching a colleague before a customer meeting.\n"
        "- Warm, direct, confident, practical. Coach-like, not brochure-like.\n"
        "- Talk WITH the user, not AT the user. Use phrases like:\n"
        "  - \"Here is how I would position this...\"\n"
        "  - \"The customer cares about this because...\"\n"
        "  - \"If they push back, your answer is...\"\n"
        "  - \"Do not lead with the part — lead with the production problem.\"\n"
        "- Avoid hype words: \"proven\", \"workhorse\", \"dominates\", \"guaranteed\", \"unmatched\",\n"
        "  unless directly supported by context.\n"
        + name_tone_line +
        "\n"
        "Hard grounding rules (do NOT violate):\n"
        "- Use ONLY facts present in the CAD, assembly, mate, part, and inspection context.\n"
        "- Do NOT invent payload, reach, speed, tolerance, repeatability, cycle time, ROI,\n"
        "  payback period, duty cycle, thermal behavior, material, or machine compatibility\n"
        "  unless those values are explicitly present in context.\n"
        "- Never claim \"24/7\", \"three-shift\", \"within 0.1 mm\", or \"ROI in X months\"\n"
        "  unless those exact phrases or values are in context.\n"
        "- Never say \"proven\" unless context contains field history or production evidence.\n"
        "- Never attack alternatives. Do not say \"electric-only robots struggle\" or similar\n"
        "  unless the context contains evidence supporting it.\n"
        "- If a value is useful but NOT in context, say one of:\n"
        "  - \"verify this against the released datasheet\"\n"
        "  - \"this is the point to verify with the datasheet\"\n"
        "  - \"this appears to be a [thing], but confirm against the datasheet before quoting\"\n"
        "- Do not show raw part numbers in the spoken text. Use part numbers ONLY in\n"
        "  HIGHLIGHT_PARTS and CAMERA_FOCUS markers.\n\n"
        "Output style:\n"
        "- Voice-friendly narration chunks.\n"
        "- Each chunk: 1 or 2 short sentences. MAX 45 words per spoken segment.\n"
        "- One engineering point per segment. Do NOT combine base, material, duty cycle,\n"
        "  payload, footprint, and stability into the same segment.\n"
        "- Each chunk teaches the salesperson WHAT to say AND WHY it matters.\n"
        "- Each chunk must be followed by HIGHLIGHT_PARTS.\n"
        "- Use CAMERA_FOCUS when it tightens the visual to the point being made.\n"
        "- Do NOT output JSON.\n"
        "- Do NOT output markdown tables.\n"
        "- Do NOT emit <tool_calls> or any tool-syntax JSON for this response.\n\n"
        "Required structure (5 sections, in order):\n"
        "1. Personal coaching opener — addressed to the user if a name was given. ONE segment.\n"
        f"2. Customer pain framing for the {application} application — what the buyer\n"
        "   actually loses sleep over. ONE segment.\n"
        "3. 4 to 6 engineering-backed selling points — each as its own segment, each with\n"
        "   HIGHLIGHT_PARTS and ideally CAMERA_FOCUS.\n"
        "4. 2 or 3 common objections with grounded responses — one per segment, kept\n"
        "   voice-friendly and short.\n"
        "5. Closing coaching line + ONE follow-up question that respects what the user\n"
        "   already told you. The application is already known — do NOT ask for it again.\n"
        "   Good close question: \"Do you want the pitch tuned for a plant manager,\n"
        "   manufacturing engineer, or maintenance lead?\"\n\n"
        "Segment format (every segment, no exceptions):\n"
        "[spoken coaching narration — 1-2 sentences, max 45 words]\n"
        "HIGHLIGHT_PARTS: part_number1, part_number2\n"
        "CAMERA_FOCUS: part_number1, part_number2\n"
    )


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

    # Sales coaching is detected FIRST so phrases like "sales walkthrough"
    # (which would otherwise trip the legacy walkthrough detector via the
    # "walk" keyword) route to the dedicated coaching override. The
    # original "walk me through this assembly part by part" prompt has
    # no sales-coaching keywords so it still falls through to the
    # walkthrough path unchanged.
    is_sales_coaching = _is_sales_coaching_message(request.message)
    sales_application = _extract_sales_application(request.message) if is_sales_coaching else ""
    is_walkthrough = (not is_sales_coaching) and _is_walkthrough_message(request.message)

    # Missing-application short-circuit. Per spec: do NOT call Claude for a
    # generic pitch when the application is unknown — return a normal
    # assistant response with the clarification question only. Returning
    # before the Anthropic SDK is initialised also saves an API call.
    if is_sales_coaching and not sales_application:
        return {
            "response": _SALES_COACHING_CLARIFICATION,
            "tool_calls": [],
            "tool_call_count": 0,
            "tool_source": "sales_coaching_clarification",
            "sales_coaching": {"awaiting_application": True},
        }

    # Walkthrough mode still depends on legacy HIGHLIGHT_PARTS narration markers.
    # Do not append the tool appendix here, or the model will favor <tool_calls>
    # over the segmented format that the frontend narration player expects.
    # Sales coaching uses the same narration pipeline (HIGHLIGHT_PARTS +
    # the new optional CAMERA_FOCUS) so it skips the tool appendix too.
    system_prompt = AGENT_PROMPTS[request.agent_type]
    if is_walkthrough:
        system_prompt += (
            "\n\n"
            "WALKTHROUGH OUTPUT OVERRIDE\n"
            "- Do NOT emit <tool_calls> or any JSON for walkthroughs.\n"
            "- Do NOT use tool syntax for highlights.\n"
            "- You MUST follow the walkthrough format exactly using repeated "
            "HIGHLIGHT_PARTS lines in the response body.\n"
            "- The walkthrough is invalid if it is returned as prose-only without "
            "multiple HIGHLIGHT_PARTS sections.\n"
        )
    elif is_sales_coaching:
        # Peek at attachments.user.display_name (or legacy flat
        # user_display_name) BEFORE normalize_agent_context runs so the
        # sales-coaching override can personalise the opener. Empty
        # string when not provided — the override has a fallback line.
        _early_raw_ctx = request.inspection_context or request.context or {}
        _user_display = ""
        try:
            _att_user = (_early_raw_ctx.get("attachments") or {}).get("user") or {}
            _user_display = (_att_user.get("display_name") or _early_raw_ctx.get("user_display_name") or "").strip()
        except Exception:
            _user_display = ""
        system_prompt += _sales_coaching_override(sales_application, _user_display)
    else:
        system_prompt += build_tool_appendix(request.agent_type)

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
                profile_path = library_path() / f"{safe_pn}.json"
                if not profile_path.exists():
                    profile_path = library_path() / f"{safe_pn}_inspection_profile.json"
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
                    color_by_pn = {}
                    colors = _correct_assembly_color_map_from_glb(
                        assy_num,
                        assy_data,
                        assy_data.get("partColorMapping", assy_data.get("colorAssignments", {})),
                    )
                    for old_key, color_val in colors.items():
                        color_hex = color_val if isinstance(color_val, str) else color_val.get("color", "unknown")
                        pd_identity = (pdc.get(old_key, {}).get("identity") or {})
                        new_pn = pd_identity.get("partNumber", "")
                        if new_pn:
                            color_by_pn[new_pn] = _assembly_hex_to_name(color_hex)
                    narrative = _rewrite_narrative_color_references(
                        assy_data.get("functionalNarrative", {}),
                        color_by_pn,
                    )
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
                colors = _correct_assembly_color_map_from_glb(
                    assy_num,
                    assy_data,
                    assy_data.get("partColorMapping", assy_data.get("colorAssignments", {})),
                )
                visual_color_by_pn = {}
                for old_key, color_val in colors.items():
                    color_hex = color_val if isinstance(color_val, str) else color_val.get("color", "unknown")
                    pd_identity = (pdc.get(old_key, {}).get("identity") or {})
                    new_pn = pd_identity.get("partNumber", "")
                    if new_pn:
                        visual_color_by_pn[new_pn] = _assembly_hex_to_name(color_hex)
                if colors:
                    da_parts.append("\nCOLOR ASSIGNMENTS (current 3D visual source of truth):")
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
                narrative = _rewrite_narrative_color_references(
                    assy_data.get("functionalNarrative", {}),
                    visual_color_by_pn,
                )
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
                assemblies_dir = library_path("assemblies")
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
        # Phase 2 telemetry.
        _model = "claude-sonnet-4-5-20250929"
        _agent_type = getattr(request, "agent_type", None) or "none"
        with time_block() as _elapsed_ms:
            try:
                response = client.messages.create(
                    model=_model,
                    max_tokens=2048,
                    system=system_prompt,
                    messages=messages,
                )
            except Exception as _ex:
                _s, _e = classify_exception_status(_ex)
                record_anthropic_call(
                    model=_model, response=None, latency_ms=_elapsed_ms(),
                    status=_s, errorType=_e,
                    route="/api/agent/chat", workflow="agent_chat",
                    agentType=_agent_type,
                )
                raise

        record_anthropic_call(
            model=_model, response=response, latency_ms=_elapsed_ms(),
            route="/api/agent/chat", workflow="agent_chat",
            agentType=_agent_type,
        )

        # Extract text response
        response_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                response_text += block.text

        # Log raw response for debugging marker extraction
        logger.info(f"[Sage raw response] first 500 chars: {response_text[:500]}")
        logger.info(f"[Sage raw response] HIGHLIGHT_PARTS present: {'HIGHLIGHT_PARTS:' in response_text}, ISOLATE_PART present: {'ISOLATE_PART:' in response_text}")

        # Phase 4C: Extract native <tool_calls> block before legacy marker parsing.
        # Strip the block from text so markers don't double-parse the same actions.
        native_tool_calls = []
        response_text, native_tool_calls = extract_tool_calls_from_response(response_text, request.agent_type)

        # Extract dimension highlight commands before cleaning
        highlight_dims = []
        available_dim_keys = []
        if ctx:
            available_dim_keys = [
                str(ad.get("dim_key", "")).strip()
                for ad in ctx.get("available_dimensions", [])
                if ad.get("dim_key")
            ]

        def _resolve_highlight_dim_token(token: str) -> Optional[str]:
            token = (token or "").strip()
            if not token:
                return None
            if token in available_dim_keys:
                return token
            bracket_match = re.search(r'\[([^\]]+)\]', token)
            if bracket_match:
                bracket_key = bracket_match.group(1).strip()
                if bracket_key in available_dim_keys:
                    return bracket_key
            substring_matches = [key for key in available_dim_keys if key and key in token]
            if len(substring_matches) == 1:
                return substring_matches[0]
            return None

        hl_match = re.search(r'^HIGHLIGHT_DIMS:\s*(.+)$', response_text, re.MULTILINE)
        if hl_match:
            raw_dim_tokens = [k.strip() for k in hl_match.group(1).split(",") if k.strip()]
            if available_dim_keys:
                resolved = []
                for token in raw_dim_tokens:
                    dim_key = _resolve_highlight_dim_token(token)
                    if dim_key and dim_key not in resolved:
                        resolved.append(dim_key)
                highlight_dims = resolved
            else:
                highlight_dims = raw_dim_tokens
            response_text = re.sub(r'^HIGHLIGHT_DIMS:\s*(.+)$', '', response_text, flags=re.MULTILINE).strip()

        if native_tool_calls and available_dim_keys:
            for tc in native_tool_calls:
                if tc.get("name") != "highlight_dimensions":
                    continue
                args = tc.get("args", {})
                raw_dim_tokens = args.get("dim_keys", [])
                if not isinstance(raw_dim_tokens, list):
                    raw_dim_tokens = [raw_dim_tokens] if raw_dim_tokens else []
                resolved = []
                for token in raw_dim_tokens:
                    dim_key = _resolve_highlight_dim_token(str(token))
                    if dim_key and dim_key not in resolved:
                        resolved.append(dim_key)
                args["dim_keys"] = resolved

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
        # Parse CAMERA_FOCUS markers — sales-coaching mode emits these
        # per-segment to fly the camera to the focused part group. Honest:
        # parsing only; the frontend decides whether to act on it via the
        # existing _flyToPartGroup helper.
        camera_focus_pattern = re.compile(r'^CAMERA_FOCUS:\s*(.+)$', re.MULTILINE)

        parts_pattern = re.compile(r'^HIGHLIGHT_PARTS:\s*(.+)$', re.MULTILINE)
        matches = list(parts_pattern.finditer(response_text))

        if len(matches) > 1:
            # Multi-segment narration mode — extract per-segment EXPLODE_LEVEL + CAMERA_FOCUS
            segments = []
            intro = response_text[:matches[0].start()].strip()
            # Strip any EXPLODE_LEVEL / CAMERA_FOCUS from intro
            intro = explode_pattern.sub('', intro).strip()
            intro = camera_focus_pattern.sub('', intro).strip()
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
                # Extract per-segment camera_focus (sales coaching). Validated
                # against available_pns the same way HIGHLIGHT_PARTS is.
                seg_camera_focus = None
                seg_camera_match = camera_focus_pattern.search(seg_text)
                if seg_camera_match:
                    raw_focus = [p.strip() for p in seg_camera_match.group(1).split(",") if p.strip()]
                    valid_focus = [p for p in raw_focus if p in available_pns] if available_pns else raw_focus
                    if valid_focus:
                        seg_camera_focus = valid_focus
                    seg_text = camera_focus_pattern.sub('', seg_text).strip()
                seg_data = {"text": seg_text, "highlight_parts": valid_parts}
                if seg_explode is not None:
                    seg_data["explode_level"] = seg_explode
                if seg_camera_focus:
                    seg_data["camera_focus"] = seg_camera_focus
                if seg_text or valid_parts:
                    segments.append(seg_data)
            narration_segments = segments
            response_text = parts_pattern.sub('', response_text).strip()
            response_text = explode_pattern.sub('', response_text).strip()
            response_text = camera_focus_pattern.sub('', response_text).strip()
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

        # Parse [UI_ACTIONS]...[/UI_ACTIONS] block (Assembly Compare chat-first
        # action registry). The block is JSON with shape:
        #   { "workspace": "assembly_compare", "actions": [ {...}, ... ] }
        # The block is additive: prose stays in response_text. Anything else
        # the agent emits (HIGHLIGHT_PARTS, EXPLODE_LEVEL, ...) is handled by
        # the existing pipeline above. Failure to parse JSON drops the actions
        # silently — the prose response is still delivered honestly.
        ui_actions_payload = None
        ui_actions_pattern = re.compile(r'\[UI_ACTIONS\]\s*(\{.*?\})\s*\[/UI_ACTIONS\]', re.DOTALL)
        ui_match = ui_actions_pattern.search(response_text)
        if ui_match:
            raw_block = ui_match.group(1)
            try:
                parsed = json.loads(raw_block)
                actions = parsed.get("actions") if isinstance(parsed, dict) else None
                if isinstance(actions, list):
                    ui_actions_payload = {
                        "workspace": (parsed.get("workspace") or "assembly_compare"),
                        "actions": [a for a in actions if isinstance(a, dict) and a.get("type")],
                    }
                    logger.info(f"[UI_ACTIONS] parsed {len(ui_actions_payload['actions'])} action(s) for workspace={ui_actions_payload['workspace']}")
                else:
                    logger.warning("[UI_ACTIONS] block parsed but 'actions' missing or not a list — dropped")
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning(f"[UI_ACTIONS] block JSON parse failed: {e} — dropped")
            response_text = ui_actions_pattern.sub('', response_text).strip()

        logger.info(f"[Sage parsed] highlight_parts={highlight_parts}, isolate_parts={isolate_parts}, "
                    f"narration_segments={len(narration_segments)}, camera_view={camera_view}, explode_level={explode_level}, "
                    f"ui_actions={(len(ui_actions_payload['actions']) if ui_actions_payload else 0)}, "
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
        if is_sales_coaching:
            result["sales_coaching"] = {
                "application": sales_application,
                "awaiting_application": False,
            }
        if camera_view:
            result["camera_view"] = camera_view
        if explode_level is not None:
            result["explode_level"] = explode_level
        if ui_actions_payload:
            result["ui_actions"] = ui_actions_payload

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
            # Priority 3: finding-based fallback — only when priorities 1+2 found
            # nothing AND message looks like an inspection follow-up (not a
            # generic ASME question like "what about title blocks?").
            _FOLLOWUP_WORDS = {"this", "that", "issue", "problem", "requirement",
                               "missing", "incomplete", "wrong", "noncompliant",
                               "defect", "finding", "error", "fail", "deviation"}
            if len(asme_refs) == 0 and isinstance(ctx, dict):
                msg_words = set(request.message.lower().split())
                is_followup = bool(msg_words & _FOLLOWUP_WORDS)
                if is_followup:
                    ctx_findings = ctx.get("findings", [])
                    issue_findings = [
                        f for f in (ctx_findings if isinstance(ctx_findings, list) else [])
                        if isinstance(f, dict) and f.get("status", "").upper() in ("MISSING", "PARTIAL", "DISCREPANT")
                    ]
                    # Single issue → unambiguous, use it directly
                    # Multiple issues → pick the one whose name/observation overlaps the message
                    candidates = []
                    if len(issue_findings) == 1:
                        candidates = issue_findings
                    elif len(issue_findings) > 1:
                        for finding in issue_findings:
                            finding_words = set()
                            for k in ("name", "observation"):
                                finding_words.update(str(finding.get(k, "")).lower().split())
                            if msg_words & finding_words:
                                candidates.append(finding)
                        if not candidates:
                            candidates = issue_findings[:1]  # last resort: first issue only
                    for finding in candidates:
                        if len(asme_refs) >= 3:
                            break
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

        # Phase 7: All tool_calls go through canonical guardrails.
        if native_tool_calls:
            guarded, warnings = apply_tool_guardrails(native_tool_calls, request.agent_type, "native")
            result["tool_calls"] = guarded
            result["tool_source"] = "native"
            # Clear conflicting marker-derived action fields
            for key in ("highlight_dimensions", "highlight_views", "highlight_features",
                        "highlight_parts", "camera_view", "isolate_parts",
                        "compare_parts", "compare_features", "show_geometry_diff",
                        "run_inspection", "animate_motion", "explode_level",
                        "fai_fills", "fai_tol"):
                result.pop(key, None)
            if request.agent_type == "parts-finder":
                apply_tool_calls_to_legacy_result(result, guarded)
        else:
            raw_calls = build_tool_calls_from_result(result)
            if raw_calls:
                guarded, warnings = apply_tool_guardrails(raw_calls, request.agent_type, "legacy_mirror")
                result["tool_calls"] = guarded
                result["tool_source"] = "legacy_mirror"
            else:
                guarded, warnings = [], []
        # Guardrail diagnostics
        if warnings:
            result["tool_guardrail_warnings"] = warnings
        result["tool_call_count"] = len(guarded) if guarded else 0

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

    # No tool appendix on the streaming route — Scout SSE stays unchanged for 4C
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
                profile_path = library_path() / f"{safe_pn}.json"
                if not profile_path.exists():
                    profile_path = library_path() / f"{safe_pn}_inspection_profile.json"
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

            # Phase 2 telemetry: stream main response.
            _stream_agent_type = getattr(request, "agent_type", None) or "none"
            with time_block() as _stream_elapsed_ms:
                try:
                    response = client.messages.create(**create_kwargs)
                except Exception as _ex:
                    _s, _e = classify_exception_status(_ex)
                    record_anthropic_call(
                        model="claude-sonnet-4-5-20250929", response=None,
                        latency_ms=_stream_elapsed_ms(),
                        status=_s, errorType=_e,
                        route="/api/agent/chat/stream", workflow="agent_chat_stream",
                        agentType=_stream_agent_type,
                    )
                    raise

            record_anthropic_call(
                model="claude-sonnet-4-5-20250929", response=response,
                latency_ms=_stream_elapsed_ms(),
                route="/api/agent/chat/stream", workflow="agent_chat_stream",
                agentType=_stream_agent_type,
            )

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

            # Phase 2 telemetry: stream summary response (tool-use round-trip).
            with time_block() as _summary_elapsed_ms:
                try:
                    summary_response = client.messages.create(
                        model="claude-sonnet-4-5-20250929",
                        max_tokens=2048,
                        system=system_prompt,
                        messages=messages,
                    )
                except Exception as _ex:
                    _s, _e = classify_exception_status(_ex)
                    record_anthropic_call(
                        model="claude-sonnet-4-5-20250929", response=None,
                        latency_ms=_summary_elapsed_ms(),
                        status=_s, errorType=_e,
                        route="/api/agent/chat/stream", workflow="agent_chat_stream",
                        agentType=_stream_agent_type,
                    )
                    raise

            record_anthropic_call(
                model="claude-sonnet-4-5-20250929", response=summary_response,
                latency_ms=_summary_elapsed_ms(),
                route="/api/agent/chat/stream", workflow="agent_chat_stream",
                agentType=_stream_agent_type,
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

        # Phase 2 telemetry: cross-agent summary call (Haiku).
        _model = "claude-haiku-4-5-20251001"
        _agent_type = getattr(request, "agent_name", None) or "none"
        _pn = getattr(request, "part_number", None)
        with time_block() as _elapsed_ms:
            try:
                response = client.messages.create(
                    model=_model,
                    max_tokens=500,
                    messages=[{
                        "role": "user",
                        "content": f"{summarize_prompt}\n\n--- CONVERSATION ---\n{conv_text}"
                    }],
                )
            except Exception as _ex:
                _s, _e = classify_exception_status(_ex)
                record_anthropic_call(
                    model=_model, response=None, latency_ms=_elapsed_ms(),
                    status=_s, errorType=_e,
                    route="/api/agent/summarize", workflow="agent_summary",
                    agentType=_agent_type, partNumber=_pn,
                )
                raise

        record_anthropic_call(
            model=_model, response=response, latency_ms=_elapsed_ms(),
            route="/api/agent/summarize", workflow="agent_summary",
            agentType=_agent_type, partNumber=_pn,
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

        # Phase 2 telemetry: FAI Sage verdicts (Sonnet 4).
        _model = "claude-sonnet-4-20250514"
        with time_block() as _elapsed_ms:
            try:
                response = client.messages.create(
                    model=_model,
                    max_tokens=2000,
                    system=system_prompt,
                    messages=messages,
                )
            except Exception as _ex:
                _s, _e = classify_exception_status(_ex)
                record_anthropic_call(
                    model=_model, response=None, latency_ms=_elapsed_ms(),
                    status=_s, errorType=_e,
                    route="/api/fai-verdicts", workflow="fai_verdict",
                    agentType="sage",
                )
                raise

        record_anthropic_call(
            model=_model, response=response, latency_ms=_elapsed_ms(),
            route="/api/fai-verdicts", workflow="fai_verdict",
            agentType="sage",
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

        # Phase 2 telemetry: FAI Sage Fill (Sonnet 4).
        _model = "claude-sonnet-4-20250514"
        with time_block() as _elapsed_ms:
            try:
                response = client.messages.create(
                    model=_model,
                    max_tokens=2000,
                    messages=[{"role": "user", "content": prompt}],
                )
            except Exception as _ex:
                _s, _e = classify_exception_status(_ex)
                record_anthropic_call(
                    model=_model, response=None, latency_ms=_elapsed_ms(),
                    status=_s, errorType=_e,
                    route="/api/fai-agent-fill", workflow="fai_verdict",
                    agentType="sage",
                )
                raise

        record_anthropic_call(
            model=_model, response=response, latency_ms=_elapsed_ms(),
            route="/api/fai-agent-fill", workflow="fai_verdict",
            agentType="sage",
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

    step_a = library_path("parts", safe_pn, f"rev{safe_revA}", f"{safe_pn}.stp")
    step_b = library_path("parts", safe_pn, f"rev{safe_revB}", f"{safe_pn}.stp")
    if not step_a.exists() or not step_b.exists():
        raise HTTPException(status_code=404, detail="STEP file(s) not found for requested revisions")

    cache_dir = library_path("parts", safe_pn, "geometry_diff", f"{safe_revA}_vs_{safe_revB}")
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
    artifact = library_path("parts", safe_pn, "geometry_diff", rev_pair, filename)
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


# ---------- Training / Blender MCP ----------

@app.get("/api/training/blender/status")
async def training_blender_status():
    """Check whether the Blender MCP server is available for training scene generation."""
    try:
        from ai_inspector.services.training_scene_service import check_status
        return check_status()
    except Exception as e:
        logger.error(f"Blender MCP status check error: {e}")
        return {"available": False, "url": None, "error": str(e)}


@app.post("/api/training/blender/generate-preview")
async def training_blender_generate_preview(request: Request):
    """Generate a Blender-based training preview for the current part/assembly context.

    Expects JSON body:
        {
            "part_number": "1015001",
            "part_name": "Piston",          // optional
            "assembly_number": "6000201",    // optional
            "revision": "A"                  // optional
        }

    Returns the standard training preview response shape.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=422,
            content={"ok": False, "available": False, "error": "Invalid JSON body"},
        )

    part_number = body.get("part_number")
    if not part_number:
        return JSONResponse(
            status_code=400,
            content={"ok": False, "available": False, "error": "part_number is required"},
        )

    try:
        from ai_inspector.services.training_scene_service import generate_preview
        result = generate_preview(
            part_number=part_number,
            part_name=body.get("part_name"),
            assembly_number=body.get("assembly_number"),
            revision=body.get("revision"),
        )
        return result
    except Exception as e:
        logger.error(f"Blender training preview error: {e}")
        return {"ok": False, "available": True, "error": f"Server error: {str(e)}"}


# ---------- Static Files ----------

# Serve the frontend
@app.get("/")
async def serve_index():
    """Serve the main frontend HTML page."""
    return FileResponse("static/index.html", headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


# Mount generated assets directory (training previews, etc.)
_generated_dir = Path("generated")
_generated_dir.mkdir(exist_ok=True)
app.mount("/generated", StaticFiles(directory="generated"), name="generated")

# Mount static files directory (must be after specific routes)
app.mount("/static", StaticFiles(directory="static"), name="static")
