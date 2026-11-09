"""Model-only trusted dependency discovery, without executing uploaded modules."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_inspector.facility_layout import model_import_runtime as module
from ai_inspector.packaging_shipping import sources


def packages(root):
    for name in ("numpy", "PIL"):
        folder = root / name
        folder.mkdir(parents=True)
        (folder / "__init__.py").write_bytes(b"")
    return lambda name: SimpleNamespace(origin=str(root / name / "__init__.py"))


def test_user_site_dependencies_override_default_purelib(tmp_path, monkeypatch):
    user = tmp_path / "user-site"
    pure = tmp_path / "purelib"
    pure.mkdir()
    monkeypatch.setattr(sources, "_RUNTIME", None)
    monkeypatch.setattr(sources.sysconfig, "get_path", lambda _: str(pure))
    monkeypatch.setattr(module, "find_spec", packages(user))
    assert module.model_import_runtime().dependency_root == user.resolve()
    assert sources.glb_runtime().dependency_root == pure.resolve()  # Packaging is unchanged.


def test_configured_runtime_wins_without_discovery(tmp_path, monkeypatch):
    runtime = sources.GlbRuntime(tmp_path)
    monkeypatch.setattr(sources, "_RUNTIME", runtime)
    monkeypatch.setattr(module, "find_spec", lambda _: pytest.fail("Configured runtime must win"))
    assert module.model_import_runtime() is runtime


@pytest.mark.parametrize("case", ["missing", "split", "relative", "no_origin", "linked", "linked_init"])
def test_unusable_specs_fall_back_to_purelib(tmp_path, monkeypatch, case):
    pure = tmp_path / "purelib"
    pure.mkdir()
    specs = packages(tmp_path / "user-site")
    other = packages(tmp_path / "other-site")
    if case == "missing":
        specs = lambda _: None
    elif case == "split":
        original = specs
        specs = lambda name: original(name) if name == "numpy" else other(name)
    elif case == "relative":
        specs = lambda name: SimpleNamespace(origin=f"user-site/{name}/__init__.py")
    elif case == "no_origin":
        specs = lambda _: SimpleNamespace(origin=None)
    else:
        original_link = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink",
                            lambda p: p.name == ("__init__.py" if case == "linked_init" else "numpy") or original_link(p))
    monkeypatch.setattr(sources, "_RUNTIME", None)
    monkeypatch.setattr(sources.sysconfig, "get_path", lambda _: str(pure))
    monkeypatch.setattr(module, "find_spec", specs)
    assert module.model_import_runtime().dependency_root == pure.resolve()


def test_junction_in_package_chain_is_rejected(tmp_path, monkeypatch):
    pure = tmp_path / "purelib"
    pure.mkdir()
    monkeypatch.setattr(module, "find_spec", packages(tmp_path / "user-site"))
    monkeypatch.setattr(Path, "is_junction", lambda p: p.name == "user-site", raising=False)
    monkeypatch.setattr(sources, "_RUNTIME", None)
    monkeypatch.setattr(sources.sysconfig, "get_path", lambda _: str(pure))
    assert module.model_import_runtime().dependency_root == pure.resolve()
