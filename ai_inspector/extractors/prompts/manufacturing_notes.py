"""Manufacturing notes extraction prompt for Qwen VLM."""

MANUFACTURING_NOTES_PROMPT = '''Examine this engineering drawing for manufacturing-related notes and specifications. Return a JSON object:

{
  "hasManufacturingNotes": true/false,
  "heatTreatment": {
    "specified": true/false,
    "specification": "e.g., HEAT TREAT TO 58-62 HRC",
    "hardness": "e.g., 58-62 HRC",
    "process": "e.g., carburize, through harden, case harden"
  },
  "surfaceFinish": {
    "specified": true/false,
    "generalFinish": "e.g., 125 RMS, 63 Ra",
    "specificFinishes": [
      {"surface": "bore", "finish": "32 Ra"},
      {"surface": "OD", "finish": "63 Ra"}
    ]
  },
  "platingOrCoating": {
    "specified": true/false,
    "type": "e.g., ZINC PLATE, ANODIZE, PAINT BLACK, POWDER COAT",
    "specification": "e.g., PER MIL-C-5541, CLASS 2",
    "thickness": "if specified"
  },
  "weldingNotes": {
    "specified": true/false,
    "weldSpec": "e.g., AWS D1.1",
    "weldTypes": ["fillet", "groove", "spot"],
    "notes": "any welding-specific notes"
  },
  "specialProcesses": [
    {
      "process": "e.g., stress relieve, shot peen, passivate",
      "specification": "details if given"
    }
  ],
  "inspectionRequirements": {
    "specified": true/false,
    "requirements": ["e.g., 100% INSPECT THREADS", "CMM REQUIRED", "FIRST ARTICLE"]
  },
  "generalNotes": [
    "REMOVE ALL BURRS AND SHARP EDGES",
    "BREAK EDGES .005-.015",
    "any other manufacturing notes"
  ],
  "certifications": ["e.g., MATERIAL CERT REQUIRED", "PPAP REQUIRED"]
}

Extract ALL manufacturing-related information visible on the drawing. If a category has no information, set specified to false.
Only return valid JSON, no other text.'''
