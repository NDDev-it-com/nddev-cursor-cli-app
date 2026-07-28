#!/usr/bin/env python3
"""Transactional setup manager for a caller-selected Cursor CLI config root."""

from __future__ import annotations

import argparse
import base64
import contextlib
import errno
import fcntl
import glob
import hashlib
import json
import os
import platform as py_platform
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
SETUP_CATALOG_ROOT = ROOT / "setups"
PROFILE_CATALOG_ROOT = ROOT / "profiles"
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
PRODUCT_NAME = "nddev-cursor-cli-app"
CURSOR_COMMAND = "agent"
CONFIG_NAME = "cli-config.json"
STAMP_NAME = "NDDEV-CURSOR-CLI-SETUP.json"
BACKUP_NAME = "NDDEV-CURSOR-CLI-BACKUP.json"
SOFTWARE_STAMP_NAME = "NDDEV-CURSOR-CLI-SOFTWARE.json"
SOFTWARE_TRANSACTION_NAME = "NDDEV-CURSOR-CLI-TRANSACTION.json"
SOFTWARE_REMOVE_ROLLBACK_PREFIX = ".remove-rollback-"
CONTROL_ROOT_NAME = ".nddev-cursor-cli"
CONTROL_LOCKS_NAME = "locks"
CONTROL_LOCK_NAME = "target.lock"
CONTROL_BACKUPS_NAME = "backups"
CONTROL_CLEANUP_PENDING_NAME = "cleanup-pending"
MANAGED_TRANSACTION_PREFIX = ".managed-txn-"
BACKUP_STAGE_PREFIX = ".slot-stage-"
BACKUP_RETIRED_PREFIX = ".slot-retired-"
BACKUP_CLEANUP_PREFIX = ".slot-cleanup-"
CLEANUP_STAGE_PREFIX = ".cleanup-stage-"
CLEANUP_JOURNAL_NAME = "journal.json"
CLEANUP_TOMBSTONES_NAME = "tombstones"
CLEANUP_SCHEMA_VERSION = 1
CLEANUP_MAX_TOMBSTONES = 8
CLEANUP_MAX_ENTRIES = 20000
BOOTSTRAP_LOCK_ROOT_PREFIX = "nddev-cursor-cli-app-locks"
BOOTSTRAP_PRODUCT_LOCK_NAME = "global.lock"
BOOTSTRAP_LOCK_MAX_BYTES = 4096
OWNER_FILE_MODE = 0o600
OWNER_DIRECTORY_MODE = 0o700
OWNER_EXEC_MODE = 0o700
LOCK_HELD_DIRECTORY_MODE = 0o500
METADATA_MAX_BYTES = 256 * 1024
MANAGED_PAYLOAD_MAX_BYTES = 8 * 1024 * 1024
SOFTWARE_ARTIFACT_MAX_BYTES = 300 * 1024 * 1024
CLEANUP_MAX_TOTAL_SIZE = SOFTWARE_ARTIFACT_MAX_BYTES
DEFAULT_CONTENT_SETUP_ID = "nddev-builder"
DEFAULT_PROFILE_ID = "full-auto"
TARGET_COMMANDS = frozenset(
    {
        "status",
        "plan",
        "install",
        "update",
        "switch",
        "migrate",
        "restore",
        "remove",
        "software-status",
        "install-cli",
        "update-cli",
        "remove-cli",
        "launch",
    }
)
LEGACY_SETUP_PROFILE_IDS = {
    "full-auto": "full-auto",
    "safe": "safe",
    "review": None,
}
CURSOR_VERSION = "2026.07.23-e383d2b"
CURSOR_RELEASE_BASE_URL = f"https://downloads.cursor.com/lab/{CURSOR_VERSION}"
CURSOR_RUNTIME_ROOT = Path("dist-package")
CURSOR_RUNTIME_ENTRYPOINT = Path("cursor-agent")
LAUNCH_IMAGES_NAME = "launch-images"
LAUNCH_IMAGE_AGENT_NAME = "agent"
CURSOR_RUNTIME_REQUIRED_FILES = frozenset(
    {CURSOR_RUNTIME_ENTRYPOINT, Path("node"), Path("index.js")}
)
CURSOR_RUNTIME_EPHEMERAL_ROOTS = frozenset({Path(".running")})
LINUX_OS_RELEASE_PATH = Path("/etc/os-release")
SUPPORTED_LINUX_DISTRIBUTION_ID = "ubuntu"
SUPPORTED_LINUX_LIBC = "glibc"
MUSL_LOADER_GLOBS = (
    "/lib/ld-musl-*.so.1",
    "/usr/lib/ld-musl-*.so.1",
    "/lib/*/ld-musl-*.so.1",
    "/usr/lib/*/ld-musl-*.so.1",
)
CURSOR_OFFICIAL_ASSETS = {
    ("darwin", "arm64"): (
        "darwin/arm64/agent-cli-package.tar.gz",
        "f2eb25851f2079dcdf0558a816e06c402d187abfca93255d35167020439ebbf2",
        69706672,
    ),
    ("darwin", "x64"): (
        "darwin/x64/agent-cli-package.tar.gz",
        "f44194dfcb41468f85bfb4e53978ac098a2a78ce629806490c32b80b40975aa2",
        71981431,
    ),
    ("linux", "arm64"): (
        "linux/arm64/agent-cli-package.tar.gz",
        "f40b99647cb24e0da885e97620a2048034f1fe8961910d573d827d77c4d26dcb",
        81115960,
    ),
    ("linux", "x64"): (
        "linux/x64/agent-cli-package.tar.gz",
        "702ad595213bee5df0268be9f80a19f29fcceaa2a42fc55e39f2b5199051f0c4",
        82521188,
    ),
}
SUPPORTED_HOST_IDS = (
    "macos-arm64",
    "macos-x64",
    "ubuntu-glibc-arm64",
    "ubuntu-glibc-x64",
)
UNSUPPORTED_HOST_CATEGORIES = (
    "windows",
    "non-ubuntu-linux",
    "linux-musl",
    "unsupported-architecture",
)
VENDOR_ASSET_HOST_MAP = {
    "macos-arm64": ("darwin", "arm64"),
    "macos-x64": ("darwin", "x64"),
    "ubuntu-glibc-arm64": ("linux", "arm64"),
    "ubuntu-glibc-x64": ("linux", "x64"),
}
PROVIDER_SECRET_NAMES = {
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GROK_API_KEY",
    "XAI_API_KEY",
    "CURSOR_API_KEY",
    "CURSOR_TOKEN",
}
BLOCKED_LAUNCH_LONG_FLAGS = {
    "--approve-mcps",
    "--force",
    "--network",
    "--sandbox",
    "--skip-worktree-setup",
    "--trust",
    "--worktree",
    "--yolo",
}
BLOCKED_LAUNCH_SHORT_FLAGS = {
    "f": "--force",
    "w": "--worktree",
}
BLOCKED_LAUNCH_COMMANDS = {
    "acp",
    "install-shell-integration",
    "sandbox",
    "uninstall-shell-integration",
    "update",
    "worker",
}
PRODUCT_LIFECYCLE_LOCK_KEY = f"/__{PRODUCT_NAME}_product_lifecycle__"
READ_ONLY_TARGET_COMMANDS = frozenset({"status", "plan", "software-status"})
_PARSER_JSON_ERROR_REQUESTED = False
SETUP_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
CLEANUP_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}\Z")
MANAGED_CONFIG_KEYS = (
    "version",
    "editor",
    "permissions",
    "approvalMode",
    "sandbox",
    "network",
    "hints",
    "notifications",
)
BUILDER_SOURCE_ROOT = ROOT / "plugins" / "nddev-builder"
ISOLATED_HOME_ROOT = Path(".nddev-cursor-home")
MUTABLE_RUNTIME_ROOT = Path(".nddev-cursor-runtime")
MUTABLE_RUNTIME_TMP_ROOT = MUTABLE_RUNTIME_ROOT / "tmp"
LEGACY_BUILDER_TARGET_ROOT = Path("plugins") / "local" / "nddev-builder"
BUILDER_TARGET_ROOT = ISOLATED_HOME_ROOT / ".cursor" / "plugins" / "local" / "nddev-builder"
BUILDER_ROOT_FILES = (Path("README.md"),)
BUILDER_COMPONENT_ROOTS = (
    Path(".cursor-plugin"),
    Path("rules"),
    Path("skills"),
    Path("agents"),
    Path("commands"),
)
BUILDER_MAX_FILE_COUNT = 200
MANAGED_CORE_PATHS = (
    Path(CONFIG_NAME),
    Path(STAMP_NAME),
)
STAMP_KEYS_V1 = {
    "schema_version",
    "product_name",
    "build_version",
    "setup_id",
    "canonical_target",
    "managed_files",
    "builder_projection",
}
STAMP_KEYS_V2 = {
    "schema_version",
    "product_name",
    "build_version",
    "content_setup_id",
    "profile_id",
    "canonical_target",
    "managed_files",
    "builder_projection",
}
BACKUP_SCHEMA_VERSION = 3
BACKUP_KEYS_V3 = {
    "schema_version",
    "product_name",
    "build_version",
    "slot",
    "canonical_target",
    "source_content_setup_id",
    "source_profile_id",
    "source_legacy_setup_id",
    "managed_files",
    "created_at",
    "files",
}
BACKUP_FILE_KEYS_V1 = {
    "payload",
    "sha256",
}
BACKUP_FILE_DIGEST_DOMAIN = b"nddev-cursor-cli-backup-file-v1\0"
SHA256_HEX_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
BOOTSTRAP_LOCK_KEYS_V1 = {
    "schema_version",
    "product_name",
    "lock_key",
    "target_sha256",
}
CLEANUP_JOURNAL_KEYS_V1 = {
    "schema_version",
    "product_name",
    "build_version",
    "canonical_target",
    "cleanup_parent",
    "tombstone_count",
    "entry_count",
    "total_size",
    "created_at",
    "tombstones",
}
CLEANUP_TOMBSTONE_KEYS_V1 = {
    "name",
    "kind",
    "entry_count",
    "total_size",
    "entries",
}
CLEANUP_ENTRY_KEYS_V1 = {
    "relative",
    "kind",
    "uid",
    "mode",
    "nlink",
    "device",
    "inode",
    "size",
    "mtime_ns",
    "sha256",
}
_BOOTSTRAP_LOCKS: dict[str, dict[str, Any]] = {}
_BOOTSTRAP_STATE_LOCK = threading.RLock()


class CursorSetupError(Exception):
    """A safe, user-facing lifecycle failure."""


class CursorArgumentError(Exception):
    """A parser failure that can be rendered through the JSON error boundary."""


def fail(message: str) -> NoReturn:
    raise CursorSetupError(message)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def fsync_existing_parent(path: Path) -> None:
    fsync_directory(path.parent)


def require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        fail(f"{label} has invalid keys (missing={missing}, extra={extra})")


def require_bounded_size(info: os.stat_result, label: str, max_bytes: int) -> None:
    if info.st_size > max_bytes:
        fail(f"{label} exceeds the {max_bytes}-byte size limit")


def require_regular_file(path: Path, label: str, *, max_bytes: int) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail(f"{label} is missing")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        fail(f"{label} must be a regular non-symlink file")
    if info.st_nlink != 1:
        fail(f"{label} must not have hard-link aliases")
    require_bounded_size(info, label, max_bytes)
    return info


def read_regular_file(
    path: Path, label: str, *, max_bytes: int = MANAGED_PAYLOAD_MAX_BYTES
) -> bytes:
    before = require_regular_file(path, label, max_bytes=max_bytes)
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            fail(f"{label} changed while it was being opened")
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            fail(f"{label} changed to an unsafe file")
        require_bounded_size(opened, label, max_bytes)
        blocks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, 65536)
            if not block:
                break
            total += len(block)
            if total > max_bytes:
                fail(f"{label} exceeds the {max_bytes}-byte size limit")
            blocks.append(block)
        after = os.fstat(descriptor)
        require_bounded_size(after, label, max_bytes)
    finally:
        os.close(descriptor)
    final = require_regular_file(path, label, max_bytes=max_bytes)
    expected = (before.st_dev, before.st_ino)
    if (after.st_dev, after.st_ino) != expected or (final.st_dev, final.st_ino) != expected:
        fail(f"{label} changed while it was being read")
    return b"".join(blocks)


def path_exists_no_follow_local(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def capture_exact_tree_snapshot(root: Path, label: str) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    if not path_exists_no_follow_local(root):
        snapshot["."] = {"kind": "absent"}
        return snapshot

    def capture(path: Path, relative: str) -> None:
        info = path.lstat()
        record: dict[str, Any] = {
            "device": info.st_dev,
            "inode": info.st_ino,
            "mode": stat.S_IMODE(info.st_mode),
            "mtime_ns": info.st_mtime_ns,
            "size": info.st_size,
        }
        if stat.S_ISLNK(info.st_mode):
            record["kind"] = "symlink"
            record["target"] = os.readlink(path)
        elif stat.S_ISDIR(info.st_mode):
            record["kind"] = "dir"
        elif stat.S_ISREG(info.st_mode):
            content = read_regular_file(
                path,
                f"{label} snapshot file {relative}",
                max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES,
            )
            record["kind"] = "file"
            record["size"] = len(content)
            record["sha256"] = sha256_bytes(content)
            record["content"] = content
        else:
            fail(f"{label} snapshot path is unsupported: {relative}")
        snapshot[relative] = record

    capture(root, ".")
    if snapshot["."]["kind"] != "dir":
        return snapshot
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        capture(path, path.relative_to(root).as_posix())
    return snapshot


def remove_extra_snapshot_path(path: Path) -> None:
    if not path_exists_no_follow_local(path):
        return
    info = path.lstat()
    if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
        shutil.rmtree(path)
    else:
        path.unlink()
    fsync_existing_parent(path)


def restore_snapshot_file_content(path: Path, record: dict[str, Any], label: str) -> None:
    info = require_regular_file(path, label, max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES)
    if (info.st_dev, info.st_ino) != (record["device"], record["inode"]):
        fail(f"{label} inode changed before exact rollback")
    flags = os.O_WRONLY | os.O_TRUNC
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        view = memoryview(record["content"])
        while view:
            written = os.write(descriptor, view)
            if written == 0:
                fail(f"{label} rollback write made no progress")
            view = view[written:]
        os.fchmod(descriptor, record["mode"])
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def restore_snapshot_metadata(path: Path, record: dict[str, Any], label: str) -> None:
    info = path.lstat()
    if (info.st_dev, info.st_ino) != (record["device"], record["inode"]):
        fail(f"{label} inode changed before exact rollback")
    if record["kind"] != "symlink":
        os.chmod(path, record["mode"])
    os.utime(
        path,
        ns=(info.st_atime_ns, record["mtime_ns"]),
        follow_symlinks=False,
    )


def capture_existing_directory_object(path: Path, label: str) -> dict[str, Any]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail(f"{label} is missing")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a real directory")
    return {
        "kind": "dir",
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode),
        "mtime_ns": info.st_mtime_ns,
        "size": info.st_size,
    }


def restore_existing_directory_object(
    path: Path, snapshot: dict[str, Any], label: str
) -> None:
    errors: list[str] = []
    for _ in range(4):
        try:
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                fail(f"{label} rollback path kind changed")
            if (info.st_dev, info.st_ino) != (snapshot["device"], snapshot["inode"]):
                fail(f"{label} inode changed before exact rollback")
            if stat.S_IMODE(info.st_mode) != snapshot["mode"]:
                os.chmod(path, snapshot["mode"])
            if path.lstat().st_mtime_ns != snapshot["mtime_ns"]:
                os.utime(
                    path,
                    ns=(path.lstat().st_atime_ns, snapshot["mtime_ns"]),
                    follow_symlinks=False,
                )
            fsync_directory(path)
            current = capture_existing_directory_object(path, label)
            if current == snapshot:
                return
            errors.append(f"current={current!r}, expected={snapshot!r}")
        except BaseException as exc:  # noqa: BLE001 - retry exact restoration.
            errors.append(str(exc))
    fail(f"{label} exact directory rollback verification failed: {errors[-5:]}")


def current_snapshot_paths(root: Path) -> set[str]:
    if not path_exists_no_follow_local(root):
        return set()
    paths = {"."}
    if root.is_dir() and not root.is_symlink():
        paths.update(path.relative_to(root).as_posix() for path in root.rglob("*"))
    return paths


def restore_exact_tree_snapshot(
    root: Path, snapshot: dict[str, dict[str, Any]], label: str
) -> None:
    if snapshot.get(".", {}).get("kind") == "absent":
        if path_exists_no_follow_local(root):
            remove_extra_snapshot_path(root)
        return
    errors: list[str] = []
    for _ in range(4):
        try:
            expected_paths = set(snapshot)
            for relative in sorted(
                current_snapshot_paths(root) - expected_paths,
                key=lambda item: (item.count("/"), item),
                reverse=True,
            ):
                remove_extra_snapshot_path(root / relative)
            for relative, record in sorted(
                snapshot.items(),
                key=lambda item: (item[0].count("/"), item[0]),
                reverse=True,
            ):
                path = root if relative == "." else root / relative
                if not path_exists_no_follow_local(path):
                    fail(f"{label} rollback cannot restore missing path: {relative}")
                info = path.lstat()
                kind = record["kind"]
                if kind == "file":
                    content = read_regular_file(
                        path,
                        f"{label} rollback file {relative}",
                        max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES,
                    )
                    if content != record["content"] or stat.S_IMODE(info.st_mode) != record["mode"]:
                        restore_snapshot_file_content(
                            path, record, f"{label} rollback file {relative}"
                        )
                elif kind == "dir":
                    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                        fail(f"{label} rollback path kind changed: {relative}")
                elif kind == "symlink":
                    if not stat.S_ISLNK(info.st_mode) or os.readlink(path) != record["target"]:
                        fail(f"{label} rollback symlink changed: {relative}")
                else:
                    fail(f"{label} rollback snapshot has invalid kind: {relative}")
                restore_snapshot_metadata(path, record, f"{label} rollback path {relative}")
            if capture_exact_tree_snapshot(root, label) == snapshot:
                return
        except BaseException as exc:  # noqa: BLE001 - retry exact restoration.
            errors.append(str(exc))
    fail(f"{label} exact rollback verification failed: {errors[-5:]}")


def parse_json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        fail(f"cannot read valid JSON from {label}: {exc}")
    if not isinstance(value, dict):
        fail(f"{label} must contain a JSON object")
    return value


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    return parse_json_object(read_regular_file(path, label, max_bytes=METADATA_MAX_BYTES), label)


def validate_setup_id(setup_id: str) -> None:
    if not SETUP_ID_PATTERN.fullmatch(setup_id):
        fail(f"invalid setup id: {setup_id!r}")


def validate_supported_selection(content_setup_id: str, profile_id: str) -> None:
    if content_setup_id != DEFAULT_CONTENT_SETUP_ID:
        if content_setup_id in LEGACY_SETUP_PROFILE_IDS:
            fail(
                f"{content_setup_id!r} is a legacy setup id; use "
                f"--setup {DEFAULT_CONTENT_SETUP_ID} --profile <full-auto|safe>"
            )
        fail(f"unsupported content setup: {content_setup_id}")
    if profile_id not in {"full-auto", "safe"}:
        if profile_id in {"review", "balanced"}:
            fail(f"unsupported Cursor permission profile: {profile_id}")
        fail(f"unknown profile: {profile_id}")


def validate_config(config: dict[str, Any], label: str) -> None:
    if config.get("version") != 1:
        fail(f"{label} must declare version 1")
    editor = config.get("editor")
    if (
        not isinstance(editor, dict)
        or set(editor) != {"vimMode"}
        or not isinstance(editor.get("vimMode"), bool)
    ):
        fail(f"{label} has invalid editor settings")
    permissions = config.get("permissions")
    if not isinstance(permissions, dict) or set(permissions) != {"allow", "deny"}:
        fail(f"{label} has invalid permissions")
    for key in ("allow", "deny"):
        values = permissions.get(key)
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            fail(f"{label} permissions.{key} must be a string array")
    if config.get("approvalMode") not in {"allowlist", "auto-review", "unrestricted"}:
        fail(f"{label} has invalid approvalMode")
    sandbox = config.get("sandbox")
    if not isinstance(sandbox, dict) or set(sandbox) != {"mode", "networkAccess"}:
        fail(f"{label} has invalid sandbox settings")
    if sandbox.get("mode") not in {"enabled", "disabled"}:
        fail(f"{label} has invalid sandbox.mode")
    if sandbox.get("networkAccess") not in {"enabled", "disabled"}:
        fail(f"{label} has invalid sandbox.networkAccess")
    network = config.get("network")
    if not isinstance(network, dict) or set(network) != {"useHttp1ForAgent"}:
        fail(f"{label} has invalid network settings")
    if not isinstance(network.get("useHttp1ForAgent"), bool):
        fail(f"{label} network.useHttp1ForAgent must be a boolean")


def validate_profile_config(profile: dict[str, Any], config: dict[str, Any], label: str) -> None:
    validate_config(config, label)
    expected = {
        "approvalMode": profile["approval_mode"],
        "sandbox": {
            "mode": profile["sandbox_mode"],
            "networkAccess": profile["network_access"],
        },
    }
    for key, value in expected.items():
        if config.get(key) != value:
            fail(f"{label} does not match profile {profile['id']} {key}")
    if config["approvalMode"] == "auto-review":
        fail(f"{label} uses unsupported auto-review approval mode")


def managed_config_view(config: dict[str, Any]) -> dict[str, Any]:
    return {key: config[key] for key in MANAGED_CONFIG_KEYS if key in config}


