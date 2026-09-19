"""Atomic local repository for revisioned Assembly Knowledge Packages."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from .manifest import canonical_json_bytes, canonical_json_sha256, package_revision
from .schema import AssemblyKnowledgeSchemaError, validate_package_documents


_PRODUCT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_PACKAGE_ID_RE = re.compile(r"^akp-[a-f0-9]{8,64}$")


class AssemblyKnowledgeRepositoryError(RuntimeError):
    pass


class AssemblyKnowledgeConflict(AssemblyKnowledgeRepositoryError):
    def __init__(self, current_revision: str):
        self.current_revision = current_revision
        super().__init__(f"Package revision conflict; current revision is {current_revision}.")


class AssemblyKnowledgeRepository:
    def __init__(self, training_root: str | Path):
        self.training_root = Path(training_root).resolve()

    def package_dir(self, product_id: str, package_id: str) -> Path:
        if _PRODUCT_ID_RE.fullmatch(product_id) is None:
            raise AssemblyKnowledgeRepositoryError("Invalid productId.")
        if _PACKAGE_ID_RE.fullmatch(package_id) is None:
            raise AssemblyKnowledgeRepositoryError("Invalid packageId.")
        target = (
            self.training_root
            / product_id
            / "assembly_knowledge"
            / package_id
        ).resolve()
        try:
            target.relative_to(self.training_root)
        except ValueError as exc:
            raise AssemblyKnowledgeRepositoryError(
                "Package path escapes the training root."
            ) from exc
        return target

    def read(self, product_id: str, package_id: str) -> Dict[str, Dict[str, Any]]:
        package_dir = self.package_dir(product_id, package_id)
        index_path = package_dir / "package.json"
        if not index_path.is_file():
            raise AssemblyKnowledgeRepositoryError("Assembly knowledge package not found.")
        index = json.loads(index_path.read_text("ascii"))
        documents: Dict[str, Dict[str, Any]] = {"package.json": index}
        for name in sorted(index.get("documentHashes", {})):
            path = (package_dir / name).resolve()
            try:
                path.relative_to(package_dir)
            except ValueError as exc:
                raise AssemblyKnowledgeRepositoryError(
                    f"Document path escapes package: {name}"
                ) from exc
            if not path.is_file():
                raise AssemblyKnowledgeRepositoryError(
                    f"Package document is missing: {name}"
                )
            raw = path.read_bytes()
            document = json.loads(raw.decode("ascii"))
            if canonical_json_sha256(document) != index["documentHashes"][name]:
                raise AssemblyKnowledgeRepositoryError(
                    f"Package document hash mismatch: {name}"
                )
            documents[name] = document
        errors = [
            item
            for item in validate_package_documents(documents)
            if item.get("severity") == "error"
        ]
        if errors:
            raise AssemblyKnowledgeSchemaError(errors)
        actual_revision = package_revision(
            index,
            {k: v for k, v in documents.items() if k != "package.json"},
            index.get("assetHashes", {}),
        )
        if actual_revision != index.get("packageRevision"):
            raise AssemblyKnowledgeRepositoryError("Package revision mismatch.")
        return documents

    def list_packages(self, product_id: str) -> List[Dict[str, Any]]:
        if _PRODUCT_ID_RE.fullmatch(product_id) is None:
            raise AssemblyKnowledgeRepositoryError("Invalid productId.")
        product_root = (self.training_root / product_id).resolve()
        try:
            product_root.relative_to(self.training_root)
        except ValueError as exc:
            raise AssemblyKnowledgeRepositoryError(
                "Product path escapes the training root."
            ) from exc
        knowledge_root = product_root / "assembly_knowledge"
        if not knowledge_root.is_dir():
            return []
        packages: List[Dict[str, Any]] = []
        for candidate in sorted(knowledge_root.iterdir(), key=lambda path: path.name):
            if not candidate.is_dir() or _PACKAGE_ID_RE.fullmatch(candidate.name) is None:
                continue
            documents = self.read(product_id, candidate.name)
            index = documents["package.json"]
            packages.append(
                {
                    "packageId": index["packageId"],
                    "packageRevision": index["packageRevision"],
                    "sourceRevision": index["sourceRevision"],
                    "readiness": index["readiness"],
                    "productionEligible": index["productionEligible"],
                    "occurrenceCount": len(
                        documents["product_structure.json"].get("occurrences", [])
                    ),
                    "pendingReviewCount": sum(
                        1
                        for name in (
                            "functional_context.json",
                            "process_candidates.json",
                        )
                        for claim in documents[name].get("claims", [])
                        if isinstance(claim, Mapping)
                        and claim.get("reviewStatus") == "pending"
                    ),
                }
            )
        return packages

    def resolve_asset(
        self,
        product_id: str,
        package_id: str,
        relative_path: str,
    ) -> Path:
        documents = self.read(product_id, package_id)
        asset_hashes = documents["package.json"].get("assetHashes", {})
        expected_hash = asset_hashes.get(relative_path)
        if not isinstance(expected_hash, str):
            raise AssemblyKnowledgeRepositoryError(
                "Asset is not registered in the package."
            )
        package_dir = self.package_dir(product_id, package_id)
        target = (package_dir / relative_path).resolve()
        try:
            target.relative_to(package_dir)
        except ValueError as exc:
            raise AssemblyKnowledgeRepositoryError(
                "Asset path escapes the package."
            ) from exc
        if not target.is_file() or sha256_file_bytes(target) != expected_hash:
            raise AssemblyKnowledgeRepositoryError(
                "Package asset is missing or does not match its content hash."
            )
        return target

    def bind_source_root(
        self,
        product_id: str,
        package_id: str,
        source_root: str | Path,
    ) -> Dict[str, Any]:
        documents = self.read(product_id, package_id)
        root = Path(source_root).resolve()
        if not root.is_dir():
            raise AssemblyKnowledgeRepositoryError(
                "Assembly source root does not exist."
            )
        binding = {
            "packageId": package_id,
            "sourceRevision": documents["package.json"]["sourceRevision"],
            "sourceRoot": str(root),
            "boundAt": datetime.now(timezone.utc).isoformat().replace(
                "+00:00",
                "Z",
            ),
        }
        package_dir = self.package_dir(product_id, package_id)
        self._write_atomic(
            package_dir / ".source-root.json",
            canonical_json_bytes(binding),
        )
        status = self.source_status(product_id, package_id)
        if not status["current"]:
            try:
                (package_dir / ".source-root.json").unlink(missing_ok=True)
            except OSError:
                pass
            raise AssemblyKnowledgeRepositoryError(
                "Assembly source root does not match the package source manifest."
            )
        return status

    def source_status(
        self,
        product_id: str,
        package_id: str,
    ) -> Dict[str, Any]:
        documents = self.read(product_id, package_id)
        package_dir = self.package_dir(product_id, package_id)
        binding_path = package_dir / ".source-root.json"
        if not binding_path.is_file():
            return {
                "bound": False,
                "current": False,
                "checkedSourceCount": 0,
                "findings": [
                    {
                        "severity": "error",
                        "code": "source_root_unbound",
                        "message": (
                            "The package has no server-local source binding, "
                            "so source currency cannot be verified."
                        ),
                    }
                ],
            }
        try:
            binding = json.loads(binding_path.read_text("ascii"))
            root = Path(str(binding["sourceRoot"])).resolve()
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return {
                "bound": False,
                "current": False,
                "checkedSourceCount": 0,
                "findings": [
                    {
                        "severity": "error",
                        "code": "source_binding_invalid",
                        "message": "The server-local source binding is invalid.",
                    }
                ],
            }
        findings = []
        package = documents["package.json"]
        if (
            binding.get("packageId") != package_id
            or binding.get("sourceRevision") != package["sourceRevision"]
        ):
            findings.append(
                {
                    "severity": "error",
                    "code": "source_binding_stale",
                    "message": "The source binding targets another package revision.",
                }
            )
        if not root.is_dir():
            findings.append(
                {
                    "severity": "error",
                    "code": "source_root_missing",
                    "message": "The bound assembly source root is unavailable.",
                }
            )
        checked = 0
        for record in documents["source_manifest.json"].get("sources", []):
            if not isinstance(record, Mapping) or record.get("available") is False:
                continue
            relative = str(record.get("path") or "")
            target = (root / relative).resolve()
            try:
                target.relative_to(root)
            except ValueError:
                findings.append(
                    {
                        "severity": "error",
                        "code": "source_path_escape",
                        "message": "A source path escapes the bound source root.",
                        "sourceId": record.get("sourceId"),
                    }
                )
                continue
            checked += 1
            if not target.is_file():
                findings.append(
                    {
                        "severity": "error",
                        "code": "source_file_missing",
                        "message": f"Assembly source is missing: {relative}",
                        "sourceId": record.get("sourceId"),
                    }
                )
            elif sha256_file_bytes(target) != record.get("sha256"):
                findings.append(
                    {
                        "severity": "error",
                        "code": "source_file_changed",
                        "message": f"Assembly source changed: {relative}",
                        "sourceId": record.get("sourceId"),
                    }
                )
        return {
            "bound": True,
            "current": not findings,
            "checkedSourceCount": checked,
            "findings": findings,
        }

    def write(
        self,
        documents: Mapping[str, Mapping[str, Any]],
        *,
        base_revision: Optional[str] = None,
        assets: Optional[Mapping[str, bytes]] = None,
    ) -> str:
        copied = {
            str(name): json.loads(canonical_json_bytes(value).decode("ascii"))
            for name, value in documents.items()
        }
        errors = [
            item
            for item in validate_package_documents(copied)
            if item.get("severity") == "error"
        ]
        if errors:
            raise AssemblyKnowledgeSchemaError(errors)
        index = copied["package.json"]
        product_id = str(index["productId"])
        package_id = str(index["packageId"])
        package_dir = self.package_dir(product_id, package_id)
        current_documents: Optional[Dict[str, Dict[str, Any]]] = None
        if package_dir.exists():
            current_documents = self.read(product_id, package_id)
            current_revision = str(
                current_documents["package.json"]["packageRevision"]
            )
            if base_revision is None or base_revision != current_revision:
                raise AssemblyKnowledgeConflict(current_revision)
        elif base_revision is not None:
            raise AssemblyKnowledgeConflict("")

        structured = {
            name: document for name, document in copied.items() if name != "package.json"
        }
        revision = package_revision(index, structured, index.get("assetHashes", {}))
        if revision != index.get("packageRevision"):
            raise AssemblyKnowledgeRepositoryError(
                "Claimed packageRevision does not match package content."
            )
        package_dir.mkdir(parents=True, exist_ok=True)
        supplied_assets = dict(assets or {})
        for relative_path, expected_hash in sorted(index.get("assetHashes", {}).items()):
            target = (package_dir / relative_path).resolve()
            try:
                target.relative_to(package_dir)
            except ValueError as exc:
                raise AssemblyKnowledgeRepositoryError(
                    f"Asset path escapes package: {relative_path}"
                ) from exc
            payload = supplied_assets.get(relative_path)
            if payload is not None:
                import hashlib

                if hashlib.sha256(payload).hexdigest() != expected_hash:
                    raise AssemblyKnowledgeRepositoryError(
                        f"Supplied asset hash mismatch: {relative_path}"
                    )
                self._write_atomic(target, payload)
            elif not target.is_file():
                raise AssemblyKnowledgeRepositoryError(
                    f"Package asset is missing: {relative_path}"
                )
            elif sha256_file_bytes(target) != expected_hash:
                raise AssemblyKnowledgeRepositoryError(
                    f"Package asset hash mismatch: {relative_path}"
                )
        backup_dir: Optional[Path] = None
        if (
            current_documents is not None
            and current_documents["package.json"]["packageRevision"] != revision
        ):
            backup_dir = self._backup_documents(package_dir, current_documents)
        try:
            # The index is written last, so readers never observe a new revision
            # before every content-addressed document is durable.
            for name in sorted(structured):
                self._write_atomic(
                    package_dir / name,
                    canonical_json_bytes(structured[name]),
                )
            self._write_atomic(
                package_dir / "package.json",
                canonical_json_bytes(index),
            )
        except OSError:
            if current_documents is not None:
                self._restore_documents(package_dir, current_documents)
            raise
        if backup_dir is not None:
            self._prune_backups(package_dir)
        return revision

    def _backup_documents(
        self,
        package_dir: Path,
        documents: Mapping[str, Mapping[str, Any]],
    ) -> Path:
        revision = str(documents["package.json"]["packageRevision"])
        backups_root = package_dir / ".backups"
        # Keep the directory compact enough for Windows/OneDrive path limits.
        # The complete revision remains recorded and verified inside it.
        target = backups_root / f"rev-{revision[:16]}"
        marker = target / ".complete"
        if target.is_dir() and marker.is_file():
            recorded = (target / "revision.txt").read_text("ascii").strip()
            if recorded != revision:
                raise AssemblyKnowledgeRepositoryError(
                    "Backup revision prefix collision."
                )
            return target
        backups_root.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
        try:
            for name, document in sorted(documents.items()):
                destination = (target / name).resolve()
                try:
                    destination.relative_to(target)
                except ValueError as exc:
                    raise AssemblyKnowledgeRepositoryError(
                        f"Backup document path escapes package: {name}"
                    ) from exc
                self._write_atomic(destination, canonical_json_bytes(document))
            self._write_atomic(
                target / "revision.txt",
                (revision + "\n").encode("ascii"),
            )
            self._write_atomic(marker, b"complete\n")
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise
        return target

    def _restore_documents(
        self,
        package_dir: Path,
        documents: Mapping[str, Mapping[str, Any]],
    ) -> None:
        for name, document in sorted(documents.items()):
            self._write_atomic(package_dir / name, canonical_json_bytes(document))

    @staticmethod
    def _backup_retention_limit() -> int:
        raw = os.getenv("INSPECTORPRO_ASSEMBLY_KNOWLEDGE_BACKUPS", "20")
        try:
            return min(200, max(1, int(raw)))
        except (TypeError, ValueError):
            return 20

    def _prune_backups(self, package_dir: Path) -> None:
        backups_root = package_dir / ".backups"
        if not backups_root.is_dir():
            return
        backups = sorted(
            (
                path
                for path in backups_root.iterdir()
                if path.is_dir()
                and re.fullmatch(r"rev-[a-f0-9]{16}", path.name)
                and (path / ".complete").is_file()
            ),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for stale in backups[self._backup_retention_limit():]:
            shutil.rmtree(stale, ignore_errors=True)

    @staticmethod
    def _replace_with_retry(source: Path, destination: Path) -> None:
        for attempt in range(6):
            try:
                os.replace(source, destination)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.02 * (attempt + 1))

    @staticmethod
    def _write_atomic(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=".tmp-",
            suffix=".tmp",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            AssemblyKnowledgeRepository._replace_with_retry(
                Path(temporary),
                path,
            )
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def sha256_file_bytes(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()
