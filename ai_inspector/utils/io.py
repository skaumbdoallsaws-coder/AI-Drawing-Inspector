"""File I/O utilities."""

import json
from pathlib import Path
from typing import Dict, Optional, Tuple, Union


def load_json_robust(filepath: Union[str, Path]) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Load JSON with BOM (Byte Order Mark) handling.

    SolidWorks and other tools sometimes export JSON with encoding issues.
    This function tries multiple encodings to handle these cases.

    Encoding order:
    1. utf-8-sig: UTF-8 with BOM (handles Windows exports)
    2. utf-8: Standard UTF-8
    3. latin-1: Fallback for legacy files

    Args:
        filepath: Path to JSON file

    Returns:
        Tuple of (data, error):
        - On success: (dict, None)
        - On failure: (None, error_message)

    Example:
        data, err = load_json_robust("part.json")
        if err:
            print(f"Failed to load: {err}")
        else:
            print(data["identity"]["partNumber"])
    """
    filepath = Path(filepath)

    if not filepath.exists():
        return None, f"File not found: {filepath}"

    for encoding in ["utf-8-sig", "utf-8", "latin-1"]:
        try:
            with open(filepath, "r", encoding=encoding) as f:
                return json.load(f), None
        except UnicodeDecodeError:
            continue
        except json.JSONDecodeError as e:
            # BOM-related JSON errors - try next encoding
            if "BOM" in str(e) and encoding == "utf-8":
                continue
            return None, f"JSON error: {str(e)[:100]}"
        except Exception as e:
            return None, f"Error: {str(e)[:100]}"

    return None, f"Failed all encodings for: {filepath}"