def merge_config(existing: dict[str, Any] | None, setup_config: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if existing is not None:
        for key, value in existing.items():
            if key not in MANAGED_CONFIG_KEYS:
                result[key] = value
    result.update(managed_config_view(setup_config))
    return result


def render_content_setup(content_setup_id: str) -> dict[str, Any]:
    validate_setup_id(content_setup_id)
    setup_root = SETUP_CATALOG_ROOT / content_setup_id
    if not setup_root.is_dir() or setup_root.is_symlink():
        fail(f"unknown setup: {content_setup_id}")
    metadata = load_json_object(setup_root / "setup.json", f"setup {content_setup_id} metadata")
    require_exact_keys(
        metadata,
        {
            "schema_version",
            "id",
            "description",
            "managed_files",
            "builder_projection",
            "plugin_id",
        },
        f"setup {content_setup_id} metadata",
    )
    if metadata["schema_version"] != 1:
        fail(f"setup {content_setup_id} metadata has unsupported schema")
    if metadata["id"] != content_setup_id:
        fail(f"setup {content_setup_id} metadata identity mismatch")
    if metadata["managed_files"] != [CONFIG_NAME]:
        fail(f"setup {content_setup_id} managed file declaration is invalid")
    if metadata["builder_projection"] != "default-on":
        fail(f"setup {content_setup_id} must enable the builder projection")
    if metadata["plugin_id"] != "nddev-builder":
        fail(f"setup {content_setup_id} must use the nddev-builder plugin")
    return metadata


def render_profile(profile_id: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    validate_setup_id(profile_id)
    profile_root = PROFILE_CATALOG_ROOT / profile_id
    if not profile_root.is_dir() or profile_root.is_symlink():
        fail(f"unknown profile: {profile_id}")
    metadata = load_json_object(profile_root / "profile.json", f"profile {profile_id} metadata")
    require_exact_keys(
        metadata,
        {
            "schema_version",
            "id",
            "description",
            "permission_profile",
            "managed_files",
            "approval_mode",
            "sandbox_mode",
            "network_access",
        },
        f"profile {profile_id} metadata",
    )
    if metadata["schema_version"] != 1:
        fail(f"profile {profile_id} metadata has unsupported schema")
    if metadata["id"] != profile_id or metadata["permission_profile"] != profile_id:
        fail(f"profile {profile_id} metadata identity mismatch")
    if metadata["managed_files"] != [CONFIG_NAME]:
        fail(f"profile {profile_id} managed file declaration is invalid")
    validate_supported_selection(DEFAULT_CONTENT_SETUP_ID, profile_id)
    config = load_json_object(profile_root / CONFIG_NAME, f"profile {profile_id}/{CONFIG_NAME}")
    validate_profile_config(metadata, config, f"profile {profile_id}/{CONFIG_NAME}")
    return metadata, {CONFIG_NAME: canonical_json(config)}


def render_selection(
    content_setup_id: str, profile_id: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, bytes]]:
    validate_supported_selection(content_setup_id, profile_id)
    setup = render_content_setup(content_setup_id)
    profile, rendered = render_profile(profile_id)
    return setup, profile, rendered


def builder_source_files(target_root: Path = BUILDER_TARGET_ROOT) -> tuple[tuple[Path, Path], ...]:
    files: list[tuple[Path, Path]] = []
    for source_relative in BUILDER_ROOT_FILES:
        source = BUILDER_SOURCE_ROOT / source_relative
        info = require_regular_file(
            source,
            f"builder projection source {source_relative.as_posix()}",
            max_bytes=MANAGED_PAYLOAD_MAX_BYTES,
        )
        if stat.S_IMODE(info.st_mode) & 0o022:
            fail(f"builder projection source must not be group/world-writable: {source_relative}")
        files.append((source_relative, target_root / source_relative))
    for component_root in BUILDER_COMPONENT_ROOTS:
        source_root = BUILDER_SOURCE_ROOT / component_root
        if not source_root.exists() and not source_root.is_symlink():
            fail(f"builder projection component is missing: {component_root.as_posix()}")
        root_info = source_root.lstat()
        if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
            fail(f"builder projection component must be a real directory: {component_root}")
        for source in sorted(source_root.rglob("*")):
            relative = source.relative_to(BUILDER_SOURCE_ROOT)
            info = source.lstat()
            if stat.S_ISLNK(info.st_mode):
                fail(f"builder projection source must not be a symlink: {relative.as_posix()}")
            if stat.S_ISDIR(info.st_mode):
                continue
            if not stat.S_ISREG(info.st_mode):
                fail(
                    "builder projection source must contain only regular files: "
                    f"{relative.as_posix()}"
                )
            if source.name == ".DS_Store":
                fail(f"builder projection source contains local metadata: {relative.as_posix()}")
            files.append((relative, target_root / relative))
    if len(files) > BUILDER_MAX_FILE_COUNT:
        fail("builder projection source exceeds the file-count limit")
    return tuple(files)


def builder_projection_files_for(source_files: tuple[tuple[Path, Path], ...]) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for source_relative, target_relative in source_files:
        source = BUILDER_SOURCE_ROOT / source_relative
        content = read_regular_file(
            source,
            f"builder projection source {source_relative.as_posix()}",
            max_bytes=MANAGED_PAYLOAD_MAX_BYTES,
        )
        content.decode("utf-8")
        files[target_relative.as_posix()] = content
    return files


def builder_projection_files() -> dict[str, bytes]:
    return builder_projection_files_for(builder_source_files())


def managed_paths() -> tuple[Path, ...]:
    return (
        *MANAGED_CORE_PATHS,
        *(target for _, target in builder_source_files(BUILDER_TARGET_ROOT)),
        *(target for _, target in builder_source_files(LEGACY_BUILDER_TARGET_ROOT)),
    )


def list_setups() -> list[dict[str, Any]]:
    if not SETUP_CATALOG_ROOT.is_dir() or SETUP_CATALOG_ROOT.is_symlink():
        fail("setup catalog is missing or unsafe")
    entries: list[dict[str, Any]] = []
    for candidate in sorted(SETUP_CATALOG_ROOT.iterdir(), key=lambda path: path.name):
        if not candidate.is_dir() or candidate.is_symlink():
            fail(f"catalog entry must be a real directory: {candidate.name}")
        metadata = render_content_setup(candidate.name)
        entries.append(
            {
                "id": metadata["id"],
                "description": metadata["description"],
                "managed_files": metadata["managed_files"],
            }
        )
    if not entries:
        fail("setup catalog is empty")
    return entries


def list_profiles() -> list[dict[str, Any]]:
    if not PROFILE_CATALOG_ROOT.is_dir() or PROFILE_CATALOG_ROOT.is_symlink():
        fail("profile catalog is missing or unsafe")
    entries: list[dict[str, Any]] = []
    for candidate in sorted(PROFILE_CATALOG_ROOT.iterdir(), key=lambda path: path.name):
        if not candidate.is_dir() or candidate.is_symlink():
            fail(f"profile entry must be a real directory: {candidate.name}")
        metadata, _ = render_profile(candidate.name)
        entries.append(
            {
                "id": metadata["id"],
                "description": metadata["description"],
                "approval_mode": metadata["approval_mode"],
                "sandbox_mode": metadata["sandbox_mode"],
                "network_access": metadata["network_access"],
            }
        )
    if not entries:
        fail("profile catalog is empty")
    return entries


def lexical_target_text(raw_target: Any) -> str:
    try:
        raw_text = os.fspath(raw_target)
    except TypeError:
        fail("--target must be a path string")
    if not isinstance(raw_text, str) or not raw_text:
        fail("--target must be a path string")
    if not os.path.isabs(raw_text):
        fail("--target must be an absolute path")
    normalized = os.path.normpath(raw_text)
    if normalized == os.path.abspath(os.sep):
        fail("filesystem root cannot be a target")
    return normalized


def resolve_target(raw_target: str) -> Path:
    expanded = Path(lexical_target_text(raw_target))
    if not expanded.is_absolute():
        fail("--target must be an absolute path")
    try:
        raw_info = expanded.lstat()
    except FileNotFoundError:
        raw_info = None
    if raw_info is not None and stat.S_ISLNK(raw_info.st_mode):
        fail("--target must not be a symlink")
    target = expanded.resolve(strict=False)
    if target == Path(target.anchor):
        fail("filesystem root cannot be a target")
    parent = target.parent
    try:
        parent_info = parent.lstat()
    except FileNotFoundError:
        fail("--target parent must already exist")
    if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
        fail("canonical --target parent must be a real directory")
    if target.exists():
        target_info = target.lstat()
        if stat.S_ISLNK(target_info.st_mode) or not stat.S_ISDIR(target_info.st_mode):
            fail("--target must be a real directory when it exists")
    return target


def canonical_target_text(target: Path) -> str:
    if not target.is_absolute():
        fail("--target must be an absolute path")
    parent = target.parent
    try:
        parent_info = parent.lstat()
    except FileNotFoundError:
        fail("--target parent must already exist")
    if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
        fail("canonical --target parent must be a real directory")
    if target.exists() or target.is_symlink():
        target_info = target.lstat()
        if stat.S_ISLNK(target_info.st_mode) or not stat.S_ISDIR(target_info.st_mode):
            fail("--target must be a real directory when it exists")
    return str(parent.resolve(strict=True) / target.name)


def bootstrap_lock_system_root() -> Path:
    return Path("/tmp").resolve(strict=True)


def require_bootstrap_lock_system_root() -> Path:
    parent = bootstrap_lock_system_root()
    try:
        parent_info = parent.lstat()
    except FileNotFoundError:
        fail("system temp root must exist")
    if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(parent_info.st_mode):
        fail("system temp root must be a real directory")
    if not (parent_info.st_mode & stat.S_ISVTX):
        fail("system temp root must be sticky")
    return parent


@contextlib.contextmanager
def bootstrap_anchor_creation_guard() -> Iterator[None]:
    parent = require_bootstrap_lock_system_root()
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(parent, flags)
    locked = False
    try:
        path_info = parent.lstat()
        fd_info = os.fstat(descriptor)
        if (path_info.st_dev, path_info.st_ino) != (fd_info.st_dev, fd_info.st_ino):
            fail("system temp root changed while it was being opened")
        if stat.S_ISLNK(path_info.st_mode) or not stat.S_ISDIR(fd_info.st_mode):
            fail("system temp root must be a real directory")
        if not (fd_info.st_mode & stat.S_ISVTX):
            fail("system temp root must be sticky")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                fail("target is already locked")
            fail(f"bootstrap anchor creation guard could not be acquired: {exc}")
        locked = True
        yield
    finally:
        if locked:
            with contextlib.suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def capture_bootstrap_lock_envelope(root: Path) -> dict[str, Any]:
    return {
        "parent": capture_existing_directory_object(root.parent, "bootstrap lock parent"),
        "root": capture_exact_tree_snapshot(root, "bootstrap lock root"),
    }


def restore_bootstrap_lock_envelope(root: Path, envelope: dict[str, Any]) -> None:
    restore_exact_tree_snapshot(root, envelope["root"], "bootstrap lock root")
    restore_existing_directory_object(root.parent, envelope["parent"], "bootstrap lock parent")
    if capture_exact_tree_snapshot(root, "bootstrap lock root") != envelope["root"]:
        fail("bootstrap lock root exact rollback verification failed")
    if capture_existing_directory_object(root.parent, "bootstrap lock parent") != envelope["parent"]:
        fail("bootstrap lock parent exact rollback verification failed")


def prepare_bootstrap_lock_root() -> tuple[Path, dict[str, Any]]:
    uid = current_user_id()
    if uid is None:
        fail("bootstrap lifecycle locks require POSIX current-user identity")
    parent = require_bootstrap_lock_system_root()
    root = parent / f"{BOOTSTRAP_LOCK_ROOT_PREFIX}-{uid}"
    envelope = capture_bootstrap_lock_envelope(root)
    created_root = False
    try:
        root.mkdir(mode=OWNER_DIRECTORY_MODE)
        created_root = True
    except FileExistsError:
        require_owner_private_directory(root, "bootstrap lock root")
    else:
        try:
            root.chmod(OWNER_DIRECTORY_MODE)
            require_owner_private_directory(root, "bootstrap lock root")
        except BaseException:
            restore_bootstrap_lock_envelope(root, envelope)
            raise
    if created_root:
        try:
            require_owner_private_directory(root, "bootstrap lock root")
        except BaseException:
            restore_bootstrap_lock_envelope(root, envelope)
            raise
    return root, envelope


def bootstrap_lock_root() -> Path:
    root, _envelope = prepare_bootstrap_lock_root()
    return root


def bootstrap_lock_root_path() -> Path:
    uid = current_user_id()
    if uid is None:
        fail("bootstrap lifecycle locks require POSIX current-user identity")
    return require_bootstrap_lock_system_root() / f"{BOOTSTRAP_LOCK_ROOT_PREFIX}-{uid}"


def bootstrap_lock_digest(lock_key: str) -> str:
    return sha256_bytes(PRODUCT_NAME.encode("utf-8") + b"\0" + lock_key.encode("utf-8"))


def bootstrap_lock_path_without_create(target: Any) -> tuple[Path, str, str]:
    lexical = lexical_target_text(target)
    digest = bootstrap_lock_digest(lexical)
    return bootstrap_lock_root_path() / f"{PRODUCT_NAME}-{digest}.lock", lexical, digest


def bootstrap_lock_path(target: Any) -> tuple[Path, str, str]:
    lexical = lexical_target_text(target)
    digest = bootstrap_lock_digest(lexical)
    return bootstrap_lock_root() / f"{PRODUCT_NAME}-{digest}.lock", lexical, digest


def bootstrap_lock_path_for_acquire(target: Any) -> tuple[Path, str, str, dict[str, Any]]:
    lexical = lexical_target_text(target)
    digest = bootstrap_lock_digest(lexical)
    root, envelope = prepare_bootstrap_lock_root()
    return root / f"{PRODUCT_NAME}-{digest}.lock", lexical, digest, envelope


def product_lock_path_without_create() -> tuple[Path, str, str]:
    digest = bootstrap_lock_digest(PRODUCT_LIFECYCLE_LOCK_KEY)
    return bootstrap_lock_root_path() / BOOTSTRAP_PRODUCT_LOCK_NAME, PRODUCT_LIFECYCLE_LOCK_KEY, digest


def product_lock_path_for_acquire() -> tuple[Path, str, str, dict[str, Any]]:
    digest = bootstrap_lock_digest(PRODUCT_LIFECYCLE_LOCK_KEY)
    root, envelope = prepare_bootstrap_lock_root()
    return root / BOOTSTRAP_PRODUCT_LOCK_NAME, PRODUCT_LIFECYCLE_LOCK_KEY, digest, envelope


def open_existing_bootstrap_lock_file(path: Path) -> int:
    require_owner_private_directory(path.parent, "bootstrap lock root")
    flags = os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            fail("bootstrap lock path is unsafe")
        fail(f"bootstrap lock could not be opened: {exc}")
    try:
        require_lock_file_matches_fd(
            path, descriptor, "bootstrap lock", allowed_nlinks={1, 2}
        )
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def open_bootstrap_lock_file(path: Path) -> int:
    return open_existing_bootstrap_lock_file(path)


def fd_read_bounded(descriptor: int, label: str, max_bytes: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    content = os.read(descriptor, max_bytes + 1)
    if len(content) > max_bytes:
        fail(f"{label} exceeds the {max_bytes}-byte size limit")
    return content


def fd_write_new_all(descriptor: int, content: bytes, label: str) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    view = memoryview(content)
    while view:
        written = os.write(descriptor, view)
        if written == 0:
            fail(f"{label} write made no progress")
        view = view[written:]
    os.fsync(descriptor)


def read_valid_bootstrap_binding(
    descriptor: int, path: Path, lock_key: str, digest: str
) -> dict[str, Any] | None:
    require_lock_file_matches_fd(path, descriptor, "bootstrap lock")
    content = fd_read_bounded(descriptor, "bootstrap lock", BOOTSTRAP_LOCK_MAX_BYTES)
    if not content.strip():
        return None
    try:
        loaded = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        fail("bootstrap lock binding is invalid")
    if not isinstance(loaded, dict):
        fail("bootstrap lock must contain a JSON object")
    require_exact_keys(loaded, BOOTSTRAP_LOCK_KEYS_V1, "bootstrap lock")
    if (
        loaded["schema_version"] != 1
        or loaded["product_name"] != PRODUCT_NAME
        or loaded["target_sha256"] != digest
        or loaded["lock_key"] != lock_key
    ):
        fail("bootstrap lock target binding mismatch")
    return loaded


def validate_or_write_bootstrap_binding(
    descriptor: int, path: Path, lock_key: str, digest: str
) -> None:
    if read_valid_bootstrap_binding(descriptor, path, lock_key, digest) is None:
        fail("bootstrap lock binding is missing")


def bootstrap_binding_bytes(lock_key: str, digest: str) -> bytes:
    binding = canonical_json(
        {
            "schema_version": 1,
            "product_name": PRODUCT_NAME,
            "lock_key": lock_key,
            "target_sha256": digest,
        }
    )
    if len(binding) > BOOTSTRAP_LOCK_MAX_BYTES:
        fail("bootstrap lock binding exceeds the size limit")
    return binding


def write_complete_bootstrap_binding_file(
    descriptor: int, path: Path, lock_key: str, digest: str
) -> None:
    binding = bootstrap_binding_bytes(lock_key, digest)
    fd_write_new_all(descriptor, binding, "bootstrap lock")
    os.fchmod(descriptor, OWNER_FILE_MODE)
    os.fsync(descriptor)
    require_lock_file_matches_fd(path, descriptor, "bootstrap lock")


def bootstrap_anchor_temp_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.nddev-anchor-tmp.{os.getpid()}.{time.time_ns()}")


def is_bootstrap_publication_alias(candidate: Path, final: Path) -> bool:
    name = candidate.name
    prefix = f".{final.name}.nddev-anchor-tmp."
    if not name.startswith(prefix):
        return False
    suffix = name[len(prefix) :]
    parts = suffix.split(".")
    if len(parts) != 2:
        return False
    return all(part.isdecimal() and 1 <= len(part) <= 32 for part in parts)


def recover_bootstrap_publication_alias(
    path: Path, descriptor: int, lock_key: str, digest: str
) -> None:
    info = require_lock_file_matches_fd(
        path, descriptor, "bootstrap lock", allowed_nlinks={1, 2}
    )
    if info.st_nlink == 1:
        return
    same_inode: list[Path] = []
    try:
        children = list(path.parent.iterdir())
    except OSError as exc:
        fail(f"bootstrap lock parent could not be inspected for recovery: {exc}")
    for child in children:
        if child.name == path.name:
            continue
        try:
            child_info = child.lstat()
        except FileNotFoundError:
            continue
        if (child_info.st_dev, child_info.st_ino) == (info.st_dev, info.st_ino):
            same_inode.append(child)
    if len(same_inode) != 1:
        fail("bootstrap lock has unknown hard-link aliases")
    alias = same_inode[0]
    if not is_bootstrap_publication_alias(alias, path):
        fail("bootstrap lock has an unknown publication alias")
    alias.unlink()
    fsync_existing_parent(path)
    require_lock_file_matches_fd(path, descriptor, "bootstrap lock")
    validate_or_write_bootstrap_binding(descriptor, path, lock_key, digest)


def open_new_bootstrap_anchor_temp(path: Path) -> tuple[Path, int]:
    require_owner_private_directory(path.parent, "bootstrap lock root")
    temporary = bootstrap_anchor_temp_path(path)
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(temporary, flags, OWNER_FILE_MODE)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            fail("bootstrap lock temporary path is unsafe")
        fail(f"bootstrap lock temporary file could not be opened: {exc}")
    try:
        os.fchmod(descriptor, OWNER_FILE_MODE)
        require_lock_file_matches_fd(temporary, descriptor, "bootstrap lock")
    except BaseException:
        os.close(descriptor)
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise
    return temporary, descriptor


def publish_bootstrap_anchor_no_replace(
    path: Path, temporary: Path, descriptor: int
) -> None:
    try:
        os.link(temporary, path)
    except FileExistsError:
        raise
    except OSError as exc:
        if exc.errno in {errno.EEXIST}:
            raise FileExistsError(str(path)) from exc
        fail(f"bootstrap lock could not be published atomically: {exc}")
    require_lock_file_matches_fd(path, descriptor, "bootstrap lock", allowed_nlinks={2})


def open_or_publish_bootstrap_anchor(
    path: Path,
    lock_key: str,
    digest: str,
    envelope: dict[str, Any],
) -> tuple[int, bool]:
    try:
        descriptor = open_existing_bootstrap_lock_file(path)
    except FileNotFoundError:
        descriptor = None
    else:
        return descriptor, False

    temporary: Path | None = None
    final_visible = False
    prelocked = False
    try:
        temporary, descriptor = open_new_bootstrap_anchor_temp(path)
        write_complete_bootstrap_binding_file(descriptor, temporary, lock_key, digest)
        try:
            publish_bootstrap_anchor_no_replace(path, temporary, descriptor)
            final_visible = True
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EAGAIN}:
                    fail("target is already locked")
                fail(f"bootstrap lock could not be acquired after publication: {exc}")
            prelocked = True
            temporary.unlink()
            temporary = None
            fsync_existing_parent(path)
            require_lock_file_matches_fd(path, descriptor, "bootstrap lock")
        except FileExistsError:
            os.close(descriptor)
            descriptor = None
            if temporary is not None:
                with contextlib.suppress(FileNotFoundError):
                    temporary.unlink()
                fsync_existing_parent(path)
                temporary = None
            descriptor = open_existing_bootstrap_lock_file(path)
            return descriptor, False
        return descriptor, prelocked
    except BaseException:
        if descriptor is not None:
            if prelocked:
                with contextlib.suppress(OSError):
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            with contextlib.suppress(OSError):
                os.close(descriptor)
        if temporary is not None:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()
        if not final_visible:
            restore_bootstrap_lock_envelope(path.parent, envelope)
        raise


def record_bootstrap_lock_handoff(
    lock_key: str, descriptor: int, path: Path, owner: tuple[int, int]
) -> None:
    with _BOOTSTRAP_STATE_LOCK:
        held = _BOOTSTRAP_LOCKS.get(lock_key)
        if held is None or held.get("owner") != owner:
            fail("bootstrap lock owner changed while acquiring")
        held["depth"] = 1
        held["descriptor"] = descriptor
        held["path"] = path


@contextlib.contextmanager
def bootstrap_anchor_lock(
    path: Path,
    lock_key: str,
    digest: str,
    *,
    create: bool,
    exclusive: bool,
    envelope: dict[str, Any] | None = None,
) -> Iterator[None]:
    owner = (os.getpid(), threading.get_ident())
    descriptor: int | None = None
    locked = False
    reentrant = False
    with _BOOTSTRAP_STATE_LOCK:
        for key, held in list(_BOOTSTRAP_LOCKS.items()):
            held_owner = held.get("owner")
            if held_owner is not None and held_owner[0] != owner[0]:
                inherited_descriptor = held.get("descriptor")
                if inherited_descriptor is not None:
                    with contextlib.suppress(OSError):
                        os.close(int(inherited_descriptor))
                del _BOOTSTRAP_LOCKS[key]
        held = _BOOTSTRAP_LOCKS.get(lock_key)
        if held is not None:
            if held.get("owner") == owner and held.get("descriptor") is not None:
                held["depth"] += 1
                reentrant = True
            else:
                fail("target is already locked")
        else:
            _BOOTSTRAP_LOCKS[lock_key] = {
                "depth": 0,
                "descriptor": None,
                "owner": owner,
                "path": path,
            }
    if reentrant:
        try:
            yield
        finally:
            with _BOOTSTRAP_STATE_LOCK:
                held = _BOOTSTRAP_LOCKS.get(lock_key)
                if held is not None and held.get("owner") == owner:
                    held["depth"] -= 1
        return
    try:
        if create:
            if envelope is None:
                fail("bootstrap lock creation requires a rollback envelope")
            descriptor, locked = open_or_publish_bootstrap_anchor(
                path, lock_key, digest, envelope
            )
        else:
            descriptor = open_existing_bootstrap_lock_file(path)
        lock_info = require_lock_file_matches_fd(
            path, descriptor, "bootstrap lock", allowed_nlinks={1, 2}
        )
        needs_alias_recovery = lock_info.st_nlink == 2
        lock_mode = fcntl.LOCK_EX if exclusive or needs_alias_recovery else fcntl.LOCK_SH
        if not locked:
            try:
                fcntl.flock(descriptor, lock_mode | fcntl.LOCK_NB)
            except OSError as exc:
                if exc.errno in {errno.EACCES, errno.EAGAIN}:
                    fail("target is already locked")
                fail(f"bootstrap lock could not be acquired: {exc}")
            locked = True
        if needs_alias_recovery:
            recover_bootstrap_publication_alias(path, descriptor, lock_key, digest)
            if not exclusive:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
                except OSError as exc:
                    if exc.errno in {errno.EACCES, errno.EAGAIN}:
                        fail("target is already locked")
                    fail(f"bootstrap lock could not be downgraded after recovery: {exc}")
        validate_or_write_bootstrap_binding(descriptor, path, lock_key, digest)
        record_bootstrap_lock_handoff(lock_key, descriptor, path, owner)
        try:
            yield
        finally:
            with _BOOTSTRAP_STATE_LOCK:
                held = _BOOTSTRAP_LOCKS.get(lock_key)
                if held is not None and held.get("owner") == owner:
                    held["depth"] -= 1
                    if held["depth"] == 0:
                        del _BOOTSTRAP_LOCKS[lock_key]
    finally:
        if locked and descriptor is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
        with _BOOTSTRAP_STATE_LOCK:
            held = _BOOTSTRAP_LOCKS.get(lock_key)
            if held is not None and held.get("owner") == owner and held["depth"] == 0:
                del _BOOTSTRAP_LOCKS[lock_key]


@contextlib.contextmanager
def bootstrap_lifecycle_lock(target: Any) -> Iterator[None]:
    target_context: Any = None
    with product_lifecycle_lock(create=True, exclusive=True):
        path, lexical, digest, envelope = bootstrap_lock_path_for_acquire(target)
        target_context = bootstrap_anchor_lock(
            path,
            lexical,
            digest,
            create=True,
            exclusive=True,
            envelope=envelope,
        )
        target_context.__enter__()
    try:
        yield
    except BaseException:
        target_context.__exit__(*sys.exc_info())
        raise
    else:
        target_context.__exit__(None, None, None)


def bootstrap_locked(function: Any) -> Any:
    def wrapped(target: Path, *args: Any, **kwargs: Any) -> Any:
        with bootstrap_lifecycle_lock(target):
            return function(target, *args, **kwargs)

    return wrapped


@contextlib.contextmanager
def product_lifecycle_lock(*, create: bool, exclusive: bool) -> Iterator[bool]:
    if create:
        with bootstrap_anchor_creation_guard():
            path, lock_key, digest, envelope = product_lock_path_for_acquire()
            with bootstrap_anchor_lock(
                path,
                lock_key,
                digest,
                create=True,
                exclusive=exclusive,
                envelope=envelope,
            ):
                yield True
        return
    path, lock_key, digest = product_lock_path_without_create()
    try:
        path.parent.lstat()
    except FileNotFoundError:
        yield False
        return
    try:
        path.lstat()
    except FileNotFoundError:
        yield False
        return
    with bootstrap_anchor_lock(
        path,
        lock_key,
        digest,
        create=False,
        exclusive=exclusive,
    ):
        yield True


def product_anchor_present_no_create() -> bool:
    path, _lock_key, _digest = product_lock_path_without_create()
    try:
        path.parent.lstat()
    except FileNotFoundError:
        return False
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def bootstrap_anchor_path_exists_no_create(path: Path) -> bool:
    try:
        path.parent.lstat()
    except FileNotFoundError:
        return False
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def canonical_anchor_present_no_create(target: Any) -> bool:
    path, _lexical, _digest = bootstrap_lock_path_without_create(target)
    return bootstrap_anchor_path_exists_no_create(path)


def fail_if_orphaned_canonical_anchor(target: Path) -> None:
    if canonical_anchor_present_no_create(str(target)):
        fail(
            "canonical bootstrap anchor exists without the product anchor; "
            "run an explicit cleanup or migration before reading this target"
        )


@contextlib.contextmanager
def existing_bootstrap_lifecycle_lock(target: Any) -> Iterator[bool]:
    path, lexical, digest = bootstrap_lock_path_without_create(target)
    try:
        path.parent.lstat()
    except FileNotFoundError:
        yield False
        return
    try:
        path.lstat()
    except FileNotFoundError:
        yield False
        return
    with bootstrap_anchor_lock(
        path,
        lexical,
        digest,
        create=False,
        exclusive=False,
    ):
        yield True


def with_read_bootstrap_target(target_input: Any, function: Any, *args: Any, **kwargs: Any) -> Any:
    require_current_host_supported()
    lexical = lexical_target_text(target_input)
    if not product_anchor_present_no_create():
        target = resolve_target(lexical)
        fail_if_orphaned_canonical_anchor(target)
        result = function(target, *args, **kwargs)
        if not product_anchor_present_no_create():
            return result

    product_context = product_lifecycle_lock(create=False, exclusive=False)
    product_locked = product_context.__enter__()
    if not product_locked:
        try:
            target = resolve_target(lexical)
            fail_if_orphaned_canonical_anchor(target)
            result = function(target, *args, **kwargs)
            if product_anchor_present_no_create():
                retry = True
            else:
                retry = False
        except BaseException:
            product_context.__exit__(*sys.exc_info())
            raise
        else:
            product_context.__exit__(None, None, None)
            if retry:
                return with_read_bootstrap_target(target_input, function, *args, **kwargs)
            return result
    target_context: Any = None
    target_entered = False
    try:
        target = resolve_target(lexical)
        target_context = existing_bootstrap_lifecycle_lock(str(target))
        target_locked = target_context.__enter__()
        target_entered = True
        if target_locked:
            product_context.__exit__(None, None, None)
            product_context = None
        result = function(target, *args, **kwargs)
    except BaseException:
        if target_context is not None and target_entered:
            target_context.__exit__(*sys.exc_info())
        if product_context is not None:
            product_context.__exit__(*sys.exc_info())
        raise
    else:
        if target_context is not None and target_entered:
            target_context.__exit__(None, None, None)
        if product_context is not None:
            product_context.__exit__(None, None, None)
        return result


def with_mutation_bootstrap_target(
    target_input: Any, function: Any, *args: Any, **kwargs: Any
) -> Any:
    require_current_host_supported()
    lexical = lexical_target_text(target_input)
    product_context = product_lifecycle_lock(create=True, exclusive=True)
    product_context.__enter__()
    target_context: Any = None
    target_entered = False
    try:
        target = resolve_target(lexical)
        path, canonical, digest, envelope = bootstrap_lock_path_for_acquire(str(target))
        target_context = bootstrap_anchor_lock(
            path,
            canonical,
            digest,
            create=True,
            exclusive=True,
            envelope=envelope,
        )
        target_context.__enter__()
        target_entered = True
        product_context.__exit__(None, None, None)
        product_context = None
        cleanup_drained = drain_cleanup_pending(target, fail_closed=True)
        result = function(target, *args, **kwargs)
        if isinstance(result, dict):
            result.setdefault("cleanup_drained", cleanup_drained)
            result.setdefault(
                "cleanup_pending",
                bool(cleanup_pending_metadata(target, recover_alias=False)["pending"]),
            )
    except BaseException:
        if target_context is not None and target_entered:
            target_context.__exit__(*sys.exc_info())
        if product_context is not None:
            product_context.__exit__(*sys.exc_info())
        raise
    else:
        if target_context is not None and target_entered:
            target_context.__exit__(None, None, None)
        return result


def with_bootstrap_target(target_input: Any, function: Any, *args: Any, **kwargs: Any) -> Any:
    return with_mutation_bootstrap_target(target_input, function, *args, **kwargs)


@contextlib.contextmanager
def exact_target_lifecycle_guard(target: Path, label: str) -> Iterator[None]:
    snapshot = capture_exact_tree_snapshot(target, label)
    parent_snapshot = capture_existing_directory_object(target.parent, f"{label} target parent")
    try:
        yield
    except BaseException:
        restore_exact_tree_snapshot(target, snapshot, label)
        fsync_directory(target.parent)
        restore_existing_directory_object(
            target.parent, parent_snapshot, f"{label} target parent"
        )
        if capture_exact_tree_snapshot(target, label) != snapshot:
            fail(f"{label} target exact rollback verification failed")
        raise


@contextlib.contextmanager
def target_lock(
    target: Path,
    *,
    cleanup_empty_target_on_error: bool = False,
    protect_lock_parent: bool = False,
) -> Iterator[None]:
    root: Path | None = None
    lock_root: Path | None = None
    lock_root_fd: int | None = None
    lock: Path | None = None
    lock_fd: int | None = None
    lock_directory_protected = False
    failed = True
    try:
        del protect_lock_parent
        require_owner_private_directory(target, "--target")
        root = ensure_control_root(target)
        lock_root = ensure_control_lock_root(target)
        lock_root_fd = open_control_lock_root_fd(lock_root)
        lock = target_lock_path(target)
        lock_fd = open_target_lock_file(lock)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                fail("target is already locked")
            fail(f"target lock could not be acquired: {exc}")
        require_lock_file_matches_fd(lock, lock_fd, "target lock")
        set_owner_directory_fd_mode(
            lock_root, lock_root_fd, "target lock directory", LOCK_HELD_DIRECTORY_MODE
        )
        lock_directory_protected = True
        require_lock_file_matches_fd(lock, lock_fd, "target lock")
        yield
        failed = False
    finally:
        active_error = sys.exc_info()[1]
        cleanup_error: BaseException | None = None
        if lock_directory_protected and lock_root is not None and lock_root_fd is not None:
            try:
                set_owner_directory_fd_mode(
                    lock_root, lock_root_fd, "target lock directory", OWNER_DIRECTORY_MODE
                )
            except BaseException as exc:  # noqa: BLE001 - preserve original failure.
                cleanup_error = exc
        if lock_fd is not None:
            with contextlib.suppress(OSError):
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            with contextlib.suppress(OSError):
                os.close(lock_fd)
        if lock_root_fd is not None:
            with contextlib.suppress(OSError):
                os.close(lock_root_fd)
        if failed and cleanup_empty_target_on_error:
            cleanup_empty_persistent_lock_target(target, root, lock_root, lock)
        if cleanup_error is not None:
            if active_error is not None:
                note = f"target lock directory restore failed: {cleanup_error}"
                add_note = getattr(active_error, "add_note", None)
                if add_note is not None:
                    with contextlib.suppress(Exception):
                        add_note(note)
                with contextlib.suppress(Exception):
                    print(f"nddev-cursor-cli: warning: {note}", file=sys.stderr)
            else:
                raise cleanup_error


def require_private_or_sticky_parent(parent: Path) -> os.stat_result:
    try:
        info = parent.lstat()
    except FileNotFoundError:
        fail("--target parent must already exist")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("--target parent must be a real directory")
    mode = stat.S_IMODE(info.st_mode)
    uid = current_user_id()
    current_user_owned = uid is None or info.st_uid == uid
    owner_non_writable_by_others = current_user_owned and not (mode & 0o022)
    sticky = bool(info.st_mode & stat.S_ISVTX)
    if not owner_non_writable_by_others and not sticky:
        fail("--target parent must be current-user non-writable-by-others or sticky")
    return info


def ensure_target_directory(target: Path, *, create_missing: bool) -> bool:
    if target.exists() or target.is_symlink():
        require_owner_private_directory(target, "--target")
        return False
    if not create_missing:
        fail("--target is missing")
    require_private_or_sticky_parent(target.parent)
    try:
        target.mkdir(mode=OWNER_DIRECTORY_MODE)
    except FileExistsError:
        fail("--target appeared concurrently")
    except FileNotFoundError:
        fail("--target parent disappeared")
    target.chmod(OWNER_DIRECTORY_MODE)
    require_owner_private_directory(target, "--target")
    return True


def prepare_lifecycle_target(target: Path, *, create_missing: bool) -> bool:
    return ensure_target_directory(target, create_missing=create_missing)


def control_root(target: Path) -> Path:
    return target / CONTROL_ROOT_NAME


def ensure_control_root(target: Path) -> Path:
    root = control_root(target)
    try:
        root.mkdir(mode=OWNER_DIRECTORY_MODE)
    except FileExistsError:
        require_owner_private_directory(root, "control root")
    else:
        root.chmod(OWNER_DIRECTORY_MODE)
        require_owner_private_directory(root, "control root")
    return root


def control_lock_root(target: Path) -> Path:
    return control_root(target) / CONTROL_LOCKS_NAME


def target_lock_path(target: Path) -> Path:
    return control_lock_root(target) / CONTROL_LOCK_NAME


def ensure_control_lock_root(target: Path) -> Path:
    ensure_control_root(target)
    root = control_lock_root(target)
    try:
        root.mkdir(mode=OWNER_DIRECTORY_MODE)
    except FileExistsError:
        require_lock_root_directory(root)
    else:
        root.chmod(OWNER_DIRECTORY_MODE)
        require_lock_root_directory(root)
    return root


def builder_projection_digest() -> str:
    files = builder_projection_files()
    return sha256_bytes(b"".join(files[path] for path in sorted(files)))


def stamp_bytes(target: Path, content_setup_id: str, profile_id: str) -> bytes:
    projected_files = sorted(builder_projection_files())
    return canonical_json(
        {
            "schema_version": 2,
            "product_name": PRODUCT_NAME,
            "build_version": VERSION,
            "content_setup_id": content_setup_id,
            "profile_id": profile_id,
            "canonical_target": str(target.resolve(strict=False)),
            "managed_files": [CONFIG_NAME],
            "builder_projection": {
                "default_on": True,
                "target_plugin_path": BUILDER_TARGET_ROOT.as_posix(),
                "source_sha256": builder_projection_digest(),
                "projected_files": projected_files,
            },
        }
    )


def stamp_is_legacy(stamp: dict[str, Any]) -> bool:
    return stamp.get("schema_version") == 1


def stamp_content_setup_id(stamp: dict[str, Any]) -> str | None:
    if stamp_is_legacy(stamp):
        return None
    return str(stamp["content_setup_id"])


def stamp_profile_id(stamp: dict[str, Any]) -> str | None:
    if stamp_is_legacy(stamp):
        return LEGACY_SETUP_PROFILE_IDS.get(str(stamp["setup_id"]))
    return str(stamp["profile_id"])


def stamp_legacy_setup_id(stamp: dict[str, Any]) -> str | None:
    if stamp_is_legacy(stamp):
        return str(stamp["setup_id"])
    return None


def load_stamp(target: Path) -> dict[str, Any] | None:
    stamp_path = target / STAMP_NAME
    if not stamp_path.exists() and not stamp_path.is_symlink():
        return None
    stamp = load_json_object(stamp_path, f"target stamp {stamp_path}")
    schema_version = stamp.get("schema_version")
    if schema_version == 1:
        require_exact_keys(stamp, STAMP_KEYS_V1, "target stamp")
    elif schema_version == 2:
        require_exact_keys(stamp, STAMP_KEYS_V2, "target stamp")
    else:
        fail("target stamp is not owned by nddev-cursor-cli-app")
    if stamp["product_name"] != PRODUCT_NAME:
        fail("target stamp is not owned by nddev-cursor-cli-app")
    if stamp["canonical_target"] != str(target.resolve(strict=False)):
        fail("target stamp belongs to a different canonical target")
    if schema_version == 1:
        legacy_id = str(stamp["setup_id"])
        validate_setup_id(legacy_id)
        if legacy_id not in LEGACY_SETUP_PROFILE_IDS:
            fail(f"unsupported legacy setup id in target stamp: {legacy_id}")
    else:
        validate_setup_id(str(stamp["content_setup_id"]))
        validate_setup_id(str(stamp["profile_id"]))
        validate_supported_selection(str(stamp["content_setup_id"]), str(stamp["profile_id"]))
    return stamp


def load_target_config(target: Path) -> dict[str, Any] | None:
    config_path = target / CONFIG_NAME
    if not config_path.exists() and not config_path.is_symlink():
        return None
    config = load_json_object(config_path, f"target {CONFIG_NAME}")
    validate_config(
        {**config, **{k: config.get(k) for k in MANAGED_CONFIG_KEYS if k in config}},
        f"target {CONFIG_NAME}",
    )
    return config


def inspect_builder_projection(
    target: Path,
    *,
    source_files: tuple[tuple[Path, Path], ...] | None = None,
    compare_content: bool = True,
) -> str:
    desired = builder_projection_files_for(
        builder_source_files() if source_files is None else source_files
    )
    missing = False
    drifted = False
    for relative, content in desired.items():
        path = target / relative
        if not path.exists() and not path.is_symlink():
            missing = True
            continue
        try:
            actual = read_regular_file(path, f"target builder projection {relative}")
        except CursorSetupError:
            raise
        if compare_content and actual != content:
            drifted = True
    if drifted:
        return "drifted"
    if missing:
        return "missing"
    return "current"


def drift_for_target(target: Path, stamp: dict[str, Any]) -> list[str]:
    current = load_target_config(target)
    if current is None:
        return [CONFIG_NAME]
    drift: list[str] = []
    if stamp_is_legacy(stamp):
        profile_id = stamp_profile_id(stamp)
        if profile_id is not None:
            _, rendered = render_profile(profile_id)
            expected_config = parse_json_object(
                rendered[CONFIG_NAME], f"profile {profile_id}/{CONFIG_NAME}"
            )
            if managed_config_view(current) != managed_config_view(expected_config):
                drift.append(CONFIG_NAME)
        return drift
    content_setup_id = str(stamp["content_setup_id"])
    profile_id = str(stamp["profile_id"])
    _, _, rendered = render_selection(content_setup_id, profile_id)
    expected_config = parse_json_object(
        rendered[CONFIG_NAME], f"profile {profile_id}/{CONFIG_NAME}"
    )
    if managed_config_view(current) != managed_config_view(expected_config):
        drift.append(CONFIG_NAME)
    builder_findings = builder_parent_findings(target)
    if builder_findings:
        drift.extend(builder_findings)
        drift.append(BUILDER_TARGET_ROOT.as_posix())
        return drift
    builder_state = inspect_builder_projection(target)
    if builder_state == "drifted":
        drift.append(BUILDER_TARGET_ROOT.as_posix())
    elif builder_state == "missing":
        drift.append(BUILDER_TARGET_ROOT.as_posix())
    return drift


def inspect_target(target: Path) -> dict[str, Any]:
    return with_read_bootstrap_target(target, _inspect_target_locked)


def _inspect_target_locked(target: Path) -> dict[str, Any]:
    if not target.exists() and not target.is_symlink():
        return {
            "state": "missing",
            "setup_id": None,
            "content_setup_id": None,
            "profile_id": None,
            "legacy_setup_id": None,
            "legacy": False,
            "drift": [],
            "builder_projection": "missing",
            "launchable": False,
            "cleanup_pending": False,
            "cleanup": None,
        }
    if target.is_symlink() or not target.is_dir():
        fail("--target must be a real directory")
    cleanup = cleanup_pending_result(target)
    target_safety = target_safety_findings(target)
    stamp = load_stamp(target)
    config_exists = (target / CONFIG_NAME).exists() or (target / CONFIG_NAME).is_symlink()
    if stamp is None:
        builder_findings = builder_parent_findings(target)
        runtime_findings = target_local_parent_findings(target, runtime_parent_directories(target))
        control_findings = control_state_findings(target, require_persistent_lock=False)
        drift = [*target_safety, *builder_findings, *runtime_findings, *control_findings]
        return {
            "state": "unmanaged" if config_exists else "empty",
            "setup_id": None,
            "content_setup_id": None,
            "profile_id": None,
            "legacy_setup_id": None,
            "legacy": False,
            "drift": list(dict.fromkeys(drift)),
            "builder_projection": (
                "unsafe"
                if builder_findings
                else inspect_builder_projection(target)
                if target.exists()
                else "missing"
            ),
            "launchable": False,
            **cleanup,
        }
    drift = [
        *target_safety,
        *control_state_findings(target, require_persistent_lock=True),
        *drift_for_target(target, stamp),
        *target_local_parent_findings(target, runtime_parent_directories(target)),
    ]
    drift = list(dict.fromkeys(drift))
    if stamp_is_legacy(stamp):
        builder_state = inspect_builder_projection(
            target,
            source_files=builder_source_files(LEGACY_BUILDER_TARGET_ROOT),
            compare_content=False,
        )
    else:
        if builder_parent_drifted(drift):
            builder_state = "unsafe"
        else:
            builder_state = (
                "current"
                if BUILDER_TARGET_ROOT.as_posix() not in drift
                else inspect_builder_projection(target)
            )
    content_setup_id = stamp_content_setup_id(stamp)
    profile_id = stamp_profile_id(stamp)
    legacy_setup_id = stamp_legacy_setup_id(stamp)
    return {
        "state": "managed",
        "setup_id": content_setup_id if content_setup_id is not None else legacy_setup_id,
        "content_setup_id": content_setup_id,
        "profile_id": profile_id,
        "legacy_setup_id": legacy_setup_id,
        "legacy": stamp_is_legacy(stamp),
        "drift": drift,
        "builder_projection": builder_state,
        "launchable": not stamp_is_legacy(stamp) and not drift,
        **cleanup,
    }


def require_clean_managed(target: Path) -> dict[str, Any]:
    require_owner_private_directory(target, "--target")
    state = _inspect_target_locked(target)
    if state["state"] != "managed":
        fail(f"target is not managed (state={state['state']})")
    if state.get("legacy"):
        fail("legacy managed target must be migrated before launch or switch")
    if state["drift"]:
        fail(f"managed target has drift: {', '.join(state['drift'])}")
    return state


def backup_pool(target: Path) -> Path:
    return control_root(target) / CONTROL_BACKUPS_NAME


def current_user_id() -> int | None:
    getuid = getattr(os, "getuid", None)
    if getuid is None:
        return None
    return int(getuid())


def target_safety_findings(target: Path) -> list[str]:
    if not target.exists() and not target.is_symlink():
        return []
    try:
        info = target.lstat()
    except FileNotFoundError:
        return []
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("--target must be a real directory")
    findings: list[str] = []
    uid = current_user_id()
    if uid is not None and info.st_uid != uid:
        findings.append("target:owner")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        findings.append("target:mode")
    return findings


def control_state_findings(target: Path, *, require_persistent_lock: bool) -> list[str]:
    findings: list[str] = []
    uid = current_user_id()
    for path, label in (
        (control_root(target), CONTROL_ROOT_NAME),
        (control_lock_root(target), f"{CONTROL_ROOT_NAME}/{CONTROL_LOCKS_NAME}"),
    ):
        try:
            info = path.lstat()
        except FileNotFoundError:
            if require_persistent_lock:
                findings.append(f"{label}:missing")
            return findings
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            findings.append(f"{label}:unsafe")
            return findings
        if uid is not None and info.st_uid != uid:
            findings.append(f"{label}:owner")
        allowed_modes = (
            {OWNER_DIRECTORY_MODE, LOCK_HELD_DIRECTORY_MODE}
            if label == f"{CONTROL_ROOT_NAME}/{CONTROL_LOCKS_NAME}"
            else {OWNER_DIRECTORY_MODE}
        )
        if stat.S_IMODE(info.st_mode) not in allowed_modes:
            findings.append(f"{label}:mode")
    lock = target_lock_path(target)
    try:
        info = lock.lstat()
    except FileNotFoundError:
        if require_persistent_lock:
            findings.append(f"{CONTROL_ROOT_NAME}/{CONTROL_LOCKS_NAME}/{CONTROL_LOCK_NAME}:missing")
        return findings
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        findings.append(f"{CONTROL_ROOT_NAME}/{CONTROL_LOCKS_NAME}/{CONTROL_LOCK_NAME}:unsafe")
        return findings
    if uid is not None and info.st_uid != uid:
        findings.append(f"{CONTROL_ROOT_NAME}/{CONTROL_LOCKS_NAME}/{CONTROL_LOCK_NAME}:owner")
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        findings.append(f"{CONTROL_ROOT_NAME}/{CONTROL_LOCKS_NAME}/{CONTROL_LOCK_NAME}:mode")
    if info.st_nlink != 1:
        findings.append(f"{CONTROL_ROOT_NAME}/{CONTROL_LOCKS_NAME}/{CONTROL_LOCK_NAME}:hardlink")
    return findings


def cleanup_pending_root(target: Path) -> Path:
    return control_root(target) / CONTROL_CLEANUP_PENDING_NAME


def cleanup_tombstones_root(target: Path) -> Path:
    return cleanup_pending_root(target) / CLEANUP_TOMBSTONES_NAME


def cleanup_journal_path(target: Path) -> Path:
    return cleanup_pending_root(target) / CLEANUP_JOURNAL_NAME


def cleanup_journal_temp_path(journal: Path) -> Path:
    return journal.with_name(
        f".{journal.name}.nddev-cleanup-tmp.{os.getpid()}.{time.time_ns()}"
    )


def is_cleanup_publication_alias(candidate: Path, final: Path) -> bool:
    name = candidate.name
    prefix = f".{final.name}.nddev-cleanup-tmp."
    if not name.startswith(prefix):
        return False
    suffix = name[len(prefix) :]
    parts = suffix.split(".")
    if len(parts) != 2:
        return False
    return all(part.isdecimal() and 1 <= len(part) <= 32 for part in parts)


def cleanup_metadata_error(message: str) -> NoReturn:
    fail(f"cleanup-pending state is malformed: {message}")


def require_cleanup_name(name: str, label: str) -> str:
    if not CLEANUP_NAME_PATTERN.fullmatch(name):
        cleanup_metadata_error(f"{label} name is not bounded machine syntax")
    if "/" in name or name in {".", ".."}:
        cleanup_metadata_error(f"{label} name is not relative")
    return name


def cleanup_tree_manifest(root: Path, name: str, label: str) -> dict[str, Any]:
    require_cleanup_name(name, label)
    if not path_exists_no_follow(root):
        cleanup_metadata_error(f"{label} is missing")
    uid = current_user_id()
    entries: list[dict[str, Any]] = []
    total_size = 0

    def record_path(path: Path, relative: str) -> None:
        nonlocal total_size
        info = path.lstat()
        if uid is not None and info.st_uid != uid:
            cleanup_metadata_error(f"{label} entry owner mismatch: {relative}")
        mode = stat.S_IMODE(info.st_mode)
        record: dict[str, Any] = {
            "relative": relative,
            "kind": "",
            "uid": info.st_uid,
            "mode": mode,
            "nlink": info.st_nlink,
            "device": info.st_dev,
            "inode": info.st_ino,
            "size": info.st_size,
            "mtime_ns": info.st_mtime_ns,
            "sha256": None,
        }
        if stat.S_ISLNK(info.st_mode):
            cleanup_metadata_error(f"{label} must not contain symlinks: {relative}")
        if stat.S_ISDIR(info.st_mode):
            if mode != OWNER_DIRECTORY_MODE:
                cleanup_metadata_error(f"{label} directory mode mismatch: {relative}")
            record["kind"] = "dir"
        elif stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1:
                cleanup_metadata_error(f"{label} file has hard-link aliases: {relative}")
            if mode not in {OWNER_FILE_MODE, OWNER_EXEC_MODE}:
                cleanup_metadata_error(f"{label} file mode mismatch: {relative}")
            content = read_regular_file(
                path, f"{label} file {relative}", max_bytes=CLEANUP_MAX_TOTAL_SIZE
            )
            total_size += len(content)
            if total_size > CLEANUP_MAX_TOTAL_SIZE:
                cleanup_metadata_error(f"{label} exceeds cleanup size bound")
            record["kind"] = "file"
            record["size"] = len(content)
            record["sha256"] = sha256_bytes(content)
        else:
            cleanup_metadata_error(f"{label} contains unsupported object: {relative}")
        entries.append(record)
        if len(entries) > CLEANUP_MAX_ENTRIES:
            cleanup_metadata_error(f"{label} exceeds cleanup entry bound")

    record_path(root, ".")
    if not entries or entries[0]["kind"] != "dir":
        cleanup_metadata_error(f"{label} tombstone must be a directory")
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        record_path(path, path.relative_to(root).as_posix())
    return {
        "name": name,
        "kind": "directory-tree",
        "entry_count": len(entries),
        "total_size": total_size,
        "entries": entries,
    }


def cleanup_journal_bytes(target: Path, tombstones: list[dict[str, Any]]) -> bytes:
    if not tombstones:
        cleanup_metadata_error("cleanup journal must declare at least one tombstone")
    if len(tombstones) > CLEANUP_MAX_TOMBSTONES:
        cleanup_metadata_error("cleanup journal exceeds tombstone bound")
    names = [str(tombstone["name"]) for tombstone in tombstones]
    if len(set(names)) != len(names):
        cleanup_metadata_error("cleanup journal tombstone names are not unique")
    entry_count = sum(int(tombstone["entry_count"]) for tombstone in tombstones)
    total_size = sum(int(tombstone["total_size"]) for tombstone in tombstones)
    if entry_count > CLEANUP_MAX_ENTRIES or total_size > CLEANUP_MAX_TOTAL_SIZE:
        cleanup_metadata_error("cleanup journal exceeds declared bounds")
    return canonical_json(
        {
            "schema_version": CLEANUP_SCHEMA_VERSION,
            "product_name": PRODUCT_NAME,
            "build_version": VERSION,
            "canonical_target": str(target.resolve(strict=False)),
            "cleanup_parent": CONTROL_CLEANUP_PENDING_NAME,
            "tombstone_count": len(tombstones),
            "entry_count": entry_count,
            "total_size": total_size,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tombstones": tombstones,
        }
    )


def publish_cleanup_journal_no_replace(journal: Path, content: bytes) -> bool:
    temporary = cleanup_journal_temp_path(journal)
    descriptor: int | None = None
    final_visible = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written == 0:
                fail("cleanup journal write made no progress")
            view = view[written:]
        os.fchmod(descriptor, OWNER_FILE_MODE)
        os.fsync(descriptor)
        os.link(temporary, journal)
        final_visible = True
        info = journal.lstat()
        opened = os.fstat(descriptor)
        if (
            (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino)
            or stat.S_ISLNK(info.st_mode)
            or not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 2
            or info.st_uid != opened.st_uid
            or stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE
        ):
            cleanup_metadata_error("cleanup journal final publication binding mismatch")
        try:
            temporary.unlink()
            fsync_directory(journal.parent)
            require_regular_file(journal, "cleanup journal", max_bytes=METADATA_MAX_BYTES)
        except BaseException:
            return True
    except FileExistsError:
        if descriptor is not None:
            os.close(descriptor)
            descriptor = None
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        fsync_directory(journal.parent)
        raise
    except BaseException:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
                descriptor = None
        if not final_visible:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()
        raise
    finally:
        if descriptor is not None:
            with contextlib.suppress(OSError):
                os.close(descriptor)
    return False


def recover_cleanup_journal_publication_alias(journal: Path) -> None:
    try:
        info = journal.lstat()
    except FileNotFoundError:
        fail("cleanup journal is missing")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        cleanup_metadata_error("cleanup journal must be a regular non-symlink file")
    uid = current_user_id()
    if uid is not None and info.st_uid != uid:
        cleanup_metadata_error("cleanup journal must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        cleanup_metadata_error("cleanup journal must have mode 0600")
    require_bounded_size(info, "cleanup journal", METADATA_MAX_BYTES)
    if info.st_nlink == 1:
        return
    if info.st_nlink != 2:
        cleanup_metadata_error("cleanup journal has an unsafe hard-link count")
    same_inode: list[Path] = []
    try:
        children = list(journal.parent.iterdir())
    except OSError as exc:
        cleanup_metadata_error(f"cleanup journal parent cannot be inspected: {exc}")
    for child in children:
        if child.name == journal.name:
            continue
        try:
            child_info = child.lstat()
        except FileNotFoundError:
            continue
        if (child_info.st_dev, child_info.st_ino) == (info.st_dev, info.st_ino):
            same_inode.append(child)
    if len(same_inode) != 1:
        cleanup_metadata_error("cleanup journal has unknown hard-link aliases")
    alias = same_inode[0]
    if not is_cleanup_publication_alias(alias, journal):
        cleanup_metadata_error("cleanup journal has an unknown publication alias")
    alias.unlink()
    fsync_directory(journal.parent)
    final = require_regular_file(journal, "cleanup journal", max_bytes=METADATA_MAX_BYTES)
    if final.st_nlink != 1:
        cleanup_metadata_error("cleanup journal alias recovery did not restore nlink=1")


def load_cleanup_journal(target: Path, *, recover_alias: bool) -> dict[str, Any]:
    root = cleanup_pending_root(target)
    journal = cleanup_journal_path(target)
    if recover_alias:
        recover_cleanup_journal_publication_alias(journal)
    info = require_regular_file(journal, "cleanup journal", max_bytes=METADATA_MAX_BYTES)
    if info.st_nlink != 1:
        cleanup_metadata_error("cleanup journal publication is incomplete")
    loaded = load_json_object(journal, "cleanup journal")
    require_exact_keys(loaded, CLEANUP_JOURNAL_KEYS_V1, "cleanup journal")
    if (
        loaded["schema_version"] != CLEANUP_SCHEMA_VERSION
        or loaded["product_name"] != PRODUCT_NAME
        or loaded["build_version"] != VERSION
        or loaded["canonical_target"] != str(target.resolve(strict=False))
        or loaded["cleanup_parent"] != CONTROL_CLEANUP_PENDING_NAME
    ):
        cleanup_metadata_error("cleanup journal target or product binding mismatch")
    tombstones = loaded["tombstones"]
    if not isinstance(tombstones, list):
        cleanup_metadata_error("cleanup journal tombstones must be a list")
    if loaded["tombstone_count"] != len(tombstones):
        cleanup_metadata_error("cleanup journal tombstone count mismatch")
    if len(tombstones) > CLEANUP_MAX_TOMBSTONES:
        cleanup_metadata_error("cleanup journal exceeds tombstone bound")
    expected_names: set[str] = set()
    entry_count = 0
    total_size = 0
    for tombstone in tombstones:
        if not isinstance(tombstone, dict):
            cleanup_metadata_error("cleanup tombstone record must be an object")
        require_exact_keys(tombstone, CLEANUP_TOMBSTONE_KEYS_V1, "cleanup tombstone")
        name = require_cleanup_name(str(tombstone["name"]), "cleanup tombstone")
        if name in expected_names:
            cleanup_metadata_error("cleanup tombstone name is duplicated")
        expected_names.add(name)
        if tombstone["kind"] != "directory-tree":
            cleanup_metadata_error("cleanup tombstone kind mismatch")
        entries = tombstone["entries"]
        if not isinstance(entries, list):
            cleanup_metadata_error("cleanup tombstone entries must be a list")
        if tombstone["entry_count"] != len(entries):
            cleanup_metadata_error("cleanup tombstone entry count mismatch")
        entry_count += int(tombstone["entry_count"])
        total_size += int(tombstone["total_size"])
        if entry_count > CLEANUP_MAX_ENTRIES or total_size > CLEANUP_MAX_TOTAL_SIZE:
            cleanup_metadata_error("cleanup journal exceeds declared bounds")
        for entry in entries:
            if not isinstance(entry, dict):
                cleanup_metadata_error("cleanup entry must be an object")
            require_exact_keys(entry, CLEANUP_ENTRY_KEYS_V1, "cleanup entry")
            relative = str(entry["relative"])
            if relative != ".":
                safe_relative(relative)
            if entry["kind"] not in {"dir", "file"}:
                cleanup_metadata_error("cleanup entry kind mismatch")
            if entry["kind"] == "file":
                digest = entry["sha256"]
                if not isinstance(digest, str) or not SHA256_HEX_PATTERN.fullmatch(digest):
                    cleanup_metadata_error("cleanup file digest is invalid")
            elif entry["sha256"] is not None:
                cleanup_metadata_error("cleanup directory digest must be null")
    if loaded["entry_count"] != entry_count or loaded["total_size"] != total_size:
        cleanup_metadata_error("cleanup journal aggregate mismatch")
    if not root.is_dir() or root.is_symlink():
        cleanup_metadata_error("cleanup parent must be a real directory")
    actual_root_names = {child.name for child in root.iterdir()}
    allowed_root_names = {CLEANUP_JOURNAL_NAME, CLEANUP_TOMBSTONES_NAME}
    if actual_root_names - allowed_root_names:
        cleanup_metadata_error("cleanup parent contains unknown entries")
    if CLEANUP_TOMBSTONES_NAME not in actual_root_names:
        cleanup_metadata_error("cleanup tombstones directory is missing")
    tombstones_root = cleanup_tombstones_root(target)
    require_owner_private_directory(tombstones_root, "cleanup tombstones")
    actual_tombstone_names = {child.name for child in tombstones_root.iterdir()}
    if actual_tombstone_names - expected_names:
        cleanup_metadata_error("cleanup tombstones contain unknown entries")
    return loaded


def cleanup_entry_matches(path: Path, entry: dict[str, Any], label: str) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode):
        cleanup_metadata_error(f"{label} became a symlink")
    if (
        info.st_uid != entry["uid"]
        or stat.S_IMODE(info.st_mode) != entry["mode"]
        or info.st_nlink != entry["nlink"]
        or info.st_dev != entry["device"]
        or info.st_ino != entry["inode"]
        or info.st_size != entry["size"]
        or info.st_mtime_ns != entry["mtime_ns"]
    ):
        return False
    if entry["kind"] == "dir":
        return stat.S_ISDIR(info.st_mode)
    if not stat.S_ISREG(info.st_mode):
        return False
    content = read_regular_file(path, label, max_bytes=CLEANUP_MAX_TOTAL_SIZE)
    return sha256_bytes(content) == entry["sha256"]


def validate_cleanup_tombstone_identity(target: Path, tombstone: dict[str, Any]) -> bool:
    remaining, _deleted = cleanup_tombstone_progress(target, tombstone, allow_partial=True)
    return remaining


def cleanup_child_relative(parent: str, child: str) -> str:
    if parent == ".":
        return child
    return f"{parent}/{child}"


def cleanup_entry_map(tombstone: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(entry["relative"]): entry for entry in tombstone["entries"]}


def cleanup_deletion_order(entries: dict[str, dict[str, Any]]) -> list[str]:
    return [
        relative
        for relative, _entry in sorted(
            entries.items(),
            key=lambda item: (item[0].count("/"), item[0]),
            reverse=True,
        )
    ]


def cleanup_remaining_children(entries: dict[str, dict[str, Any]], deleted: set[str]) -> dict[str, set[str]]:
    remaining = set(entries) - deleted
    children: dict[str, set[str]] = {relative: set() for relative in remaining}
    for relative in remaining:
        if relative == ".":
            continue
        parent = str(Path(relative).parent)
        if parent == "":
            parent = "."
        if parent in children:
            children[parent].add(Path(relative).name)
    return children


def cleanup_stable_directory_matches(path: Path, entry: dict[str, Any], label: str) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        cleanup_metadata_error(f"{label} is not a real directory")
    return (
        info.st_uid == entry["uid"]
        and stat.S_IMODE(info.st_mode) == entry["mode"]
        and info.st_dev == entry["device"]
        and info.st_ino == entry["inode"]
    )


def cleanup_tombstone_progress(
    target: Path, tombstone: dict[str, Any], *, allow_partial: bool
) -> tuple[bool, set[str]]:
    name = require_cleanup_name(str(tombstone["name"]), "cleanup tombstone")
    root = cleanup_tombstones_root(target) / name
    entries = cleanup_entry_map(tombstone)
    expected_relatives = set(entries)
    order = cleanup_deletion_order(entries)
    if not path_exists_no_follow(root):
        return False, set(expected_relatives)
    current_relatives = current_snapshot_paths(root)
    unknown = current_relatives - expected_relatives
    if unknown:
        cleanup_metadata_error("cleanup tombstone contains unknown entries")
    deleted = expected_relatives - current_relatives
    if deleted:
        if not allow_partial:
            cleanup_metadata_error("cleanup tombstone topology mismatch")
        if deleted != set(order[: len(deleted)]):
            cleanup_metadata_error("cleanup tombstone partial drain is not a completed prefix")
    remaining_children = cleanup_remaining_children(entries, deleted)
    exact_directories = not deleted
    for relative in expected_relatives - deleted:
        entry = entries[relative]
        path = root if relative == "." else root / safe_relative(relative)
        if entry["kind"] == "dir" and not exact_directories:
            if not cleanup_stable_directory_matches(
                path, entry, f"cleanup tombstone {name}/{relative}"
            ):
                cleanup_metadata_error("cleanup tombstone directory identity changed")
            try:
                actual_children = {child.name for child in path.iterdir()}
            except OSError as exc:
                cleanup_metadata_error(f"cleanup tombstone directory cannot be listed: {exc}")
            if actual_children != remaining_children.get(relative, set()):
                cleanup_metadata_error("cleanup tombstone directory child set mismatch")
        elif not cleanup_entry_matches(path, entry, f"cleanup tombstone {name}/{relative}"):
            cleanup_metadata_error("cleanup tombstone identity mismatch")
    return bool(expected_relatives - deleted), deleted


def cleanup_pending_metadata(target: Path, *, recover_alias: bool) -> dict[str, Any]:
    root = cleanup_pending_root(target)
    if not path_exists_no_follow(root):
        control = control_root(target)
        if path_exists_no_follow(control) and control.is_dir() and not control.is_symlink():
            for child in control.iterdir():
                if child.name.startswith(CLEANUP_STAGE_PREFIX):
                    cleanup_metadata_error("cleanup publication stage is incomplete")
        return {"pending": False, "metadata": None}
    require_owner_private_directory(root, "cleanup pending")
    journal = load_cleanup_journal(target, recover_alias=recover_alias)
    remaining = 0
    for tombstone in journal["tombstones"]:
        if validate_cleanup_tombstone_identity(target, tombstone):
            remaining += 1
    return {
        "pending": True,
        "metadata": {
            "schema_version": CLEANUP_SCHEMA_VERSION,
            "tombstone_count": journal["tombstone_count"],
            "remaining_tombstone_count": remaining,
            "entry_count": journal["entry_count"],
            "total_size": journal["total_size"],
            "build_version": journal["build_version"],
        },
    }


def cleanup_pending_result(target: Path) -> dict[str, Any]:
    state = cleanup_pending_metadata(target, recover_alias=False)
    return {
        "cleanup_pending": bool(state["pending"]),
        "cleanup": state["metadata"],
    }


def remove_cleanup_tombstone(target: Path, tombstone: dict[str, Any]) -> None:
    name = require_cleanup_name(str(tombstone["name"]), "cleanup tombstone")
    root = cleanup_tombstones_root(target) / name
    remaining, deleted = cleanup_tombstone_progress(target, tombstone, allow_partial=True)
    if not remaining:
        return
    entries = cleanup_entry_map(tombstone)
    for relative in cleanup_deletion_order(entries):
        if relative in deleted:
            continue
        entry = entries[relative]
        path = root if relative == "." else root / safe_relative(relative)
        if not path_exists_no_follow(path):
            deleted.add(relative)
            continue
        if entry["kind"] == "dir":
            if not cleanup_stable_directory_matches(
                path, entry, f"cleanup tombstone {name}/{relative}"
            ):
                cleanup_metadata_error("cleanup tombstone directory identity changed")
            remaining_children = cleanup_remaining_children(entries, deleted).get(relative, set())
            try:
                actual_children = {child.name for child in path.iterdir()}
            except OSError as exc:
                cleanup_metadata_error(f"cleanup tombstone directory cannot be listed: {exc}")
            if actual_children != remaining_children:
                cleanup_metadata_error("cleanup tombstone directory child set mismatch")
            path.rmdir()
        else:
            if not cleanup_entry_matches(path, entry, f"cleanup tombstone {name}/{relative}"):
                cleanup_metadata_error("cleanup tombstone object identity changed")
            path.unlink()
        fsync_directory(path.parent)
        deleted.add(relative)


def drain_cleanup_pending(target: Path, *, fail_closed: bool) -> bool:
    try:
        state = cleanup_pending_metadata(target, recover_alias=True)
        if not state["pending"]:
            return False
        journal = load_cleanup_journal(target, recover_alias=True)
        for tombstone in journal["tombstones"]:
            remove_cleanup_tombstone(target, tombstone)
        for tombstone in journal["tombstones"]:
            if validate_cleanup_tombstone_identity(target, tombstone):
                cleanup_metadata_error("cleanup tombstone survived deletion")
        journal_path = cleanup_journal_path(target)
        journal_path.unlink()
        fsync_directory(journal_path.parent)
        tombstones_root = cleanup_tombstones_root(target)
        tombstones_root.rmdir()
        fsync_directory(tombstones_root.parent)
        pending = cleanup_pending_root(target)
        pending.rmdir()
        fsync_directory(pending.parent)
        return True
    except BaseException:
        if fail_closed:
            raise
        return True


def publish_cleanup_pending(target: Path, sources: list[tuple[Path, str]]) -> bool:
    active_sources = [
        (source, require_cleanup_name(name, "cleanup tombstone"))
        for source, name in sources
        if path_exists_no_follow(source)
    ]
    if not active_sources:
        return False
    root = ensure_control_root(target)
    pending = cleanup_pending_root(target)
    if path_exists_no_follow(pending):
        cleanup_metadata_error("cleanup-pending state already exists")
    pending_created = False
    journal_visible = False
    moved: list[tuple[Path, Path]] = []
    try:
        pending.mkdir(mode=OWNER_DIRECTORY_MODE)
        pending_created = True
        pending.chmod(OWNER_DIRECTORY_MODE)
        fsync_directory(root)
        tombstones_root = pending / CLEANUP_TOMBSTONES_NAME
        tombstones_root.mkdir(mode=OWNER_DIRECTORY_MODE)
        tombstones_root.chmod(OWNER_DIRECTORY_MODE)
        fsync_directory(pending)
        tombstones: list[dict[str, Any]] = []
        for source, name in active_sources:
            destination = tombstones_root / name
            if destination.exists() or destination.is_symlink():
                cleanup_metadata_error("cleanup tombstone destination already exists")
            os.rename(source, destination)
            fsync_directory(source.parent)
            fsync_directory(tombstones_root)
            moved.append((destination, source))
            tombstones.append(cleanup_tree_manifest(destination, name, "cleanup tombstone"))
        journal_content = cleanup_journal_bytes(target, tombstones)
        if publish_cleanup_journal_no_replace(pending / CLEANUP_JOURNAL_NAME, journal_content):
            journal_visible = True
            return True
        journal_visible = True
    except BaseException:
        if not journal_visible:
            for destination, source in reversed(moved):
                if path_exists_no_follow(destination) and not path_exists_no_follow(source):
                    with contextlib.suppress(BaseException):
                        os.rename(destination, source)
                        fsync_directory(source.parent)
            with contextlib.suppress(BaseException):
                if pending_created:
                    shutil.rmtree(pending)
                    fsync_directory(root)
            raise
        return True
    return drain_cleanup_pending(target, fail_closed=False)


def require_owner_directory_mode(path: Path, label: str, allowed_modes: set[int]) -> os.stat_result:
    try:
        info = path.lstat()
    except FileNotFoundError:
        fail(f"{label} is missing")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a real directory")
    uid = current_user_id()
    if uid is not None and info.st_uid != uid:
        fail(f"{label} must be owned by the current user")
    mode = stat.S_IMODE(info.st_mode)
    if mode not in allowed_modes:
        allowed = " or ".join(oct(item).replace("0o", "0") for item in sorted(allowed_modes))
        fail(f"{label} must have mode {allowed}")
    return info


def require_owner_private_directory(path: Path, label: str) -> os.stat_result:
    return require_owner_directory_mode(path, label, {OWNER_DIRECTORY_MODE})


def require_control_root_directory(path: Path) -> os.stat_result:
    return require_owner_private_directory(path, "control root")


def require_lock_root_directory(path: Path) -> os.stat_result:
    return require_owner_directory_mode(
        path, "target lock directory", {LOCK_HELD_DIRECTORY_MODE, OWNER_DIRECTORY_MODE}
    )


def require_directory_matches_fd(
    path: Path, descriptor: int, label: str, allowed_modes: set[int]
) -> os.stat_result:
    try:
        path_info = path.lstat()
    except FileNotFoundError:
        fail(f"{label} disappeared")
    fd_info = os.fstat(descriptor)
    if (path_info.st_dev, path_info.st_ino) != (fd_info.st_dev, fd_info.st_ino):
        fail(f"{label} changed while it was being opened")
    if stat.S_ISLNK(path_info.st_mode) or not stat.S_ISDIR(fd_info.st_mode):
        fail(f"{label} path is unsafe")
    uid = current_user_id()
    if uid is not None and fd_info.st_uid != uid:
        fail(f"{label} must be owned by the current user")
    mode = stat.S_IMODE(fd_info.st_mode)
    if mode not in allowed_modes:
        allowed = " or ".join(oct(item).replace("0o", "0") for item in sorted(allowed_modes))
        fail(f"{label} must have mode {allowed}")
    return fd_info


def open_control_lock_root_fd(path: Path) -> int:
    require_lock_root_directory(path)
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            fail("target lock directory path is unsafe")
        fail(f"target lock directory could not be opened: {exc}")
    try:
        require_directory_matches_fd(
            path,
            descriptor,
            "target lock directory",
            {LOCK_HELD_DIRECTORY_MODE, OWNER_DIRECTORY_MODE},
        )
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def set_owner_directory_mode(path: Path, label: str, mode: int) -> None:
    require_owner_directory_mode(path, label, {LOCK_HELD_DIRECTORY_MODE, OWNER_DIRECTORY_MODE})
    os.chmod(path, mode)
    require_owner_directory_mode(path, label, {mode})


def set_owner_directory_fd_mode(path: Path, descriptor: int, label: str, mode: int) -> None:
    require_directory_matches_fd(
        path, descriptor, label, {LOCK_HELD_DIRECTORY_MODE, OWNER_DIRECTORY_MODE}
    )
    os.fchmod(descriptor, mode)
    require_directory_matches_fd(path, descriptor, label, {mode})


def require_lock_file_matches_fd(
    path: Path, descriptor: int, label: str, *, allowed_nlinks: set[int] | None = None
) -> os.stat_result:
    if allowed_nlinks is None:
        allowed_nlinks = {1}
    try:
        path_info = path.lstat()
    except FileNotFoundError:
        fail(f"{label} disappeared")
    fd_info = os.fstat(descriptor)
    if (path_info.st_dev, path_info.st_ino) != (fd_info.st_dev, fd_info.st_ino):
        fail(f"{label} changed while it was being opened")
    if stat.S_ISLNK(path_info.st_mode) or not stat.S_ISREG(fd_info.st_mode):
        fail(f"{label} path is unsafe")
    if fd_info.st_nlink not in allowed_nlinks:
        fail(f"{label} must not have hard-link aliases")
    uid = current_user_id()
    if uid is not None and fd_info.st_uid != uid:
        fail(f"{label} must be owned by the current user")
    if stat.S_IMODE(fd_info.st_mode) != OWNER_FILE_MODE:
        fail(f"{label} must have mode 0600")
    return fd_info


def open_target_lock_file(path: Path) -> int:
    require_lock_root_directory(path.parent)
    flags = os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    created = False
    try:
        descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, OWNER_FILE_MODE)
        created = True
    except FileExistsError:
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
                fail("target lock path is unsafe")
            raise
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            fail("target lock path is unsafe")
        fail(f"target lock could not be opened: {exc}")
    try:
        if created:
            os.fchmod(descriptor, OWNER_FILE_MODE)
        require_lock_file_matches_fd(path, descriptor, "target lock")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def cleanup_empty_persistent_lock_target(
    target: Path, root: Path | None, lock_root: Path | None, lock: Path | None
) -> None:
    if lock is not None:
        with contextlib.suppress(CursorSetupError, FileNotFoundError, OSError):
            info = require_regular_file(lock, "target lock", max_bytes=METADATA_MAX_BYTES)
            uid = current_user_id()
            if uid is None or info.st_uid == uid:
                lock.unlink()
    if lock_root is not None:
        with contextlib.suppress(OSError):
            lock_root.rmdir()
    if root is not None:
        with contextlib.suppress(OSError):
            root.rmdir()
    remove_empty_directory_if_created(target, existed_before=False)


