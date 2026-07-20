"""Strict loader for versioned prompt modules."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from ai_inspector.agent_skills.runtime import PromptSection


_ID_RE = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class PromptModuleError(ValueError):
    """Raised when prompt module source is invalid."""


@dataclass(frozen=True)
class PromptModule:
    id: str
    version: str
    path: Path
    agents: tuple[str, ...]
    modes: tuple[str, ...]
    content: str
    sha256: str

    def metadata(self) -> dict:
        return {
            "id": self.id,
            "version": self.version,
            "source": self.path.as_posix(),
            "chars": len(self.content),
            "sha256": self.sha256,
        }


class PromptModuleRegistry:
    """Load immutable prompt modules from one checked manifest."""

    def __init__(self, root: Path, modules: Iterable[PromptModule]):
        self.root = root
        self._modules = tuple(modules)

    @classmethod
    def load(cls, root: Path | None = None) -> "PromptModuleRegistry":
        module_root = root or Path(__file__).resolve().parent
        manifest_path = module_root / "modules.json"
        try:
            payload = json.loads(manifest_path.read_text(encoding="ascii"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PromptModuleError(f"invalid prompt module manifest: {exc}") from exc
        if payload.get("schema_version") != 1 or not isinstance(payload.get("modules"), list):
            raise PromptModuleError("prompt module manifest must use schema_version 1")

        modules = []
        seen = set()
        for row in payload["modules"]:
            if not isinstance(row, dict):
                raise PromptModuleError("prompt module entries must be objects")
            module_id = str(row.get("id") or "")
            version = str(row.get("version") or "")
            if not _ID_RE.fullmatch(module_id) or not _SEMVER_RE.fullmatch(version):
                raise PromptModuleError(f"invalid prompt module identity: {module_id}@{version}")
            if module_id in seen:
                raise PromptModuleError(f"duplicate prompt module id: {module_id}")
            seen.add(module_id)
            rel_path = Path(str(row.get("path") or ""))
            path = (module_root / rel_path).resolve()
            if module_root.resolve() not in path.parents:
                raise PromptModuleError(f"prompt module leaves root: {rel_path}")
            try:
                raw = path.read_bytes()
                content = raw.decode("ascii").strip()
            except (OSError, UnicodeError) as exc:
                raise PromptModuleError(f"invalid ASCII prompt module {module_id}: {exc}") from exc
            if not content:
                raise PromptModuleError(f"prompt module is empty: {module_id}")
            agents = tuple(str(v) for v in row.get("agents") or [])
            modes = tuple(str(v) for v in row.get("modes") or [])
            if not agents or not modes:
                raise PromptModuleError(f"prompt module requires agents and modes: {module_id}")
            modules.append(PromptModule(
                id=module_id,
                version=version,
                path=path.relative_to(module_root),
                agents=agents,
                modes=modes,
                content=content,
                sha256=hashlib.sha256(content.encode("ascii")).hexdigest(),
            ))
        return cls(module_root, modules)

    def select(self, *, agent: str, mode: str) -> tuple[PromptModule, ...]:
        selected = tuple(
            module for module in self._modules
            if agent in module.agents and ("*" in module.modes or mode in module.modes)
        )
        if not selected:
            raise PromptModuleError(f"no prompt modules for {agent}/{mode}")
        return selected

    def get(self, module_id: str) -> PromptModule:
        for module in self._modules:
            if module.id == module_id:
                return module
        raise PromptModuleError(f"unknown prompt module: {module_id}")

    def prompt_sections(self, *, agent: str, mode: str) -> tuple[PromptSection, ...]:
        return tuple(
            PromptSection(
                id=f"prompt.{module.id}",
                content=module.content,
                source=f"{module.path.as_posix()}@{module.version}",
                kind="prompt_module",
            )
            for module in self.select(agent=agent, mode=mode)
        )

    def metadata(self, *, agent: str, mode: str) -> list[dict]:
        return [module.metadata() for module in self.select(agent=agent, mode=mode)]
