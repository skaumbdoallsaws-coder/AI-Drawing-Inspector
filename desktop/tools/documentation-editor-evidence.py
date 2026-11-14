"""Owned, hidden evidence helper: dependency identity, exports, a press on a native dialog button.

This is a test driver, never imported by the managed backend. It neither opens
accounts nor sends HTTP. The only native window operation targets the supplied
owned Electron PID and one named button of its #32770 dialog with the named title.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import zipfile
from xml.etree import ElementTree


def dependencies():
    result = {}
    for name in ("fastapi", "uvicorn", "numpy", "PIL", "fitz", "docx", "dotenv"):
        spec = importlib.util.find_spec(name)
        result[name] = None if spec is None else spec.origin
    return {"python": sys.executable, "version": sys.version, "dependencies": result,
            "searchPath": sys.path, "complete": all(result.values())}


def inspect(file):
    if file.suffix.lower() == ".pdf":
        import fitz
        with fitz.open(file) as pdf:
            return {"kind": "pdf", "pages": len(pdf), "text": "\n".join(page.get_text() for page in pdf)}
    with zipfile.ZipFile(file) as archive:
        if archive.testzip() is not None:
            raise ValueError("Incomplete DOCX")
        node = ElementTree.fromstring(archive.read("word/document.xml"))
        return {"kind": "docx", "members": len(archive.namelist()),
                "text": "\n".join(n.text or "" for n in node.iter()
                                   if n.tag == "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")}


def press_owned_dialog(pid, title_text, button_text, timeout):
    if os.name != "nt":
        return {"pressed": False, "reason": "Windows native dialog automation only"}
    import ctypes
    from ctypes import wintypes
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.SendMessageW.restype = ctypes.c_ssize_t
    user.EnumWindows.argtypes = [callback, wintypes.LPARAM]
    user.EnumChildWindows.argtypes = [wintypes.HWND, callback, wintypes.LPARAM]
    deadline = time.monotonic() + timeout
    found = []

    @callback
    def window(hwnd, _):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user.IsWindowVisible(hwnd):
            return True
        cls = ctypes.create_unicode_buffer(80)
        user.GetClassNameW(hwnd, cls, len(cls))
        if cls.value != "#32770":
            return True
        title = ctypes.create_unicode_buffer(256)
        user.GetWindowTextW(hwnd, title, len(title))
        if title.value != title_text:
            return True

        @callback
        def child(button, _):
            label = ctypes.create_unicode_buffer(256)
            user.GetWindowTextW(button, label, len(label))
            kind = ctypes.create_unicode_buffer(80)
            user.GetClassNameW(button, kind, len(kind))
            # A command link's text is its label, optionally followed by a note on further lines.
            if kind.value.lower() == "button" and label.value.replace("&", "").split(chr(10))[0].strip() == button_text:
                user.SendMessageW(button, 0x00F5, 0, 0)  # BM_CLICK: actual native dialog, not a mocked result.
                found.append({"pressed": True, "processId": pid, "title": title_text, "button": button_text})
                return False
            return True
        user.EnumChildWindows(hwnd, child, 0)
        return not found

    while time.monotonic() < deadline:
        user.EnumWindows(window, 0)
        if found:
            return found[0]
        time.sleep(0.1)  # Poll for the named owned dialog; never used as a completion assertion.
    return {"pressed": False, "reason": "No owned native dialog with that title and button before the deadline",
            "processId": pid, "title": title_text, "button": button_text}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["dependencies", "inspect", "press-dialog"])
    parser.add_argument("--title")
    parser.add_argument("--button")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--pid", type=int)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "dependencies":
        result = dependencies()
    elif args.action == "inspect":
        result = inspect(args.file)
    else:
        if not args.pid or args.pid < 1 or not args.title or not args.button:
            raise ValueError("Owned Electron PID, dialog title and button label required")
        result = press_owned_dialog(args.pid, args.title, args.button, args.timeout)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="ascii", newline="\n")


if __name__ == "__main__":
    main()