def directory_component_label(relative: Path) -> str:
    return relative.as_posix()


def directory_component_finding(relative: Path, reason: str) -> str:
    return f"{directory_component_label(relative)}:{reason}"


def target_local_directory_chain_findings(target: Path, relative: Path) -> list[str]:
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        fail(f"unsafe target-local directory path: {relative.as_posix()}")
    findings: list[str] = []
    current = target
    walked = Path()
    uid = current_user_id()
    for part in relative.parts:
        walked = walked / part
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            break
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            findings.append(directory_component_finding(walked, "unsafe"))
            break
        if uid is not None and info.st_uid != uid:
            findings.append(directory_component_finding(walked, "owner"))
        if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
            findings.append(directory_component_finding(walked, "mode"))
    return findings


def require_target_local_directory_chain(target: Path, relative: Path, label: str) -> Path:
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        fail(f"unsafe {label} path: {relative.as_posix()}")
    current = target
    walked = Path()
    uid = current_user_id()
    for part in relative.parts:
        walked = walked / part
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            fail(f"{label} directory is missing: {walked.as_posix()}")
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail(f"{label} directory path is unsafe: {walked.as_posix()}")
        if uid is not None and info.st_uid != uid:
            fail(f"{label} directory must be owned by the current user: {walked.as_posix()}")
        if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
            fail(f"{label} directory must have mode 0700: {walked.as_posix()}")
    return target / relative


