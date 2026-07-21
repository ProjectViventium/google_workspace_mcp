import importlib.util
from pathlib import Path
import zipfile

import pytest

_BUILD_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_dxt.py"
_SPEC = importlib.util.spec_from_file_location("google_workspace_mcp_build_dxt", _BUILD_SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_BUILD_DXT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BUILD_DXT)
build_bundle = _BUILD_DXT.build_bundle
collect_bundle_files = _BUILD_DXT.collect_bundle_files


def test_bundle_inventory_excludes_local_and_stale_artifacts():
    root = Path(__file__).resolve().parents[1]

    bundle_files = {path.as_posix() for path in collect_bundle_files(root)}

    assert "manifest.json" in bundle_files
    assert "uv.lock" in bundle_files
    assert "auth/google_auth.py" in bundle_files
    assert "auth/secure_storage.py" in bundle_files
    assert not any(".ruff_cache" in path for path in bundle_files)
    assert not any(path.endswith(".dxt") for path in bundle_files)
    assert "changes_since_120.txt" not in bundle_files


def test_build_bundle_is_version_aligned_and_reproducible(tmp_path):
    root = Path(__file__).resolve().parents[1]
    first = tmp_path / "first.dxt"
    second = tmp_path / "second.dxt"

    build_bundle(root, first)
    build_bundle(root, second)

    assert first.read_bytes() == second.read_bytes()
    with zipfile.ZipFile(first) as archive:
        manifest = archive.read("manifest.json").decode()
        assert '"version": "1.5.2"' in manifest
        assert "auth/secure_storage.py" in archive.namelist()
        assert ".ruff_cache/CACHEDIR.TAG" not in archive.namelist()


def test_checked_in_bundle_matches_the_current_runtime_sources(tmp_path):
    root = Path(__file__).resolve().parents[1]
    rebuilt = tmp_path / "rebuilt.dxt"

    build_bundle(root, rebuilt)

    assert (root / "google_workspace_mcp.dxt").read_bytes() == rebuilt.read_bytes()


def test_bundle_fails_closed_when_manifest_and_project_versions_differ(tmp_path):
    root = Path(__file__).resolve().parents[1]
    manifest = (
        (root / "manifest.json")
        .read_text()
        .replace('"version": "1.5.2"', '"version": "0.0.0"')
    )
    (tmp_path / "manifest.json").write_text(manifest)
    (tmp_path / "pyproject.toml").write_text((root / "pyproject.toml").read_text())

    with pytest.raises(ValueError, match="version"):
        build_bundle(tmp_path, tmp_path / "invalid.dxt")
