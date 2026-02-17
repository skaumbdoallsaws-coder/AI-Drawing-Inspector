"""
InspectorPro - FastAPI Web Server
Thin wrapper around the SpatialInspector engine for engineering drawing QC inspection.
"""
# Updated: proper HTTP error codes for malformed requests
# Reloaded: ASME prompt improvements (feature #109) - reinstalled package

import os
import re
import base64
import json
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ai_inspector.spatial import SpatialInspector
from ai_inspector.spatial.profile_validator import validate_all_profiles

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("inspectorpro")

# Global inspector instance
inspector: SpatialInspector = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize SpatialInspector on startup."""
    global inspector
    logger.info("Initializing SpatialInspector with library_dir='400S_Sorted_Library'...")
    inspector = SpatialInspector(library_dir="400S_Sorted_Library")
    logger.info("SpatialInspector initialized successfully.")
    yield
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

AGENT_SYSTEM_PROMPT = """You are an expert engineering drawing assistant integrated into InspectorPro, a drawing quality inspection tool. You help engineers fix issues found during inspection.
You have deep knowledge of:
- ASME Y14.5-2018 dimensioning and tolerancing standards
- SolidWorks drawing annotation workflows (Insert > Annotations > ...)
- Proper GD&T callout notation and representation
- Engineering drawing best practices

You are given ASME reference material as context images — use them to ground your answers but do NOT reference them directly (do not say 'as shown in the reference' or 'per the attached document'). Just give clear, direct answers.

Keep responses concise and actionable. When explaining SolidWorks steps, use the menu path format (e.g., Insert > Annotations > Hole Callout). When showing callout formats, use proper engineering notation."""


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
    """Build a context string from inspection results."""
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

    return "\n\n".join(parts)


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

    try:
        client = anthropic.Anthropic(api_key=api_key)

        # Merge inspection_context from either field name
        ctx = request.inspection_context or request.context or {}

        # Build context message
        context_text = _build_context_message(ctx)

        # RAG: find and load relevant ASME reference images
        rag_dirs = _find_relevant_rag_dirs(request.message, ctx)
        rag_images = _load_rag_images(rag_dirs, max_images=4)
        logger.info(f"Agent chat: loaded {len(rag_images)} RAG images from {rag_dirs}")

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

        # Add inspection context
        if context_text:
            user_content.append({
                "type": "text",
                "text": f"=== CURRENT INSPECTION CONTEXT ===\n{context_text}"
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
            max_tokens=1024,
            system=AGENT_SYSTEM_PROMPT,
            messages=messages,
        )

        # Extract text response
        response_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                response_text += block.text

        return {"response": response_text}

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


# ---------- Static Files ----------

# Serve the frontend
@app.get("/")
async def serve_index():
    """Serve the main frontend HTML page."""
    return FileResponse("static/index.html")


# Mount static files directory (must be after specific routes)
app.mount("/static", StaticFiles(directory="static"), name="static")