def builder_parent_directories() -> set[Path]:
    parents = {ISOLATED_HOME_ROOT}
    for _, target_path in builder_source_files(BUILDER_TARGET_ROOT):
        parent = target_path.parent
        while parent != Path("."):
            parents.add(parent)
            parent = parent.parent
    return parents


def runtime_parent_directories(target: Path) -> set[Path]:
    directories = {
        software_container(target),
        software_root(target),
        launch_images_root(target),
        software_root(target) / "versions",
        software_version_dir(target),
        managed_agent_path(target).parent,
        ISOLATED_HOME_ROOT,
        MUTABLE_RUNTIME_ROOT,
        MUTABLE_RUNTIME_TMP_ROOT,
    }
    relatives: set[Path] = set()
    for directory in directories:
        if directory.is_absolute():
            try:
                relative = directory.relative_to(target)
            except ValueError:
                continue
        else:
            relative = directory
        if relative != Path("."):
            relatives.add(relative)
    return relatives


def target_local_parent_findings(target: Path, relatives: set[Path]) -> list[str]:
    findings: list[str] = []
    for relative in sorted(relatives, key=lambda item: item.as_posix()):
        findings.extend(target_local_directory_chain_findings(target, relative))
    return sorted(dict.fromkeys(findings))


def builder_parent_findings(target: Path) -> list[str]:
    return target_local_parent_findings(target, builder_parent_directories())


def builder_parent_drifted(drift: list[str]) -> bool:
    builder_roots = (ISOLATED_HOME_ROOT.as_posix(), f"{ISOLATED_HOME_ROOT.as_posix()}/")
    return any(item == builder_roots[0] or item.startswith(builder_roots[1]) for item in drift)


