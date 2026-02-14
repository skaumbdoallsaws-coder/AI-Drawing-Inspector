"""
InspectorPro - FastAPI Web Server
Thin wrapper around the SpatialInspector engine for engineering drawing QC inspection.
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from ai_inspector.spatial import SpatialInspector

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
    except Exception as e:
        logger.error(f"Error listing profiles: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/detect-pn")
async def detect_part_number(filename: str = Query(..., description="Filename to detect part number from")):
    """Auto-detect part number from a filename."""
    try:
        result = inspector.detect_part_number(filename)
        return result
    except Exception as e:
        logger.error(f"Error detecting part number from '{filename}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/reference-views/{part_number}")
async def get_reference_views(part_number: str):
    """Return base64-encoded CAD reference view images for a part number."""
    try:
        views = inspector.get_reference_views(part_number)
        return views
    except Exception as e:
        logger.error(f"Error getting reference views for '{part_number}': {e}")
        raise HTTPException(status_code=404, detail=f"No reference views found for part number '{part_number}'")


@app.post("/api/inspect")
async def run_inspection(
    file: UploadFile = File(...),
    part_number: str = Form(...),
    send_reference_views: bool = Form(True),
):
    """Run a full inspection on an uploaded drawing."""
    try:
        drawing_bytes = await file.read()
        filename = file.filename or "unknown"

        logger.info(f"Running inspection: part={part_number}, file={filename}, ref_views={send_reference_views}")

        result = inspector.inspect(
            drawing_bytes=drawing_bytes,
            filename=filename,
            part_number=part_number,
            send_reference_views=send_reference_views,
        )

        logger.info(f"Inspection complete for {part_number}: {result.get('gap_summary', {}).get('completeness', 'N/A')}")
        return result
    except Exception as e:
        logger.error(f"Error during inspection: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ---------- Static Files ----------

# Serve the frontend
@app.get("/")
async def serve_index():
    """Serve the main frontend HTML page."""
    return FileResponse("static/index.html")


# Mount static files directory (must be after specific routes)
app.mount("/static", StaticFiles(directory="static"), name="static")
