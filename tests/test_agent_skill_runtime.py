"""Phase 1 registry, validation, accounting, and test-endpoint checks."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from ai_inspector.agent_skills import (
    ManifestValidationError,
    PromptSection,
    RegistryValidationError,
    SkillRegistry,
    SkillRuntimeError,
    SkillRuntimeSettings,
    WorkflowRegistry,
    compose_prompt_sections,
)


SKILL_ROOT = REPO_ROOT / "ai_inspector" / "agent_skills"
WORKFLOW_ROOT = REPO_ROOT / "ai_inspector" / "agent_workflows"


def _expect_raises(error_type, action, contains: str = ""):
    try:
        action()
    except error_type as exc:
        if contains:
            assert contains in str(exc), str(exc)
        return exc
    raise AssertionError(f"Expected {error_type.__name__}")


def _write_skill(
    root: Path,
    skill_id: str,
    version: str,
    *,
    dependencies: tuple[str, ...] = (),
    body: str = "# Test Skill\n\nUse validated evidence.",
) -> Path:
    package = root / skill_id
    package.mkdir(parents=True)
    dependency_lines = "\n".join(f"  - {item}" for item in dependencies)
    depends_value = f"\n{dependency_lines}" if dependency_lines else " []"
    manifest = (
        "schema_version: 1\n"
        f"id: {skill_id}\n"
        f"version: {version}\n"
        "description: Test skill package.\n"
        "agents:\n  - sage\n"
        "workflows:\n  - test-workflow\n"
        "modes:\n  - report_fai\n"
        "requires_context: []\n"
        "optional_context: []\n"
        "allowed_tools: []\n"
        "side_effects: []\n"
        f"depends_on:{depends_value}\n"
        "conflicts_with: []\n"
        "composable_with: []\n"
        "evidence_policy: computed_fields_only\n"
    )
    (package / "manifest.yaml").write_text(manifest, encoding="ascii")
    (package / "SKILL.md").write_text(
        "---\n"
        f"name: {skill_id}\n"
        "description: Test runtime skill.\n"
        "---\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return package


def test_production_catalog_loads_and_schema_documents_match():
    workflows = WorkflowRegistry.from_roots(
        [WORKFLOW_ROOT],
        known_agents={"sage", "iris", "scout"},
    )
    skills = SkillRegistry.from_roots(
        [SKILL_ROOT],
        workflow_ids=set(workflows.ids),
        known_agents={"sage", "iris", "scout"},
        known_modes={"report_fai", "report", "drawing", "assembly"},
        known_tools_by_agent={
            "sage": {"ui_actions", "highlight_features"},
            "iris": set(),
            "scout": set(),
        },
    )
    workflow = workflows.get("supplier-fai-disposition")
    skill = skills.get("assess-fai-characteristic")
    assert workflow.manifest.version == "1.0.0"
    assert skill.manifest.version == "1.0.0"
    assert skill.body_sha256 == "7281a9966de5255d675becca0a43c3248857b0f80313909af3a490a84847c6a3"
    assert "100006" not in skill.body
    assert skills.ids == {
        "assess-fai-characteristic",
        "recommend-fai-disposition",
        "reason-about-part-features",
        "reason-about-assembly-context",
        "trace-assembly-impact",
        "reason-about-motion",
        "control-cad-viewport",
    }
    for skill_id in skills.ids:
        package = skills.get(skill_id)
        assert all(byte < 128 for byte in (package.path / "SKILL.md").read_bytes())
        assert "100006" not in package.body

    skill_schema = json.loads(
        (SKILL_ROOT / "schemas" / "skill-manifest.schema.json").read_text(encoding="ascii")
    )
    workflow_schema = json.loads(
        (WORKFLOW_ROOT / "schemas" / "workflow-manifest.schema.json").read_text(encoding="ascii")
    )
    assert set(skill_schema["required"]) == set(skill_schema["properties"])
    assert set(workflow_schema["required"]) == set(workflow_schema["properties"])


def test_semver_latest_and_exact_version_resolution():
    with tempfile.TemporaryDirectory() as temp_dir:
        base = Path(temp_dir)
        first = base / "first"
        second = base / "second"
        first.mkdir()
        second.mkdir()
        _write_skill(first, "versioned-skill", "1.2.0")
        _write_skill(second, "versioned-skill", "1.10.0")
        registry = SkillRegistry.from_roots(
            [first, second],
            workflow_ids={"test-workflow"},
        )
        assert registry.versions("versioned-skill") == ("1.2.0", "1.10.0")
        assert registry.get("versioned-skill").manifest.version == "1.10.0"
        assert registry.get("versioned-skill", "1.2.0").manifest.version == "1.2.0"
        _expect_raises(
            RegistryValidationError,
            lambda: registry.get("versioned-skill", "2.0.0"),
            "unknown skill version",
        )


def test_manifest_rejects_non_ascii_duplicate_keys_and_unknown_fields():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        package = _write_skill(root, "strict-skill", "1.0.0")
        skill_path = package / "SKILL.md"
        skill_path.write_text(
            "---\nname: strict-skill\ndescription: Bad text.\n---\n\nUses +/- and \u00b1.\n",
            encoding="utf-8",
        )
        _expect_raises(
            ManifestValidationError,
            lambda: SkillRegistry.from_roots([root], workflow_ids={"test-workflow"}),
            "ASCII-only",
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        package = _write_skill(root, "duplicate-skill", "1.0.0")
        manifest_path = package / "manifest.yaml"
        original = manifest_path.read_text(encoding="ascii")
        manifest_path.write_text(original + "id: duplicate-skill\n", encoding="ascii")
        _expect_raises(
            ManifestValidationError,
            lambda: SkillRegistry.from_roots([root], workflow_ids={"test-workflow"}),
            "duplicate key",
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        package = _write_skill(root, "unknown-field-skill", "1.0.0")
        manifest_path = package / "manifest.yaml"
        original = manifest_path.read_text(encoding="ascii")
        manifest_path.write_text(original + "surprise: true\n", encoding="ascii")
        _expect_raises(
            ManifestValidationError,
            lambda: SkillRegistry.from_roots([root], workflow_ids={"test-workflow"}),
            "unknown keys",
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        package = _write_skill(root, "alias-skill", "1.0.0")
        manifest_path = package / "manifest.yaml"
        original = manifest_path.read_text(encoding="ascii")
        manifest_path.write_text(
            original.replace("agents:\n  - sage", "agents: &agents\n  - sage").replace(
                "modes:\n  - report_fai", "modes: *agents"
            ),
            encoding="ascii",
        )
        _expect_raises(
            ManifestValidationError,
            lambda: SkillRegistry.from_roots([root], workflow_ids={"test-workflow"}),
            "aliases are not allowed",
        )


def test_registry_rejects_unknown_references_and_dependency_cycles():
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _write_skill(root, "depends-on-missing", "1.0.0", dependencies=("missing-skill",))
        _expect_raises(
            RegistryValidationError,
            lambda: SkillRegistry.from_roots([root], workflow_ids={"test-workflow"}),
            "unknown skills",
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        _write_skill(root, "cycle-a", "1.0.0", dependencies=("cycle-b",))
        _write_skill(root, "cycle-b", "1.0.0", dependencies=("cycle-a",))
        _expect_raises(
            RegistryValidationError,
            lambda: SkillRegistry.from_roots([root], workflow_ids={"test-workflow"}),
            "dependency cycle",
        )


def test_selection_enforces_agent_workflow_mode_and_skill_limit():
    workflows = WorkflowRegistry.from_roots([WORKFLOW_ROOT])
    skills = SkillRegistry.from_roots(
        [SKILL_ROOT],
        workflow_ids=set(workflows.ids),
    )
    selected = skills.resolve_selection(
        primary_id="assess-fai-characteristic",
        supporting_ids=[],
        agent="sage",
        workflow_id="supplier-fai-disposition",
        mode="report_fai",
    )
    assert [package.manifest.id for package in selected] == ["assess-fai-characteristic"]
    _expect_raises(
        RegistryValidationError,
        lambda: skills.resolve_selection(
            primary_id="assess-fai-characteristic",
            supporting_ids=[],
            agent="iris",
            workflow_id="supplier-fai-disposition",
            mode="report_fai",
        ),
        "not allowed for agent",
    )


def test_prompt_section_accounting_is_exact_and_deterministic():
    sections = (
        PromptSection(id="core.sage", content="alpha", source="test", kind="core"),
        PromptSection(id="skill.test", content="beta\ngamma", source="test", kind="skill"),
    )
    first = compose_prompt_sections(sections)
    second = compose_prompt_sections(sections)
    assert first.prompt == "alpha\n\nbeta\ngamma"
    assert first.accounting == second.accounting
    assert first.accounting["total_chars"] == len(first.prompt)
    assert first.accounting["section_count"] == 2
    assert first.accounting["separator_chars"] == 2
    assert sum(row["chars"] for row in first.accounting["sections"]) + 2 == len(first.prompt)
    _expect_raises(
        SkillRuntimeError,
        lambda: compose_prompt_sections((sections[0], sections[0])),
        "must be unique",
    )


def test_feature_flag_parsing_is_strict():
    settings = SkillRuntimeSettings.from_env(
        {
            "INSPECTORPRO_SKILLS_ENABLED": "true",
            "INSPECTORPRO_SKILLS_SHADOW": "0",
            "INSPECTORPRO_SKILL_ROUTER_MODEL": "test-router",
        }
    )
    assert settings.enabled is True
    assert settings.shadow is False
    assert settings.router_model == "test-router"
    _expect_raises(
        SkillRuntimeError,
        lambda: SkillRuntimeSettings.from_env({"INSPECTORPRO_SKILLS_ENABLED": "maybe"}),
        "invalid boolean",
    )


def test_internal_test_compose_is_gated_and_does_not_mutate_production_prompts():
    import server
    from fastapi import HTTPException

    tracked = (
        "INSPECTORPRO_SKILLS_ENABLED",
        "INSPECTORPRO_SKILLS_SHADOW",
        "INSPECTORPRO_SKILL_ROUTER_MODEL",
    )
    original_env = {key: os.environ.get(key) for key in tracked}
    original_prompts = dict(server.AGENT_PROMPTS)
    try:
        os.environ["INSPECTORPRO_SKILLS_ENABLED"] = "0"
        os.environ["INSPECTORPRO_SKILLS_SHADOW"] = "0"
        server._reset_agent_skill_runtime_cache_for_tests()
        status = asyncio.run(server.agent_skill_runtime_status())
        assert status["phase"] == 5
        assert status["production_chat_integration"] is False
        assert status["runtime_loaded"] is False
        assert status["skills"] == []
        request = server.AgentSkillTestComposeRequest(include_skill_bodies=True)
        error = _expect_raises(
            HTTPException,
            lambda: asyncio.run(server.agent_skill_test_compose(request)),
        )
        assert error.status_code == 404

        os.environ["INSPECTORPRO_SKILLS_ENABLED"] = "1"
        server._reset_agent_skill_runtime_cache_for_tests()
        status = asyncio.run(server.agent_skill_runtime_status())
        assert status["phase"] == 5
        assert status["production_chat_integration"] is True
        assert status["runtime_loaded"] is True
        assert len(status["skills"]) == 7
        assert status["skills"][0]["id"] == "assess-fai-characteristic"
        result = asyncio.run(server.agent_skill_test_compose(request))
        assert result["production_chat_integration"] is True
        assert result["workflow"] == {"id": "supplier-fai-disposition", "version": "1.0.0"}
        assert result["selection"][0]["id"] == "assess-fai-characteristic"
        assert result["selection"][0]["side_effects"] == []
        assert "[SKILL assess-fai-characteristic@1.0.0]" in result["skill_prompt"]
        assert result["prompt_accounting"]["section_count"] == 4
        assert server.AGENT_PROMPTS == original_prompts
        assert "[SKILL assess-fai-characteristic" not in server.AGENT_PROMPTS["deviation-analyst"]
    finally:
        for key, value in original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        server._reset_agent_skill_runtime_cache_for_tests()


def _run_without_pytest() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"{len(tests) - failures} passed, {failures} failed")
    return failures


if __name__ == "__main__":
    raise SystemExit(_run_without_pytest())
