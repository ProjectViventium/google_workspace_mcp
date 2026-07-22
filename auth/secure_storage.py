"""Owner-only, symlink-safe JSON storage for OAuth secrets and tokens."""

from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any


PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
MAX_PRIVATE_JSON_BYTES = 16 * 1024 * 1024


class StorageSecurityError(PermissionError):
    """Raised when secret-bearing storage is not owned and isolated safely."""


def _effective_uid() -> int | None:
    get_euid = getattr(os, "geteuid", None)
    return get_euid() if get_euid is not None else None


def _assert_owner(file_stat: os.stat_result, path: Path) -> None:
    expected_uid = _effective_uid()
    if expected_uid is not None and file_stat.st_uid != expected_uid:
        raise StorageSecurityError(
            f"Secret-bearing path must be owned by the current user: {path}"
        )


def _assert_regular_file(file_stat: os.stat_result, path: Path) -> None:
    if stat.S_ISLNK(file_stat.st_mode):
        raise StorageSecurityError(
            f"Secret-bearing path must not be a symbolic link: {path}"
        )
    if not stat.S_ISREG(file_stat.st_mode):
        raise StorageSecurityError(
            f"Secret-bearing path must be a regular file: {path}"
        )


def _assert_directory(file_stat: os.stat_result, path: Path) -> None:
    if stat.S_ISLNK(file_stat.st_mode):
        raise StorageSecurityError(
            f"Secret-bearing directory must not be a symbolic link: {path}"
        )
    if not stat.S_ISDIR(file_stat.st_mode):
        raise StorageSecurityError(
            f"Secret-bearing path must be a directory: {path}"
        )


def _validate_leaf_name(name: str) -> None:
    if not name or name in {".", ".."} or Path(name).name != name:
        raise StorageSecurityError(f"Unsafe secret-bearing filename: {name!r}")
    if "\x00" in name or "/" in name or "\\" in name:
        raise StorageSecurityError(f"Unsafe secret-bearing filename: {name!r}")


def _open_private_directory(
    path: Path,
    *,
    create: bool,
    repair_mode: bool = True,
    require_owner: bool = True,
) -> int:
    path = Path(path)
    try:
        initial = os.lstat(path)
    except FileNotFoundError:
        if not create:
            raise
        # mkdir(parents=True) may traverse intentional parent-directory aliases, but
        # the secret-bearing leaf itself is subsequently opened with O_NOFOLLOW.
        path.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
        initial = os.lstat(path)

    _assert_directory(initial, path)
    if require_owner:
        _assert_owner(initial, path)

    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    directory_fd = os.open(path, flags)
    try:
        opened = os.fstat(directory_fd)
        _assert_directory(opened, path)
        if require_owner:
            _assert_owner(opened, path)
        if repair_mode:
            os.fchmod(directory_fd, PRIVATE_DIRECTORY_MODE)
            if stat.S_IMODE(os.fstat(directory_fd).st_mode) != PRIVATE_DIRECTORY_MODE:
                raise StorageSecurityError(
                    f"Secret-bearing directory must have mode 0700: {path}"
                )
        return directory_fd
    except Exception:
        os.close(directory_fd)
        raise


def ensure_private_directory(path: str | os.PathLike[str]) -> Path:
    """Create or harden an owned secret directory and return its path."""
    private_path = Path(path)
    directory_fd = _open_private_directory(private_path, create=True)
    os.close(directory_fd)
    return private_path


def _open_private_file(
    path: Path,
    *,
    repair_mode: bool,
    private_directory: bool,
) -> int:
    _validate_leaf_name(path.name)
    directory_fd = _open_private_directory(
        path.parent,
        create=False,
        repair_mode=private_directory,
        require_owner=private_directory,
    )
    try:
        flags = os.O_RDONLY
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        try:
            file_fd = os.open(path.name, flags, dir_fd=directory_fd)
        except OSError as exc:
            # macOS reports ELOOP for O_NOFOLLOW; surface a stable, actionable error.
            try:
                leaf_stat = os.stat(
                    path.name, dir_fd=directory_fd, follow_symlinks=False
                )
            except OSError:
                raise exc
            if stat.S_ISLNK(leaf_stat.st_mode):
                raise StorageSecurityError(
                    f"Secret-bearing path must not be a symbolic link: {path}"
                ) from exc
            raise

        try:
            file_stat = os.fstat(file_fd)
            _assert_regular_file(file_stat, path)
            _assert_owner(file_stat, path)
            mode = stat.S_IMODE(file_stat.st_mode)
            if mode != PRIVATE_FILE_MODE:
                if not repair_mode:
                    raise StorageSecurityError(
                        f"Secret-bearing file must have mode 0600: {path}"
                    )
                os.fchmod(file_fd, PRIVATE_FILE_MODE)
                if stat.S_IMODE(os.fstat(file_fd).st_mode) != PRIVATE_FILE_MODE:
                    raise StorageSecurityError(
                        f"Secret-bearing file must have mode 0600: {path}"
                    )
            return file_fd
        except Exception:
            os.close(file_fd)
            raise
    finally:
        os.close(directory_fd)


