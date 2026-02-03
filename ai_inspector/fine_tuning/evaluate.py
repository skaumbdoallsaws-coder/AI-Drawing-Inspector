"""Evaluation harness for the YOLO-OBB pipeline.

Evaluates pipeline predictions against ground truth annotations.
Provides stage-by-stage metrics to identify bottleneck stages.

Ground truth format (sidecar YAML):
```yaml
image: page_001.png
annotations:
  - class: Hole
    obb_points: [[100,100],[300,100],[300,200],[100,200]]
    text: "\u2300.500 THRU"
    parsed:
      calloutType: Hole
      diameter: ".500"
      depth: THRU
  - class: TappedHole
    ...
```

Evaluation stages:
1. Detection: OBB IoU-based pairing (or center-distance proxy)
2. Transcription: CER/WER on IoU-paired detections
3. Parsing: field-level accuracy on paired detections
4. Matching: instance-level metrics on expanded results
"""

import math
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False


# --- IoU / Pairing ---

def _box_from_obb(
    obb_points: List[List[float]],
) -> Tuple[float, float, float, float]:
    """
    Compute axis-aligned bounding box from OBB points.
    Returns (x_min, y_min, x_max, y_max).
    Used as a proxy when full polygon IoU is not needed.
    """
    xs = [p[0] for p in obb_points]
    ys = [p[1] for p in obb_points]
    return min(xs), min(ys), max(xs), max(ys)


def _aabb_iou(
    box1: Tuple[float, float, float, float],
    box2: Tuple[float, float, float, float],
) -> float:
    """
    Compute IoU between two axis-aligned bounding boxes.
    Each box is (x_min, y_min, x_max, y_max).
    """
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])

    intersection = max(0, x2 - x1) * max(0, y2 - y1)

    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])

    union = area1 + area2 - intersection

    if union <= 0:
        return 0.0

    return intersection / union


