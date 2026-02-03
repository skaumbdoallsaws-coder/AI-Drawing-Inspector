"""Select and stage training images for YOLO-OBB annotation.

Usage:
    python scripts/select_training_images.py --output staging/training_images

Selects images from Drawing_Analysis_By_Type/ and drawing_samples_batch/
for upload to Roboflow.
"""

import argparse
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ai_inspector.fine_tuning.data_generator import select_training_images


def main():
    parser = argparse.ArgumentParser(description="Select training images for YOLO-OBB annotation")
    parser.add_argument("--output", default="staging/training_images", help="Output directory")
    parser.add_argument("--machined", type=int, default=80, help="Max images from Machined Parts")
    parser.add_argument("--sheet-metal", type=int, default=20, help="Max images from Sheet Metal")
    parser.add_argument("--samples", type=int, default=20, help="Max images from drawing_samples_batch")
    args = parser.parse_args()

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    source_dirs = [
        os.path.join(project_root, "Drawing_Analysis_By_Type", "01_Machined_Parts"),
        os.path.join(project_root, "Drawing_Analysis_By_Type", "02_Sheet_Metal"),
        os.path.join(project_root, "drawing_samples_batch"),
    ]

    max_per_dir = {
        source_dirs[0]: args.machined,
        source_dirs[1]: args.sheet_metal,
        source_dirs[2]: args.samples,
    }

    copied = select_training_images(source_dirs, args.output, max_per_dir)

    print(f"Selected {len(copied)} images -> {args.output}/")
    print(f"  Machined Parts: {min(args.machined, len([f for f in copied if 'Machined' in f or '01_' in f]))}")
    print(f"  Sheet Metal:    {min(args.sheet_metal, len([f for f in copied if 'Sheet' in f or '02_' in f]))}")
    print(f"  Samples:        {min(args.samples, len([f for f in copied if 'samples' in f]))}")
    print(f"\nUpload this folder to Roboflow for annotation.")


if __name__ == "__main__":
    main()