def path_exists_no_follow(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def ensure_backup_pool(pool: Path) -> None:
    require_owner_private_directory(pool.parent, "control root")
    try:
        pool.mkdir(mode=OWNER_DIRECTORY_MODE)
    except FileExistsError:
        require_owner_private_directory(pool, "backup pool")
    else:
        pool.chmod(OWNER_DIRECTORY_MODE)
        require_owner_private_directory(pool, "backup pool")


def require_backup_envelope_file(path: Path, label: str) -> os.stat_result:
    info = require_regular_file(path, label, max_bytes=METADATA_MAX_BYTES)
    uid = current_user_id()
    if uid is not None and info.st_uid != uid:
        fail(f"{label} must be owned by the current user")
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        fail(f"{label} must have mode 0600")
    return info


def remove_backup_slot(slot_path: Path) -> None:
    require_owner_private_directory(slot_path, f"backup slot {slot_path.name}")
    entries = list(slot_path.iterdir())
    if len(entries) > 1 or (entries and entries[0].name != BACKUP_NAME):
        fail(f"backup slot {slot_path.name} contains unmanaged files")
    if entries:
        envelope = entries[0]
        require_backup_envelope_file(envelope, f"backup slot {slot_path.name} envelope")
        envelope.unlink()
        fsync_directory(slot_path)
    slot_path.rmdir()
    fsync_directory(slot_path.parent)


def require_exact_backup_slot(slot_path: Path, slot: int) -> Path:
    require_owner_private_directory(slot_path, f"backup slot {slot}")
    entries = sorted(slot_path.iterdir(), key=lambda path: path.name)
    names = [path.name for path in entries]
    if names != [BACKUP_NAME]:
        fail(f"backup slot {slot} must contain exactly {BACKUP_NAME}")
    return slot_path / BACKUP_NAME


def choose_backup_slot(pool: Path) -> int:
    ensure_backup_pool(pool)
    for slot in range(10):
        slot_path = pool / str(slot)
        if not path_exists_no_follow(slot_path):
            return slot
        require_owner_private_directory(slot_path, f"backup slot {slot}")
    oldest = min(range(10), key=lambda slot: (pool / str(slot)).lstat().st_mtime_ns)
    return oldest


class BackupPublication:
    def __init__(
        self,
        *,
        target: Path,
        slot: int,
        pool: Path,
        pool_existed: bool,
        retired_slot: Path | None,
    ) -> None:
        self.target = target
        self.slot = slot
        self.pool = pool
        self.pool_existed = pool_existed
        self.retired_slot = retired_slot


def capture_managed_files(target: Path) -> dict[str, bytes | None]:
    captured: dict[str, bytes | None] = {}
    for relative in managed_paths():
        path = target / relative
        if path.exists() or path.is_symlink():
            captured[relative.as_posix()] = read_regular_file(
                path,
                f"managed path {relative.as_posix()}",
                max_bytes=MANAGED_PAYLOAD_MAX_BYTES,
            )
        else:
            captured[relative.as_posix()] = None
    return captured


def backup_stage_path(pool: Path) -> Path:
    stage = Path(tempfile.mkdtemp(prefix=f"{BACKUP_STAGE_PREFIX}{os.getpid()}-", dir=str(pool)))
    stage.chmod(OWNER_DIRECTORY_MODE)
    fsync_directory(pool)
    return stage


def backup_retired_path(pool: Path, slot: int) -> Path:
    return pool / f"{BACKUP_RETIRED_PREFIX}{slot}-{os.getpid()}-{secrets.token_hex(8)}"


def backup_cleanup_path(pool: Path, slot: int) -> Path:
    return pool / f"{BACKUP_CLEANUP_PREFIX}{slot}-{os.getpid()}-{secrets.token_hex(8)}"


def validate_backup_envelope(target: Path, slot: int, envelope: dict[str, Any], label: str) -> None:
    schema_version = envelope.get("schema_version")
    if schema_version != BACKUP_SCHEMA_VERSION:
        fail("backup schema version must include per-file digests")
    require_exact_keys(envelope, BACKUP_KEYS_V3, label)
    if envelope["product_name"] != PRODUCT_NAME:
        fail("backup is not owned by nddev-cursor-cli-app")
    if envelope["canonical_target"] != str(target.resolve(strict=False)):
        fail("backup belongs to a different canonical target")
    if envelope["slot"] != slot:
        fail("backup slot identity mismatch")
    if envelope["managed_files"] != [CONFIG_NAME]:
        fail("backup managed_files mismatch")


def load_backup_from_path(target: Path, slot: int, path: Path, label: str) -> dict[str, Any]:
    require_backup_envelope_file(path, label)
    envelope = load_json_object(path, label)
    validate_backup_envelope(target, slot, envelope, label)
    return envelope


def write_backup(target: Path, source_state: dict[str, Any]) -> BackupPublication:
    pool = backup_pool(target)
    pool_existed = path_exists_no_follow(pool)
    if pool_existed:
        require_owner_private_directory(pool, "backup pool")
    else:
        ensure_backup_pool(pool)
    slot = choose_backup_slot(pool)
    slot_path = pool / str(slot)
    stage = backup_stage_path(pool)
    retired_slot: Path | None = None
    files = capture_managed_files(target)
    envelope = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "slot": slot,
        "canonical_target": str(target.resolve(strict=False)),
        "source_content_setup_id": source_state.get("content_setup_id"),
        "source_profile_id": source_state.get("profile_id"),
        "source_legacy_setup_id": source_state.get("legacy_setup_id"),
        "managed_files": [CONFIG_NAME],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": {
            relative: backup_file_record(relative, content) for relative, content in files.items()
        },
    }
    envelope_path = stage / BACKUP_NAME
    try:
        write_exclusive_file(envelope_path, canonical_json(envelope))
        fsync_directory(stage)
        load_backup_from_path(target, slot, envelope_path, f"backup slot {slot} staged envelope")
        if path_exists_no_follow(slot_path):
            retired_slot = backup_retired_path(pool, slot)
            os.rename(slot_path, retired_slot)
            fsync_directory(pool)
        os.rename(stage, slot_path)
        fsync_directory(pool)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            shutil.rmtree(stage)
            fsync_directory(pool)
        if retired_slot is not None and (retired_slot.exists() or retired_slot.is_symlink()):
            with contextlib.suppress(FileNotFoundError):
                os.rename(retired_slot, slot_path)
                fsync_directory(pool)
        if not pool_existed:
            with contextlib.suppress(OSError):
                pool.rmdir()
                fsync_directory(pool.parent)
        raise
    return BackupPublication(
        target=target,
        slot=slot,
        pool=pool,
        pool_existed=pool_existed,
        retired_slot=retired_slot,
    )


def finish_backup_publication(publication: BackupPublication | None) -> None:
    sources = backup_cleanup_sources(publication)
    if publication is None or not sources:
        return
    publish_cleanup_pending(publication.target, sources)
    mark_backup_cleanup_promoted(publication)


def backup_cleanup_sources(publication: BackupPublication | None) -> list[tuple[Path, str]]:
    if publication is None or publication.retired_slot is None:
        return []
    return [(publication.retired_slot, f"backup-slot-{publication.slot}")]


def mark_backup_cleanup_promoted(publication: BackupPublication | None) -> None:
    if publication is not None:
        publication.retired_slot = None


def rollback_backup_publication(publication: BackupPublication | None) -> None:
    if publication is None:
        return
    slot_path = publication.pool / str(publication.slot)
    if slot_path.exists() or slot_path.is_symlink():
        remove_backup_slot(slot_path)
    if publication.retired_slot is not None and (
        publication.retired_slot.exists() or publication.retired_slot.is_symlink()
    ):
        os.rename(publication.retired_slot, slot_path)
        fsync_directory(publication.pool)
        publication.retired_slot = None
    if not publication.pool_existed:
        with contextlib.suppress(OSError):
            publication.pool.rmdir()
            fsync_directory(publication.pool.parent)


def load_backup(target: Path, slot: int) -> dict[str, Any]:
    slot_path = backup_pool(target) / str(slot)
    path = require_exact_backup_slot(slot_path, slot)
    return load_backup_from_path(target, slot, path, f"backup slot {slot} envelope")


def safe_relative(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        fail(f"unsafe managed relative path: {relative}")
    return path


def remove_empty_parents(target: Path, path: Path) -> None:
    parent = path.parent
    while parent != target and parent.is_relative_to(target):
        try:
            parent.rmdir()
            fsync_directory(parent.parent)
        except OSError:
            pass
        parent = parent.parent


def ensure_real_directory(root: Path, relative: Path) -> None:
    current = root
    uid = current_user_id()
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            try:
                info = current.lstat()
            except FileNotFoundError:
                fail(f"managed directory appeared concurrently: {current}")
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                fail(f"managed directory path is unsafe: {current}")
            if uid is not None and info.st_uid != uid:
                fail(f"managed directory must be owned by the current user: {current}")
            if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
                fail(f"managed directory must have mode 0700: {current}")
            continue
        current.mkdir(mode=OWNER_DIRECTORY_MODE)
        current.chmod(OWNER_DIRECTORY_MODE)
        fsync_directory(current.parent)


def write_exclusive_file_with_mode(path: Path, content: bytes, mode: int) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, mode)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written == 0:
                fail(f"managed write made no progress: {path}")
            view = view[written:]
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_exclusive_file(path: Path, content: bytes) -> None:
    write_exclusive_file_with_mode(path, content, OWNER_FILE_MODE)


def snapshot_managed_path(target: Path, relative: Path) -> tuple[bytes | None, int | None]:
    destination = target / relative
    if not destination.exists() and not destination.is_symlink():
        return None, None
    content = read_regular_file(
        destination,
        f"managed path {relative.as_posix()}",
        max_bytes=MANAGED_PAYLOAD_MAX_BYTES,
    )
    info = require_regular_file(
        destination,
        f"managed path {relative.as_posix()}",
        max_bytes=MANAGED_PAYLOAD_MAX_BYTES,
    )
    return content, stat.S_IMODE(info.st_mode)


def managed_path_matches(
    target: Path, relative: Path, content: bytes | None, mode: int | None
) -> bool:
    destination = target / relative
    if content is None:
        return not (destination.exists() or destination.is_symlink())
    if not (destination.exists() or destination.is_symlink()):
        return False
    try:
        current = read_regular_file(
            destination,
            f"managed path {relative.as_posix()}",
            max_bytes=MANAGED_PAYLOAD_MAX_BYTES,
        )
        info = require_regular_file(
            destination,
            f"managed path {relative.as_posix()}",
            max_bytes=MANAGED_PAYLOAD_MAX_BYTES,
        )
    except CursorSetupError:
        return False
    return current == content and stat.S_IMODE(info.st_mode) == (mode or OWNER_FILE_MODE)


def managed_transaction_path(target: Path) -> Path:
    root = ensure_control_root(target)
    transaction = Path(
        tempfile.mkdtemp(prefix=f"{MANAGED_TRANSACTION_PREFIX}{os.getpid()}-", dir=str(root))
    )
    try:
        transaction.chmod(OWNER_DIRECTORY_MODE)
        fsync_directory(root)
    except BaseException:
        with contextlib.suppress(BaseException):
            shutil.rmtree(transaction)
        raise
    return transaction


def cleanup_managed_transaction(transaction: Path) -> None:
    if transaction.exists() or transaction.is_symlink():
        shutil.rmtree(transaction)
        fsync_directory(transaction.parent)


def managed_parent_chain(relative: Path) -> tuple[Path, ...]:
    parents: list[Path] = []
    parent = relative.parent
    while parent != Path("."):
        parents.append(parent)
        parent = parent.parent
    return tuple(parents)


def existing_managed_parents(target: Path, relative: Path) -> set[Path]:
    existing: set[Path] = set()
    for parent in managed_parent_chain(relative):
        path = target / parent
        if path.exists() or path.is_symlink():
            existing.add(parent)
    return existing


def remove_created_managed_parents(
    target: Path, relative: Path, preexisting_parents: set[Path]
) -> None:
    for parent in managed_parent_chain(relative):
        if parent in preexisting_parents:
            break
        path = target / parent
        with contextlib.suppress(FileNotFoundError, OSError):
            path.rmdir()
            fsync_directory(path.parent)


def discard_managed_destination(transaction: Path, destination: Path) -> None:
    if not (destination.exists() or destination.is_symlink()):
        return
    require_regular_file(
        destination,
        f"managed path {destination}",
        max_bytes=MANAGED_PAYLOAD_MAX_BYTES,
    )
    discarded = transaction / f"discard-{secrets.token_hex(8)}"
    os.rename(destination, discarded)
    fsync_existing_parent(destination)
    with contextlib.suppress(FileNotFoundError):
        discarded.unlink()
        fsync_directory(transaction)


class ManagedStateTransaction:
    def __init__(
        self,
        target: Path,
        transaction: Path | None,
        records: list[dict[str, Any]],
    ) -> None:
        self.target = target
        self.transaction = transaction
        self.records = records
        self.closed = False

    def publish(self) -> None:
        if self.transaction is None:
            return
        published: list[dict[str, Any]] = []
        try:
            for record in self.records:
                relative: Path = record["relative"]
                destination = self.target / relative
                before_content = record["before_content"]
                desired_content = record["desired_content"]
                before_store: Path | None = record["before_store"]
                desired_store: Path | None = record["desired_store"]
                published.append(record)
                ensure_real_directory(self.target, relative.parent)
                if before_content is not None:
                    require_regular_file(
                        destination,
                        f"managed path {relative.as_posix()}",
                        max_bytes=MANAGED_PAYLOAD_MAX_BYTES,
                    )
                    if before_store is None:
                        fail("managed transaction missing before store")
                    os.rename(destination, before_store)
                    fsync_existing_parent(destination)
                elif destination.exists() or destination.is_symlink():
                    fail(f"managed path appeared concurrently: {relative.as_posix()}")
                if desired_content is not None:
                    if desired_store is None:
                        fail("managed transaction missing desired store")
                    os.rename(desired_store, destination)
                    fsync_existing_parent(destination)
            if not self.matches("desired"):
                fail("managed transaction desired verification failed")
        except BaseException:
            self.rollback(records=published)
            raise

    def matches(self, state: str) -> bool:
        return all(
            managed_path_matches(
                self.target,
                record["relative"],
                record[f"{state}_content"],
                record[f"{state}_mode"],
            )
            for record in self.records
        )

    def rollback(self, *, records: list[dict[str, Any]] | None = None) -> None:
        if self.closed or self.transaction is None:
            return
        active_records = self.records if records is None else records
        errors: list[str] = []
        for _ in range(4):
            for record in reversed(active_records):
                relative: Path = record["relative"]
                destination = self.target / relative
                before_content = record["before_content"]
                before_store: Path | None = record["before_store"]
                try:
                    if not managed_path_matches(
                        self.target,
                        relative,
                        before_content,
                        record["before_mode"],
                    ):
                        discard_managed_destination(self.transaction, destination)
                        if before_content is not None:
                            if before_store is None or not before_store.exists():
                                fail(
                                    "managed transaction cannot restore missing before object: "
                                    f"{relative.as_posix()}"
                                )
                            ensure_real_directory(self.target, relative.parent)
                            os.rename(before_store, destination)
                            fsync_existing_parent(destination)
                    if before_content is None:
                        remove_created_managed_parents(
                            self.target,
                            relative,
                            record["preexisting_parents"],
                        )
                except BaseException as exc:  # noqa: BLE001 - retry the whole rollback set.
                    errors.append(f"{relative.as_posix()}: {exc}")
            if self.matches("before"):
                cleanup_managed_transaction(self.transaction)
                self.closed = True
                return
        fail(f"managed transaction rollback verification failed: {errors[-5:]}")

    def commit(self) -> None:
        if self.closed:
            return
        if self.transaction is not None:
            publish_cleanup_pending(self.target, self.cleanup_sources())
            self.transaction = None
        self.closed = True

    def cleanup_sources(self) -> list[tuple[Path, str]]:
        if self.closed or self.transaction is None:
            return []
        return [(self.transaction, "managed-transaction")]

    def mark_cleanup_promoted(self) -> None:
        self.transaction = None
        self.closed = True


def validate_expected_managed_state(
    target: Path, selected: tuple[str, ...], expected: Any | None
) -> None:
    if expected is None:
        return
    if not isinstance(expected, dict):
        fail("managed transaction expected pre-state must be an object")
    for relative_name in selected:
        relative = safe_relative(relative_name)
        key = relative.as_posix()
        if key not in expected:
            fail(f"managed transaction expected pre-state is missing {key}")
        content = expected[key]
        if content is not None and not isinstance(content, bytes):
            fail(f"managed transaction expected pre-state for {key} must be bytes or absent")
        mode = None if content is None else OWNER_FILE_MODE
        if not managed_path_matches(target, relative, content, mode):
            fail(f"managed transaction pre-state changed before write: {key}")


def replace_managed_state(
    target: Path,
    desired: dict[str, bytes | None],
    expected: Any | None = None,
    *,
    names: tuple[str, ...] | None = None,
) -> None:
    transaction = begin_managed_state_transaction(target, desired, expected, names=names)
    try:
        transaction.publish()
        transaction.commit()
    except BaseException:
        transaction.rollback()
        raise


def begin_managed_state_transaction(
    target: Path,
    desired: dict[str, bytes | None],
    expected: Any | None = None,
    *,
    names: tuple[str, ...] | None = None,
) -> ManagedStateTransaction:
    selected = tuple(desired) if names is None else names
    validate_expected_managed_state(target, selected, expected)
    records: list[dict[str, Any]] = []
    for relative_name in selected:
        relative = safe_relative(relative_name)
        before_content, before_mode = snapshot_managed_path(target, relative)
        desired_content = desired.get(relative_name)
        desired_mode = None if desired_content is None else OWNER_FILE_MODE
        if before_content == desired_content and before_mode == desired_mode:
            continue
        records.append(
            {
                "relative": relative,
                "before_content": before_content,
                "before_mode": before_mode,
                "desired_content": desired_content,
                "desired_mode": desired_mode,
                "preexisting_parents": existing_managed_parents(target, relative),
                "before_store": None,
                "desired_store": None,
            }
        )
    if not records:
        return ManagedStateTransaction(target, None, [])
    transaction = managed_transaction_path(target)
    try:
        for index, record in enumerate(records):
            if record["before_content"] is not None:
                record["before_store"] = transaction / f"{index}.before"
            desired_content = record["desired_content"]
            if desired_content is not None:
                desired_store = transaction / f"{index}.desired"
                record["desired_store"] = desired_store
                write_exclusive_file_with_mode(desired_store, desired_content, OWNER_FILE_MODE)
        journal = [
            {
                "path": record["relative"].as_posix(),
                "before_sha256": None
                if record["before_content"] is None
                else sha256_bytes(record["before_content"]),
                "desired_sha256": None
                if record["desired_content"] is None
                else sha256_bytes(record["desired_content"]),
            }
            for record in records
        ]
        write_exclusive_file(transaction / "journal.json", canonical_json(journal))
        fsync_directory(transaction)
        return ManagedStateTransaction(target, transaction, records)
    except BaseException:
        with contextlib.suppress(BaseException):
            cleanup_managed_transaction(transaction)
        raise


def backup_file_digest(relative: str, content: bytes | None) -> str:
    digest = hashlib.sha256()
    digest.update(BACKUP_FILE_DIGEST_DOMAIN)
    digest.update(relative.encode("utf-8"))
    digest.update(b"\0")
    if content is None:
        digest.update(b"absent\0")
    else:
        digest.update(b"present\0")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\0")
        digest.update(content)
    return digest.hexdigest()


def backup_file_record(relative: str, content: bytes | None) -> dict[str, str | None]:
    return {
        "payload": None if content is None else base64.b64encode(content).decode("ascii"),
        "sha256": backup_file_digest(relative, content),
    }


def changed_paths_for_desired(target: Path, desired: dict[str, bytes | None]) -> list[str]:
    before = capture_managed_files(target)
    return [relative for relative, content in desired.items() if before.get(relative) != content]


PLAN_LOCK_BOOTSTRAP_FINDINGS = frozenset(
    {
        CONTROL_ROOT_NAME + ":missing",
        f"{CONTROL_ROOT_NAME}/{CONTROL_LOCKS_NAME}:missing",
        f"{CONTROL_ROOT_NAME}/{CONTROL_LOCKS_NAME}/{CONTROL_LOCK_NAME}:missing",
    }
)
SETUP_UPDATE_REPAIRABLE_DRIFT = frozenset({CONFIG_NAME, BUILDER_TARGET_ROOT.as_posix()})


def plan_blocking_drift(drift: list[str]) -> list[str]:
    return [finding for finding in drift if finding not in PLAN_LOCK_BOOTSTRAP_FINDINGS]


def setup_update_blocking_drift(drift: list[str]) -> list[str]:
    return [finding for finding in drift if finding not in SETUP_UPDATE_REPAIRABLE_DRIFT]


def desired_for_selection(
    target: Path,
    content_setup_id: str,
    profile_id: str,
    existing_config: dict[str, Any] | None,
) -> dict[str, bytes | None]:
    _, _, rendered = render_selection(content_setup_id, profile_id)
    setup_config = parse_json_object(rendered[CONFIG_NAME], f"profile {profile_id}/{CONFIG_NAME}")
    desired_config = merge_config(existing_config, setup_config)
    desired: dict[str, bytes | None] = {
        CONFIG_NAME: canonical_json(desired_config),
        STAMP_NAME: stamp_bytes(target, content_setup_id, profile_id),
    }
    desired.update(builder_projection_files())
    for _, legacy_target in builder_source_files(LEGACY_BUILDER_TARGET_ROOT):
        desired.setdefault(legacy_target.as_posix(), None)
    return desired


def desired_for_remove(target: Path) -> dict[str, bytes | None]:
    desired: dict[str, bytes | None] = {relative.as_posix(): None for relative in managed_paths()}
    existing_config = load_target_config(target)
    if existing_config is not None:
        unmanaged = {
            key: value for key, value in existing_config.items() if key not in MANAGED_CONFIG_KEYS
        }
        desired[CONFIG_NAME] = canonical_json(unmanaged) if unmanaged else None
    return desired


def restore_files_from_backup(envelope: dict[str, Any]) -> dict[str, bytes | None]:
    files = envelope.get("files")
    if not isinstance(files, dict):
        fail("backup files must be an object")
    expected_paths = {relative.as_posix() for relative in managed_paths()}
    actual_paths = set(files)
    if actual_paths != expected_paths:
        missing = sorted(expected_paths - actual_paths)
        extra = sorted(actual_paths - expected_paths)
        fail(f"backup files path set mismatch (missing={missing}, extra={extra})")
    desired: dict[str, bytes | None] = {}
    for relative, record in files.items():
        path = safe_relative(str(relative))
        if path.as_posix() != relative:
            fail(f"backup file path must be canonical: {relative}")
        if not isinstance(record, dict):
            fail(f"backup file record for {relative} must be an object")
        require_exact_keys(record, BACKUP_FILE_KEYS_V1, f"backup file record {relative}")
        encoded = record["payload"]
        declared_digest = record["sha256"]
        if not isinstance(declared_digest, str) or not SHA256_HEX_PATTERN.fullmatch(
            declared_digest
        ):
            fail(f"backup digest for {relative} must be a lowercase SHA-256 digest")
        content: bytes | None
        if not isinstance(encoded, str):
            if encoded is not None:
                fail(f"backup payload for {relative} must be a base64 string")
            content = None
        else:
            try:
                content = base64.b64decode(encoded.encode("ascii"), validate=True)
            except (ValueError, UnicodeEncodeError) as exc:
                fail(f"backup payload for {relative} is invalid: {exc}")
        if backup_file_digest(relative, content) != declared_digest:
            fail(f"backup digest mismatch for {relative}")
        desired[path.as_posix()] = content
    return desired


def plan_setup(target: Path, content_setup_id: str, profile_id: str) -> dict[str, Any]:
    return with_read_bootstrap_target(target, _plan_setup_locked, content_setup_id, profile_id)


def _plan_setup_locked(target: Path, content_setup_id: str, profile_id: str) -> dict[str, Any]:
    render_selection(content_setup_id, profile_id)
    state = _inspect_target_locked(target)
    cleanup = {
        "cleanup_pending": state["cleanup_pending"],
        "cleanup": state["cleanup"],
    }
    operation = "install"
    backup_required = False
    changes: list[str] = []
    if state["state"] == "managed":
        blocking_drift = plan_blocking_drift(state["drift"])
        if state.get("legacy"):
            operation = "migrate"
            backup_required = True
            changes = (
                ["blocked-by-drift"]
                if blocking_drift
                else changed_paths_for_desired(
                    target,
                    desired_for_selection(
                        target, content_setup_id, profile_id, load_target_config(target)
                    ),
                )
            )
        else:
            current_setup = state["content_setup_id"]
            current_profile = state["profile_id"]
            selected_current = current_setup == content_setup_id and current_profile == profile_id
            operation = "update" if selected_current else "switch"
            backup_required = not selected_current
            if blocking_drift:
                changes = ["blocked-by-drift"]
            elif not selected_current:
                changes = changed_paths_for_desired(
                    target,
                    desired_for_selection(
                        target, content_setup_id, profile_id, load_target_config(target)
                    ),
                )
            else:
                desired = desired_for_selection(
                    target, content_setup_id, profile_id, load_target_config(target)
                )
                changes = changed_paths_for_desired(target, desired)
    elif state["state"] in {"missing", "empty"}:
        changes = (
            ["blocked-by-drift"]
            if state["drift"]
            else changed_paths_for_desired(
                target,
                desired_for_selection(target, content_setup_id, profile_id, None),
            )
        )
    else:
        changes = ["blocked-by-unmanaged-target"]
    return {
        "schema_version": 2,
        "command": "plan",
        "operation": operation,
        "content_setup_id": content_setup_id,
        "profile_id": profile_id,
        "target": str(target),
        "mutates": False,
        "backup_required": backup_required,
        "changes": changes,
        "builder_projection": "default-on",
        **cleanup,
    }


def mutate_setup(
    target: Path, content_setup_id: str, profile_id: str, command: str
) -> dict[str, Any]:
    return with_bootstrap_target(
        target, _mutate_setup_locked, content_setup_id, profile_id, command
    )


def _mutate_setup_locked(
    target: Path, content_setup_id: str, profile_id: str, command: str
) -> dict[str, Any]:
    if command not in {"install", "update", "switch"}:
        fail(f"unsupported setup mutation command: {command}")
    if command != "update":
        render_selection(content_setup_id, profile_id)
    cleanup_pending = False
    with exact_target_lifecycle_guard(target, f"setup {command}"):
        if command == "update" and not (target.exists() or target.is_symlink()):
            fail("update requires an existing managed target")
        created_target = prepare_lifecycle_target(target, create_missing=command == "install")
        try:
            with target_lock(target, cleanup_empty_target_on_error=created_target):
                state = _inspect_target_locked(target)
                if state["state"] == "unmanaged":
                    fail("unmanaged target contains Cursor CLI state; refusing to overwrite")
                if state["state"] == "managed" and state.get("legacy"):
                    fail("legacy managed target must be migrated before install, update, or switch")
                if command in {"switch", "update"} and state["state"] != "managed":
                    fail(f"{command} requires an existing managed target")
                if command == "update":
                    blocking_update_drift = setup_update_blocking_drift(state["drift"])
                    if blocking_update_drift:
                        fail(f"managed target has drift: {', '.join(blocking_update_drift)}")
                elif state["state"] == "managed" and state["drift"]:
                    fail(f"managed target has drift: {', '.join(state['drift'])}")
                current_setup = state["content_setup_id"] if state["state"] == "managed" else None
                current_profile = state["profile_id"] if state["state"] == "managed" else None
                if command == "update":
                    if current_setup is None or current_profile is None:
                        fail("update requires an installed setup/profile identity")
                    content_setup_id = str(current_setup)
                    profile_id = str(current_profile)
                    render_selection(content_setup_id, profile_id)
                selected_current = (
                    current_setup == content_setup_id and current_profile == profile_id
                )
                if command == "switch" and selected_current:
                    fail("switch requires a different setup or profile")
                existing_config = (
                    load_target_config(target) if state["state"] == "managed" else None
                )
                desired = desired_for_selection(
                    target, content_setup_id, profile_id, existing_config
                )
                before = capture_managed_files(target)
                changed = [
                    relative
                    for relative, content in desired.items()
                    if before.get(relative) != content
                ]
                backup_publication: BackupPublication | None = None
                if state["state"] == "managed" and not selected_current:
                    backup_publication = write_backup(target, state)
                managed_transaction: ManagedStateTransaction | None = None
                try:
                    if changed:
                        managed_transaction = begin_managed_state_transaction(
                            target, desired, before
                        )
                        managed_transaction.publish()
                    final = _inspect_target_locked(target)
                    if (
                        final["state"] != "managed"
                        or final.get("legacy")
                        or final["content_setup_id"] != content_setup_id
                        or final["profile_id"] != profile_id
                        or final["drift"]
                    ):
                        fail("setup mutation postcondition failed")
                    cleanup_sources = backup_cleanup_sources(backup_publication)
                    if managed_transaction is not None:
                        cleanup_sources.extend(managed_transaction.cleanup_sources())
                    cleanup_pending = publish_cleanup_pending(target, cleanup_sources)
                    mark_backup_cleanup_promoted(backup_publication)
                    if managed_transaction is not None:
                        managed_transaction.mark_cleanup_promoted()
                except BaseException:
                    if managed_transaction is not None:
                        managed_transaction.rollback()
                    rollback_backup_publication(backup_publication)
                    raise
        except BaseException:
            if created_target:
                remove_empty_directory_if_created(target, existed_before=False)
            raise
    return {
        "schema_version": 2,
        "command": command,
        "target": str(target),
        "content_setup_id": content_setup_id,
        "profile_id": profile_id,
        "changed": changed,
        "backup_slot": None if backup_publication is None else backup_publication.slot,
        "builder_projection": "current",
        "cleanup_pending": cleanup_pending,
    }


