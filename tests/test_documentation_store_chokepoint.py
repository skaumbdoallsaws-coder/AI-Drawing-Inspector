"""Keep each document file owned by its existing in-place repository.

All filename references that can flow into an I/O helper are forbidden outside
the store, including constants and path-returning functions. Checking the origin
of a path, not just calls named ``open``, catches wrappers and assigned filenames.
Docstrings/comments are not path expressions. No other I/O owner is allowlisted.
"""
import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
OWNERS = {"documentation-scene.json": "ai_inspector/parts_manual/documentation.py",
          "slots.json": "ai_inspector/specification_sheet/slots.py"}
NAMES = ("documentation-scene.json", "slots.json")
# Exact (file, qualified function) -> reason. A compatibility display/reference
# exception may be reviewed here; it must never authorize another I/O owner.
ALLOWLIST: dict[tuple[str, str], str] = {}


def constant_text(node, constants):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Div)):
        left, right = constant_text(node.left, constants), constant_text(node.right, constants)
        if left is not None and right is not None:
            return left + ("/" if isinstance(node.op, ast.Div) else "") + right
    if isinstance(node, ast.JoinedStr):
        pieces = [constant_text(item, constants) if not isinstance(item, ast.FormattedValue)
                  else constant_text(item.value, constants) for item in node.values]
        if all(piece is not None for piece in pieces):
            return "".join(pieces)
    return None


def scan(source, filename):
    tree = ast.parse(source, filename=filename)
    constants = {}
    # Resolve aliases and literal concatenation regardless of assignment order.
    for _ in range(8):
        old = dict(constants)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = constant_text(node.value, constants)
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if value is not None:
                    for target in targets:
                        if isinstance(target, ast.Name):
                            constants[target.id] = value
        if old == constants:
            break
    findings = []

    def visit(node, scope="<module>"):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            scope = node.name if scope == "<module>" else scope + "." + node.name
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return  # non-executable string documentation, never a path operand
        value = constant_text(node, constants)
        if value is not None and any(name in value.replace("\\", "/").split("/") and filename != OWNERS[name] for name in NAMES):
            key = (filename, scope)
            if key not in ALLOWLIST:
                findings.append({"file": filename, "function": scope, "line": node.lineno})
                return
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree)
    return findings


def test_production_legacy_io_is_owned_only_by_store():
    findings = []
    for path in [ROOT / "server.py", *sorted((ROOT / "ai_inspector").rglob("*.py"))]:
        filename = path.relative_to(ROOT).as_posix()
        findings.extend(scan(path.read_text(encoding="utf-8-sig"), filename))
    assert not findings, "Document I/O outside its owner: " + repr(findings)


@pytest.mark.parametrize("source", [
    'def read(root):\n    return (root / "documentation-scene.json").read_text()\n',
    'def write(root):\n    (root / "slots.json").write_bytes(b"{}");\n',
    'NAME = "slots.json"\ndef read(root):\n    return helper(root / NAME)\n',
    'NAME = "documentation-" + "scene.json"\ndef read(root):\n    return open(root / NAME)\n',
    'NAME = "slots"\nEXT = ".json"\nPATH = NAME + EXT\ndef write(root):\n    helper(root / PATH)\n',
    'def filename(root):\n    return root / "documentation-scene.json"\n',
    'def copy(root):\n    shutil.copyfile("slots.json", root / "backup")\n',
    'def read(root):\n    p = Path(root, "slots.json")\n    return json.load(p.open())\n',
    'NAME = "slots"\ndef read(root):\n    return read_json(root / f"{NAME}.json")\n',
])
def test_indirect_readers_and_writers_are_detected(source):
    assert scan(source, "ai_inspector/example.py")


def test_store_is_the_only_initial_owner():
    assert ALLOWLIST == {}
    assert not scan('open("slots.json", "wb")', OWNERS["slots.json"])
    assert scan('open("slots.json", "wb")', OWNERS["documentation-scene.json"])
    assert not scan('open("documentation-scene.json", "rb")', OWNERS["documentation-scene.json"])
    assert scan('open("slots.json", "rb")', "server.py")


def test_comments_docstrings_and_unrelated_json_are_not_io():
    assert not scan('''# slots.json is mentioned here
def explain():
    """documentation-scene.json is a historical format."""
    return read_json("manual-plan.json")
''', "ai_inspector/example.py")
