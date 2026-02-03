"""OBB cropper with padding and minimum crop constraints."""

import math
from typing import List

import numpy as np
from PIL import Image

from ..config import default_config
from ..contracts import CropResult, DetectionResult


# Minimum crop dimensions (width, height) in pixels
# These module-level constants are derived from config for backward compatibility.
MIN_CROP_WIDTH = default_config.min_crop_width
MIN_CROP_HEIGHT = default_config.min_crop_height


def order_points(pts: np.ndarray) -> np.ndarray:
    """
    Order 4 points as: top-left, top-right, bottom-right, bottom-left.

    Uses the sum and difference of coordinates to determine ordering.
    """
    rect = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).flatten()

    rect[0] = pts[np.argmin(s)]      # top-left
    rect[2] = pts[np.argmax(s)]      # bottom-right
    rect[1] = pts[np.argmin(diff)]   # top-right
    rect[3] = pts[np.argmax(diff)]   # bottom-left

    return rect


def compute_obb_angle(pts: np.ndarray) -> float:
    """
    Compute the rotation angle of the OBB from ordered points.
    Returns angle in degrees.
    """
    # Top-left to top-right vector
    dx = pts[1][0] - pts[0][0]
    dy = pts[1][1] - pts[0][1]
    angle = math.degrees(math.atan2(dy, dx))
    return angle


def crop_obb(
    image: Image.Image,
    obb_points: List[List[float]],
    pad_ratio: float = 0.15,
    min_width: int = MIN_CROP_WIDTH,
    min_height: int = MIN_CROP_HEIGHT,
    det_id: str = "",
) -> CropResult:
    """
    Crop an oriented bounding box region from an image.

    Steps:
    1. Order the 4 OBB corner points
    2. Compute rotation angle
    3. Rotate full image to make the OBB axis-aligned
    4. Compute axis-aligned bounding box in rotated space
    5. Apply padding
    6. Enforce minimum crop size
    7. Crop and return

    Args:
        image: Source PIL Image
        obb_points: 4 corner points [[x,y], ...]
        pad_ratio: Padding ratio (0.15 = 15% on each side)
        min_width: Minimum crop width in pixels
        min_height: Minimum crop height in pixels
        det_id: Detection ID for tracking

    Returns:
        CropResult with cropped image and metadata
    """
    pts = np.array(obb_points, dtype=np.float32)
    ordered = order_points(pts)

    # Compute rotation angle
    angle = compute_obb_angle(ordered)

    # Compute OBB dimensions from ordered points
    width_obb = float(np.linalg.norm(ordered[1] - ordered[0]))
    height_obb = float(np.linalg.norm(ordered[3] - ordered[0]))

    # Ensure width >= height (landscape orientation)
    if height_obb > width_obb:
        width_obb, height_obb = height_obb, width_obb
        angle += 90

    # Center of the OBB
    center_x = float(pts[:, 0].mean())
    center_y = float(pts[:, 1].mean())

    # Rotate the full image around the OBB center
    rotated = image.rotate(
        angle,
        resample=Image.BICUBIC,
        expand=True,
        center=(center_x, center_y),
    )

    # After rotation with expand=True, the center shifts
    # Calculate new center position
    orig_w, orig_h = image.size
    rot_w, rot_h = rotated.size

    # The expansion offsets
    offset_x = (rot_w - orig_w) / 2
    offset_y = (rot_h - orig_h) / 2

    new_cx = center_x + offset_x
    new_cy = center_y + offset_y

    # Apply padding
    pad_w = width_obb * pad_ratio
    pad_h = height_obb * pad_ratio

    crop_w = width_obb + 2 * pad_w
    crop_h = height_obb + 2 * pad_h

    # Enforce minimum crop size
    crop_w = max(crop_w, min_width)
    crop_h = max(crop_h, min_height)

    # Compute crop box (left, upper, right, lower)
    left = new_cx - crop_w / 2
    upper = new_cy - crop_h / 2
    right = new_cx + crop_w / 2
    lower = new_cy + crop_h / 2

    # Clamp to image bounds
    left = max(0, left)
    upper = max(0, upper)
    right = min(rot_w, right)
    lower = min(rot_h, lower)

    # Crop
    cropped = rotated.crop((int(left), int(upper), int(right), int(lower)))

    return CropResult(
        image=cropped,
        meta={
            "pad_ratio": pad_ratio,
            "crop_w": cropped.size[0],
            "crop_h": cropped.size[1],
            "det_id": det_id,
            "rotation_angle": angle,
            "obb_width": float(width_obb),
            "obb_height": float(height_obb),
            "center": [float(center_x), float(center_y)],
        },
    )


def crop_detections(
    image: Image.Image,
    detections: List[DetectionResult],
    pad_ratio: float = 0.15,
) -> List[CropResult]:
    """
    Crop all detections from an image.

    Args:
        image: Source PIL Image
        detections: List of DetectionResult from YOLO detector
        pad_ratio: Padding ratio for each crop

    Returns:
        List of CropResult, one per detection
    """
    crops = []
    for det in detections:
        crop = crop_obb(
            image=image,
            obb_points=det.obb_points,
            pad_ratio=pad_ratio,
            det_id=det.det_id,
        )
        crops.append(crop)
    return crops
