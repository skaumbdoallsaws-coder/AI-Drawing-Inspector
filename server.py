"""
InspectorPro - FastAPI Web Server
Thin wrapper around the SpatialInspector engine for engineering drawing QC inspection.
"""
# Updated: proper HTTP error codes for malformed requests
# Reloaded: ASME prompt improvements (feature #109) - reinstalled package

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

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


# ---------- Static Files ----------

# Serve the frontend
@app.get("/")
async def serve_index():
    """Serve the main frontend HTML page."""
    return FileResponse("static/index.html")


# Mount static files directory (must be after specific routes)
app.mount("/static", StaticFiles(directory="static"), name="static")
