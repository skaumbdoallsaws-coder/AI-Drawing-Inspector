# YOLO-OBB Training Data

## Roboflow Setup

1. Create project at app.roboflow.com:
   - Name: `ai-inspector-callout-detection`
   - Type: Object Detection (OBB)

2. Create 4 classes:
   - `Hole` — diameter callouts (dia .500 THRU)
   - `TappedHole` — thread callouts (M6x1.0, 1/4-20 UNC)
   - `Fillet` — radius callouts (R.125)
   - `Chamfer` — chamfer callouts (.030 X 45 deg)

3. Upload images from `staging/training_images/`

## Annotation Guidelines

- Draw OBB tightly around the callout TEXT only (not the leader line or feature)
- Include quantity prefix (2X), symbols, dimensions, and depth/angle specs
- Align OBB rotation with text reading direction
- If a callout has both hole + thread info, label as TappedHole

## After Annotation

1. Export from Roboflow as YOLOv8-OBB format
2. Remap labels: Roboflow uses alphabetical indices, pipeline needs classes.py indices
3. Use `notebooks/train_yolo_obb.ipynb` for training on A100

## Class Index Mapping

Roboflow (alphabetical) -> classes.py:
- Chamfer (0) -> 5
- Fillet (1) -> 4
- Hole (2) -> 0
- TappedHole (3) -> 1
