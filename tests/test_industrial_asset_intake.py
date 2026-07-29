import hashlib
import json
from pathlib import Path

import pytest

import ai_inspector.industrial_assets.discover as discover_module
from ai_inspector.industrial_assets import (
    DependencyReference,
    DiscoveryPolicy,
    SourcePathRejected,
    TrustedSourceRoots,
    build_normalized_source_identity,
    canonical_json_sha256,
    discover_source_tree,
    resolve_dependency_graph,
)


def _write(path: Path, value: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


def _discover(root: Path, **policy_values):
    return discover_source_tree(
        root,
        allowed_roots=TrustedSourceRoots.from_paths([root.parent]),
        policy=DiscoveryPolicy(**policy_values),
    )


def test_recursive_discovery_is_deterministic_and_hashes_file_bytes(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root in (first, second):
        _write(root / "Nested" / "Wheel.SLDPRT", b"wheel-v1")
        _write(root / "Top.SLDASM", b"assembly-v1")
        _write(root / "readme.txt", b"ignored")

    a = _discover(first)
    b = _discover(second)

    assert [item.relative_path for item in a.records] == [
        "Nested/Wheel.SLDPRT",
        "Top.SLDASM",
    ]
    assert [item.to_dict() for item in a.records] == [
        item.to_dict() for item in b.records
    ]
    assert a.source_fingerprint == b.source_fingerprint
    assert a.ignored_file_count == 1
    wheel = a.records[0]
    assert wheel.sha256 == hashlib.sha256(b"wheel-v1").hexdigest()
    assert wheel.source_kind == "part"
    assert not a.quarantined


def test_discovery_rejects_source_root_outside_allowlist(tmp_path):
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()

    roots = TrustedSourceRoots.from_paths([allowed])
    with pytest.raises(SourcePathRejected) as error:
        discover_source_tree(outside, allowed_roots=roots)

    assert error.value.code == "source_root_outside_configured_roots"
    assert str(outside) not in str(error.value)


def test_discovery_requires_absolute_configured_and_requested_roots(tmp_path):
    with pytest.raises(SourcePathRejected) as configured:
        TrustedSourceRoots.from_paths(["relative/library"])
    assert configured.value.code == "configured_root_not_absolute"

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    with pytest.raises(SourcePathRejected) as requested:
        discover_source_tree(
            "relative/request",
            allowed_roots=TrustedSourceRoots.from_paths([allowed]),
        )
    assert requested.value.code == "source_root_not_absolute"


def test_discovery_limits_fail_closed_without_partial_authority(tmp_path):
    root = tmp_path / "library"
    _write(root / "A.SLDPRT", b"a")
    _write(root / "B.SLDPRT", b"b")

    result = _discover(root, maximum_source_files=1)

    assert result.quarantined
    assert [item.relative_path for item in result.records] == ["A.SLDPRT"]
    assert "source_file_limit_exceeded" in {
        item.code for item in result.findings
    }


def test_discovery_rejects_file_replaced_between_inspection_and_open(
    tmp_path,
    monkeypatch,
):
    root = tmp_path / "library"
    source = _write(root / "Machine.SLDPRT", b"reviewed-source")
    original_open = discover_module.os.open
    swapped = False

    def swap_before_open(path, flags, *args, **kwargs):
        nonlocal swapped
        if Path(path) == source and not swapped:
            swapped = True
            source.unlink()
            source.write_bytes(b"replacement-source")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(discover_module.os, "open", swap_before_open)
    result = _discover(root)

    assert swapped is True
    assert result.records == ()
    assert result.quarantined is True
    assert "source_file_unstable_or_unreadable" in {
        item.code for item in result.findings
    }


def test_duplicate_basename_dependency_is_quarantined_not_guessed(tmp_path):
    root = tmp_path / "library"
    _write(root / "Machine.SLDASM", b"assembly")
    _write(root / "left" / "Bolt.SLDPRT", b"left")
    _write(root / "right" / "Bolt.SLDPRT", b"right")
    discovery = _discover(root)

    graph = resolve_dependency_graph(
        discovery,
        [DependencyReference("Machine.SLDASM", "Bolt.SLDPRT")],
        requested_root="Machine.SLDASM",
        reference_graph_complete=True,
    )

    assert graph.status == "quarantined"
    assert graph.selected_root == "Machine.SLDASM"
    assert graph.edges == ()
    ambiguous = next(
        item for item in graph.findings if item.code == "dependency_ambiguous"
    )
    assert ambiguous.candidates == (
        "left/Bolt.SLDPRT",
        "right/Bolt.SLDPRT",
    )


def test_missing_dependency_quarantines_selected_root(tmp_path):
    root = tmp_path / "library"
    _write(root / "Machine.SLDASM", b"assembly")
    discovery = _discover(root)

    graph = resolve_dependency_graph(
        discovery,
        [DependencyReference("Machine.SLDASM", "Missing.SLDPRT")],
        requested_root="Machine.SLDASM",
        reference_graph_complete=True,
    )

    assert graph.status == "quarantined"
    assert graph.edges == ()
    assert "dependency_missing" in {item.code for item in graph.findings}


def test_path_qualified_reference_resolves_duplicate_basenames_exactly(tmp_path):
    root = tmp_path / "library"
    _write(root / "Machine.SLDASM", b"assembly")
    _write(root / "left" / "Bolt.SLDPRT", b"left")
    _write(root / "right" / "Bolt.SLDPRT", b"right")
    discovery = _discover(root)

    graph = resolve_dependency_graph(
        discovery,
        [DependencyReference("Machine.SLDASM", "left/Bolt.SLDPRT")],
        requested_root="Machine.SLDASM",
        reference_graph_complete=True,
    )

    assert graph.status == "resolved"
    assert graph.source_paths == ("left/Bolt.SLDPRT", "Machine.SLDASM")
    assert [(item.owner_path, item.target_path) for item in graph.edges] == [
        ("Machine.SLDASM", "left/Bolt.SLDPRT")
    ]
    assert "duplicate_source_basename" in {
        item.code for item in graph.findings
    }
    assert not any(item.severity == "error" for item in graph.findings)


def test_dependency_traversal_or_absolute_reference_is_rejected(tmp_path):
    root = tmp_path / "library"
    _write(root / "Machine.SLDASM", b"assembly")
    discovery = _discover(root)

    for unsafe in ("../outside.SLDPRT", "C:\\outside\\Part.SLDPRT"):
        graph = resolve_dependency_graph(
            discovery,
            [DependencyReference("Machine.SLDASM", unsafe)],
            requested_root="Machine.SLDASM",
            reference_graph_complete=True,
        )
        assert graph.status == "quarantined"
        assert graph.edges == ()
        assert "dependency_reference_invalid" in {
            item.code for item in graph.findings
        }


def test_multiple_roots_require_explicit_selection(tmp_path):
    root = tmp_path / "library"
    _write(root / "MachineA.SLDASM", b"a")
    _write(root / "MachineB.SLDASM", b"b")
    discovery = _discover(root)

    unresolved = resolve_dependency_graph(
        discovery,
        [],
        reference_graph_complete=True,
    )
    assert unresolved.status == "selection_required"
    assert unresolved.selected_root is None
    assert unresolved.root_candidates == (
        "MachineA.SLDASM",
        "MachineB.SLDASM",
    )

    selected = resolve_dependency_graph(
        discovery,
        [],
        requested_root="MachineB.SLDASM",
        reference_graph_complete=True,
    )
    assert selected.status == "resolved"
    assert selected.selected_root == "MachineB.SLDASM"
    assert selected.source_paths == ("MachineB.SLDASM",)


def test_dependency_cycle_is_quarantined(tmp_path):
    root = tmp_path / "library"
    _write(root / "A.SLDASM", b"a")
    _write(root / "B.SLDASM", b"b")
    discovery = _discover(root)

    graph = resolve_dependency_graph(
        discovery,
        [
            DependencyReference("A.SLDASM", "B.SLDASM"),
            DependencyReference("B.SLDASM", "A.SLDASM"),
        ],
        requested_root="A.SLDASM",
        reference_graph_complete=True,
    )

    assert graph.status == "quarantined"
    assert "dependency_cycle" in {item.code for item in graph.findings}


def test_incomplete_reference_graph_stays_candidate_only(tmp_path):
    root = tmp_path / "library"
    _write(root / "Machine.SLDASM", b"assembly")
    discovery = _discover(root)
    graph = resolve_dependency_graph(
        discovery,
        [],
        requested_root="Machine.SLDASM",
        reference_graph_complete=False,
    )

    identity = build_normalized_source_identity(
        discovery,
        graph,
        configuration="Default",
        extraction_inputs={"extractor": "standalone", "version": "1"},
    ).to_dict()

    assert graph.status == "candidate_only"
    assert identity["status"] == "draft"
    assert identity["sourceRevision"] is None


def test_normalized_identity_is_deterministic_safe_and_dependency_bound(tmp_path):
    root = tmp_path / "library"
    _write(root / "Machine.SLDASM", b"assembly")
    _write(root / "parts" / "Frame.SLDPRT", b"frame")
    discovery = _discover(root)
    graph = resolve_dependency_graph(
        discovery,
        [DependencyReference("Machine.SLDASM", "parts/Frame.SLDPRT")],
        requested_root="Machine.SLDASM",
        reference_graph_complete=True,
    )

    first = build_normalized_source_identity(
        discovery,
        graph,
        configuration="Default",
        extraction_inputs={"exporterVersion": "p2-test", "resolve": True},
    ).to_dict()
    second = build_normalized_source_identity(
        discovery,
        graph,
        configuration="Default",
        extraction_inputs={"resolve": True, "exporterVersion": "p2-test"},
    ).to_dict()

    assert first == second
    assert first["status"] == "draft"
    assert len(first["sourceRevision"]) == 64
    assert first["identityFingerprint"] == second["identityFingerprint"]
    serialized = json.dumps(first, sort_keys=True)
    assert str(tmp_path) not in serialized
    assert '"localPath":' not in serialized
    assert '"sourcePath":' not in serialized
    assert [item["relativePath"] for item in first["sourceFiles"]] == [
        "Machine.SLDASM",
        "parts/Frame.SLDPRT",
    ]

    changed_configuration = build_normalized_source_identity(
        discovery,
        graph,
        configuration="Alternate",
        extraction_inputs={"exporterVersion": "p2-test", "resolve": True},
    ).to_dict()
    assert changed_configuration["sourceRevision"] != first["sourceRevision"]

    expected = canonical_json_sha256(
        {
            "configuration": "Default",
            "extractionInputs": {
                "exporterVersion": "p2-test",
                "resolve": True,
            },
            "sourceFileHashes": [
                {
                    "pathKey": item.path_key,
                    "sha256": item.sha256,
                }
                for item in discovery.records
            ],
        }
    )
    assert first["sourceRevision"] == expected


def test_source_content_change_changes_fingerprint_and_source_revision(tmp_path):
    root = tmp_path / "library"
    source = _write(root / "Machine.SLDPRT", b"revision-one")

    first_discovery = _discover(root)
    first_graph = resolve_dependency_graph(
        first_discovery,
        [],
        requested_root="Machine.SLDPRT",
        reference_graph_complete=True,
    )
    first = build_normalized_source_identity(
        first_discovery,
        first_graph,
        configuration="Default",
        extraction_inputs={"extractorVersion": "1"},
    ).to_dict()

    source.write_bytes(b"revision-two")
    second_discovery = _discover(root)
    second_graph = resolve_dependency_graph(
        second_discovery,
        [],
        requested_root="Machine.SLDPRT",
        reference_graph_complete=True,
    )
    second = build_normalized_source_identity(
        second_discovery,
        second_graph,
        configuration="Default",
        extraction_inputs={"extractorVersion": "1"},
    ).to_dict()

    assert first_discovery.source_fingerprint != second_discovery.source_fingerprint
    assert first["sourceRevision"] != second["sourceRevision"]
    assert first["candidateId"] != second["candidateId"]


def test_normalized_identity_rejects_protected_path_input_fields(tmp_path):
    root = tmp_path / "library"
    _write(root / "Machine.SLDPRT", b"machine")
    discovery = _discover(root)
    graph = resolve_dependency_graph(
        discovery,
        [],
        requested_root="Machine.SLDPRT",
        reference_graph_complete=True,
    )

    with pytest.raises(ValueError, match="protected path fields"):
        build_normalized_source_identity(
            discovery,
            graph,
            configuration="Default",
            extraction_inputs={
                "extractor": {
                    "sourcePath": str(root / "Machine.SLDPRT"),
                }
            },
        )


def test_quarantined_graph_produces_no_source_revision(tmp_path):
    root = tmp_path / "library"
    _write(root / "Machine.SLDASM", b"assembly")
    discovery = _discover(root)
    graph = resolve_dependency_graph(
        discovery,
        [DependencyReference("Machine.SLDASM", "Missing.SLDPRT")],
        requested_root="Machine.SLDASM",
        reference_graph_complete=True,
    )

    identity = build_normalized_source_identity(
        discovery,
        graph,
        configuration="Default",
        extraction_inputs={"extractor": "none"},
    ).to_dict()

    assert identity["status"] == "quarantined"
    assert identity["sourceRevision"] is None
    assert "dependency_missing" in {
        item["code"] for item in identity["findings"]
    }
