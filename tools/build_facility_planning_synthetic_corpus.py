"""Generate and verify the illustrative Facility Planning corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_inspector.facility_layout.host import build_private_local_asset_catalog
from ai_inspector.facility_layout.synthetic_planning_corpus import (
    evaluate_synthetic_facility_corpus,
)


DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "generated"
    / "facility_planning"
    / "synthetic-corpus"
    / "v1"
)


def _validated_output_root(output_root: str | Path) -> Path:
    output = Path(output_root).resolve()
    generated_root = (PROJECT_ROOT / "generated" / "facility_planning").resolve()
    if output == generated_root or generated_root not in output.parents:
        raise ValueError(
            "Synthetic corpus output must be a child of "
            f"{generated_root}; received {output}."
        )
    return output


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, values: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(item, sort_keys=True, ensure_ascii=True) + "\n"
            for item in values
        ),
        encoding="utf-8",
    )


def build_corpus(output_root: str | Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    output = _validated_output_root(output_root)
    catalog = build_private_local_asset_catalog(PROJECT_ROOT)
    evaluation = evaluate_synthetic_facility_corpus(catalog)

    temporary = output.with_name(f"{output.name}.building")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True, exist_ok=True)

    manifest_examples = []
    for example in evaluation["examples"]:
        package = example["package"]
        metadata = example["metadata"]
        package_id = str(package["packageId"])
        package_relative = Path("packages") / metadata["split"] / f"{package_id}.json"
        layout_relative = Path("layouts") / metadata["split"] / f"{package_id}.json"
        _write_json(temporary / package_relative, package)
        _write_json(temporary / layout_relative, example["layout"])
        manifest_examples.append(
            {
                "packageId": package_id,
                "displayName": package["displayName"],
                "archetypeId": metadata["archetypeId"],
                "variantId": metadata["variantId"],
                "split": metadata["split"],
                "traits": metadata["traits"],
                "packagePath": package_relative.as_posix(),
                "layoutPath": layout_relative.as_posix(),
                "packageRevision": example["packageRevision"],
                "compileRevision": example["compileRevision"],
                "facilityProgramRevision": example["facilityProgramRevision"],
                "operationPlanRevision": example["operationPlanRevision"],
                "layoutRevision": example["layoutRevision"],
                "counts": example["counts"],
                "receiptCount": example["receiptCount"],
                "saved": example["saved"],
                "authority": "illustrative",
                "productionEligible": False,
            }
        )

    manifest = {
        "schemaVersion": "facility-planning-synthetic-corpus-manifest-v1",
        "corpusId": evaluation["corpusId"],
        "corpusRevision": evaluation["corpusRevision"],
        "authority": evaluation["authority"],
        "summary": evaluation["summary"],
        "examples": manifest_examples,
    }
    report = {
        "schemaVersion": evaluation["schemaVersion"],
        "corpusId": evaluation["corpusId"],
        "corpusRevision": evaluation["corpusRevision"],
        "authority": evaluation["authority"],
        "summary": evaluation["summary"],
        "results": [
            {
                key: value
                for key, value in item.items()
                if key not in {"package", "layout"}
            }
            for item in evaluation["examples"]
        ],
        "negativeEvaluation": evaluation["negativeEvaluation"],
    }
    _write_json(temporary / "manifest.json", manifest)
    _write_json(temporary / "evaluation-report.json", report)
    _write_json(
        temporary / "negative-cases.json",
        evaluation["negativeEvaluation"],
    )
    _write_jsonl(temporary / "intent-cases.jsonl", evaluation["intentCases"])

    if output.exists():
        shutil.rmtree(output)
    temporary.replace(output)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    manifest = build_corpus(args.output)
    if args.summary:
        print(json.dumps(manifest["summary"], indent=2, sort_keys=True))
    else:
        print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
