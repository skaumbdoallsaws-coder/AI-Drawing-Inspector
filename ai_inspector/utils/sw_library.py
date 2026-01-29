"""
SolidWorks JSON Library

Manages the collection of SolidWorks part JSON files extracted from CAD models.
Provides lookup by part number or filename.
"""

import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def load_json_robust(filepath) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Load JSON with BOM (Byte Order Mark) handling.

    Tries multiple encodings: utf-8-sig, utf-8, latin-1
    This handles Windows-generated JSON files that may have BOM markers.

    Args:
        filepath: Path to JSON file

    Returns:
        Tuple of (data, error_message). If successful, error is None.
    """
    filepath = Path(filepath)
    for enc in ['utf-8-sig', 'utf-8', 'latin-1']:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return json.load(f), None
        except UnicodeDecodeError:
            continue
        except json.JSONDecodeError as e:
            if 'BOM' in str(e) and enc == 'utf-8':
                continue
            return None, f"JSON error: {str(e)[:50]}"
        except Exception as e:
            return None, f"Error: {str(e)[:50]}"
    return None, "Failed all encodings"


@dataclass
class SwPartEntry:
    """Container for a SolidWorks part JSON file."""
    json_path: str  # Full path to JSON file
    part_number: str  # Part number from identity.partNumber
    filename_stem: str = ""  # Filename without extension
    data: Dict[str, Any] = field(default_factory=dict)  # Full JSON content

    @property
    def identity(self) -> Dict[str, Any]:
        """Get identity section of the part data."""
        return self.data.get('identity', {})

    @property
    def features(self) -> Dict[str, Any]:
        """Get features section of the part data."""
        return self.data.get('features', {})

    @property
    def comparison(self) -> Dict[str, Any]:
        """Get comparison section of the part data."""
        return self.data.get('comparison', {})

    @property
    def hole_groups(self) -> List[Dict]:
        """Get hole groups from comparison data."""
        return self.comparison.get('holeGroups', [])

    @property
    def threads(self) -> List[Dict]:
        """Get tapped holes from features."""
        return self.features.get('tappedHoles', [])


class SwJsonLibrary:
    """
    Manager for SolidWorks part JSON files.

    Supports loading from a directory or ZIP file, and provides
    lookup by part number or filename.
    """

    def __init__(self):
        self.by_part_number: Dict[str, SwPartEntry] = {}
        self.by_filename: Dict[str, SwPartEntry] = {}
        self.all_entries: List[SwPartEntry] = []

    def _normalize(self, s: str) -> str:
        """Normalize string for fuzzy matching (remove hyphens, spaces, underscores)."""
        return re.sub(r'[-\s_]', '', str(s or '')).lower()

    def load_from_directory(self, directory: str, verbose: bool = True) -> int:
        """
        Load all JSON files from a directory.

        Args:
            directory: Path to directory containing JSON files
            verbose: Print progress messages

        Returns:
            Number of files loaded
        """
        json_files = list(Path(directory).glob("**/*.json"))
        if verbose:
            print(f"Found {len(json_files)} JSON files")

        loaded = 0
        for jp in json_files:
            data, err = load_json_robust(jp)
            if data is None:
                if verbose and err:
                    print(f"  Warning: {jp.name} - {err}")
                continue

            pn = data.get('identity', {}).get('partNumber', '')
            entry = SwPartEntry(str(jp), pn, jp.stem, data)
            self.all_entries.append(entry)

            # Index by part number
            if pn:
                self.by_part_number[pn] = entry
                self.by_part_number[self._normalize(pn)] = entry

            # Index by filename
            self.by_filename[jp.stem] = entry
            self.by_filename[self._normalize(jp.stem)] = entry
            loaded += 1

        if verbose:
            print(f"Loaded {loaded} files")
        return loaded

    def load_from_zip(self, zip_path: str, extract_dir: str = None, verbose: bool = True) -> int:
        """
        Load JSON files from a ZIP archive.

        Args:
            zip_path: Path to ZIP file
            extract_dir: Directory to extract to (default: same directory as ZIP)
            verbose: Print progress messages

        Returns:
            Number of files loaded
        """
        zip_path = Path(zip_path)
        if extract_dir is None:
            extract_dir = zip_path.parent / zip_path.stem

        if verbose:
            print(f"Extracting {zip_path.name} to {extract_dir}")

        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(extract_dir)

        return self.load_from_directory(str(extract_dir), verbose=verbose)

    def lookup(self, candidate: str) -> Optional[SwPartEntry]:
        """
        Look up a part by part number or filename.

        Tries exact match first, then normalized (no hyphens/underscores).

        Args:
            candidate: Part number or filename to look up

        Returns:
            SwPartEntry if found, None otherwise
        """
        if not candidate:
            return None

        norm = self._normalize(candidate)

        # Try exact matches first
        if candidate in self.by_part_number:
            return self.by_part_number[candidate]
        if candidate in self.by_filename:
            return self.by_filename[candidate]

        # Try normalized matches
        if norm in self.by_part_number:
            return self.by_part_number[norm]
        if norm in self.by_filename:
            return self.by_filename[norm]

        return None

    def lookup_multiple(self, candidates: List[str]) -> Optional[SwPartEntry]:
        """
        Try multiple candidates, return first match.

        Args:
            candidates: List of part numbers/filenames to try

        Returns:
            First matching SwPartEntry, or None
        """
        for candidate in candidates:
            entry = self.lookup(candidate)
            if entry:
                return entry
        return None

    def get_all_part_numbers(self) -> List[str]:
        """Get list of all unique part numbers in the library."""
        return list(set(e.part_number for e in self.all_entries if e.part_number))

    def __len__(self) -> int:
        return len(self.all_entries)

    def __contains__(self, item: str) -> bool:
        return self.lookup(item) is not None