def _center_distance(obb1: List[List[float]], obb2: List[List[float]]) -> float:
    """Euclidean distance between OBB centers."""
    cx1 = sum(p[0] for p in obb1) / len(obb1)
    cy1 = sum(p[1] for p in obb1) / len(obb1)
    cx2 = sum(p[0] for p in obb2) / len(obb2)
    cy2 = sum(p[1] for p in obb2) / len(obb2)
    return math.sqrt((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2)


def pair_detections_iou(
    predictions: List[Dict[str, Any]],
    ground_truth: List[Dict[str, Any]],
    iou_threshold: float = 0.3,
) -> List[Tuple[Optional[int], Optional[int], float]]:
    """
    Pair predictions to ground truth using IoU (greedy matching).

    NEVER uses zip -- always IoU-based pairing to handle ordering differences.

    Args:
        predictions: List of prediction dicts with 'obb_points'
        ground_truth: List of GT dicts with 'obb_points'
        iou_threshold: Minimum IoU for a valid pair

    Returns:
        List of (pred_idx, gt_idx, iou) tuples.
        Unpaired predictions have gt_idx=None.
        Unpaired GT have pred_idx=None.
    """
    if not predictions or not ground_truth:
        pairs = []
        for i in range(len(predictions)):
            pairs.append((i, None, 0.0))
        for j in range(len(ground_truth)):
            pairs.append((None, j, 0.0))
        return pairs

    # Compute IoU matrix
    pred_boxes = [_box_from_obb(p["obb_points"]) for p in predictions]
    gt_boxes = [_box_from_obb(g["obb_points"]) for g in ground_truth]

    iou_matrix = []
    for i, pb in enumerate(pred_boxes):
        for j, gb in enumerate(gt_boxes):
            iou = _aabb_iou(pb, gb)
            if iou >= iou_threshold:
                iou_matrix.append((iou, i, j))

    # Greedy matching: highest IoU first
    iou_matrix.sort(key=lambda x: x[0], reverse=True)

    used_pred = set()
    used_gt = set()
    pairs = []

    for iou, pi, gi in iou_matrix:
        if pi not in used_pred and gi not in used_gt:
            pairs.append((pi, gi, iou))
            used_pred.add(pi)
            used_gt.add(gi)

    # Unpaired predictions
    for i in range(len(predictions)):
        if i not in used_pred:
            pairs.append((i, None, 0.0))

    # Unpaired GT
    for j in range(len(ground_truth)):
        if j not in used_gt:
            pairs.append((None, j, 0.0))

    return pairs


# --- Transcription metrics ---

def _edit_distance(s1: str, s2: str) -> int:
    """Levenshtein edit distance."""
    if len(s1) < len(s2):
        return _edit_distance(s2, s1)

    if len(s2) == 0:
        return len(s1)

    prev = list(range(len(s2) + 1))

    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            insert = prev[j + 1] + 1
            delete = curr[j] + 1
            replace = prev[j] + (0 if c1 == c2 else 1)
            curr.append(min(insert, delete, replace))
        prev = curr

    return prev[-1]


def compute_cer(predicted: str, reference: str) -> float:
    """
    Character Error Rate.
    CER = edit_distance(pred, ref) / len(ref)
    """
    if not reference:
        return 0.0 if not predicted else 1.0
    return _edit_distance(predicted, reference) / len(reference)


def compute_wer(predicted: str, reference: str) -> float:
    """
    Word Error Rate.
    WER = edit_distance(pred_words, ref_words) / len(ref_words)
    """
    pred_words = predicted.split()
    ref_words = reference.split()

    if not ref_words:
        return 0.0 if not pred_words else 1.0

    return _edit_distance_words(pred_words, ref_words) / len(ref_words)


def _edit_distance_words(s1: List[str], s2: List[str]) -> int:
    """Word-level edit distance."""
    if len(s1) < len(s2):
        return _edit_distance_words(s2, s1)

    if len(s2) == 0:
        return len(s1)

    prev = list(range(len(s2) + 1))

    for i, w1 in enumerate(s1):
        curr = [i + 1]
        for j, w2 in enumerate(s2):
            insert = prev[j + 1] + 1
            delete = curr[j] + 1
            replace = prev[j] + (0 if w1 == w2 else 1)
            curr.append(min(insert, delete, replace))
        prev = curr

    return prev[-1]


# --- Parsing accuracy ---

def compute_parsing_accuracy(
    predicted_parsed: Dict[str, Any],
    gt_parsed: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Compare predicted parsed fields against GT parsed fields.

    Returns:
        Dict with 'correct', 'total', 'accuracy', and per-field results
    """
    # Compare all GT fields
    correct = 0
    total = 0
    field_results = {}

    for key, gt_value in gt_parsed.items():
        if key.startswith("_"):
            continue  # Skip internal fields
        total += 1
        pred_value = predicted_parsed.get(key)

        is_correct = str(pred_value).strip() == str(gt_value).strip()
        if is_correct:
            correct += 1

        field_results[key] = {
            "predicted": pred_value,
            "expected": gt_value,
            "correct": is_correct,
        }

    return {
        "correct": correct,
        "total": total,
        "accuracy": correct / total if total > 0 else 1.0,
        "fields": field_results,
    }


# --- Ground truth loading ---

def load_sidecar(path: str) -> Dict[str, Any]:
    """
    Load a sidecar ground truth YAML file.

    Expected format:
    ```yaml
    image: page_001.png
    annotations:
      - class: Hole
        obb_points: [[x,y], [x,y], [x,y], [x,y]]
        text: "\u2300.500 THRU"
        parsed:
          calloutType: Hole
          diameter: ".500"
    ```
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        if path.suffix in (".yaml", ".yml"):
            if not _YAML_AVAILABLE:
                raise ImportError(
                    "pyyaml is required to load YAML sidecar files. "
                    "Install it with: pip install pyyaml"
                )
            return yaml.safe_load(f)
        else:
            return json.load(f)


def load_sidecars(directory: str) -> List[Dict[str, Any]]:
    """Load all sidecar files from a directory."""
    sidecars = []
    dir_path = Path(directory)

    for ext in ("*.yaml", "*.yml", "*.json"):
        for path in sorted(dir_path.glob(ext)):
            sidecars.append(load_sidecar(str(path)))

    return sidecars


# --- Full evaluation ---

def evaluate_page(
    predictions: List[Dict[str, Any]],
    ground_truth: List[Dict[str, Any]],
    iou_threshold: float = 0.3,
) -> Dict[str, Any]:
    """
    Evaluate predictions against ground truth for a single page.

    Computes:
    - Detection metrics (precision, recall, F1)
    - Transcription metrics (mean CER, mean WER) on paired detections
    - Parsing accuracy on paired detections
    - Class-level breakdown

    Args:
        predictions: List of prediction dicts with 'obb_points', 'text', 'parsed', 'class'
        ground_truth: List of GT annotation dicts
        iou_threshold: IoU threshold for pairing

    Returns:
        Dict with stage-by-stage metrics
    """
    # Stage 1: Detection pairing
    pairs = pair_detections_iou(predictions, ground_truth, iou_threshold)

    true_positives = [(pi, gi, iou) for pi, gi, iou in pairs if pi is not None and gi is not None]
    false_positives = [(pi, gi, iou) for pi, gi, iou in pairs if pi is not None and gi is None]
    false_negatives = [(pi, gi, iou) for pi, gi, iou in pairs if pi is None and gi is not None]

    n_tp = len(true_positives)
    n_fp = len(false_positives)
    n_fn = len(false_negatives)

    precision = n_tp / (n_tp + n_fp) if (n_tp + n_fp) > 0 else 0.0
    recall = n_tp / (n_tp + n_fn) if (n_tp + n_fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    detection_metrics = {
        "true_positives": n_tp,
        "false_positives": n_fp,
        "false_negatives": n_fn,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "mean_iou": round(sum(iou for _, _, iou in true_positives) / n_tp, 4) if n_tp > 0 else 0.0,
    }

    # Stage 2: Transcription metrics (on paired only)
    cer_values = []
    wer_values = []

    for pi, gi, iou in true_positives:
        pred_text = predictions[pi].get("text", "")
        gt_text = ground_truth[gi].get("text", "")

        if gt_text:  # Only compute if GT has text
            cer_values.append(compute_cer(pred_text, gt_text))
            wer_values.append(compute_wer(pred_text, gt_text))

    transcription_metrics = {
        "evaluated_count": len(cer_values),
        "mean_cer": round(sum(cer_values) / len(cer_values), 4) if cer_values else 0.0,
        "mean_wer": round(sum(wer_values) / len(wer_values), 4) if wer_values else 0.0,
    }

    # Stage 3: Parsing accuracy (on paired only)
    parsing_correct = 0
    parsing_total = 0

    for pi, gi, iou in true_positives:
        pred_parsed = predictions[pi].get("parsed", {})
        gt_parsed = ground_truth[gi].get("parsed", {})

        if gt_parsed:
            result = compute_parsing_accuracy(pred_parsed, gt_parsed)
            parsing_correct += result["correct"]
            parsing_total += result["total"]

    parsing_metrics = {
        "fields_correct": parsing_correct,
        "fields_total": parsing_total,
        "accuracy": round(parsing_correct / parsing_total, 4) if parsing_total > 0 else 0.0,
    }

    # Stage 4: Class-level breakdown
    class_breakdown = {}
    for pi, gi, iou in true_positives:
        pred_class = predictions[pi].get("class", "Unknown")
        gt_class = ground_truth[gi].get("class", "Unknown")

        key = gt_class
        if key not in class_breakdown:
            class_breakdown[key] = {"tp": 0, "class_match": 0}
        class_breakdown[key]["tp"] += 1
        if pred_class == gt_class:
            class_breakdown[key]["class_match"] += 1

    return {
        "detection": detection_metrics,
        "transcription": transcription_metrics,
        "parsing": parsing_metrics,
        "class_breakdown": class_breakdown,
        "summary": {
            "detection_f1": detection_metrics["f1"],
            "mean_cer": transcription_metrics["mean_cer"],
            "parsing_accuracy": parsing_metrics["accuracy"],
            "bottleneck": _identify_bottleneck(
                detection_metrics, transcription_metrics, parsing_metrics
            ),
        },
    }


def _identify_bottleneck(
    det: Dict[str, Any], trans: Dict[str, Any], parse: Dict[str, Any],
) -> str:
    """Identify the weakest pipeline stage."""
    scores = {
        "detection": det["f1"],
        "transcription": 1.0 - trans["mean_cer"],  # Lower CER = better
        "parsing": parse["accuracy"],
    }

    if not scores:
        return "unknown"

    return min(scores, key=scores.get)


def evaluate_batch(
    all_predictions: List[List[Dict[str, Any]]],
    all_ground_truth: List[List[Dict[str, Any]]],
    iou_threshold: float = 0.3,
) -> Dict[str, Any]:
    """
    Evaluate across multiple pages and aggregate.

    Returns:
        Aggregated metrics across all pages
    """
    page_results = []

    for preds, gts in zip(all_predictions, all_ground_truth):
        page_results.append(evaluate_page(preds, gts, iou_threshold))

    if not page_results:
        return {"pages": 0}

    # Aggregate
    n_pages = len(page_results)

    total_tp = sum(r["detection"]["true_positives"] for r in page_results)
    total_fp = sum(r["detection"]["false_positives"] for r in page_results)
    total_fn = sum(r["detection"]["false_negatives"] for r in page_results)

    agg_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    agg_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    agg_f1 = 2 * agg_precision * agg_recall / (agg_precision + agg_recall) if (agg_precision + agg_recall) > 0 else 0.0

    mean_cer = sum(r["transcription"]["mean_cer"] for r in page_results) / n_pages
    mean_parse_acc = sum(r["parsing"]["accuracy"] for r in page_results) / n_pages

    return {
        "pages": n_pages,
        "aggregate_detection": {
            "precision": round(agg_precision, 4),
            "recall": round(agg_recall, 4),
            "f1": round(agg_f1, 4),
        },
        "aggregate_transcription": {
            "mean_cer": round(mean_cer, 4),
        },
        "aggregate_parsing": {
            "accuracy": round(mean_parse_acc, 4),
        },
        "bottleneck": _identify_bottleneck(
            {"f1": agg_f1},
            {"mean_cer": mean_cer},
            {"accuracy": mean_parse_acc},
        ),
        "per_page": page_results,
    }


def print_evaluation_table(results: Dict[str, Any]) -> None:
    """Print a formatted evaluation summary table."""
    print("\n" + "=" * 60)
    print("PIPELINE EVALUATION RESULTS")
    print("=" * 60)

    if "aggregate_detection" in results:
        # Batch results
        det = results["aggregate_detection"]
        trans = results["aggregate_transcription"]
        parse = results["aggregate_parsing"]
        print(f"Pages evaluated: {results['pages']}")
    elif "detection" in results:
        # Single page
        det = results["detection"]
        trans = results["transcription"]
        parse = results["parsing"]
        print("Single page evaluation")
    else:
        print("No results to display")
        return

    print(f"\n{'Stage':<20} {'Metric':<20} {'Value':<10}")
    print("-" * 50)
    print(f"{'Detection':<20} {'Precision':<20} {det.get('precision', 'N/A')}")
    print(f"{'':<20} {'Recall':<20} {det.get('recall', 'N/A')}")
    print(f"{'':<20} {'F1':<20} {det.get('f1', 'N/A')}")
    print(f"{'Transcription':<20} {'Mean CER':<20} {trans.get('mean_cer', 'N/A')}")
    print(f"{'Parsing':<20} {'Accuracy':<20} {parse.get('accuracy', 'N/A')}")

    bottleneck = results.get("bottleneck", results.get("summary", {}).get("bottleneck", "unknown"))
    print(f"\n>>> Bottleneck stage: {bottleneck.upper()}")
    print("=" * 60)
