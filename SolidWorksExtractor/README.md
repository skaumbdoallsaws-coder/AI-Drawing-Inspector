# SolidWorks Data Extractor

A C# (.NET Framework 4.8) tool that extracts comprehensive data from SolidWorks parts and assemblies to clean JSON format.

## Features

### Part Extraction
- **Identity**: Part number, description, revision, author, material, custom properties
- **Physical Properties**: Mass, volume, surface area, bounding box, center of mass
- **Features** (typed extraction):
  - Hole Wizard: type, diameter, depth, thread info, counterbore/countersink
  - Extrudes/Cuts: end conditions, depths, draft angles
  - Revolves/Sweeps/Lofts: angles, profiles
  - Fillets/Chamfers: radii, distances, angles
  - Patterns: linear, circular, mirror with counts and spacing
  - Sheet Metal: thickness, bend radius, K-factor, bend allowance
- **Geometry Ground Truth** (independent of features):
  - Cylindrical features: diameter, depth, through/blind classification
  - Planar faces: normals, orientations
  - Edge analysis: linear, circular, helical counts
- **Verification Checklist**: Auto-generated for drawing inspection

### Assembly Extraction
- **Component Hierarchy**: Full tree with parent-child relationships
- **Component State**: Resolved, lightweight, suppressed status
- **Transforms**: Position/orientation in assembly space
- **Mates**: All mate types with participating entities
- **Mate Relationships**: Component pairs with aggregated mates
- **Part Data Cache**: Extracted data for all unique parts (deduped)

## Requirements

- **SolidWorks 2023** (or compatible version)
- **.NET Framework 4.8**
- **Visual Studio 2019/2022** (for building)

## Building

1. Open `SolidWorksExtractor.sln` in Visual Studio
2. Verify SolidWorks Interop references point to your installation:
   - `C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.sldworks.dll`
   - `C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS\api\redist\SolidWorks.Interop.swconst.dll`
3. Build solution (F6 or Build → Build Solution)
4. Output: `bin\Debug\SolidWorksExtractor.exe`

## Usage

```bash
# Extract from active document (most common)
SolidWorksExtractor.exe

# Extract from specific part
SolidWorksExtractor.exe "C:\Parts\bracket.sldprt"

# Extract from assembly with all parts
SolidWorksExtractor.exe "C:\Assemblies\machine.sldasm"

# Resolve lightweight components first
SolidWorksExtractor.exe machine.sldasm --resolve

# Custom output path
SolidWorksExtractor.exe part.sldprt --output "C:\Output\part_data.json"

# Skip part extraction for assemblies (faster)
SolidWorksExtractor.exe assembly.sldasm --no-parts
```

### Options

| Option | Description |
|--------|-------------|
| `--help`, `-h` | Show help message |
| `--active`, `-a` | Use currently active document |
| `--output`, `-o` | Specify output JSON file path |
| `--no-parts` | Skip extracting part data from assembly components |
| `--resolve` | Resolve lightweight components before extraction |
| `--start` | Start SolidWorks if not running |

## Output JSON Structure

### Part Output
```json
{
  "fileName": "bracket.sldprt",
  "identity": {
    "partNumber": "017-134",
    "description": "BRACKET SPRING BOTTOM",
    "material": "AISI 1020"
  },
  "physical": {
    "mass": 0.245,
    "boundingBox": { "length": 0.1, "width": 0.05, "height": 0.02 }
  },
  "features": {
    "holeWizardHoles": [
      {
        "name": "M8 Tapped Hole1",
        "holeType": "Straight Tap",
        "diameter": 0.008,
        "threadSize": "M8x1.25",
        "isThrough": true,
        "instanceCount": 4
      }
    ],
    "fillets": [...],
    "chamfers": [...]
  },
  "geometry": {
    "cylinders": [
      {
        "type": "ThroughHole",
        "diameter": 0.008,
        "isInternal": true
      }
    ]
  },
  "verificationChecklist": [
    "Thread callout: M8x1.25 THRU (4x)",
    "Fillet: R2.00mm"
  ]
}
```

### Assembly Output
```json
{
  "fileName": "machine.sldasm",
  "statistics": {
    "totalComponents": 156,
    "uniquePartCount": 48,
    "totalMates": 234
  },
  "components": [...],
  "mates": [
    {
      "name": "Concentric1",
      "type": "Concentric",
      "entity1": { "componentFileName": "shaft.sldprt" },
      "entity2": { "componentFileName": "bearing.sldprt" }
    }
  ],
  "partDataCache": {
    "shaft.sldprt": { /* full part data */ },
    "bearing.sldprt": { /* full part data */ }
  }
}
```

## Recommended Workflow

### For Main Assembly Extraction
1. Open the top-level assembly in SolidWorks
2. Set components to Resolved (not Lightweight) for full data extraction
3. Run: `SolidWorksExtractor.exe --resolve`
4. Output contains all components, mates, and part data in one JSON

### For Individual Parts
1. Open the part or have it active
2. Run: `SolidWorksExtractor.exe`
3. Output contains full feature and geometry data

## Comparison with VBA Approach

| Aspect | VBA Macros | C# Extractor |
|--------|-----------|--------------|
| Stability | Frequent crashes | Robust error handling |
| Hole Diameter | Returns 0.0 (API bug) | Parses from name + geometry |
| Output Format | Text files needing parsing | Clean JSON |
| Maintainability | Difficult | Well-structured classes |
| Feature Types | Limited | Comprehensive typed extraction |
| Geometry Analysis | None | Cylinder/plane detection |
| Assembly Context | Separate extraction | Single unified output |

## Troubleshooting

### "Could not connect to SolidWorks"
- Ensure SolidWorks is running
- Or use `--start` flag to launch it

### Missing Interop References
- Update HintPath in .csproj to match your SolidWorks installation path
- Ensure "Embed Interop Types" is set to `false`

### Lightweight Components Show No Data
- Use `--resolve` flag to resolve components before extraction
- Or manually resolve in SolidWorks before running

### Hole Diameters Still Zero
- The extractor attempts to parse diameter from hole name
- Geometry analyzer provides independent diameter measurement
- Check `geometry.cylinders` for ground truth values

## Project Structure

```
SolidWorksExtractor/
├── Program.cs                    # Entry point, CLI interface
├── Services/
│   ├── SolidWorksConnection.cs   # Connect to SW, open docs
│   ├── PropertyExtractor.cs      # Custom props, material, mass
│   ├── FeatureExtractor.cs       # Feature tree traversal
│   ├── GeometryAnalyzer.cs       # Cylinder/face detection
│   └── AssemblyExtractor.cs      # Mates, hierarchy, transforms
├── Models/
│   ├── PartData.cs               # Part output model
│   ├── FeatureData.cs            # Typed feature models
│   ├── GeometryData.cs           # Geometry ground truth
│   └── AssemblyData.cs           # Assembly output model
└── Output/
    └── JsonSerializer.cs         # Clean JSON generation
```
