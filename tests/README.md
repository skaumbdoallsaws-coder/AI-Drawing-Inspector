# AI Inspector -- YOLO-OBB Pipeline Tests

## Testing Approach

All testing for this project is done via **Google Colab notebooks**. There are no
local pytest suites -- every test notebook is designed to run on Colab with access
to an A100 GPU.

### Why Colab?

- The pipeline depends on YOLO-OBB inference and LightOnOCR-2 (1B params), both of
  which require a GPU.
- An **A100 GPU** is available in Colab, which provides enough VRAM for full-pipeline
  testing and future finetuning experiments.
- Colab makes it easy to visualize intermediate results (crops, annotated images,
  match tables) inline.

### Notebook Organization

Notebooks are organized by pipeline stage so you can test each module independently:

| Notebook | Pipeline Stages | Modules Tested |
|---|---|---|
| `test_detection.ipynb` | M1 + M2 | `yolo_detector`, `cropper` |
| `test_ocr_pipeline.ipynb` | M3 + M4 + M5 | `rotation`, `ocr_adapter`, `crop_reader` |
| `test_normalize_validate.ipynb` | M7 + M8 | `unit_normalizer`, `validator` |
| `test_matching.ipynb` | M9 + M10 | `quantity_expander`, `matcher` |
| `test_full_pipeline.ipynb` | M11 (end-to-end) | `yolo_pipeline.YOLOPipeline` |
| `test_finetuning_prep.ipynb` | M12 + future | `evaluate`, YOLO training config |

### How to Run

1. **Upload** the desired notebook to Google Colab.
2. **Set runtime** to GPU (Runtime > Change runtime type > A100 if available, else T4).
3. The first cell in every notebook clones the GitHub repo and installs dependencies.
4. **Mount Google Drive** when prompted (for model weights, sample images, SW JSON files).
5. Set your **HF_TOKEN** in the environment cell if running OCR notebooks (LightOnOCR-2 is a gated model).
6. Run cells sequentially from top to bottom.

### File Paths

Notebooks expect the following Drive layout by default (configurable in each notebook):

```
/content/AI-Drawing-Inspector/     # Cloned repo
/content/drive/MyDrive/
    ai_inspector_models/
        best.pt                    # YOLO-OBB model weights
    ai_inspector_data/
        sample_pages/              # Test page images (PNG/JPG)
        sw_json/                   # SolidWorks JSON exports
        ground_truth/              # Sidecar YAML annotations
```

### GPU Memory Notes

- YOLO-OBB detection: ~500 MB VRAM
- LightOnOCR-2 (1B): ~4 GB VRAM
- Full pipeline: ~5 GB VRAM total
- A100 (40 GB or 80 GB) leaves plenty of headroom for finetuning
