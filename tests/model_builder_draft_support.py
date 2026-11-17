"""Temporary-root MB4a fixtures; real kernel, cheap protocol-shaped pictures."""
from types import SimpleNamespace

from ai_inspector.industrial_assets.model_builder import drafts, protocol
from ai_inspector.industrial_assets.model_builder.build import build_model
from ai_inspector.industrial_assets.model_builder.recipe import normalize_recipe
from ai_inspector.industrial_assets.model_builder.job_io import validate_allowed
from ai_inspector.facility_layout.model_import_store import ModelImportStore
from tests.model_import_store_support import PNG, WEBP, layout_reader, inspect_worker, prepare_worker
from tests.model_builder_test_support import recipe


def write_build(raw, destination, cancel, *, dependency_root, categories, appearance_ids,
                scope, created, include_catalog=None, derived_from=None):
    allowed = validate_allowed({"categories": list(categories), "appearanceIds": list(appearance_ids)})
    normalized = normalize_recipe(raw, allowed_categories=categories, allowed_appearance_ids=appearance_ids)
    sources = include_catalog.resolve_recipe(normalized) if include_catalog is not None else None
    built = build_model(normalized, allowed_categories=categories, allowed_appearance_ids=appearance_ids,
                        include_sources=sources)
    result = protocol.make_result(built, allowed)
    return drafts.write_draft(destination, built.recipe, result, built.glb, PNG, WEBP,
                              scope=scope, created=created, derived_from=derived_from)


def store(tmp_path, **options):
    return ModelImportStore(tmp_path, layout_reader=layout_reader,
                            runtime=lambda: SimpleNamespace(dependency_root=tmp_path),
                            inspect_worker=inspect_worker, prepare_worker=prepare_worker,
                            build_worker=options.pop("build_worker", write_build), **options)


def build(store, scope, raw=None, cancel=None, **options):
    raw = raw or recipe()
    return store.build(scope, raw, cancel, categories=[raw["category"]], appearance_ids=[], **options)


def project(tmp_path):
    from ai_inspector.industrial_assets.authored_library import CATALOG
    from ai_inspector.facility_layout.model_import_files import encode
    root = tmp_path / "project"
    target = root / CATALOG
    target.parent.mkdir(parents=True)
    target.write_bytes(encode({"schemaVersion": 1, "assets": [], "summary": {"total": 0}}))
    return root
