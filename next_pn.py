"""Generate the next available part number not already in the library.

Usage:
    python next_pn.py              # next available in 1030xxx series
    python next_pn.py 1020         # next available in 1020xxx series
    python next_pn.py 1040         # next available in 1040xxx series
"""
import sys
from pathlib import Path

LIBRARY = Path("400S_Sorted_Library")

def get_used_numbers():
    """Scan library for all part numbers currently in use."""
    used = set()
    for f in LIBRARY.glob("*.json"):
        stem = f.stem
        # Skip non-part files
        if any(stem.endswith(s) for s in ("_drawing_map", "_highlight_boxes", "_inspection_profile")):
            continue
        # Extract numeric prefix (handles stems like "1030001", "023-298", etc.)
        used.add(stem)
    # Also scan assembly subdirectories
    for f in LIBRARY.glob("assemblies/*_assembly.json"):
        used.add(f.stem.replace("_assembly", ""))
    return used


def next_pn(prefix="1030"):
    used = get_used_numbers()
    # Try sequential numbers: prefix + 001, 002, ...
    width = 7 - len(prefix)  # e.g. prefix "1030" -> 3 digits -> 1030001
    for i in range(1, 1000):
        candidate = f"{prefix}{str(i).zfill(width)}"
        if candidate not in used:
            return candidate
    raise RuntimeError(f"No available part numbers in {prefix}xxx range")


if __name__ == "__main__":
    prefix = sys.argv[1] if len(sys.argv) > 1 else "1030"
    pn = next_pn(prefix)
    print(f"Next available: {pn}")