def migrate_setup(
    target: Path, content_setup_id: str, requested_profile_id: str | None
) -> dict[str, Any]:
    return with_bootstrap_target(
        target, _migrate_setup_locked, content_setup_id, requested_profile_id
    )


def _migrate_setup_locked(
    target: Path, content_setup_id: str, requested_profile_id: str | None
) -> dict[str, Any]:
    render_content_setup(content_setup_id)
    cleanup_pending = False
    with exact_target_lifecycle_guard(target, "setup migrate"):
        prepare_lifecycle_target(target, create_missing=False)
        with target_lock(target):
            state = _inspect_target_locked(target)
            if state["state"] != "managed" or not state.get("legacy"):
                fail("migrate requires a legacy managed target")
            legacy_setup_id = state["legacy_setup_id"]
            profile_id = requested_profile_id or LEGACY_SETUP_PROFILE_IDS.get(str(legacy_setup_id))
            if profile_id is None:
                fail(
                    "legacy review targets require an explicit --profile full-auto or --profile safe"
                )
            render_selection(content_setup_id, profile_id)
            if state["drift"]:
                fail(f"legacy managed target has drift: {', '.join(state['drift'])}")
            existing_config = load_target_config(target)
            desired = desired_for_selection(target, content_setup_id, profile_id, existing_config)
            before = capture_managed_files(target)
            changed = [
                relative for relative, content in desired.items() if before.get(relative) != content
            ]
            backup_publication = write_backup(target, state)
            managed_transaction: ManagedStateTransaction | None = None
            try:
                managed_transaction = begin_managed_state_transaction(target, desired, before)
                managed_transaction.publish()
                final = _inspect_target_locked(target)
                if (
                    final["state"] != "managed"
                    or final.get("legacy")
                    or final["content_setup_id"] != content_setup_id
                    or final["profile_id"] != profile_id
                    or final["drift"]
                ):
                    fail("migrate postcondition failed")
                cleanup_sources = backup_cleanup_sources(backup_publication)
                cleanup_sources.extend(managed_transaction.cleanup_sources())
                cleanup_pending = publish_cleanup_pending(target, cleanup_sources)
                mark_backup_cleanup_promoted(backup_publication)
                managed_transaction.mark_cleanup_promoted()
            except BaseException:
                if managed_transaction is not None:
                    managed_transaction.rollback()
                rollback_backup_publication(backup_publication)
                raise
    return {
        "schema_version": 2,
        "command": "migrate",
        "target": str(target),
        "from_legacy_setup_id": legacy_setup_id,
        "content_setup_id": content_setup_id,
        "profile_id": profile_id,
        "changed": changed,
        "backup_slot": backup_publication.slot,
        "builder_projection": "current",
        "cleanup_pending": cleanup_pending,
    }


def restore_slot(target: Path, slot: int) -> dict[str, Any]:
    return with_bootstrap_target(target, _restore_slot_locked, slot)


def _restore_slot_locked(target: Path, slot: int) -> dict[str, Any]:
    cleanup_pending = False
    with exact_target_lifecycle_guard(target, "setup restore"):
        prepare_lifecycle_target(target, create_missing=False)
        with target_lock(target):
            envelope = load_backup(target, slot)
            state = _inspect_target_locked(target)
            if state["state"] == "managed" and state["drift"] and not state.get("legacy"):
                fail(f"managed target has drift: {', '.join(state['drift'])}")
            before = capture_managed_files(target)
            desired = restore_files_from_backup(envelope)
            managed_transaction: ManagedStateTransaction | None = None
            try:
                managed_transaction = begin_managed_state_transaction(target, desired, before)
                managed_transaction.publish()
                final = _inspect_target_locked(target)
                if final["state"] != "managed" or final["drift"]:
                    fail("restore postcondition failed")
                cleanup_pending = publish_cleanup_pending(
                    target, managed_transaction.cleanup_sources()
                )
                managed_transaction.mark_cleanup_promoted()
            except BaseException:
                if managed_transaction is not None:
                    managed_transaction.rollback()
                raise
    return {
        "schema_version": 2,
        "command": "restore",
        "target": str(target),
        "backup_slot": slot,
        "content_setup_id": envelope.get("source_content_setup_id"),
        "profile_id": envelope.get("source_profile_id"),
        "legacy_setup_id": envelope.get("source_legacy_setup_id"),
        "builder_projection": "current",
        "cleanup_pending": cleanup_pending,
    }


def remove_setup(target: Path) -> dict[str, Any]:
    return with_bootstrap_target(target, _remove_setup_locked)


def _remove_setup_locked(target: Path) -> dict[str, Any]:
    cleanup_pending = False
    with exact_target_lifecycle_guard(target, "setup remove"):
        prepare_lifecycle_target(target, create_missing=False)
        with target_lock(target):
            state = _inspect_target_locked(target)
            if state["state"] != "managed":
                fail(f"target is not managed (state={state['state']})")
            before = capture_managed_files(target)
            desired = desired_for_remove(target)
            managed_transaction: ManagedStateTransaction | None = None
            try:
                managed_transaction = begin_managed_state_transaction(target, desired, before)
                managed_transaction.publish()
                cleanup_pending = publish_cleanup_pending(
                    target, managed_transaction.cleanup_sources()
                )
                managed_transaction.mark_cleanup_promoted()
            except BaseException:
                if managed_transaction is not None:
                    managed_transaction.rollback()
                raise
    return {
        "schema_version": 2,
        "command": "remove",
        "target": str(target),
        "removed_content_setup_id": state.get("content_setup_id"),
        "removed_profile_id": state.get("profile_id"),
        "removed_legacy_setup_id": state.get("legacy_setup_id"),
        "cleanup_pending": cleanup_pending,
    }


def software_root(target: Path) -> Path:
    return target / ".nddev-software" / "cursor-cli"


def software_container(target: Path) -> Path:
    return target / ".nddev-software"


def software_version_dir(target: Path) -> Path:
    return software_root(target) / "versions" / CURSOR_VERSION


def software_tree_binary(target: Path) -> Path:
    return software_version_dir(target) / "cursor-agent"


def managed_agent_path(target: Path) -> Path:
    return target / "bin" / CURSOR_COMMAND


def launch_images_root(target: Path) -> Path:
    return software_root(target) / LAUNCH_IMAGES_NAME


def mutable_runtime_tmp_dir(target: Path) -> Path:
    return target / MUTABLE_RUNTIME_TMP_ROOT


def software_stamp_path(target: Path) -> Path:
    return software_root(target) / SOFTWARE_STAMP_NAME


def software_transaction_path(target: Path) -> Path:
    return software_root(target) / SOFTWARE_TRANSACTION_NAME


def write_software_transaction_marker(target: Path, command: str) -> None:
    marker = {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "command": command,
        "canonical_target": str(target.resolve(strict=False)),
        "started_at": int(time.time()),
        "capability": "recoverable-non-current-marker",
    }
    atomic_write(software_transaction_path(target), canonical_json(marker))


def clear_software_transaction_marker(target: Path) -> None:
    marker = software_transaction_path(target)
    if marker.exists() or marker.is_symlink():
        require_regular_file(
            marker, "Cursor software transaction marker", max_bytes=METADATA_MAX_BYTES
        )
        marker.unlink()
        fsync_existing_parent(marker)


def existing_path_label(path: Path, label: str) -> str | None:
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    return label


def software_presence(target: Path) -> list[str]:
    file_labels = (
        (software_transaction_path(target), SOFTWARE_TRANSACTION_NAME),
        (software_stamp_path(target), SOFTWARE_STAMP_NAME),
        (managed_agent_path(target), "bin/agent"),
    )
    directory_labels = (
        (software_container(target), ".nddev-software"),
        (software_root(target), ".nddev-software/cursor-cli"),
        (
            software_version_dir(target),
            ".nddev-software/cursor-cli/versions/2026.07.23-e383d2b",
        ),
    )
    presence = [
        label for path, label in file_labels if existing_path_label(path, label) is not None
    ]
    for path, label in directory_labels:
        if not (path.exists() or path.is_symlink()):
            continue
        if path.is_symlink() or not path.is_dir():
            presence.append(label)
            continue
        if any(child.is_symlink() or child.is_file() for child in path.rglob("*")):
            presence.append(label)
    return sorted(presence)


def parse_os_release(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def read_linux_os_release(path: Path = LINUX_OS_RELEASE_PATH) -> dict[str, str]:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"unsupported Cursor CLI Linux host: cannot read {path}: {exc}")
    return parse_os_release(content)


def detect_linux_libc() -> str:
    libc_name = py_platform.libc_ver()[0].lower()
    if libc_name in {SUPPORTED_LINUX_LIBC, "musl"}:
        return libc_name
    for pattern in MUSL_LOADER_GLOBS:
        if glob.glob(pattern):
            return "musl"
    return libc_name or "unknown"


def require_supported_ubuntu_linux(
    *,
    os_release: dict[str, str] | None = None,
    libc: str | None = None,
) -> None:
    release = read_linux_os_release() if os_release is None else os_release
    distro_id = release.get("ID", "").strip().lower() or "unknown"
    if distro_id != SUPPORTED_LINUX_DISTRIBUTION_ID:
        fail(
            "unsupported Cursor CLI Linux distribution (non-ubuntu-linux): "
            f"{distro_id}; supported Linux host is Ubuntu"
        )
    libc_name = (detect_linux_libc() if libc is None else libc).strip().lower() or "unknown"
    if libc_name != SUPPORTED_LINUX_LIBC:
        fail(
            "unsupported Cursor CLI Linux libc (linux-musl): "
            f"{libc_name}; supported Ubuntu host must use glibc"
        )


def current_platform_host_id(
    *,
    system_platform: str | None = None,
    machine: str | None = None,
    linux_os_release: dict[str, str] | None = None,
    linux_libc: str | None = None,
) -> str:
    active_platform = sys.platform if system_platform is None else system_platform
    if active_platform.startswith("linux"):
        require_supported_ubuntu_linux(os_release=linux_os_release, libc=linux_libc)
        host_family = "ubuntu-glibc"
    elif active_platform == "darwin":
        host_family = "macos"
    elif active_platform.startswith(("win", "cygwin", "msys")):
        fail(f"unsupported Cursor CLI host category windows: {active_platform}")
    else:
        fail(f"unsupported Cursor CLI installer platform: {active_platform}")
    active_machine = (os.uname().machine if machine is None else machine).lower()
    if active_machine in {"arm64", "aarch64"}:
        arch = "arm64"
    elif active_machine in {"x86_64", "amd64"}:
        arch = "x64"
    else:
        fail(f"unsupported Cursor CLI host category unsupported-architecture: {active_machine}")
    return f"{host_family}-{arch}"


def current_platform_asset(
    *,
    system_platform: str | None = None,
    machine: str | None = None,
    linux_os_release: dict[str, str] | None = None,
    linux_libc: str | None = None,
) -> tuple[str, str, int]:
    host_id = current_platform_host_id(
        system_platform=system_platform,
        machine=machine,
        linux_os_release=linux_os_release,
        linux_libc=linux_libc,
    )
    return CURSOR_OFFICIAL_ASSETS[VENDOR_ASSET_HOST_MAP[host_id]]


def require_current_host_supported() -> None:
    current_platform_asset()


def official_asset_url(asset_path: str) -> str:
    return f"{CURSOR_RELEASE_BASE_URL}/{asset_path}"


