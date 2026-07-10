"""Strict Phase 1 loader for versioned InspectorPro skills and workflows.

This module has no dependency on server.py and performs no model calls or tool
execution. Production routing remains unchanged until a later rollout phase.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml


_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_TOKEN_RE = re.compile(r"^[a-z][a-z0-9_.-]*$")
_MAX_MANIFEST_BYTES = 128 * 1024
_MAX_SKILL_BYTES = 256 * 1024
_SIDE_EFFECTS = frozenset({"viewport_write", "asset_write", "system_write"})


class SkillRuntimeError(ValueError):
    """Base exception for deterministic skill-runtime failures."""


class ManifestValidationError(SkillRuntimeError):
    """Raised when one package manifest or SKILL.md is invalid."""

    def __init__(self, path: Path, issues: Sequence[str]):
        self.path = Path(path)
        self.issues = tuple(str(issue) for issue in issues)
        joined = "; ".join(self.issues)
        super().__init__(f"{self.path}: {joined}")


class RegistryValidationError(SkillRuntimeError):
    """Raised when individually valid packages form an invalid registry."""

    def __init__(self, issues: Sequence[str]):
        self.issues = tuple(str(issue) for issue in issues)
        super().__init__("; ".join(self.issues))


class _StrictSafeLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            event = self.get_event()
            raise yaml.composer.ComposerError(
                None,
                None,
                f"YAML aliases are not allowed: *{event.anchor}",
                event.start_mark,
            )
        return super().compose_node(parent, index)


def _construct_unique_mapping(loader: _StrictSafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _read_ascii(path: Path, max_bytes: int) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ManifestValidationError(path, [f"cannot read file: {exc}"]) from exc
    if len(raw) > max_bytes:
        raise ManifestValidationError(path, [f"file exceeds {max_bytes} bytes"])
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as exc:
        raise ManifestValidationError(path, [f"must be ASCII-only (byte offset {exc.start})"]) from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _load_yaml_text(text: str, path: Path) -> dict[str, Any]:
    try:
        value = yaml.load(text, Loader=_StrictSafeLoader)
    except yaml.YAMLError as exc:
        raise ManifestValidationError(path, [f"invalid YAML: {exc}"]) from exc
    if not isinstance(value, dict):
        raise ManifestValidationError(path, ["document must be a mapping"])
    if not all(isinstance(key, str) for key in value):
        raise ManifestValidationError(path, ["all keys must be strings"])
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    return _load_yaml_text(_read_ascii(path, _MAX_MANIFEST_BYTES), path)


def _validate_keys(
    data: Mapping[str, Any],
    required: set[str],
    optional: set[str],
    issues: list[str],
) -> None:
    missing = sorted(required - set(data))
    unknown = sorted(set(data) - required - optional)
    if missing:
        issues.append("missing keys: " + ", ".join(missing))
    if unknown:
        issues.append("unknown keys: " + ", ".join(unknown))


def _string_value(
    data: Mapping[str, Any],
    key: str,
    issues: list[str],
    *,
    pattern: re.Pattern[str] | None = None,
    max_length: int = 1000,
) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        issues.append(f"{key} must be a non-empty string")
        return ""
    value = value.strip()
    if len(value) > max_length:
        issues.append(f"{key} exceeds {max_length} characters")
    if pattern is not None and not pattern.fullmatch(value):
        issues.append(f"{key} has invalid format: {value!r}")
    return value


def _string_list(
    data: Mapping[str, Any],
    key: str,
    issues: list[str],
    *,
    required: bool = False,
    pattern: re.Pattern[str] | None = _TOKEN_RE,
) -> tuple[str, ...]:
    value = data.get(key)
    if not isinstance(value, list):
        issues.append(f"{key} must be a list")
        return ()
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            issues.append(f"{key}[{index}] must be a non-empty string")
            continue
        item = item.strip()
        if pattern is not None and not pattern.fullmatch(item):
            issues.append(f"{key}[{index}] has invalid format: {item!r}")
        result.append(item)
    if required and not result:
        issues.append(f"{key} must contain at least one value")
    duplicates = sorted({item for item in result if result.count(item) > 1})
    if duplicates:
        issues.append(f"{key} contains duplicates: " + ", ".join(duplicates))
    return tuple(result)


def parse_semver(value: str) -> tuple[int, int, int]:
    match = _SEMVER_RE.fullmatch(value or "")
    if not match:
        raise ValueError(f"invalid semantic version: {value!r}")
    return tuple(int(group) for group in match.groups())


@dataclass(frozen=True)
class SkillManifest:
    schema_version: int
    id: str
    version: str
    description: str
    agents: tuple[str, ...]
    workflows: tuple[str, ...]
    modes: tuple[str, ...]
    requires_context: tuple[str, ...]
    optional_context: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    side_effects: tuple[str, ...]
    depends_on: tuple[str, ...]
    conflicts_with: tuple[str, ...]
    composable_with: tuple[str, ...]
    evidence_policy: str

    @property
    def version_key(self) -> tuple[int, int, int]:
        return parse_semver(self.version)


@dataclass(frozen=True)
class WorkflowManifest:
    schema_version: int
    id: str
    version: str
    description: str
    agents: tuple[str, ...]
    entry_signals: tuple[str, ...]
    required_assets: tuple[str, ...]
    optional_assets: tuple[str, ...]
    stages: tuple[str, ...]
    completion: tuple[str, ...]

    @property
    def version_key(self) -> tuple[int, int, int]:
        return parse_semver(self.version)


@dataclass(frozen=True)
class SkillPackage:
    manifest: SkillManifest
    body: str
    path: Path
    body_sha256: str


@dataclass(frozen=True)
class WorkflowPackage:
    manifest: WorkflowManifest
    path: Path


@dataclass(frozen=True)
class PromptSection:
    id: str
    content: str
    source: str
    kind: str = "runtime"


@dataclass(frozen=True)
class PromptBuild:
    prompt: str
    accounting: dict[str, Any]


@dataclass(frozen=True)
class SkillRuntimeSettings:
    enabled: bool
    shadow: bool
    router_model: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "SkillRuntimeSettings":
        source = os.environ if env is None else env
        router_model = (source.get("INSPECTORPRO_SKILL_ROUTER_MODEL") or "claude-haiku-4-5").strip()
        if not router_model:
            raise SkillRuntimeError("INSPECTORPRO_SKILL_ROUTER_MODEL must not be blank")
        return cls(
            enabled=_parse_env_bool(source.get("INSPECTORPRO_SKILLS_ENABLED"), False),
            shadow=_parse_env_bool(source.get("INSPECTORPRO_SKILLS_SHADOW"), False),
            router_model=router_model,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "shadow": self.shadow,
            "router_model": self.router_model,
        }


def _parse_env_bool(value: str | None, default: bool) -> bool:
    if value is None or not str(value).strip():
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SkillRuntimeError(f"invalid boolean feature flag value: {value!r}")


def compose_prompt_sections(
    sections: Sequence[PromptSection],
    *,
    separator: str = "\n\n",
) -> PromptBuild:
    if not isinstance(separator, str):
        raise SkillRuntimeError("prompt separator must be a string")
    if not sections:
        raise SkillRuntimeError("at least one prompt section is required")
    ids = [section.id for section in sections]
    if any(not _TOKEN_RE.fullmatch(section_id) for section_id in ids):
        raise SkillRuntimeError("prompt section IDs must use lowercase token syntax")
    if len(ids) != len(set(ids)):
        raise SkillRuntimeError("prompt section IDs must be unique")

    prompt = separator.join(section.content for section in sections)
    rows = []
    for index, section in enumerate(sections):
        rows.append(
            {
                "index": index,
                "id": section.id,
                "kind": section.kind,
                "source": section.source,
                "chars": len(section.content),
                "utf8_bytes": len(section.content.encode("utf-8")),
                "lines": section.content.count("\n") + 1,
                "approx_tokens": math.ceil(len(section.content) / 4),
                "sha256": hashlib.sha256(section.content.encode("utf-8")).hexdigest(),
            }
        )
    accounting = {
        "section_count": len(rows),
        "separator_chars": max(0, len(sections) - 1) * len(separator),
        "total_chars": len(prompt),
        "total_utf8_bytes": len(prompt.encode("utf-8")),
        "total_lines": prompt.count("\n") + 1,
        "total_approx_tokens": math.ceil(len(prompt) / 4),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "sections": rows,
    }
    return PromptBuild(prompt=prompt, accounting=accounting)


_SKILL_REQUIRED_KEYS = {
    "schema_version",
    "id",
    "version",
    "description",
    "agents",
    "workflows",
    "modes",
    "requires_context",
    "optional_context",
    "allowed_tools",
    "side_effects",
    "depends_on",
    "conflicts_with",
    "composable_with",
    "evidence_policy",
}

_WORKFLOW_REQUIRED_KEYS = {
    "schema_version",
    "id",
    "version",
    "description",
    "agents",
    "entry_signals",
    "required_assets",
    "optional_assets",
    "stages",
    "completion",
}


def _load_skill_manifest(path: Path) -> SkillManifest:
    data = _load_yaml(path)
    issues: list[str] = []
    _validate_keys(data, _SKILL_REQUIRED_KEYS, set(), issues)
    schema_version = data.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        issues.append("schema_version must be integer 1")
    skill_id = _string_value(data, "id", issues, pattern=_ID_RE, max_length=63)
    version = _string_value(data, "version", issues, max_length=32)
    try:
        parse_semver(version)
    except ValueError:
        issues.append("version must use MAJOR.MINOR.PATCH numeric SemVer")
    description = _string_value(data, "description", issues, max_length=500)
    agents = _string_list(data, "agents", issues, required=True)
    workflows = _string_list(data, "workflows", issues, required=True, pattern=_ID_RE)
    modes = _string_list(data, "modes", issues, required=True)
    requires_context = _string_list(data, "requires_context", issues)
    optional_context = _string_list(data, "optional_context", issues)
    allowed_tools = _string_list(data, "allowed_tools", issues)
    side_effects = _string_list(data, "side_effects", issues)
    invalid_effects = sorted(set(side_effects) - _SIDE_EFFECTS)
    if invalid_effects:
        issues.append("side_effects contains invalid values: " + ", ".join(invalid_effects))
    depends_on = _string_list(data, "depends_on", issues, pattern=_ID_RE)
    conflicts_with = _string_list(data, "conflicts_with", issues, pattern=_ID_RE)
    composable_with = _string_list(data, "composable_with", issues, pattern=_ID_RE)
    evidence_policy = _string_value(data, "evidence_policy", issues, pattern=_TOKEN_RE, max_length=80)
    if skill_id in set(depends_on) | set(conflicts_with) | set(composable_with):
        issues.append("a skill cannot reference itself")
    if issues:
        raise ManifestValidationError(path, issues)
    return SkillManifest(
        schema_version=1,
        id=skill_id,
        version=version,
        description=description,
        agents=agents,
        workflows=workflows,
        modes=modes,
        requires_context=requires_context,
        optional_context=optional_context,
        allowed_tools=allowed_tools,
        side_effects=side_effects,
        depends_on=depends_on,
        conflicts_with=conflicts_with,
        composable_with=composable_with,
        evidence_policy=evidence_policy,
    )


def _load_workflow_manifest(path: Path) -> WorkflowManifest:
    data = _load_yaml(path)
    issues: list[str] = []
    _validate_keys(data, _WORKFLOW_REQUIRED_KEYS, set(), issues)
    schema_version = data.get("schema_version")
    if type(schema_version) is not int or schema_version != 1:
        issues.append("schema_version must be integer 1")
    workflow_id = _string_value(data, "id", issues, pattern=_ID_RE, max_length=63)
    version = _string_value(data, "version", issues, max_length=32)
    try:
        parse_semver(version)
    except ValueError:
        issues.append("version must use MAJOR.MINOR.PATCH numeric SemVer")
    description = _string_value(data, "description", issues, max_length=500)
    agents = _string_list(data, "agents", issues, required=True)
    entry_signals = _string_list(data, "entry_signals", issues, required=True, pattern=None)
    required_assets = _string_list(data, "required_assets", issues)
    optional_assets = _string_list(data, "optional_assets", issues)
    stages = _string_list(data, "stages", issues, required=True)
    completion = _string_list(data, "completion", issues, required=True, pattern=None)
    if issues:
        raise ManifestValidationError(path, issues)
    return WorkflowManifest(
        schema_version=1,
        id=workflow_id,
        version=version,
        description=description,
        agents=agents,
        entry_signals=entry_signals,
        required_assets=required_assets,
        optional_assets=optional_assets,
        stages=stages,
        completion=completion,
    )


def _load_skill_body(path: Path, expected_id: str) -> tuple[str, str]:
    text = _read_ascii(path, _MAX_SKILL_BYTES)
    if not text.startswith("---\n"):
        raise ManifestValidationError(path, ["SKILL.md must start with YAML frontmatter"])
    closing = text.find("\n---\n", 4)
    if closing < 0:
        raise ManifestValidationError(path, ["SKILL.md frontmatter is not closed"])
    metadata = _load_yaml_text(text[4:closing], path)
    issues: list[str] = []
    _validate_keys(metadata, {"name", "description"}, set(), issues)
    name = _string_value(metadata, "name", issues, pattern=_ID_RE, max_length=63)
    _string_value(metadata, "description", issues, max_length=1000)
    if name and name != expected_id:
        issues.append(f"frontmatter name {name!r} does not match manifest id {expected_id!r}")
    body = text[closing + 5 :].strip()
    if not body:
        issues.append("SKILL.md body must not be empty")
    if issues:
        raise ManifestValidationError(path, issues)
    digest = hashlib.sha256(body.encode("ascii")).hexdigest()
    return body, digest


def _package_dirs(roots: Iterable[Path]) -> list[Path]:
    discovered: list[Path] = []
    for root_value in roots:
        root = Path(root_value).resolve()
        if not root.is_dir():
            raise RegistryValidationError([f"registry root does not exist: {root}"])
        for candidate in sorted(root.iterdir(), key=lambda item: item.name):
            if candidate.is_dir() and (candidate / "manifest.yaml").is_file():
                discovered.append(candidate)
    return discovered


class WorkflowRegistry:
    def __init__(self, packages: Sequence[WorkflowPackage]):
        by_id: dict[str, dict[str, WorkflowPackage]] = {}
        issues: list[str] = []
        for package in packages:
            versions = by_id.setdefault(package.manifest.id, {})
            if package.manifest.version in versions:
                issues.append(
                    f"duplicate workflow {package.manifest.id}@{package.manifest.version}: "
                    f"{versions[package.manifest.version].path} and {package.path}"
                )
            versions[package.manifest.version] = package
        if issues:
            raise RegistryValidationError(issues)
        self._by_id = by_id

    @classmethod
    def from_roots(
        cls,
        roots: Iterable[Path],
        *,
        known_agents: set[str] | None = None,
    ) -> "WorkflowRegistry":
        packages: list[WorkflowPackage] = []
        issues: list[str] = []
        for package_dir in _package_dirs(roots):
            manifest = _load_workflow_manifest(package_dir / "manifest.yaml")
            if package_dir.name != manifest.id:
                issues.append(
                    f"workflow directory {package_dir.name!r} does not match manifest id {manifest.id!r}"
                )
            if known_agents is not None:
                unknown = sorted(set(manifest.agents) - known_agents)
                if unknown:
                    issues.append(f"{manifest.id}@{manifest.version} has unknown agents: {', '.join(unknown)}")
            packages.append(WorkflowPackage(manifest=manifest, path=package_dir))
        if issues:
            raise RegistryValidationError(issues)
        return cls(packages)

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(self._by_id)

    def versions(self, workflow_id: str) -> tuple[str, ...]:
        versions = self._by_id.get(workflow_id, {})
        return tuple(sorted(versions, key=parse_semver))

    def get(self, workflow_id: str, version: str | None = None) -> WorkflowPackage:
        versions = self._by_id.get(workflow_id)
        if not versions:
            raise RegistryValidationError([f"unknown workflow: {workflow_id}"])
        selected = version or max(versions, key=parse_semver)
        if selected not in versions:
            raise RegistryValidationError([f"unknown workflow version: {workflow_id}@{selected}"])
        return versions[selected]

    def metadata_catalog(self) -> list[dict[str, Any]]:
        rows = []
        for workflow_id in sorted(self._by_id):
            package = self.get(workflow_id)
            manifest = package.manifest
            rows.append(
                {
                    "id": manifest.id,
                    "version": manifest.version,
                    "available_versions": list(self.versions(workflow_id)),
                    "description": manifest.description,
                    "agents": list(manifest.agents),
                    "required_assets": list(manifest.required_assets),
                    "optional_assets": list(manifest.optional_assets),
                    "stages": list(manifest.stages),
                }
            )
        return rows


class SkillRegistry:
    def __init__(self, packages: Sequence[SkillPackage]):
        by_id: dict[str, dict[str, SkillPackage]] = {}
        issues: list[str] = []
        for package in packages:
            versions = by_id.setdefault(package.manifest.id, {})
            if package.manifest.version in versions:
                issues.append(
                    f"duplicate skill {package.manifest.id}@{package.manifest.version}: "
                    f"{versions[package.manifest.version].path} and {package.path}"
                )
            versions[package.manifest.version] = package
        if issues:
            raise RegistryValidationError(issues)
        self._by_id = by_id
        self._validate_references()

    @classmethod
    def from_roots(
        cls,
        roots: Iterable[Path],
        *,
        workflow_ids: set[str],
        known_agents: set[str] | None = None,
        known_modes: set[str] | None = None,
        known_tools_by_agent: Mapping[str, set[str]] | None = None,
    ) -> "SkillRegistry":
        packages: list[SkillPackage] = []
        issues: list[str] = []
        for package_dir in _package_dirs(roots):
            manifest = _load_skill_manifest(package_dir / "manifest.yaml")
            body, digest = _load_skill_body(package_dir / "SKILL.md", manifest.id)
            if package_dir.name != manifest.id:
                issues.append(f"skill directory {package_dir.name!r} does not match manifest id {manifest.id!r}")
            unknown_workflows = sorted(set(manifest.workflows) - workflow_ids)
            if unknown_workflows:
                issues.append(
                    f"{manifest.id}@{manifest.version} has unknown workflows: {', '.join(unknown_workflows)}"
                )
            if known_agents is not None:
                unknown_agents = sorted(set(manifest.agents) - known_agents)
                if unknown_agents:
                    issues.append(
                        f"{manifest.id}@{manifest.version} has unknown agents: {', '.join(unknown_agents)}"
                    )
            if known_modes is not None:
                unknown_modes = sorted(set(manifest.modes) - known_modes)
                if unknown_modes:
                    issues.append(f"{manifest.id}@{manifest.version} has unknown modes: {', '.join(unknown_modes)}")
            if known_tools_by_agent is not None:
                for agent in manifest.agents:
                    allowed = known_tools_by_agent.get(agent)
                    if allowed is None:
                        continue
                    invalid_tools = sorted(set(manifest.allowed_tools) - allowed)
                    if invalid_tools:
                        issues.append(
                            f"{manifest.id}@{manifest.version} tools unavailable to {agent}: "
                            + ", ".join(invalid_tools)
                        )
            packages.append(
                SkillPackage(
                    manifest=manifest,
                    body=body,
                    path=package_dir,
                    body_sha256=digest,
                )
            )
        if issues:
            raise RegistryValidationError(issues)
        return cls(packages)

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(self._by_id)

    def versions(self, skill_id: str) -> tuple[str, ...]:
        versions = self._by_id.get(skill_id, {})
        return tuple(sorted(versions, key=parse_semver))

    def get(self, skill_id: str, version: str | None = None) -> SkillPackage:
        versions = self._by_id.get(skill_id)
        if not versions:
            raise RegistryValidationError([f"unknown skill: {skill_id}"])
        selected = version or max(versions, key=parse_semver)
        if selected not in versions:
            raise RegistryValidationError([f"unknown skill version: {skill_id}@{selected}"])
        return versions[selected]

    def _validate_references(self) -> None:
        issues: list[str] = []
        all_ids = set(self._by_id)
        for skill_id in sorted(all_ids):
            for package in self._by_id[skill_id].values():
                manifest = package.manifest
                for field_name, references in (
                    ("depends_on", manifest.depends_on),
                    ("conflicts_with", manifest.conflicts_with),
                    ("composable_with", manifest.composable_with),
                ):
                    unknown = sorted(set(references) - all_ids)
                    if unknown:
                        issues.append(
                            f"{manifest.id}@{manifest.version} {field_name} has unknown skills: "
                            + ", ".join(unknown)
                        )

        active = {skill_id: self.get(skill_id).manifest for skill_id in all_ids}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(skill_id: str, trail: list[str]) -> None:
            if skill_id in visiting:
                start = trail.index(skill_id) if skill_id in trail else 0
                issues.append("skill dependency cycle: " + " -> ".join(trail[start:] + [skill_id]))
                return
            if skill_id in visited:
                return
            visiting.add(skill_id)
            for dependency in active[skill_id].depends_on:
                if dependency in active:
                    visit(dependency, trail + [skill_id])
            visiting.remove(skill_id)
            visited.add(skill_id)

        for skill_id in sorted(active):
            visit(skill_id, [])
        if issues:
            raise RegistryValidationError(issues)

    def resolve_selection(
        self,
        *,
        primary_id: str,
        supporting_ids: Sequence[str],
        agent: str,
        workflow_id: str,
        mode: str,
    ) -> tuple[SkillPackage, ...]:
        requested = [primary_id, *supporting_ids]
        if len(requested) != len(set(requested)):
            raise RegistryValidationError(["selected skill IDs must be unique"])
        selected: list[SkillPackage] = []
        selected_ids: set[str] = set()

        def add_skill(skill_id: str) -> None:
            if skill_id in selected_ids:
                return
            package = self.get(skill_id)
            for dependency in package.manifest.depends_on:
                add_skill(dependency)
            selected.append(package)
            selected_ids.add(skill_id)

        for skill_id in requested:
            add_skill(skill_id)
        if len(selected) > 4:
            raise RegistryValidationError(["selection exceeds one primary plus three supporting skills"])

        issues: list[str] = []
        for package in selected:
            manifest = package.manifest
            if agent not in manifest.agents:
                issues.append(f"skill {manifest.id} is not allowed for agent {agent}")
            if workflow_id not in manifest.workflows:
                issues.append(f"skill {manifest.id} is not allowed in workflow {workflow_id}")
            if mode not in manifest.modes:
                issues.append(f"skill {manifest.id} is not allowed in mode {mode}")
            conflicts = sorted(set(manifest.conflicts_with) & selected_ids)
            if conflicts:
                issues.append(f"skill {manifest.id} conflicts with: {', '.join(conflicts)}")
        if issues:
            raise RegistryValidationError(issues)
        return tuple(selected)

    def prompt_sections(self, packages: Sequence[SkillPackage]) -> tuple[PromptSection, ...]:
        sections = []
        for package in packages:
            manifest = package.manifest
            content = f"[SKILL {manifest.id}@{manifest.version}]\n{package.body}\n[/SKILL]"
            sections.append(
                PromptSection(
                    id=f"skill.{manifest.id}",
                    content=content,
                    source=f"{manifest.id}@{manifest.version}/SKILL.md",
                    kind="skill",
                )
            )
        return tuple(sections)

    def metadata_catalog(self) -> list[dict[str, Any]]:
        rows = []
        for skill_id in sorted(self._by_id):
            package = self.get(skill_id)
            manifest = package.manifest
            rows.append(
                {
                    "id": manifest.id,
                    "version": manifest.version,
                    "available_versions": list(self.versions(skill_id)),
                    "description": manifest.description,
                    "agents": list(manifest.agents),
                    "workflows": list(manifest.workflows),
                    "modes": list(manifest.modes),
                    "requires_context": list(manifest.requires_context),
                    "optional_context": list(manifest.optional_context),
                    "allowed_tools": list(manifest.allowed_tools),
                    "side_effects": list(manifest.side_effects),
                    "body_sha256": package.body_sha256,
                }
            )
        return rows
