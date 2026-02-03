"""Training data utilities for YOLO-OBB finetuning.

Handles:
- Roboflow label remapping (alphabetical -> classes.py indices)
- Dataset YAML generation with full 14-class names
- Image selection for annotation batches
"""

import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from ..detection.classes import YOLO_CLASSES, IDX_TO_CLASS

# Roboflow exports classes alphabetically.
# For the v1 4-class model (Chamfer, Fillet, Hole, TappedHole alphabetically):
ROBOFLOW_TO_CLASSES_PY = {
    0: 5,   # Roboflow Chamfer=0 -> classes.py Chamfer=5
    1: 4,   # Roboflow Fillet=1  -> classes.py Fillet=4
    2: 0,   # Roboflow Hole=2    -> classes.py Hole=0
    3: 1,   # Roboflow TappedHole=3 -> classes.py TappedHole=1
}


def remap_label_file(
    filepath: str,
    mapping: Dict[int, int],
) -> int:
    """Rewrite class indices in a single YOLO-OBB label file.

    Args:
        filepath: Path to .txt label file
        mapping: Dict mapping old class index -> new class index

    Returns:
        Number of annotations remapped
    """
    text = Path(filepath).read_text().strip()
    if not text:
        return 0

    lines = text.split("\n")
    remapped = []
    for line in lines:
        parts = line.split()
        if len(parts) < 9:  # class + 4 xy pairs = 9 minimum
            continue
        old_cls = int(parts[0])
        new_cls = mapping.get(old_cls, old_cls)
        remapped.append(f"{new_cls} {' '.join(parts[1:])}")

    Path(filepath).write_text("\n".join(remapped) + "\n")
    return len(remapped)


def remap_labels(
    label_dir: str,
    mapping: Optional[Dict[int, int]] = None,
) -> Dict[str, int]:
    """Remap all label files in a directory.

    Args:
        label_dir: Directory containing .txt label files
        mapping: Class index mapping (default: ROBOFLOW_TO_CLASSES_PY)

    Returns:
        Dict with 'files' and 'annotations' counts
    """
    if mapping is None:
        mapping = ROBOFLOW_TO_CLASSES_PY

    files_count = 0
    anno_count = 0

    for fname in sorted(os.listdir(label_dir)):
        if not fname.endswith(".txt"):
            continue
        n = remap_label_file(os.path.join(label_dir, fname), mapping)
        files_count += 1
        anno_count += n

    return {"files": files_count, "annotations": anno_count}


def generate_dataset_yaml(
    output_path: str,
    dataset_root: str,
    train_dir: str = "train/images",
    val_dir: str = "valid/images",
    test_dir: str = "test/images",
) -> str:
    """Generate ultralytics dataset.yaml with all 14 class names.

    Uses sparse class indices matching classes.py so trained model
    class IDs align with the inference pipeline.

    Args:
        output_path: Where to write dataset.yaml
        dataset_root: Root path for the dataset
        train_dir: Relative path to training images
        val_dir: Relative path to validation images
        test_dir: Relative path to test images

    Returns:
        Path to written YAML file
    """
    lines = [
        f"path: {dataset_root}",
        f"train: {train_dir}",
        f"val: {val_dir}",
        f"test: {test_dir}",
        "",
        "names:",
    ]

    for idx, name in enumerate(YOLO_CLASSES):
        lines.append(f"  {idx}: {name}")

    yaml_content = "\n".join(lines) + "\n"
    Path(output_path).write_text(yaml_content)

    return output_path


def select_training_images(
    source_dirs: List[str],
    output_dir: str,
    max_per_dir: Optional[Dict[str, int]] = None,
) -> List[str]:
    """Copy selected images to a staging directory for Roboflow upload.

    Args:
        source_dirs: List of directories to select from
        output_dir: Where to copy selected images
        max_per_dir: Optional limit per source directory

    Returns:
        List of copied file paths
    """
    os.makedirs(output_dir, exist_ok=True)
    copied = []

    for src_dir in source_dirs:
        if not os.path.isdir(src_dir):
            continue

        limit = (max_per_dir or {}).get(src_dir, None)
        count = 0

        for fname in sorted(os.listdir(src_dir)):
            if not fname.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            if limit and count >= limit:
                break

            src = os.path.join(src_dir, fname)
            dst = os.path.join(output_dir, fname)

            # Handle name collisions
            if os.path.exists(dst):
                base, ext = os.path.splitext(fname)
                dst = os.path.join(output_dir, f"{base}_{count}{ext}")

            shutil.copy2(src, dst)
            copied.append(dst)
            count += 1

    return copied
