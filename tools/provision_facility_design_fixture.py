"""Provision the reviewed FDL material-travel fixture in a local repository."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.authorization import local_facility_principal
from ai_inspector.facility_layout.authority_repository import (
    FacilityShellRepository,
    PolicySetRepository,
    authority_revision,
)
from ai_inspector.facility_layout.canonical import (
    canonical_layout_bytes,
    canonicalize_layout,
)
from ai_inspector.facility_layout.design_fixture import (
    REVIEWED_MATERIAL_TRAVEL_LAYOUT_ID,
    REVIEWED_REFERENCE_MATERIAL_TRAVEL_LAYOUT_ID,
    reviewed_material_travel_authority_documents,
    reviewed_material_travel_layout,
    reviewed_material_travel_source_provider,
    reviewed_reference_material_travel_layout,
)
from ai_inspector.facility_layout.errors import FacilityNotFoundError
from ai_inspector.facility_layout.repository import FacilityLayoutRepository


def _ensure_published(repository, principal, site_id, document, id_field):
    published = deepcopy(document)
    expected_revision = authority_revision(published)
    authority_id = published[id_field]
    try:
        current = repository.get_published(
            principal,
            site_id=site_id,
            authority_id=authority_id,
            revision=expected_revision,
        )
        return current, False
    except FacilityNotFoundError:
        pass

    draft = deepcopy(published)
    draft["status"] = "draft"
    try:
        current = repository.get_current(
            principal,
            site_id=site_id,
            authority_id=authority_id,
        )
    except FacilityNotFoundError:
        current = repository.create(
            principal,
            site_id=site_id,
            document=draft,
        ).envelope
    if current.status == "draft":
        if current.document != draft:
            raise RuntimeError(
                f"Existing test authority {authority_id} differs from the reviewed fixture."
            )
        current = repository.review(
            principal,
            site_id=site_id,
            authority_id=authority_id,
            expected_revision=current.revision,
        ).envelope
    if current.status == "reviewed":
        current = repository.publish(
            principal,
            site_id=site_id,
            authority_id=authority_id,
            expected_revision=current.revision,
        ).envelope
    if current.revision != expected_revision or current.document != published:
        raise RuntimeError(
            f"Published test authority {authority_id} does not match the reviewed fixture."
        )
    return current, True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        default=str(Path(".runtime") / "facility-layout"),
    )
    parser.add_argument("--site-id", default="site-local")
    arguments = parser.parse_args()

    root = Path(arguments.root)
    repository = FacilityLayoutRepository(root / "layouts")
    principal = local_facility_principal(site_id=arguments.site_id)
    authorities = reviewed_material_travel_authority_documents(
        site_id=arguments.site_id
    )
    shell, shell_created = _ensure_published(
        FacilityShellRepository(root / "authorities" / "shells"),
        principal,
        arguments.site_id,
        authorities["facilityShell"],
        "shellId",
    )
    policy, policy_created = _ensure_published(
        PolicySetRepository(root / "authorities" / "policies"),
        principal,
        arguments.site_id,
        authorities["policySet"],
        "policySetId",
    )
    created = False
    updated = False
    desired = reviewed_material_travel_layout(site_id=arguments.site_id)
    try:
        record = repository.get_layout(
            principal,
            arguments.site_id,
            REVIEWED_MATERIAL_TRAVEL_LAYOUT_ID,
        )
    except FacilityNotFoundError:
        record = repository.create_layout(
            principal,
            arguments.site_id,
            desired,
        )
        created = True
    else:
        candidate = deepcopy(desired)
        candidate["createdAt"] = record["layout"]["createdAt"]
        candidate["updatedAt"] = record["layout"]["updatedAt"]
        candidate = canonicalize_layout(candidate)
        if canonical_layout_bytes(candidate) != canonical_layout_bytes(
            record["layout"]
        ):
            record = repository.save_layout(
                principal,
                arguments.site_id,
                REVIEWED_MATERIAL_TRAVEL_LAYOUT_ID,
                candidate,
                record["revision"],
            )
            updated = True

    source = reviewed_material_travel_source_provider(
        principal,
        arguments.site_id,
        REVIEWED_MATERIAL_TRAVEL_LAYOUT_ID,
        {"document": record["layout"]},
        {},
    )
    reference_created = False
    reference_updated = False
    reference_desired = reviewed_reference_material_travel_layout(
        site_id=arguments.site_id
    )
    try:
        reference_record = repository.get_layout(
            principal,
            arguments.site_id,
            REVIEWED_REFERENCE_MATERIAL_TRAVEL_LAYOUT_ID,
        )
    except FacilityNotFoundError:
        reference_record = repository.create_layout(
            principal,
            arguments.site_id,
            reference_desired,
        )
        reference_created = True
    else:
        reference_candidate = deepcopy(reference_desired)
        reference_candidate["createdAt"] = reference_record["layout"][
            "createdAt"
        ]
        reference_candidate["updatedAt"] = reference_record["layout"][
            "updatedAt"
        ]
        reference_candidate = canonicalize_layout(reference_candidate)
        if canonical_layout_bytes(reference_candidate) != canonical_layout_bytes(
            reference_record["layout"]
        ):
            reference_record = repository.save_layout(
                principal,
                arguments.site_id,
                REVIEWED_REFERENCE_MATERIAL_TRAVEL_LAYOUT_ID,
                reference_candidate,
                reference_record["revision"],
            )
            reference_updated = True
    reference_source = reviewed_material_travel_source_provider(
        principal,
        arguments.site_id,
        REVIEWED_REFERENCE_MATERIAL_TRAVEL_LAYOUT_ID,
        {"document": reference_record["layout"]},
        {},
    )
    print(json.dumps({
        "created": created,
        "updated": updated,
        "layoutId": record["layout"]["layoutId"],
        "revision": record["revision"],
        "facilityShellRevision": shell.revision,
        "policySetRevision": policy.revision,
        "authorityDocumentsCreated": shell_created or policy_created,
        "candidateAuthority": source["candidateAuthority"],
        "reviewedCandidateCount": len(source["reviewedCandidateRecipes"]),
        "reference": {
            "created": reference_created,
            "updated": reference_updated,
            "layoutId": reference_record["layout"]["layoutId"],
            "revision": reference_record["revision"],
            "candidateAuthority": reference_source["candidateAuthority"],
            "reviewedCandidateCount": len(
                reference_source["reviewedCandidateRecipes"]
            ),
        },
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
