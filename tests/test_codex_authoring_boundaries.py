from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from ai_inspector.codex_runtime.policy import PilotSettings
from ai_inspector.facility_layout.decal_images import scope_directory, store_image
from ai_inspector.facility_layout.errors import FacilityValidationError
from ai_inspector.facility_layout.proposal_artifacts import validate_proposal_artwork


@pytest.fixture
def scope(tmp_path):
    return SimpleNamespace(layout_repository=SimpleNamespace(root=tmp_path)), SimpleNamespace(tenant_id="tenant-a")


def test_existing_legacy_artwork_can_be_reused_without_filesystem_access(scope):
    service, principal = scope
    path = "/generated/legacy-artwork.png"
    validate_proposal_artwork(service, principal, "site-a", {"extensions": {"old": {"imagePath": path}}},
                              [{"op": "upsert_decal", "decal": {"imagePath": path}}])


@pytest.mark.parametrize("path", ["C:/private.png", "https://example.com/art.png", "/generated/new-art.png",
    "/api/facility-decal-images/site-b/" + "a" * 64 + ".png",
    "/api/facility-decal-images/site-a/" + "b" * 64 + ".png"])
def test_new_unimported_artwork_is_rejected(scope, path):
    service, principal = scope
    with pytest.raises(FacilityValidationError, match="import|Import"):
        validate_proposal_artwork(service, principal, "site-a", {}, [{"imagePath": path}])


def test_the_site_planners_own_artwork_needs_no_import_but_other_wall_art_still_does(scope):
    from ai_inspector.facility_layout.site_plan import LOGO_IMAGE, TARGET_IMAGE
    service, principal = scope
    validate_proposal_artwork(service, principal, "site-a", {}, [
        {"op": "set_wall_finishes", "artwork": [{"imagePath": LOGO_IMAGE}]},
        {"op": "set_ground", "ground": {"marks": [{"imagePath": TARGET_IMAGE}]}}])
    with pytest.raises(FacilityValidationError, match="import|Import"):
        validate_proposal_artwork(service, principal, "site-a", {},
                                  [{"imagePath": "/generated/facility-wall-art/" + "c" * 64 + ".png"}])


def test_only_same_scope_imported_image_is_authorized(scope):
    service, principal = scope
    data = BytesIO()
    Image.new("RGBA", (8, 8), (201, 155, 57, 255)).save(data, format="PNG")
    root = service.layout_repository.root / "decal-images"
    image = store_image(root, principal, "site-a", data.getvalue())
    validate_proposal_artwork(service, principal, "site-a", {}, [{"imagePath": image["imagePath"]}])
    with pytest.raises(FacilityValidationError):
        validate_proposal_artwork(service, SimpleNamespace(tenant_id="tenant-b"), "site-a", {},
                                  [{"imagePath": image["imagePath"]}])
    target = scope_directory(root, principal, "site-a") / image["imagePath"].rsplit("/", 1)[1]
    target.write_bytes(b"")
    with pytest.raises(FacilityValidationError):
        validate_proposal_artwork(service, principal, "site-a", {}, [{"imagePath": image["imagePath"]}])


@pytest.mark.parametrize("editing,calls,seconds", [("0", 8, 120), ("1", 24, 240)])
def test_authoring_budget_is_expanded_but_bounded(tmp_path, monkeypatch, editing, calls, seconds):
    binary = tmp_path / "codex.exe"
    binary.touch()
    for name, value in {
        "INSPECTORPRO_CODEX_BINARY": str(binary), "INSPECTORPRO_CODEX_PILOT_ROOT": str(tmp_path / "isolated"),
        "INSPECTORPRO_CODEX_MODEL": "gpt-5.5", "INSPECTORPRO_CODEX_EDIT_PREVIEWS": editing,
    }.items():
        monkeypatch.setenv(name, value)
    settings = PilotSettings.from_environment()
    assert settings.max_calls == calls and settings.timeout_seconds == seconds