def read_private_json(
    path: str | os.PathLike[str],
    *,
    repair_mode: bool,
    private_directory: bool = True,
) -> Any:
    """Read bounded JSON through an owner-only regular file without following links."""
    private_path = Path(path)
    file_fd = _open_private_file(
        private_path,
        repair_mode=repair_mode,
        private_directory=private_directory,
    )
    try:
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(file_fd, min(64 * 1024, MAX_PRIVATE_JSON_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_PRIVATE_JSON_BYTES:
                raise StorageSecurityError(
                    f"Secret-bearing JSON exceeds {MAX_PRIVATE_JSON_BYTES} bytes: {private_path}"
                )
        return json.loads(b"".join(chunks))
    finally:
        os.close(file_fd)


def _assert_safe_destination(directory_fd: int, path: Path) -> None:
    try:
        destination = os.stat(
            path.name, dir_fd=directory_fd, follow_symlinks=False
        )
    except FileNotFoundError:
        return
    _assert_regular_file(destination, path)
    _assert_owner(destination, path)


def atomic_write_private_json(
    path: str | os.PathLike[str],
    value: Any,
    *,
    indent: int | None = 2,
) -> None:
    """Atomically replace owner-only JSON, preserving the old file on failure."""
    private_path = Path(path)
    _validate_leaf_name(private_path.name)
    serialized = json.dumps(value, indent=indent).encode("utf-8")
    directory_fd = _open_private_directory(private_path.parent, create=True)
    temporary_name = f".{private_path.name}.tmp-{secrets.token_hex(12)}"
    temporary_created = False
    try:
        _assert_safe_destination(directory_fd, private_path)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_CLOEXEC", 0)
        temporary_fd = os.open(
            temporary_name,
            flags,
            PRIVATE_FILE_MODE,
            dir_fd=directory_fd,
        )
        temporary_created = True
        try:
            view = memoryview(serialized)
            while view:
                written = os.write(temporary_fd, view)
                if written <= 0:
                    raise OSError("Failed writing private JSON atomically")
                view = view[written:]
            os.fchmod(temporary_fd, PRIVATE_FILE_MODE)
            os.fsync(temporary_fd)
        finally:
            os.close(temporary_fd)

        os.replace(
            temporary_name,
            private_path.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        temporary_created = False
        os.fsync(directory_fd)
    finally:
        if temporary_created:
            try:
                os.unlink(temporary_name, dir_fd=directory_fd)
            except FileNotFoundError:
                pass
        os.close(directory_fd)


def remove_private_file(path: str | os.PathLike[str]) -> bool:
    """Delete only an owned regular secret file; never follow or remove a symlink."""
    private_path = Path(path)
    _validate_leaf_name(private_path.name)
    try:
        directory_fd = _open_private_directory(private_path.parent, create=False)
    except FileNotFoundError:
        return False
    try:
        try:
            file_stat = os.stat(
                private_path.name, dir_fd=directory_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            return False
        _assert_regular_file(file_stat, private_path)
        _assert_owner(file_stat, private_path)
        os.unlink(private_path.name, dir_fd=directory_fd)
        os.fsync(directory_fd)
        return True
    finally:
        os.close(directory_fd)


def list_private_json_files(
    directory: str | os.PathLike[str],
    *,
    repair_mode: bool,
) -> list[Path]:
    """List validated owner-only JSON files in a private directory."""
    private_directory = Path(directory)
    try:
        directory_fd = _open_private_directory(private_directory, create=False)
    except FileNotFoundError:
        return []
    try:
        names = sorted(name for name in os.listdir(directory_fd) if name.endswith(".json"))
    finally:
        os.close(directory_fd)

    files: list[Path] = []
    for name in names:
        file_path = private_directory / name
        file_fd = _open_private_file(
            file_path,
            repair_mode=repair_mode,
            private_directory=True,
        )
        os.close(file_fd)
        files.append(file_path)
    return files
