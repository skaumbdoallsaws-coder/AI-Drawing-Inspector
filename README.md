# InspectorPro

Engineering drawing quality inspection tool powered by AI. Upload a drawing, select the part number, and get an automated feature-by-feature QC report.

## Overview

InspectorPro wraps the existing `SpatialInspector` engine in a web interface. Engineers upload engineering drawings (PNG, JPEG, or PDF), the backend analyzes them against pre-built inspection profiles from 3D CAD models using AI, and the frontend displays a feature-by-feature findings table plus a downloadable QC report.

## Tech Stack

- **Frontend:** Vanilla HTML/CSS/JavaScript (single page, no framework)
- **Backend:** Python 3.10+ with FastAPI
- **Engine:** `ai_inspector.spatial.SpatialInspector` (pre-built, not modified)
- **API:** REST (JSON responses, multipart form data for uploads)
- **Database:** None (stateless — data comes from flat JSON inspection profiles)

## Quick Start

```bash
# 1. Ensure prerequisites
#    - Python 3.10+ installed
#    - .env file with ANTHROPIC_API_KEY and OPENAI_API_KEY
#    - 400S_Sorted_Library/ directory with inspection profiles

# 2. Run the setup script
chmod +x init.sh
./init.sh
```

The app will be available at **http://localhost:8000**.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/profiles` | List all available inspection profiles |
| `GET` | `/api/detect-pn?filename=...` | Auto-detect part number from filename |
| `GET` | `/api/reference-views/{part_number}` | Get base64 CAD reference view images |
| `POST` | `/api/inspect` | Run full inspection (multipart form) |

## Project Structure

```
AI-tool/
├── ai_inspector/spatial/engine.py    # Backend engine (DO NOT MODIFY)
├── 400S_Sorted_Library/              # 185 inspection profiles + CAD views
├── .env                              # API keys
├── server.py                         # FastAPI web server
├── static/
│   └── index.html                    # Single-page frontend app
├── requirements.txt                  # Python dependencies
├── init.sh                           # Setup & start script
└── README.md                         # This file
```

## Design

- SolidWorks-inspired dark theme
- 3-column layout: left panel (upload + features) | center viewport (drawing + CAD views) | right panel (results)
- Chain-of-thought loading animation during 15-30s inspection wait
- Real-time feature tree with color-coded status dots
- Export QC reports as markdown or JSON

## Prerequisites

- Python 3.10+
- `.env` file with `ANTHROPIC_API_KEY` and `OPENAI_API_KEY`
- `400S_Sorted_Library/` directory with inspection profiles and CAD view images
- `ai_inspector/spatial/engine.py` (pre-built engine)
