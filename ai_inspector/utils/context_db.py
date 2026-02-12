"""Assembly context and inspector requirements database."""

import json
from pathlib import Path
from typing import Dict, List, Optional

from .io import load_json_robust


class ContextDatabase:
    """
    Manages part context and inspector requirements databases.

    These databases provide assembly-level information:
    - Part context: Siblings, mates, hierarchy from assembly
    - Inspector requirements: Thread holes derived from mates

    Usage:
        db = ContextDatabase()
        db.load(["sw_json_library", "/content"])

        ctx = db.get_part_context("1008794")
        if ctx:
            print(ctx["hierarchy"]["parent_assembly"])

        reqs = db.get_inspector_requirements("1008794")
        if reqs:
            print(reqs["requirements"])
    """

    def __init__(self):
        self.part_context: Dict = {}
        self.inspector_requirements: Dict = {}
        self.mating_context: Dict = {}
        self.mate_specs: Dict = {}

    def load(self, search_paths: List[str]) -> None:
        """
        Load databases from first found path.

        Looks for:
        - sw_part_context_complete.json
        - sw_inspector_requirements.json

        Args:
            search_paths: List of directories to search
        """
        self.part_context = (
            self._try_load("sw_part_context_complete.json", search_paths) or {}
        )
        self.inspector_requirements = (
            self._try_load("sw_inspector_requirements.json", search_paths) or {}
        )

    def load_part_context(self, path: str) -> None:
        """
        Load part context from a specific JSON file.

        The file maps part numbers to identity (old_pn, new_pn),
        hierarchy, and mating information.

        Args:
            path: Path to the sw_part_context_complete.json file
        """
        p = Path(path)
        if p.exists():
            data, err = load_json_robust(p)
            self.part_context = data or {}

    def load_mating_context(self, path: str) -> None:
        """
        Load mating context from a specific JSON file.

        The file maps part numbers to their parent assembly and sibling
        components (e.g., sw_mating_context.json).

        Args:
            path: Path to the mating context JSON file
        """
        p = Path(path)
        if p.exists():
            data, err = load_json_robust(p)
            self.mating_context = data or {}

    def load_mate_specs(self, path: str) -> None:
        """
        Load mate specifications from a specific JSON file.

        The file maps part numbers to their SolidWorks mate constraints
        (Concentric, Coincident, etc.) with thread specs where applicable.

        Args:
            path: Path to the mate specs JSON file
        """
        p = Path(path)
        if p.exists():
            data, err = load_json_robust(p)
            self.mate_specs = data or {}

    def get_mate_specs(self, part_number: str) -> Optional[Dict]:
        """
        Look up mate specifications by part number.

        Returns mate constraints including Concentric/Coincident mates
        and thread specifications for fastener interfaces.

        Also searches by sibling part numbers from mating_context,
        since mate specs may be keyed by old-style part numbers.

        Args:
            part_number: Part number to look up

        Returns:
            Mate specs dict if found, None otherwise
        """
        if not self.mate_specs:
            return None

        candidates = self._normalize_candidates(part_number)

        for key in candidates:
            if key in self.mate_specs:
                return self.mate_specs[key]

        # Search by part_number field inside entries
        for entry in self.mate_specs.values():
            if entry.get("part_number") == part_number:
                return entry

        # Try via part_context old_pn mapping
        ctx = self.get_part_context(part_number)
        if ctx:
            old_pn = ctx.get("identity", {}).get("old_pn", "")
            if old_pn:
                for key in self._normalize_candidates(old_pn):
                    if key in self.mate_specs:
                        return self.mate_specs[key]

        return None

    def get_mate_specs_for_siblings(self, part_number: str) -> List[Dict]:
        """
        Collect mate specs for all sibling parts from mating context.

        This is useful when the inspected part itself isn't in mate_specs
        but its siblings are — their concentric/thread mates imply
        features that must exist on the inspected part.

        Args:
            part_number: Part number to look up siblings for

        Returns:
            List of mate spec entries for sibling parts
        """
        if not self.mate_specs or not self.mating_context:
            return []

        mc = self.get_mating_context(part_number)
        if not mc:
            return []

        sibling_specs = []
        seen = set()
        for sib in mc.get("siblings", []):
            sib_pn = sib.get("pn", "")
            if not sib_pn or sib_pn in seen:
                continue
            seen.add(sib_pn)
            spec = self.get_mate_specs(sib_pn)
            if spec:
                sibling_specs.append(spec)

        return sibling_specs

    def get_mating_context(self, part_number: str) -> Optional[Dict]:
        """
        Look up mating context by part number.

        Returns assembly info including parent assembly and sibling
        components that mate with this part.

        Args:
            part_number: Part number to look up

        Returns:
            Mating context dict if found, None otherwise
        """
        if not self.mating_context:
            return None

        candidates = self._normalize_candidates(part_number)

        for key in candidates:
            if key in self.mating_context:
                return self.mating_context[key]

        # Search by part_number field inside entries
        for entry in self.mating_context.values():
            if entry.get("part_number") == part_number:
                return entry

        return None

    def _try_load(self, name: str, search_paths: List[str]) -> Optional[Dict]:
        """Try loading JSON from multiple paths."""
        for p in search_paths:
            full = Path(p) / name
            if full.exists():
                data, err = load_json_robust(full)
                if data:
                    return data
        return None

    def _normalize_candidates(self, pn: str) -> List[str]:
        """Generate lookup candidates for a part number."""
        return [
            pn,
            pn.upper(),
            pn.lower(),
            pn.replace("-", ""),
            pn.replace("_", ""),
            pn.replace("-", "").lower(),
        ]

    def get_part_context(self, part_number: str) -> Optional[Dict]:
        """
        Look up part context by part number.

        Context includes:
        - hierarchy: parent_assembly, hierarchy_path, siblings
        - mating: mates_with, requirements_from_mates
        - identity: new_pn, old_pn

        Tries exact match, then normalized variants, then searches
        by new_pn/old_pn fields inside entries.

        Args:
            part_number: Part number to look up

        Returns:
            Context dict if found, None otherwise
        """
        if not self.part_context:
            return None

        candidates = self._normalize_candidates(part_number)

        # Direct key lookup
        for key in candidates:
            if key in self.part_context:
                return self.part_context[key]

        # Search by new_pn/old_pn inside entries
        for entry in self.part_context.values():
            identity = entry.get("identity", {})
            if identity.get("new_pn") == part_number:
                return entry
            if identity.get("old_pn") == part_number:
                return entry

        return None

    def get_inspector_requirements(self, part_number: str) -> Optional[Dict]:
        """
        Look up inspector requirements.

        Requirements include thread holes derived from assembly mates
        (e.g., "THREAD HOLE: M8 (for fastener XYZ)").

        Uses part_context to resolve new_pn -> old_pn mapping if needed.

        Args:
            part_number: Part number to look up

        Returns:
            Requirements dict if found, None otherwise
        """
        if not self.inspector_requirements:
            return None

        candidates = self._normalize_candidates(part_number)

        # Direct lookup
        for key in candidates:
            if key in self.inspector_requirements:
                return self.inspector_requirements[key]

        # Try via part_context old_pn mapping
        ctx = self.get_part_context(part_number)
        if ctx:
            old_pn = ctx.get("identity", {}).get("old_pn", "")
            if old_pn:
                for key in self._normalize_candidates(old_pn):
                    if key in self.inspector_requirements:
                        return self.inspector_requirements[key]

        return None

    @property
    def part_context_count(self) -> int:
        """Number of entries in part context database."""
        return len(self.part_context)

    @property
    def inspector_requirements_count(self) -> int:
        """Number of entries in inspector requirements database."""
        return len(self.inspector_requirements)

    @property
    def mating_context_count(self) -> int:
        """Number of entries in mating context database."""
        return len(self.mating_context)

    @property
    def mate_specs_count(self) -> int:
        """Number of entries in mate specs database."""
        return len(self.mate_specs)