def validate_archive_path(raw_name: str) -> Path:
    if "\x00" in raw_name:
        fail("Cursor artifact contains a NUL byte in a tar path")
    normalized = raw_name.replace("\\", "/")
    if normalized.startswith("//"):
        fail("Cursor artifact contains an unsafe tar path")
    path = PurePosixPath(normalized)
    first = path.parts[0] if path.parts else ""
    if (
        path.is_absolute()
        or not path.parts
        or ":" in first
        or re.fullmatch(r"[A-Za-z]:.*", first) is not None
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        fail("Cursor artifact contains an unsafe tar path")
    return Path(*path.parts)


def read_artifact(source: str) -> bytes:
    if not source.startswith(f"{CURSOR_RELEASE_BASE_URL}/"):
        fail("Cursor software artifact source must be the pinned official release URL")
    request = urllib.request.Request(
        source,
        headers={"User-Agent": f"{PRODUCT_NAME}/{VERSION}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        expected = response.headers.get("Content-Length")
        if expected is not None:
            try:
                expected_size = int(expected)
            except ValueError:
                fail("Cursor software artifact returned an invalid Content-Length")
        else:
            expected_size = None
        blocks: list[bytes] = []
        total = 0
        while True:
            block = response.read(1024 * 1024)
            if not block:
                break
            total += len(block)
            if total > SOFTWARE_ARTIFACT_MAX_BYTES:
                fail("Cursor software artifact exceeds the bounded download limit")
            blocks.append(block)
    content = b"".join(blocks)
    if expected_size is not None and expected_size != len(content):
        fail("Cursor software artifact download length changed while reading")
    return content


def normalize_runtime_path(path: Path) -> Path | None:
    if path == CURSOR_RUNTIME_ROOT:
        return None
    if not path.parts or path.parts[0] != CURSOR_RUNTIME_ROOT.as_posix():
        fail("Cursor artifact contains a member outside dist-package")
    relative = Path(*path.parts[1:])
    if not relative.parts:
        return None
    return relative


def runtime_file_mode(member_mode: int) -> int:
    if member_mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX):
        fail("Cursor artifact contains a runtime member with special mode bits")
    if member_mode & 0o022:
        fail("Cursor artifact contains a group/world-writable runtime member")
    return OWNER_EXEC_MODE if member_mode & 0o111 else OWNER_FILE_MODE


def runtime_tree_digest(files: dict[str, tuple[bytes, int]]) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    total_size = 0
    for name in sorted(files):
        content, mode = files[name]
        total_size += len(content)
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(oct(mode).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\0")
        digest.update(sha256_bytes(content).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest(), total_size, len(files)


def extract_cursor_runtime(archive: bytes) -> dict[str, Any]:
    files: dict[str, tuple[bytes, int]] = {}
    total_size = 0
    with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as tar:
        for member in tar:
            path = validate_archive_path(member.name)
            if member.issym() or member.islnk() or member.isdev() or member.isdir():
                if member.issym() or member.islnk() or member.isdev():
                    fail("Cursor artifact runtime must not contain links or device files")
                normalize_runtime_path(path)
                continue
            if not member.isfile():
                fail("Cursor artifact runtime member must be a regular tar file")
            relative = normalize_runtime_path(path)
            if relative is None:
                fail("Cursor artifact runtime file path is empty")
            relative_name = relative.as_posix()
            if relative_name in files:
                fail("Cursor artifact contains duplicate runtime file paths")
            if member.size > SOFTWARE_ARTIFACT_MAX_BYTES:
                fail("Cursor artifact runtime file exceeds the decompressed size limit")
            mode = runtime_file_mode(member.mode)
            handle = tar.extractfile(member)
            if handle is None:
                fail("Cursor artifact runtime file could not be read")
            content = handle.read(SOFTWARE_ARTIFACT_MAX_BYTES + 1)
            if len(content) > SOFTWARE_ARTIFACT_MAX_BYTES or len(content) != member.size:
                fail("Cursor artifact runtime file size changed while reading")
            total_size += len(content)
            if total_size > SOFTWARE_ARTIFACT_MAX_BYTES:
                fail("Cursor artifact runtime tree exceeds the decompressed size limit")
            files[relative_name] = (content, mode)
    missing = sorted(
        path.as_posix() for path in CURSOR_RUNTIME_REQUIRED_FILES - {Path(name) for name in files}
    )
    if missing:
        fail(f"Cursor artifact runtime tree is missing required files: {missing}")
    runtime_sha256, runtime_size, runtime_file_count = runtime_tree_digest(files)
    entrypoint = files[CURSOR_RUNTIME_ENTRYPOINT.as_posix()][0]
    return {
        "files": files,
        "binary": entrypoint,
        "binary_sha256": sha256_bytes(entrypoint),
        "runtime_tree_sha256": runtime_sha256,
        "runtime_size": runtime_size,
        "runtime_file_count": runtime_file_count,
    }


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def agent_launcher_bytes_for_runtime_dir(runtime_dir: Path) -> bytes:
    script_dir = shell_quote(str(runtime_dir.resolve(strict=False)))
    return (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        'export CURSOR_INVOKED_AS="${0##*/}"\n'
        f"SCRIPT_DIR={script_dir}\n"
        'NODE_BIN="$SCRIPT_DIR/node"\n'
        'if [ -z "${NODE_COMPILE_CACHE:-}" ]; then\n'
        '  if [[ "${OSTYPE:-}" == darwin* ]]; then\n'
        '    export NODE_COMPILE_CACHE="$HOME/Library/Caches/cursor-compile-cache"\n'
        "  else\n"
        '    export NODE_COMPILE_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/cursor-compile-cache"\n'
        "  fi\n"
        "fi\n"
        "should_skip_system_ca() {\n"
        '  case "${AGENT_CLI_CREDENTIAL_STORE:-}" in\n'
        "    file) return 0 ;;\n"
        "  esac\n"
        "  return 1\n"
        "}\n"
        'if ! should_skip_system_ca && "$NODE_BIN" --use-system-ca --version >/dev/null 2>&1; then\n'
        '  exec -a "$0" "$NODE_BIN" --use-system-ca "$SCRIPT_DIR/index.js" "$@"\n'
        "fi\n"
        'exec -a "$0" "$NODE_BIN" "$SCRIPT_DIR/index.js" "$@"\n'
    ).encode("utf-8")


def managed_agent_launcher_bytes(target: Path) -> bytes:
    return agent_launcher_bytes_for_runtime_dir(software_version_dir(target))


def atomic_write_with_mode(path: Path, content: bytes, mode: int) -> None:
    ensure_real_directory_path(path.parent, "software file parent")
    temporary = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        try:
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written == 0:
                    fail(f"software write made no progress: {path}")
                view = view[written:]
            os.fchmod(descriptor, mode)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, path)
        fsync_existing_parent(path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise


def atomic_write(path: Path, content: bytes) -> None:
    atomic_write_with_mode(path, content, OWNER_FILE_MODE)


def atomic_write_executable(path: Path, content: bytes) -> None:
    atomic_write_with_mode(path, content, OWNER_EXEC_MODE)


def ensure_real_directory_path(path: Path, label: str) -> None:
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail(f"{label} must be a real directory")
        uid = current_user_id()
        if uid is not None and info.st_uid != uid:
            fail(f"{label} must be owned by the current user")
        if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
            fail(f"{label} must have mode 0700")
        return
    missing: list[Path] = []
    current = path
    while not (current.exists() or current.is_symlink()):
        missing.append(current)
        parent = current.parent
        if parent == current:
            fail(f"{label} has no existing owner-private parent")
        current = parent
    require_owner_private_directory(current, f"{label} parent")
    for directory in reversed(missing):
        try:
            directory.mkdir(mode=OWNER_DIRECTORY_MODE)
        except FileExistsError:
            fail(f"{label} appeared concurrently")
        directory.chmod(OWNER_DIRECTORY_MODE)
        require_owner_private_directory(directory, label)
        fsync_directory(directory.parent)


def ensure_private_directory_chain(root: Path, relative_parent: Path) -> None:
    current = root
    if relative_parent == Path("."):
        return
    uid = current_user_id()
    for part in relative_parent.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                fail(f"Cursor runtime directory path is unsafe: {current}")
            if uid is not None and info.st_uid != uid:
                fail(f"Cursor runtime directory must be owned by the current user: {current}")
            if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
                fail(f"Cursor runtime directory must have mode 0700: {current}")
            continue
        current.mkdir(mode=OWNER_DIRECTORY_MODE)
        current.chmod(OWNER_DIRECTORY_MODE)


def write_cursor_runtime_tree(root: Path, files: dict[str, tuple[bytes, int]]) -> None:
    for relative_name in sorted(files):
        relative = Path(relative_name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            fail(f"Cursor runtime path is unsafe: {relative_name}")
        content, mode = files[relative_name]
        if mode not in {OWNER_FILE_MODE, OWNER_EXEC_MODE}:
            fail("Cursor runtime file mode must be normalized to 0600 or 0700")
        ensure_private_directory_chain(root, relative.parent)
        atomic_write_with_mode(root / relative, content, mode)


def software_directory_mode_drift(path: Path, label: str) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a real directory")
    if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
        return f"{label}:mode"
    return None


def software_stamp(
    target: Path,
    *,
    asset_path: str,
    artifact_sha256: str,
    artifact_size: int,
    binary_sha256: str,
    entrypoint_sha256: str,
    runtime_tree_sha256: str,
    runtime_size: int,
    runtime_file_count: int,
    source_url: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "canonical_target": str(target.resolve(strict=False)),
        "command": CURSOR_COMMAND,
        "version": CURSOR_VERSION,
        "official_source": source_url,
        "asset_path": asset_path,
        "artifact_sha256": artifact_sha256,
        "artifact_size": artifact_size,
        "binary_sha256": binary_sha256,
        "entrypoint_sha256": entrypoint_sha256,
        "runtime_tree_sha256": runtime_tree_sha256,
        "runtime_size": runtime_size,
        "runtime_file_count": runtime_file_count,
        "installed_at": int(time.time()),
    }


def load_software_stamp(
    target: Path, *, repairable_identity: bool = False
) -> dict[str, Any] | None:
    path = software_stamp_path(target)
    if not path.exists() and not path.is_symlink():
        return None
    info = require_regular_file(path, f"Cursor software stamp {path}", max_bytes=METADATA_MAX_BYTES)
    if stat.S_IMODE(info.st_mode) != OWNER_FILE_MODE:
        if repairable_identity:
            return None
        fail("Cursor software stamp must have mode 0600")
    try:
        stamp = load_json_object(path, f"Cursor software stamp {path}")
        required = {
            "schema_version",
            "product_name",
            "build_version",
            "canonical_target",
            "command",
            "version",
            "official_source",
            "asset_path",
            "artifact_sha256",
            "artifact_size",
            "binary_sha256",
            "entrypoint_sha256",
            "runtime_tree_sha256",
            "runtime_size",
            "runtime_file_count",
            "installed_at",
        }
        require_exact_keys(stamp, required, "Cursor software stamp")
        if (
            stamp["schema_version"] != 1
            or stamp["product_name"] != PRODUCT_NAME
            or stamp["canonical_target"] != str(target.resolve(strict=False))
            or stamp["command"] != CURSOR_COMMAND
        ):
            fail("Cursor software stamp identity is invalid")
        for key in ("artifact_sha256", "binary_sha256", "entrypoint_sha256", "runtime_tree_sha256"):
            if not isinstance(stamp[key], str) or not re.fullmatch(r"[0-9a-f]{64}", stamp[key]):
                fail(f"Cursor software stamp {key} must be a lowercase SHA-256 digest")
        if not isinstance(stamp["artifact_size"], int) or stamp["artifact_size"] <= 0:
            fail("Cursor software stamp artifact_size must be a positive integer")
        if not isinstance(stamp["runtime_size"], int) or stamp["runtime_size"] <= 0:
            fail("Cursor software stamp runtime_size must be a positive integer")
        if not isinstance(stamp["runtime_file_count"], int) or stamp["runtime_file_count"] <= 0:
            fail("Cursor software stamp runtime_file_count must be a positive integer")
        if not isinstance(stamp["installed_at"], int):
            fail("Cursor software stamp installed_at must be an integer")
    except CursorSetupError:
        if repairable_identity:
            return None
        raise
    return stamp


def read_optional_software_file(path: Path, label: str) -> bytes | None:
    if not path.exists() and not path.is_symlink():
        return None
    return read_regular_file(path, label, max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES)


def snapshot_optional_software_file(path: Path, label: str) -> tuple[bytes | None, int | None]:
    if not path.exists() and not path.is_symlink():
        return None, None
    content = read_regular_file(path, label, max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES)
    info = require_regular_file(path, label, max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES)
    return content, stat.S_IMODE(info.st_mode)


def runtime_tree_identity_from_disk(root: Path) -> dict[str, Any] | None:
    if not root.exists() and not root.is_symlink():
        return None
    info = root.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail("Cursor runtime tree must be a real directory")
    files: dict[str, tuple[bytes, int]] = {}
    mode_drift = stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        entry_info = path.lstat()
        if relative.parts and Path(relative.parts[0]) in CURSOR_RUNTIME_EPHEMERAL_ROOTS:
            if stat.S_ISLNK(entry_info.st_mode):
                fail(f"Cursor runtime ephemeral state must not be a symlink: {relative.as_posix()}")
            if stat.S_ISREG(entry_info.st_mode):
                if entry_info.st_nlink != 1:
                    fail(
                        "Cursor runtime ephemeral file must not have hard-link aliases: "
                        f"{relative.as_posix()}"
                    )
                require_bounded_size(
                    entry_info,
                    f"Cursor runtime ephemeral file {relative.as_posix()}",
                    METADATA_MAX_BYTES,
                )
                continue
            if stat.S_ISDIR(entry_info.st_mode):
                continue
            fail(f"Cursor runtime ephemeral state is unsafe: {relative.as_posix()}")
        if stat.S_ISLNK(entry_info.st_mode):
            fail(f"Cursor runtime tree must not contain symlinks: {relative.as_posix()}")
        if stat.S_ISDIR(entry_info.st_mode):
            if stat.S_IMODE(entry_info.st_mode) != OWNER_DIRECTORY_MODE:
                mode_drift = True
            continue
        if not stat.S_ISREG(entry_info.st_mode):
            fail(f"Cursor runtime tree must contain only regular files: {relative.as_posix()}")
        if entry_info.st_nlink != 1:
            fail(f"Cursor runtime file must not have hard-link aliases: {relative.as_posix()}")
        mode = stat.S_IMODE(entry_info.st_mode)
        if mode not in {OWNER_FILE_MODE, OWNER_EXEC_MODE}:
            mode_drift = True
        content = read_regular_file(
            path,
            f"Cursor runtime file {relative.as_posix()}",
            max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES,
        )
        files[relative.as_posix()] = (content, mode)
    missing = sorted(
        path.as_posix() for path in CURSOR_RUNTIME_REQUIRED_FILES - {Path(name) for name in files}
    )
    if missing:
        return {
            "sha256": None,
            "size": None,
            "file_count": len(files),
            "mode_drift": mode_drift,
            "missing": missing,
        }
    digest, size, file_count = runtime_tree_digest(files)
    return {
        "sha256": digest,
        "size": size,
        "file_count": file_count,
        "mode_drift": mode_drift,
        "missing": [],
    }


def snapshot_runtime_payload(root: Path) -> dict[str, tuple[bytes, int]]:
    require_owner_private_directory(root, "Cursor runtime tree")
    files: dict[str, tuple[bytes, int]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        info = path.lstat()
        if relative.parts and Path(relative.parts[0]) in CURSOR_RUNTIME_EPHEMERAL_ROOTS:
            continue
        if stat.S_ISLNK(info.st_mode):
            fail(f"Cursor runtime tree must not contain symlinks: {relative.as_posix()}")
        if stat.S_ISDIR(info.st_mode):
            if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
                fail(f"Cursor runtime directory must have mode 0700: {relative.as_posix()}")
            continue
        if not stat.S_ISREG(info.st_mode):
            fail(f"Cursor runtime tree must contain only regular files: {relative.as_posix()}")
        if info.st_nlink != 1:
            fail(f"Cursor runtime file must not have hard-link aliases: {relative.as_posix()}")
        mode = stat.S_IMODE(info.st_mode)
        if mode not in {OWNER_FILE_MODE, OWNER_EXEC_MODE}:
            fail(f"Cursor runtime file has unsafe mode: {relative.as_posix()}")
        files[relative.as_posix()] = (
            read_regular_file(
                path,
                f"Cursor launch payload file {relative.as_posix()}",
                max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES,
            ),
            mode,
        )
    missing = sorted(
        path.as_posix() for path in CURSOR_RUNTIME_REQUIRED_FILES - {Path(name) for name in files}
    )
    if missing:
        fail(f"Cursor launch payload is missing required files: {missing}")
    return files


def path_tree_signature(root: Path, label: str) -> str | None:
    if not root.exists() and not root.is_symlink():
        return None
    info = root.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a real directory")
    digest = hashlib.sha256()
    digest.update(b"dir\0.\0")
    digest.update(oct(stat.S_IMODE(info.st_mode)).encode("ascii"))
    digest.update(b"\0")
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        entry_info = path.lstat()
        if stat.S_ISLNK(entry_info.st_mode):
            fail(f"{label} must not contain symlinks: {relative}")
        if stat.S_ISDIR(entry_info.st_mode):
            digest.update(b"dir\0")
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(oct(stat.S_IMODE(entry_info.st_mode)).encode("ascii"))
            digest.update(b"\0")
            continue
        if not stat.S_ISREG(entry_info.st_mode):
            fail(f"{label} must contain only regular files: {relative}")
        if entry_info.st_nlink != 1:
            fail(f"{label} file must not have hard-link aliases: {relative}")
        content = read_regular_file(
            path, f"{label} file {relative}", max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES
        )
        digest.update(b"file\0")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(oct(stat.S_IMODE(entry_info.st_mode)).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(len(content)).encode("ascii"))
        digest.update(b"\0")
        digest.update(sha256_bytes(content).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def software_file_mode_is(path: Path, mode: int) -> bool:
    info = path.lstat()
    return not stat.S_ISLNK(info.st_mode) and stat.S_IMODE(info.st_mode) == mode


def remove_empty_directory_if_created(path: Path, existed_before: bool) -> None:
    if existed_before:
        return
    with contextlib.suppress(FileNotFoundError, OSError):
        path.rmdir()
        fsync_directory(path.parent)


def remove_empty_directory(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError, OSError):
        path.rmdir()
        fsync_directory(path.parent)


def remove_software_path(path: Path) -> None:
    if not (path.exists() or path.is_symlink()):
        return
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()
    fsync_directory(path.parent)


def optional_software_file_matches(path: Path, content: bytes | None, mode: int | None) -> bool:
    if content is None:
        return not (path.exists() or path.is_symlink())
    if not (path.exists() or path.is_symlink()):
        return False
    try:
        current = read_regular_file(
            path, f"Cursor software file {path}", max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES
        )
        info = require_regular_file(
            path, f"Cursor software file {path}", max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES
        )
    except CursorSetupError:
        return False
    return current == content and stat.S_IMODE(info.st_mode) == (mode or OWNER_FILE_MODE)


def restore_optional_software_file(path: Path, content: bytes | None, mode: int | None) -> None:
    if content is None:
        remove_software_path(path)
    else:
        atomic_write_with_mode(path, content, mode or OWNER_FILE_MODE)


def software_file_object_identity(path: Path, label: str) -> dict[str, Any] | None:
    if not (path.exists() or path.is_symlink()):
        return None
    info = require_regular_file(path, label, max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES)
    content = read_regular_file(path, label, max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES)
    return {
        "device": info.st_dev,
        "inode": info.st_ino,
        "mode": stat.S_IMODE(info.st_mode),
        "mtime_ns": info.st_mtime_ns,
        "sha256": sha256_bytes(content),
        "size": len(content),
    }


def software_file_object_matches(path: Path, identity: dict[str, Any] | None, label: str) -> bool:
    try:
        return software_file_object_identity(path, label) == identity
    except CursorSetupError:
        return False


def software_tree_object_identity(root: Path, label: str) -> list[dict[str, Any]] | None:
    if not (root.exists() or root.is_symlink()):
        return None
    info = root.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        fail(f"{label} must be a real directory")
    records: list[dict[str, Any]] = [
        {
            "type": "dir",
            "path": ".",
            "device": info.st_dev,
            "inode": info.st_ino,
            "mode": stat.S_IMODE(info.st_mode),
            "mtime_ns": info.st_mtime_ns,
        }
    ]
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        entry_info = path.lstat()
        if stat.S_ISLNK(entry_info.st_mode):
            fail(f"{label} must not contain symlinks: {relative}")
        if stat.S_ISDIR(entry_info.st_mode):
            records.append(
                {
                    "type": "dir",
                    "path": relative,
                    "device": entry_info.st_dev,
                    "inode": entry_info.st_ino,
                    "mode": stat.S_IMODE(entry_info.st_mode),
                    "mtime_ns": entry_info.st_mtime_ns,
                }
            )
            continue
        if not stat.S_ISREG(entry_info.st_mode):
            fail(f"{label} must contain only regular files: {relative}")
        if entry_info.st_nlink != 1:
            fail(f"{label} file must not have hard-link aliases: {relative}")
        content = read_regular_file(
            path, f"{label} file {relative}", max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES
        )
        records.append(
            {
                "type": "file",
                "path": relative,
                "device": entry_info.st_dev,
                "inode": entry_info.st_ino,
                "mode": stat.S_IMODE(entry_info.st_mode),
                "mtime_ns": entry_info.st_mtime_ns,
                "sha256": sha256_bytes(content),
                "size": len(content),
            }
        )
    return records


def software_tree_object_matches(
    path: Path, identity: list[dict[str, Any]] | None, label: str
) -> bool:
    try:
        return software_tree_object_identity(path, label) == identity
    except CursorSetupError:
        return False


def software_status(target: Path) -> dict[str, Any]:
    return with_read_bootstrap_target(target, _software_status_locked)


def _software_status_locked(target: Path) -> dict[str, Any]:
    if not target.exists() and not target.is_symlink():
        return {
            "schema_version": 1,
            "command": "software-status",
            "target": str(target.resolve(strict=False)),
            "installed": False,
            "current": False,
            "present": False,
            "presence": [],
            "version": None,
            "expected_version": CURSOR_VERSION,
            "managed_command": str(managed_agent_path(target).resolve(strict=False)),
            "drift": [],
            "cleanup_pending": False,
            "cleanup": None,
        }
    resolve_target(str(target))
    cleanup = cleanup_pending_result(target)
    binary = managed_agent_path(target)
    version_binary = software_tree_binary(target)
    installed = False
    drift: list[str] = target_safety_findings(target)
    runtime_findings = target_local_parent_findings(target, runtime_parent_directories(target))
    drift.extend(runtime_findings)
    presence = [] if runtime_findings else software_presence(target)
    if runtime_findings:
        return {
            "schema_version": 1,
            "command": "software-status",
            "target": str(target.resolve(strict=False)),
            "installed": False,
            "current": False,
            "present": False,
            "presence": presence,
            "version": None,
            "expected_version": CURSOR_VERSION,
            "managed_command": str(binary),
            "drift": drift,
            **cleanup,
        }
    directory_mode_drift = False
    for directory, label in (
        (software_container(target), ".nddev-software"),
        (software_root(target), ".nddev-software/cursor-cli"),
        (software_root(target) / "versions", ".nddev-software/cursor-cli/versions"),
        (
            software_version_dir(target),
            ".nddev-software/cursor-cli/versions/2026.07.23-e383d2b",
        ),
    ):
        directory_drift = software_directory_mode_drift(directory, label)
        if directory_drift is not None:
            drift.append(directory_drift)
            directory_mode_drift = True
    transaction_active = False
    marker_path = software_transaction_path(target)
    if marker_path.exists() or marker_path.is_symlink():
        marker_info = require_regular_file(
            marker_path,
            f"Cursor software transaction marker {marker_path}",
            max_bytes=METADATA_MAX_BYTES,
        )
        transaction_active = True
        drift.append("software-transaction")
        if stat.S_IMODE(marker_info.st_mode) != OWNER_FILE_MODE:
            drift.append("software-transaction:mode")
    stamp_path = software_stamp_path(target)
    if stamp_path.exists() or stamp_path.is_symlink():
        stamp_info = require_regular_file(
            stamp_path, f"Cursor software stamp {stamp_path}", max_bytes=METADATA_MAX_BYTES
        )
        if stat.S_IMODE(stamp_info.st_mode) != OWNER_FILE_MODE:
            drift.append("software-stamp:mode")
    stamp = load_software_stamp(target, repairable_identity=True)
    if stamp is None:
        for partial_file, label in (
            (binary, "bin/agent"),
            (version_binary, ".nddev-software/cursor-cli/versions/2026.07.23-e383d2b/cursor-agent"),
        ):
            if partial_file.exists() or partial_file.is_symlink():
                read_optional_software_file(
                    partial_file, f"Cursor partial software file {partial_file}"
                )
                if not software_file_mode_is(partial_file, OWNER_EXEC_MODE):
                    drift.append(f"{label}:mode")
        if presence:
            drift.append("software-stamp")
    else:
        binary_content = read_optional_software_file(binary, f"Cursor managed launcher {binary}")
        version_content = read_optional_software_file(
            version_binary, f"Cursor managed version binary {version_binary}"
        )
        runtime_identity = runtime_tree_identity_from_disk(software_version_dir(target))
        binary_digest_ok = (
            binary_content is not None
            and sha256_bytes(binary_content) == stamp["entrypoint_sha256"]
        )
        version_digest_ok = (
            version_content is not None and sha256_bytes(version_content) == stamp["binary_sha256"]
        )
        runtime_digest_ok = (
            runtime_identity is not None
            and runtime_identity["sha256"] == stamp["runtime_tree_sha256"]
            and runtime_identity["size"] == stamp["runtime_size"]
            and runtime_identity["file_count"] == stamp["runtime_file_count"]
            and not runtime_identity["missing"]
        )
        binary_mode_ok = binary_content is not None and software_file_mode_is(
            binary, OWNER_EXEC_MODE
        )
        version_mode_ok = version_content is not None and software_file_mode_is(
            version_binary, OWNER_EXEC_MODE
        )
        if not binary_digest_ok:
            drift.append("bin/agent")
        elif not binary_mode_ok:
            drift.append("bin/agent:mode")
        if not version_digest_ok:
            drift.append(".nddev-software/cursor-cli/versions/2026.07.23-e383d2b/cursor-agent")
        elif not version_mode_ok:
            drift.append(".nddev-software/cursor-cli/versions/2026.07.23-e383d2b/cursor-agent:mode")
        if not runtime_digest_ok:
            drift.append(".nddev-software/cursor-cli/versions/2026.07.23-e383d2b:runtime")
        elif runtime_identity is not None and runtime_identity["mode_drift"]:
            drift.append(".nddev-software/cursor-cli/versions/2026.07.23-e383d2b:mode")
        installed = (
            binary_digest_ok
            and version_digest_ok
            and runtime_digest_ok
            and binary_mode_ok
            and version_mode_ok
            and not directory_mode_drift
            and not transaction_active
        )
        asset_path, artifact_sha256, artifact_size = current_platform_asset()
        expected = {
            "build_version": VERSION,
            "version": CURSOR_VERSION,
            "official_source": official_asset_url(asset_path),
            "asset_path": asset_path,
            "artifact_sha256": artifact_sha256,
            "artifact_size": artifact_size,
        }
        for key, value in expected.items():
            if stamp[key] != value:
                drift.append(key)
    return {
        "schema_version": 1,
        "command": "software-status",
        "target": str(target.resolve(strict=False)),
        "installed": installed,
        "current": installed and not drift,
        "present": bool(presence),
        "presence": presence,
        "version": None if stamp is None else stamp["version"],
        "expected_version": CURSOR_VERSION,
        "managed_command": str(binary.resolve(strict=False)),
        "drift": drift,
        **cleanup,
    }


def prepare_cursor_artifact() -> dict[str, Any]:
    asset_path, expected_sha, expected_size = current_platform_asset()
    source_url = official_asset_url(asset_path)
    archive = read_artifact(source_url)
    artifact_sha = sha256_bytes(archive)
    if artifact_sha != expected_sha or len(archive) != expected_size:
        fail("official Cursor artifact digest or size mismatch")
    runtime = extract_cursor_runtime(archive)
    return {
        "asset_path": asset_path,
        "artifact_sha256": artifact_sha,
        "artifact_size": len(archive),
        **runtime,
        "source_url": source_url,
    }


def install_cursor_cli(target: Path, command: str) -> dict[str, Any]:
    if command not in {"install-cli", "update-cli"}:
        fail(f"unsupported Cursor software command: {command}")
    return with_mutation_bootstrap_target(target, _install_cursor_cli_locked, command)


def _install_cursor_cli_locked(target: Path, command: str) -> dict[str, Any]:
    with exact_target_lifecycle_guard(target, f"software {command}"):
        before_target_exists = target.exists() or target.is_symlink()
        if command == "update-cli" and not before_target_exists:
            fail("update-cli requires existing target-owned Cursor CLI software presence")
        created_target = prepare_lifecycle_target(target, create_missing=command == "install-cli")
        with target_lock(target, cleanup_empty_target_on_error=created_target):
            status = _software_status_locked(target)
            if command == "install-cli" and status["present"]:
                fail(
                    "install-cli requires absent target-owned Cursor CLI software presence; "
                    "use update-cli for existing or partial state"
                )
            if command == "update-cli" and not status["present"]:
                fail("update-cli requires existing target-owned Cursor CLI software presence")
            if command == "update-cli" and status["current"]:
                return {
                    "schema_version": 1,
                    "command": command,
                    "operation": "current",
                    "target": str(target.resolve(strict=False)),
                    "version": CURSOR_VERSION,
                    "current": True,
                    "changed": [],
                    "managed_command": str(managed_agent_path(target).resolve(strict=False)),
                }
            artifact = prepare_cursor_artifact()
            container = software_container(target)
            root = software_root(target)
            versions = root / "versions"
            version_dir = software_version_dir(target)
            binary_path = managed_agent_path(target)
            bin_dir = binary_path.parent
            stamp_path = software_stamp_path(target)
            marker_path = software_transaction_path(target)
            before_container_exists = container.exists() or container.is_symlink()
            before_root_exists = root.exists() or root.is_symlink()
            before_versions_exists = versions.exists() or versions.is_symlink()
            before_bin_dir_exists = bin_dir.exists() or bin_dir.is_symlink()
            before_version_identity = software_tree_object_identity(
                version_dir, "Cursor software version tree"
            )
            before_binary_identity = software_file_object_identity(
                binary_path, f"Cursor managed binary {binary_path}"
            )
            before_stamp_identity = software_file_object_identity(
                stamp_path, f"Cursor software stamp {stamp_path}"
            )
            before_marker_identity = software_file_object_identity(
                marker_path, f"Cursor software transaction marker {marker_path}"
            )
            entrypoint = managed_agent_launcher_bytes(target)
            stamp_bytes = canonical_json(
                software_stamp(
                    target,
                    asset_path=artifact["asset_path"],
                    artifact_sha256=artifact["artifact_sha256"],
                    artifact_size=artifact["artifact_size"],
                    binary_sha256=artifact["binary_sha256"],
                    entrypoint_sha256=sha256_bytes(entrypoint),
                    runtime_tree_sha256=artifact["runtime_tree_sha256"],
                    runtime_size=artifact["runtime_size"],
                    runtime_file_count=artifact["runtime_file_count"],
                    source_url=artifact["source_url"],
                )
            )
            before_stamp_bytes = read_optional_software_file(
                stamp_path, f"Cursor software stamp {stamp_path}"
            )
            changed = [
                "bin/agent",
                ".nddev-software/cursor-cli/versions/2026.07.23-e383d2b",
            ]
            if before_stamp_bytes != stamp_bytes:
                changed.append(f".nddev-software/cursor-cli/{SOFTWARE_STAMP_NAME}")
            staging: Path | None = None
            rollback_parent: Path | None = None
            cleanup_pending = False
            rollback_version: Path | None = None
            rollback_binary: Path | None = None
            rollback_stamp: Path | None = None
            rollback_marker: Path | None = None

            def software_matches_before() -> bool:
                return (
                    software_tree_object_matches(
                        version_dir, before_version_identity, "Cursor software version tree"
                    )
                    and software_file_object_matches(
                        binary_path,
                        before_binary_identity,
                        f"Cursor managed binary {binary_path}",
                    )
                    and software_file_object_matches(
                        stamp_path,
                        before_stamp_identity,
                        f"Cursor software stamp {stamp_path}",
                    )
                    and software_file_object_matches(
                        marker_path,
                        before_marker_identity,
                        f"Cursor software transaction marker {marker_path}",
                    )
                )

            try:
                ensure_real_directory_path(container, "Cursor software container")
                ensure_real_directory_path(root, "Cursor software root")
                ensure_real_directory_path(versions, "Cursor software versions directory")
                rollback_parent = Path(tempfile.mkdtemp(prefix=".rollback-", dir=str(versions)))
                rollback_parent.chmod(OWNER_DIRECTORY_MODE)
                fsync_directory(versions)
                if before_marker_identity is not None:
                    rollback_marker = rollback_parent / SOFTWARE_TRANSACTION_NAME
                    os.rename(marker_path, rollback_marker)
                    fsync_existing_parent(marker_path)
                write_software_transaction_marker(target, command)
                staging = Path(tempfile.mkdtemp(prefix=".stage-", dir=str(versions)))
                staging.chmod(OWNER_DIRECTORY_MODE)
                fsync_directory(versions)
                write_cursor_runtime_tree(staging, artifact["files"])
                if before_version_identity is not None:
                    rollback_version = rollback_parent / CURSOR_VERSION
                    os.rename(version_dir, rollback_version)
                    fsync_directory(versions)
                staging.rename(version_dir)
                fsync_directory(versions)
                if before_binary_identity is not None:
                    rollback_binary = rollback_parent / "agent"
                    os.rename(binary_path, rollback_binary)
                    fsync_existing_parent(binary_path)
                atomic_write_executable(binary_path, entrypoint)
                if before_stamp_identity is not None:
                    rollback_stamp = rollback_parent / SOFTWARE_STAMP_NAME
                    os.rename(stamp_path, rollback_stamp)
                    fsync_existing_parent(stamp_path)
                atomic_write(stamp_path, stamp_bytes)
                clear_software_transaction_marker(target)
                final_status = _software_status_locked(target)
                if not final_status["installed"]:
                    fail(
                        "Cursor software install did not produce a structurally complete "
                        "target-owned CLI"
                    )
                if not final_status["current"]:
                    fail("Cursor software install did not produce the current pinned CLI identity")
            except BaseException:
                rollback_exact = False
                for _ in range(4):
                    try:
                        if not software_tree_object_matches(
                            version_dir, before_version_identity, "Cursor software version tree"
                        ):
                            remove_software_path(version_dir)
                            if rollback_version is not None and (
                                rollback_version.exists() or rollback_version.is_symlink()
                            ):
                                os.rename(rollback_version, version_dir)
                                fsync_directory(versions)
                        if not software_file_object_matches(
                            binary_path,
                            before_binary_identity,
                            f"Cursor managed binary {binary_path}",
                        ):
                            remove_software_path(binary_path)
                            if rollback_binary is not None and (
                                rollback_binary.exists() or rollback_binary.is_symlink()
                            ):
                                ensure_real_directory_path(
                                    binary_path.parent, "Cursor managed command directory"
                                )
                                os.rename(rollback_binary, binary_path)
                                fsync_existing_parent(binary_path)
                        if not software_file_object_matches(
                            stamp_path,
                            before_stamp_identity,
                            f"Cursor software stamp {stamp_path}",
                        ):
                            remove_software_path(stamp_path)
                            if rollback_stamp is not None and (
                                rollback_stamp.exists() or rollback_stamp.is_symlink()
                            ):
                                os.rename(rollback_stamp, stamp_path)
                                fsync_existing_parent(stamp_path)
                        if not software_file_object_matches(
                            marker_path,
                            before_marker_identity,
                            f"Cursor software transaction marker {marker_path}",
                        ):
                            remove_software_path(marker_path)
                            if rollback_marker is not None and (
                                rollback_marker.exists() or rollback_marker.is_symlink()
                            ):
                                os.rename(rollback_marker, marker_path)
                                fsync_existing_parent(marker_path)
                        if software_matches_before():
                            rollback_exact = True
                            break
                    except BaseException:
                        pass
                if staging is not None:
                    with contextlib.suppress(FileNotFoundError):
                        shutil.rmtree(staging)
                        fsync_directory(versions)
                if rollback_parent is not None:
                    with contextlib.suppress(FileNotFoundError):
                        shutil.rmtree(rollback_parent)
                        fsync_directory(versions)
                if rollback_exact:
                    remove_empty_directory_if_created(bin_dir, before_bin_dir_exists)
                    remove_empty_directory_if_created(versions, before_versions_exists)
                    remove_empty_directory_if_created(root, before_root_exists)
                    remove_empty_directory_if_created(container, before_container_exists)
                    remove_empty_directory_if_created(target, before_target_exists)
                raise
            if rollback_parent is not None:
                cleanup_pending = publish_cleanup_pending(
                    target, [(rollback_parent, "software-install-rollback")]
                )
                rollback_parent = None
            final_status = _software_status_locked(target)
            return {
                "schema_version": 1,
                "command": command,
                "operation": "install" if command == "install-cli" else "update",
                "target": str(target.resolve(strict=False)),
                "version": CURSOR_VERSION,
                "current": final_status["current"],
                "changed": changed,
                "asset_path": artifact["asset_path"],
                "artifact_sha256": artifact["artifact_sha256"],
                "binary_sha256": artifact["binary_sha256"],
                "entrypoint_sha256": sha256_bytes(entrypoint),
                "runtime_tree_sha256": artifact["runtime_tree_sha256"],
                "runtime_file_count": artifact["runtime_file_count"],
                "runtime_size": artifact["runtime_size"],
                "managed_command": str(binary_path.resolve(strict=False)),
                "cleanup_pending": cleanup_pending,
            }


def software_tree_matches(path: Path, signature: str | None, label: str) -> bool:
    try:
        return path_tree_signature(path, label) == signature
    except CursorSetupError:
        return False


def cleanup_software_remove_empty_parents(target: Path) -> None:
    remove_empty_directory(launch_images_root(target))
    remove_empty_directory(software_version_dir(target))
    remove_empty_directory(software_root(target) / "versions")
    remove_empty_directory(software_root(target))
    remove_empty_directory(software_container(target))
    remove_empty_directory(managed_agent_path(target).parent)


def remove_cursor_cli(target: Path) -> dict[str, Any]:
    return with_mutation_bootstrap_target(target, _remove_cursor_cli_locked)


def _remove_cursor_cli_locked(target: Path) -> dict[str, Any]:
    with exact_target_lifecycle_guard(target, "software remove-cli"):
        if not target.exists() and not target.is_symlink():
            return {
                "schema_version": 1,
                "command": "remove-cli",
                "operation": "absent",
                "target": str(target.resolve(strict=False)),
                "current": False,
                "present": False,
                "changed": [],
                "managed_command": str(managed_agent_path(target).resolve(strict=False)),
            }
        prepare_lifecycle_target(target, create_missing=False)
        with target_lock(target):
            initial_status = _software_status_locked(target)
            initial_presence = list(initial_status["presence"])
            if not initial_presence:
                return {
                    "schema_version": 1,
                    "command": "remove-cli",
                    "operation": "absent",
                    "target": str(target.resolve(strict=False)),
                    "current": False,
                    "present": False,
                    "changed": [],
                    "managed_command": str(managed_agent_path(target).resolve(strict=False)),
                }

            container = software_container(target)
            root = software_root(target)
            versions = root / "versions"
            version_dir = software_version_dir(target)
            launch_root = launch_images_root(target)
            binary_path = managed_agent_path(target)
            stamp_path = software_stamp_path(target)
            marker_path = software_transaction_path(target)
            before_container_exists = container.exists() or container.is_symlink()
            before_root_exists = root.exists() or root.is_symlink()
            before_versions_exists = versions.exists() or versions.is_symlink()
            before_bin_dir_exists = binary_path.parent.exists() or binary_path.parent.is_symlink()
            before_version_identity = software_tree_object_identity(
                version_dir, "Cursor software version tree"
            )
            before_launch_identity = software_tree_object_identity(
                launch_root, "Cursor launch images tree"
            )
            before_binary_identity = software_file_object_identity(
                binary_path, f"Cursor managed binary {binary_path}"
            )
            before_stamp_identity = software_file_object_identity(
                stamp_path, f"Cursor software stamp {stamp_path}"
            )
            before_marker_identity = software_file_object_identity(
                marker_path, f"Cursor software transaction marker {marker_path}"
            )
            rollback_parent: Path | None = None
            cleanup_pending = False
            rollback_version: Path | None = None
            rollback_launch: Path | None = None
            rollback_binary: Path | None = None
            rollback_stamp: Path | None = None
            rollback_marker: Path | None = None
            final_status: dict[str, Any] | None = None

            def matches_before() -> bool:
                return (
                    software_tree_object_matches(
                        version_dir, before_version_identity, "Cursor software version tree"
                    )
                    and software_tree_object_matches(
                        launch_root, before_launch_identity, "Cursor launch images tree"
                    )
                    and software_file_object_matches(
                        binary_path, before_binary_identity, f"Cursor managed binary {binary_path}"
                    )
                    and software_file_object_matches(
                        stamp_path, before_stamp_identity, f"Cursor software stamp {stamp_path}"
                    )
                    and software_file_object_matches(
                        marker_path,
                        before_marker_identity,
                        f"Cursor software transaction marker {marker_path}",
                    )
                )

            try:
                ensure_real_directory_path(container, "Cursor software container")
                ensure_real_directory_path(root, "Cursor software root")
                rollback_root = ensure_control_root(target)
                rollback_parent = Path(
                    tempfile.mkdtemp(prefix=SOFTWARE_REMOVE_ROLLBACK_PREFIX, dir=str(rollback_root))
                )
                rollback_parent.chmod(OWNER_DIRECTORY_MODE)
                fsync_directory(rollback_root)
                if before_version_identity is not None:
                    ensure_real_directory_path(versions, "Cursor software versions directory")
                    rollback_version = rollback_parent / "version"
                    os.rename(version_dir, rollback_version)
                    fsync_directory(versions)
                if before_launch_identity is not None:
                    rollback_launch = rollback_parent / LAUNCH_IMAGES_NAME
                    os.rename(launch_root, rollback_launch)
                    fsync_directory(root)
                if before_binary_identity is not None:
                    rollback_binary = rollback_parent / "agent"
                    os.rename(binary_path, rollback_binary)
                    fsync_existing_parent(binary_path)
                if before_stamp_identity is not None:
                    rollback_stamp = rollback_parent / SOFTWARE_STAMP_NAME
                    os.rename(stamp_path, rollback_stamp)
                    fsync_existing_parent(stamp_path)
                if before_marker_identity is not None:
                    rollback_marker = rollback_parent / SOFTWARE_TRANSACTION_NAME
                    os.rename(marker_path, rollback_marker)
                    fsync_existing_parent(marker_path)
                write_software_transaction_marker(target, "remove-cli")
                clear_software_transaction_marker(target)
                if (
                    (version_dir.exists() or version_dir.is_symlink())
                    or (launch_root.exists() or launch_root.is_symlink())
                    or (binary_path.exists() or binary_path.is_symlink())
                    or (stamp_path.exists() or stamp_path.is_symlink())
                    or (marker_path.exists() or marker_path.is_symlink())
                ):
                    fail("remove-cli software tree postcondition failed")
                final_status = _software_status_locked(target)
                if final_status["installed"] or final_status["current"]:
                    fail("remove-cli software status postcondition failed")
                cleanup_pending = publish_cleanup_pending(
                    target, [(rollback_parent, "software-remove-rollback")]
                )
                rollback_parent = None
                cleanup_software_remove_empty_parents(target)
            except BaseException:
                rollback_exact = False
                for _ in range(4):
                    try:
                        if not software_tree_object_matches(
                            version_dir, before_version_identity, "Cursor software version tree"
                        ):
                            remove_software_path(version_dir)
                            if (
                                before_version_identity is not None
                                and rollback_version is not None
                                and (rollback_version.exists() or rollback_version.is_symlink())
                            ):
                                ensure_real_directory_path(container, "Cursor software container")
                                ensure_real_directory_path(root, "Cursor software root")
                                ensure_real_directory_path(
                                    versions, "Cursor software versions directory"
                                )
                                os.rename(rollback_version, version_dir)
                                fsync_directory(versions)
                        if not software_tree_object_matches(
                            launch_root, before_launch_identity, "Cursor launch images tree"
                        ):
                            remove_software_path(launch_root)
                            if (
                                before_launch_identity is not None
                                and rollback_launch is not None
                                and (rollback_launch.exists() or rollback_launch.is_symlink())
                            ):
                                ensure_real_directory_path(root, "Cursor software root")
                                os.rename(rollback_launch, launch_root)
                                fsync_directory(root)
                        if not software_file_object_matches(
                            binary_path,
                            before_binary_identity,
                            f"Cursor managed binary {binary_path}",
                        ):
                            remove_software_path(binary_path)
                            if rollback_binary is not None and (
                                rollback_binary.exists() or rollback_binary.is_symlink()
                            ):
                                ensure_real_directory_path(
                                    binary_path.parent, "Cursor managed command directory"
                                )
                                os.rename(rollback_binary, binary_path)
                                fsync_existing_parent(binary_path)
                        if not software_file_object_matches(
                            stamp_path,
                            before_stamp_identity,
                            f"Cursor software stamp {stamp_path}",
                        ):
                            remove_software_path(stamp_path)
                            if rollback_stamp is not None and (
                                rollback_stamp.exists() or rollback_stamp.is_symlink()
                            ):
                                ensure_real_directory_path(root, "Cursor software root")
                                os.rename(rollback_stamp, stamp_path)
                                fsync_existing_parent(stamp_path)
                        if not software_file_object_matches(
                            marker_path,
                            before_marker_identity,
                            f"Cursor software transaction marker {marker_path}",
                        ):
                            remove_software_path(marker_path)
                            if rollback_marker is not None and (
                                rollback_marker.exists() or rollback_marker.is_symlink()
                            ):
                                ensure_real_directory_path(root, "Cursor software root")
                                os.rename(rollback_marker, marker_path)
                                fsync_existing_parent(marker_path)
                        if matches_before():
                            rollback_exact = True
                            break
                    except BaseException:
                        pass
                if rollback_parent is not None and (
                    rollback_parent.exists() or rollback_parent.is_symlink()
                ):
                    with contextlib.suppress(FileNotFoundError):
                        shutil.rmtree(rollback_parent)
                        fsync_directory(rollback_parent.parent)
                if rollback_exact:
                    remove_empty_directory_if_created(versions, before_versions_exists)
                    remove_empty_directory_if_created(root, before_root_exists)
                    remove_empty_directory_if_created(container, before_container_exists)
                    remove_empty_directory_if_created(binary_path.parent, before_bin_dir_exists)
                raise
            if final_status is None:
                fail("remove-cli software status postcondition did not run")
            return {
                "schema_version": 1,
                "command": "remove-cli",
                "operation": "remove",
                "target": str(target.resolve(strict=False)),
                "current": False,
                "present": final_status["present"],
                "changed": sorted(set(initial_presence)),
                "managed_command": str(binary_path.resolve(strict=False)),
                "cleanup_pending": cleanup_pending,
            }


def reject_managed_launch_overrides(cursor_args: list[str]) -> None:
    if cursor_args[:1] and cursor_args[0] in BLOCKED_LAUNCH_COMMANDS:
        fail(f"launch refuses Cursor command that bypasses managed lifecycle: {cursor_args[0]}")
    for argument in cursor_args:
        if argument == "--":
            continue
        if argument.startswith("--"):
            option = argument.split("=", 1)[0]
            if option in BLOCKED_LAUNCH_LONG_FLAGS:
                fail(f"launch refuses managed Cursor override option: {option}")
            continue
        if argument.startswith("-") and argument != "-":
            for flag in argument[1:]:
                blocked = BLOCKED_LAUNCH_SHORT_FLAGS.get(flag)
                if blocked is not None:
                    fail(f"launch refuses managed Cursor override option: -{flag} ({blocked})")


def normalized_launch_args(cursor_args: list[str]) -> list[str]:
    if cursor_args[:1] == ["--"]:
        return cursor_args[1:]
    return list(cursor_args)


def restore_managed_config_after_launch_locked(target: Path) -> None:
    stamp = load_stamp(target)
    if stamp is None:
        fail("managed target stamp disappeared during Cursor launch")
    if stamp_is_legacy(stamp):
        fail("legacy managed target cannot be restored after launch")
    profile_id = str(stamp["profile_id"])
    _, _, rendered = render_selection(str(stamp["content_setup_id"]), profile_id)
    setup_config = parse_json_object(rendered[CONFIG_NAME], f"profile {profile_id}/{CONFIG_NAME}")
    config_path = target / CONFIG_NAME
    if config_path.exists() or config_path.is_symlink():
        current = parse_json_object(
            read_regular_file(
                config_path,
                f"target {CONFIG_NAME}",
                max_bytes=METADATA_MAX_BYTES,
            ),
            f"target {CONFIG_NAME}",
        )
    else:
        current = {}
    desired = {CONFIG_NAME: canonical_json(merge_config(current, setup_config))}
    replace_managed_state(target, desired, names=(CONFIG_NAME,))


def restore_managed_config_after_launch(target: Path) -> None:
    prepare_lifecycle_target(target, create_missing=False)
    with target_lock(target):
        restore_managed_config_after_launch_locked(target)


def revalidate_software_stamp_for_launch(target: Path) -> dict[str, Any]:
    stamp = load_software_stamp(target)
    if stamp is None:
        fail("Cursor software stamp disappeared before exec handoff")
    asset_path, artifact_sha256, artifact_size = current_platform_asset()
    expected = {
        "build_version": VERSION,
        "version": CURSOR_VERSION,
        "official_source": official_asset_url(asset_path),
        "asset_path": asset_path,
        "artifact_sha256": artifact_sha256,
        "artifact_size": artifact_size,
    }
    for key, value in expected.items():
        if stamp[key] != value:
            fail(f"Cursor software stamp {key} changed before exec handoff")
    return stamp


def revalidate_executable_identity(
    executable: Path, expected_sha256: str, label: str
) -> dict[str, Any]:
    before = require_regular_file(
        executable, f"{label} {executable}", max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES
    )
    if stat.S_IMODE(before.st_mode) != OWNER_EXEC_MODE:
        fail("Cursor launch executable must have mode 0700")
    content = read_regular_file(
        executable,
        f"{label} {executable}",
        max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES,
    )
    after = require_regular_file(
        executable, f"{label} {executable}", max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES
    )
    if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        fail("Cursor launch executable changed before exec handoff")
    digest = sha256_bytes(content)
    if digest != expected_sha256:
        fail("Cursor launch executable digest changed before exec handoff")
    return {
        "device": after.st_dev,
        "inode": after.st_ino,
        "sha256": digest,
    }


def run_cursor_child(
    executable: Path, forwarded: list[str], environment: dict[str, str]
) -> subprocess.CompletedProcess[Any]:
    return subprocess.run([str(executable), *forwarded], env=environment, check=False)


def report_cleanup_failure_after_child_exception(
    child_error: BaseException, cleanup_error: BaseException
) -> None:
    note = f"managed config restore failed after child exception: {cleanup_error}"
    add_note = getattr(child_error, "add_note", None)
    if add_note is not None:
        with contextlib.suppress(Exception):
            add_note(note)
    with contextlib.suppress(Exception):
        print(f"nddev-cursor-cli: warning: {note}", file=sys.stderr)


def ensure_mutable_runtime_tmp_dir(target: Path) -> Path:
    ensure_real_directory(target, MUTABLE_RUNTIME_TMP_ROOT)
    return require_target_local_directory_chain(
        target, MUTABLE_RUNTIME_TMP_ROOT, "Cursor mutable runtime TMPDIR"
    )


def make_tree_owner_writable(path: Path) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if path.is_symlink():
        path.unlink()
        return
    if path.is_dir():
        for child in path.iterdir():
            make_tree_owner_writable(child)
        path.chmod(OWNER_DIRECTORY_MODE)
    elif path.is_file():
        path.chmod(OWNER_FILE_MODE)


def cleanup_launch_image(path: Path | None) -> None:
    if path is None:
        return
    with contextlib.suppress(FileNotFoundError):
        make_tree_owner_writable(path)
        shutil.rmtree(path)


def create_launch_image(target: Path) -> dict[str, Any]:
    images_root = launch_images_root(target)
    ensure_real_directory_path(images_root, "Cursor launch images root")
    image_root = Path(tempfile.mkdtemp(prefix=".launch-", dir=str(images_root)))
    image_root.chmod(OWNER_DIRECTORY_MODE)
    try:
        files = snapshot_runtime_payload(software_version_dir(target))
        write_cursor_runtime_tree(image_root, files)
        running = image_root / ".running"
        running.mkdir(mode=OWNER_DIRECTORY_MODE)
        running.chmod(OWNER_DIRECTORY_MODE)
        launcher = agent_launcher_bytes_for_runtime_dir(image_root)
        executable = image_root / LAUNCH_IMAGE_AGENT_NAME
        atomic_write_executable(executable, launcher)
        return {
            "root": image_root,
            "executable": executable,
            "entrypoint_sha256": sha256_bytes(launcher),
        }
    except BaseException:
        cleanup_launch_image(image_root)
        raise


def launch_protected_directories(launch_image_root: Path) -> tuple[Path, ...]:
    return (launch_image_root,)


def require_launch_protected_directories(launch_image_root: Path) -> tuple[Path, ...]:
    directories = launch_protected_directories(launch_image_root)
    for directory in directories:
        require_owner_private_directory(directory, "launch protected directory")
    return directories


@contextlib.contextmanager
def launch_write_protection(launch_image_root: Path) -> Iterator[None]:
    directories = require_launch_protected_directories(launch_image_root)
    protected: list[Path] = []
    try:
        for directory in directories:
            set_owner_directory_mode(
                directory, f"launch protected directory {directory}", LOCK_HELD_DIRECTORY_MODE
            )
            protected.append(directory)
        yield
    finally:
        active_error = sys.exc_info()[1]
        cleanup_errors: list[BaseException] = []
        for directory in reversed(protected):
            try:
                set_owner_directory_mode(
                    directory, f"launch protected directory {directory}", OWNER_DIRECTORY_MODE
                )
            except BaseException as exc:  # noqa: BLE001 - preserve original failure.
                cleanup_errors.append(exc)
        if cleanup_errors:
            cleanup_error = cleanup_errors[0]
            if active_error is not None:
                add_note = getattr(active_error, "add_note", None)
                if add_note is not None:
                    with contextlib.suppress(Exception):
                        add_note(f"launch write-protection restore failed: {cleanup_error}")
                with contextlib.suppress(Exception):
                    print(
                        "nddev-cursor-cli: warning: launch write-protection restore "
                        f"failed: {cleanup_error}",
                        file=sys.stderr,
                    )
            else:
                raise cleanup_error


def launch_cursor(target: Path, cursor_args: list[str]) -> int:
    return with_mutation_bootstrap_target(target, _launch_cursor_locked, cursor_args)


def _launch_cursor_locked(target: Path, cursor_args: list[str]) -> int:
    forwarded = list(cursor_args)
    reject_managed_launch_overrides(forwarded)
    prepare_lifecycle_target(target, create_missing=False)
    with target_lock(target, protect_lock_parent=True):
        require_clean_managed(target)
        software = _software_status_locked(target)
        if not software["installed"] or not software["current"]:
            fail("launch requires current target-owned Cursor CLI software")
        child_home = require_target_local_directory_chain(
            target, ISOLATED_HOME_ROOT, "Cursor isolated HOME"
        )
        child_tmp = ensure_mutable_runtime_tmp_dir(target)
        environment: dict[str, str] = {
            "CURSOR_CONFIG_DIR": str(target.resolve(strict=False)),
            "HOME": str(child_home.resolve(strict=False)),
            "TMPDIR": str(child_tmp.resolve(strict=False)),
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        for name in ("LANG", "LC_ALL", "LC_CTYPE", "TERM", "COLORTERM"):
            value = os.environ.get(name)
            if value:
                environment[name] = value
        for name in PROVIDER_SECRET_NAMES:
            environment.pop(name, None)
        launch_image: dict[str, Any] | None = None
        child_error: BaseException | None = None
        try:
            launch_image = create_launch_image(target)
            executable = launch_image["executable"]
            image_root = launch_image["root"]
            with launch_write_protection(image_root):
                try:
                    revalidate_software_stamp_for_launch(target)
                    revalidate_executable_identity(
                        executable,
                        str(launch_image["entrypoint_sha256"]),
                        "Cursor launch image executable",
                    )
                    completed = run_cursor_child(executable, forwarded, environment)
                except BaseException as exc:
                    child_error = exc
                    raise
                finally:
                    try:
                        restore_managed_config_after_launch_locked(target)
                    except BaseException as cleanup_error:
                        if child_error is not None:
                            report_cleanup_failure_after_child_exception(child_error, cleanup_error)
                        else:
                            raise
        finally:
            try:
                cleanup_launch_image(None if launch_image is None else launch_image["root"])
            except BaseException as cleanup_error:
                if child_error is not None:
                    report_cleanup_failure_after_child_exception(child_error, cleanup_error)
                else:
                    raise
        if completed.returncode < 0:
            return 128 + abs(completed.returncode)
        return completed.returncode


def add_target(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", required=True, help="Absolute Cursor CLI config root.")
    parser.add_argument("--json", action="store_true", dest="output_json")


def add_setup_profile(
    parser: argparse.ArgumentParser,
    *,
    profile_required: bool = False,
    profile_default: str | None = DEFAULT_PROFILE_ID,
) -> None:
    parser.add_argument(
        "--setup",
        default=DEFAULT_CONTENT_SETUP_ID,
        help=f"Content setup id. Default: {DEFAULT_CONTENT_SETUP_ID}.",
    )
    parser.add_argument(
        "--profile",
        required=profile_required,
        default=profile_default,
        help=(
            "Permission profile id."
            if profile_default is None
            else f"Permission profile id. Default: {profile_default}."
        ),
    )


def argv_requests_json(argv: list[str] | None) -> bool:
    return "--json" in (sys.argv[1:] if argv is None else argv)


class CursorArgumentParser(argparse.ArgumentParser):
    def parse_args(
        self, args: list[str] | None = None, namespace: argparse.Namespace | None = None
    ) -> argparse.Namespace:
        global _PARSER_JSON_ERROR_REQUESTED
        _PARSER_JSON_ERROR_REQUESTED = argv_requests_json(args)
        self._json_error_requested = argv_requests_json(args)
        return super().parse_args(args, namespace)

    def error(self, message: str) -> NoReturn:
        if _PARSER_JSON_ERROR_REQUESTED or getattr(self, "_json_error_requested", False):
            raise CursorArgumentError(message)
        super().error(message)


def build_parser() -> argparse.ArgumentParser:
    parser = CursorArgumentParser(
        prog="nddev-cursor-cli",
        description="Manage a portable Cursor CLI setup at an explicit target.",
    )
    subparsers = parser.add_subparsers(
        dest="command", required=True, parser_class=CursorArgumentParser
    )

    list_parser = subparsers.add_parser("list", help="List source setups.")
    list_parser.add_argument("--json", action="store_true", dest="output_json")

    status_parser = subparsers.add_parser("status", help="Inspect an explicit target.")
    add_target(status_parser)

    for command in ("plan", "install", "switch"):
        command_parser = subparsers.add_parser(command, help=f"{command.title()} a setup.")
        add_setup_profile(command_parser)
        add_target(command_parser)

    update_parser = subparsers.add_parser(
        "update", help="Refresh the installed setup/profile identity."
    )
    add_target(update_parser)

    migrate_parser = subparsers.add_parser(
        "migrate", help="Migrate a legacy managed target to the setup/profile contract."
    )
    add_setup_profile(migrate_parser, profile_required=False, profile_default=None)
    add_target(migrate_parser)

    software_status_parser = subparsers.add_parser(
        "software-status", help="Inspect target-owned Cursor CLI software."
    )
    add_target(software_status_parser)

    for command in ("install-cli", "update-cli", "remove-cli"):
        command_parser = subparsers.add_parser(
            command, help=f"{command.title()} target-owned Cursor CLI software."
        )
        add_target(command_parser)

    restore_parser = subparsers.add_parser("restore", help="Restore a target-bound backup.")
    restore_parser.add_argument("--backup", required=True, type=int, choices=range(10))
    add_target(restore_parser)

    remove_parser = subparsers.add_parser("remove", help="Remove only managed setup files.")
    add_target(remove_parser)

    launch_parser = subparsers.add_parser(
        "launch", help="Launch Cursor Agent with an isolated config root."
    )
    add_target(launch_parser)
    launch_parser.add_argument("cursor_args", nargs=argparse.REMAINDER)
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def run_target_command(target: Path, args: argparse.Namespace) -> dict[str, Any] | int:
    if args.command == "status":
        return {
            "schema_version": 2,
            "command": "status",
            "target": str(target),
            **_inspect_target_locked(target),
        }
    if args.command == "plan":
        return _plan_setup_locked(target, args.setup, args.profile)
    if args.command in {"install", "switch"}:
        return _mutate_setup_locked(target, args.setup, args.profile, args.command)
    if args.command == "update":
        return _mutate_setup_locked(target, DEFAULT_CONTENT_SETUP_ID, DEFAULT_PROFILE_ID, "update")
    if args.command == "migrate":
        return _migrate_setup_locked(target, args.setup, args.profile)
    if args.command == "software-status":
        return _software_status_locked(target)
    if args.command in {"install-cli", "update-cli"}:
        return _install_cursor_cli_locked(target, args.command)
    if args.command == "remove-cli":
        return _remove_cursor_cli_locked(target)
    if args.command == "restore":
        return _restore_slot_locked(target, args.backup)
    if args.command == "remove":
        return _remove_setup_locked(target)
    if args.command == "launch":
        return _launch_cursor_locked(target, normalized_launch_args(list(args.cursor_args)))
    fail(f"unsupported command: {args.command}")


def run(args: argparse.Namespace) -> dict[str, Any] | int:
    if args.command == "list":
        return {
            "schema_version": 2,
            "command": "list",
            "setups": list_setups(),
            "profiles": list_profiles(),
            "default_setup": DEFAULT_CONTENT_SETUP_ID,
            "default_profile": DEFAULT_PROFILE_ID,
        }
    if args.command in TARGET_COMMANDS:
        if args.command in READ_ONLY_TARGET_COMMANDS:
            return with_read_bootstrap_target(args.target, run_target_command, args)
        return with_mutation_bootstrap_target(args.target, run_target_command, args)
    fail(f"unsupported command: {args.command}")


def human_output(value: dict[str, Any]) -> str:
    command = value.get("command")
    if command == "list":
        setup_lines = [f"setup {item['id']}: {item['description']}" for item in value["setups"]]
        profile_lines = [
            f"profile {item['id']}: {item['description']}" for item in value["profiles"]
        ]
        return "\n".join([*setup_lines, *profile_lines])
    if command == "status":
        if value.get("legacy"):
            setup = f" (legacy {value['legacy_setup_id']})"
        elif value.get("content_setup_id"):
            setup = f" ({value['content_setup_id']}/{value['profile_id']})"
        else:
            setup = ""
        drift = f"; drift={','.join(value['drift'])}" if value["drift"] else ""
        builder = f"; builder={value['builder_projection']}"
        return f"{value['state']}{setup}: {value['target']}{drift}{builder}"
    if command == "plan":
        changes = ", ".join(value["changes"]) or "none"
        return (
            f"{value['operation']} {value['content_setup_id']}/{value['profile_id']} "
            f"at {value['target']}; changes: {changes}"
        )
    return json.dumps(value, indent=2, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    json_error = argv_requests_json(argv)
    args: argparse.Namespace | None = None
    try:
        args = parse_args(argv)
        result = run(args)
    except (CursorArgumentError, CursorSetupError, OSError) as exc:
        if isinstance(exc, OSError):
            error_message = exc.strerror or type(exc).__name__
            if exc.filename is not None:
                error_message += f" ({exc.filename})"
        else:
            error_message = str(exc)
        if json_error or (args is not None and getattr(args, "output_json", False)):
            print(json.dumps({"schema_version": 1, "error": error_message}, sort_keys=True))
        else:
            print(f"nddev-cursor-cli: error: {error_message}", file=sys.stderr)
        return 2
    if isinstance(result, int):
        return result
    if getattr(args, "output_json", False):
        sys.stdout.buffer.write(canonical_json(result))
    else:
        print(human_output(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
