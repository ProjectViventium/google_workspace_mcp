#!/usr/bin/env python3
"""Build the public DXT from an explicit git-tracked runtime allowlist."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import tomllib
import zipfile


ROOT_FILES = {
    ".python-version",
    "LICENSE",
    "README.md",
    "fastmcp_server.py",
    "main.py",
    "manifest.json",
    "pyproject.toml",
    "uv.lock",
}
RUNTIME_DIRECTORIES = {
    "auth",
    "core",
    "gcalendar",
    "gchat",
    "gdocs",
    "gdrive",
    "gforms",
    "gmail",
    "gsearch",
    "gsheets",
    "gslides",
    "gtasks",
}
ARCHIVE_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _validate_versions(root: Path) -> None:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    manifest_version = manifest.get("version")
    project_version = project.get("project", {}).get("version")
    if manifest_version != project_version:
        raise ValueError(
            f"manifest version {manifest_version!r} does not match project version {project_version!r}"
        )
    if manifest.get("dxt_version") != "0.1":
        raise ValueError("manifest dxt_version must be '0.1'")


def _is_runtime_path(path: PurePosixPath) -> bool:
    return path.as_posix() in ROOT_FILES or (
        len(path.parts) > 1
        and path.parts[0] in RUNTIME_DIRECTORIES
        and path.suffix in {".py", ".yaml"}
    )


def collect_bundle_files(root: Path) -> list[Path]:
    """Return the public runtime files tracked by the current git index."""
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        check=True,
        capture_output=True,
    )
    relative_paths = [
        Path(raw.decode("utf-8"))
        for raw in result.stdout.split(b"\0")
        if raw and _is_runtime_path(PurePosixPath(raw.decode("utf-8")))
    ]
    missing = sorted(ROOT_FILES - {path.as_posix() for path in relative_paths})
    if missing:
        raise ValueError(f"required bundle files are not tracked: {', '.join(missing)}")
    for relative_path in relative_paths:
        source = root / relative_path
        if source.is_symlink() or not source.is_file():
            raise ValueError(
                f"bundle input must be a regular file: {relative_path.as_posix()}"
            )
    return sorted(relative_paths, key=lambda path: path.as_posix())


def build_bundle(root: Path, output: Path) -> None:
    """Create an atomic, byte-reproducible DXT archive."""
    root = root.resolve()
    output = output.resolve()
    _validate_versions(root)
    bundle_files = collect_bundle_files(root)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)

    try:
        with zipfile.ZipFile(
            temporary_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for relative_path in bundle_files:
                info = zipfile.ZipInfo(relative_path.as_posix(), ARCHIVE_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(
                    info, (root / relative_path).read_bytes(), compresslevel=9
                )
        temporary_path.replace(output)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "google_workspace_mcp.dxt",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    build_bundle(root, args.output)
    print(args.output.resolve())


if __name__ == "__main__":
    main()
