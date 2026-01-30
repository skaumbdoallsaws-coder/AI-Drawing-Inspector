"""SolidWorks JSON library manager."""

import re
from pathlib import Path
from typing import Dict, List, Optional

from ..models.solidworks import SwPartEntry
from .io import load_json_robust


class SwJsonLibrary:
    """
    Manages a library of SolidWorks JSON exports.

    Loads all JSON files from a directory, indexes them by part number
    and filename, and provides flexible lookup with normalization.

    Usage:
        library = SwJsonLibrary()
        library.load_from_directory("sw_json_library")

        entry = library.lookup("1008794")
        if entry:
            print(entry.data["identity"]["description"])

    Lookup tries:
    1. Exact part number match
    2. Normalized part number (no dashes/spaces, lowercase)
    3. Exact filename match
    4. Normalized filename match
    """

    def __init__(self):
        self.by_part_number: Dict[str, SwPartEntry] = {}
        self.by_filename: Dict[str, SwPartEntry] = {}
        self.all_entries: List[SwPartEntry] = []

    def _normalize(self, s: str) -> str:
        """Normalize string for fuzzy matching."""
        return re.sub(r"[-\s_]", "", str(s or "")).lower()

    def load_from_directory(self, directory: str) -> int:
        """
        Load all JSON files from a directory.

        Recursively finds all .json files and indexes them by
        part number (from identity.partNumber) and filename.

        Args:
            directory: Path to directory containing JSON files

        Returns:
            Number of files loaded

        Raises:
            FileNotFoundError: If directory doesn't exist
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            raise FileNotFoundError(f"Directory not found: {directory}")

        json_files = list(dir_path.glob("**/*.json"))

        for jp in json_files:
            data, err = load_json_robust(jp)
            if data is None:
                continue

            # Extract part number from identity section
            pn = data.get("identity", {}).get("partNumber", "")

            entry = SwPartEntry(
                json_path=str(jp),
                part_number=pn,
                filename_stem=jp.stem,
                data=data,
            )

            self.all_entries.append(entry)

            # Index by part number (exact and normalized)
            if pn:
                self.by_part_number[pn] = entry
                self.by_part_number[self._normalize(pn)] = entry

            # Index by filename (exact and normalized)
            self.by_filename[jp.stem] = entry
            self.by_filename[self._normalize(jp.stem)] = entry

        return len(self.all_entries)

    def lookup(self, candidate: str) -> Optional[SwPartEntry]:
        """
        Look up a part by part number or filename.

        Tries exact match first, then normalized match.
        Searches part numbers before filenames.

        Args:
            candidate: Part number or filename to search for

        Returns:
            SwPartEntry if found, None otherwise
        """
        if not candidate:
            return None

        norm = self._normalize(candidate)

        # Try part number first (exact, then normalized)
        if candidate in self.by_part_number:
            return self.by_part_number[candidate]
        if norm in self.by_part_number:
            return self.by_part_number[norm]

        # Try filename (exact, then normalized)
        if candidate in self.by_filename:
            return self.by_filename[candidate]
        if norm in self.by_filename:
            return self.by_filename[norm]

        return None

    def __len__(self) -> int:
        """Return number of entries in library."""
        return len(self.all_entries)
