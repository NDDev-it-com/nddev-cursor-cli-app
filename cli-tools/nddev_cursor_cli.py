#!/usr/bin/env python3
"""Transactional setup manager for a caller-selected Cursor CLI config root."""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
CATALOG_ROOT = ROOT / "setups"
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
PRODUCT_NAME = "nddev-cursor-cli-app"
CURSOR_COMMAND = "agent"
CONFIG_NAME = "cli-config.json"
STAMP_NAME = "NDDEV-CURSOR-CLI-SETUP.json"
BACKUP_NAME = "NDDEV-CURSOR-CLI-BACKUP.json"
SOFTWARE_STAMP_NAME = "NDDEV-CURSOR-CLI-SOFTWARE.json"
OWNER_FILE_MODE = 0o600
OWNER_DIRECTORY_MODE = 0o700
OWNER_EXEC_MODE = 0o700
METADATA_MAX_BYTES = 256 * 1024
MANAGED_PAYLOAD_MAX_BYTES = 8 * 1024 * 1024
SOFTWARE_ARTIFACT_MAX_BYTES = 300 * 1024 * 1024
CURSOR_VERSION = "2026.07.23-e383d2b"
CURSOR_RELEASE_BASE_URL = f"https://downloads.cursor.com/lab/{CURSOR_VERSION}"
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
INTERNAL_ARTIFACT_ENV = "NDDEV_CURSOR_CLI_TEST_ARTIFACT_URL"
INTERNAL_FAIL_AFTER_VERSION_SWAP_ENV = "NDDEV_CURSOR_CLI_TEST_FAIL_AFTER_VERSION_SWAP"
INTERNAL_FAIL_AFTER_BINARY_SWAP_ENV = "NDDEV_CURSOR_CLI_TEST_FAIL_AFTER_BINARY_SWAP"
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
SETUP_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
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
BUILDER_TARGET_ROOT = Path("plugins") / "local" / "nddev-builder"
BUILDER_SOURCE_FILES = (
    (
        Path(".cursor-plugin") / "plugin.json",
        BUILDER_TARGET_ROOT / ".cursor-plugin" / "plugin.json",
    ),
    (Path("rules") / "nddev-builder.mdc", BUILDER_TARGET_ROOT / "rules" / "nddev-builder.mdc"),
    (
        Path("skills") / "nddev-builder" / "SKILL.md",
        BUILDER_TARGET_ROOT / "skills" / "nddev-builder" / "SKILL.md",
    ),
    (Path("agents") / "nddev-builder.md", BUILDER_TARGET_ROOT / "agents" / "nddev-builder.md"),
)
MANAGED_PATHS = (
    Path(CONFIG_NAME),
    Path(STAMP_NAME),
    *(target for _, target in BUILDER_SOURCE_FILES),
)
STAMP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "setup_id",
    "canonical_target",
    "managed_files",
    "builder_projection",
}
BACKUP_KEYS = {
    "schema_version",
    "product_name",
    "build_version",
    "slot",
    "canonical_target",
    "source_setup_id",
    "managed_files",
    "created_at",
    "files",
}


class CursorSetupError(Exception):
    """A safe, user-facing lifecycle failure."""


def fail(message: str) -> NoReturn:
    raise CursorSetupError(message)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


def render_setup(setup_id: str) -> tuple[dict[str, Any], dict[str, bytes]]:
    validate_setup_id(setup_id)
    setup_root = CATALOG_ROOT / setup_id
    if not setup_root.is_dir() or setup_root.is_symlink():
        fail(f"unknown setup: {setup_id}")
    metadata = load_json_object(setup_root / "setup.json", f"setup {setup_id} metadata")
    require_exact_keys(
        metadata,
        {"schema_version", "id", "description", "managed_files", "builder_projection"},
        f"setup {setup_id} metadata",
    )
    if metadata["schema_version"] != 1:
        fail(f"setup {setup_id} metadata has unsupported schema")
    if metadata["id"] != setup_id:
        fail(f"setup {setup_id} metadata identity mismatch")
    if metadata["managed_files"] != [CONFIG_NAME]:
        fail(f"setup {setup_id} managed file declaration is invalid")
    if metadata["builder_projection"] != "default-on":
        fail(f"setup {setup_id} must enable the builder projection")
    config = load_json_object(setup_root / CONFIG_NAME, f"setup {setup_id}/{CONFIG_NAME}")
    validate_config(config, f"setup {setup_id}/{CONFIG_NAME}")
    return metadata, {CONFIG_NAME: canonical_json(config)}


def builder_projection_files() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for source_relative, target_relative in BUILDER_SOURCE_FILES:
        source = BUILDER_SOURCE_ROOT / source_relative
        content = read_regular_file(
            source,
            f"builder projection source {source_relative.as_posix()}",
            max_bytes=MANAGED_PAYLOAD_MAX_BYTES,
        )
        content.decode("utf-8")
        files[target_relative.as_posix()] = content
    return files


def list_setups() -> list[dict[str, Any]]:
    if not CATALOG_ROOT.is_dir() or CATALOG_ROOT.is_symlink():
        fail("setup catalog is missing or unsafe")
    entries: list[dict[str, Any]] = []
    for candidate in sorted(CATALOG_ROOT.iterdir(), key=lambda path: path.name):
        if not candidate.is_dir() or candidate.is_symlink():
            fail(f"catalog entry must be a real directory: {candidate.name}")
        metadata, _ = render_setup(candidate.name)
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


def resolve_target(raw_target: str) -> Path:
    expanded = Path(raw_target).expanduser()
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


@contextlib.contextmanager
def target_lock(target: Path) -> Iterator[None]:
    lock = target.parent / f".{target.name}.nddev-cursor-cli-lock"
    try:
        lock.mkdir(mode=OWNER_DIRECTORY_MODE)
    except FileExistsError:
        fail("target is already locked")
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            lock.rmdir()


def ensure_target_directory(target: Path) -> None:
    if target.exists():
        info = target.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail("--target must be a real directory")
        return
    target.mkdir(mode=OWNER_DIRECTORY_MODE)
    target.chmod(OWNER_DIRECTORY_MODE)


def stamp_bytes(target: Path, setup_id: str) -> bytes:
    return canonical_json(
        {
            "schema_version": 1,
            "product_name": PRODUCT_NAME,
            "build_version": VERSION,
            "setup_id": setup_id,
            "canonical_target": str(target.resolve(strict=False)),
            "managed_files": [CONFIG_NAME],
            "builder_projection": {
                "default_on": True,
                "target_plugin_path": BUILDER_TARGET_ROOT.as_posix(),
                "source_sha256": sha256_bytes(
                    b"".join(
                        builder_projection_files()[path]
                        for path in sorted(builder_projection_files())
                    )
                ),
            },
        }
    )


def load_stamp(target: Path) -> dict[str, Any] | None:
    stamp_path = target / STAMP_NAME
    if not stamp_path.exists() and not stamp_path.is_symlink():
        return None
    stamp = load_json_object(stamp_path, f"target stamp {stamp_path}")
    require_exact_keys(stamp, STAMP_KEYS, "target stamp")
    if stamp["schema_version"] != 1 or stamp["product_name"] != PRODUCT_NAME:
        fail("target stamp is not owned by nddev-cursor-cli-app")
    if stamp["canonical_target"] != str(target.resolve(strict=False)):
        fail("target stamp belongs to a different canonical target")
    validate_setup_id(str(stamp["setup_id"]))
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


def inspect_builder_projection(target: Path) -> str:
    desired = builder_projection_files()
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
        if actual != content:
            drifted = True
    if drifted:
        return "drifted"
    if missing:
        return "missing"
    return "current"


def drift_for_target(target: Path, stamp: dict[str, Any]) -> list[str]:
    _, rendered = render_setup(str(stamp["setup_id"]))
    current = load_target_config(target)
    if current is None:
        return [CONFIG_NAME]
    expected_config = parse_json_object(
        rendered[CONFIG_NAME], f"setup {stamp['setup_id']}/{CONFIG_NAME}"
    )
    drift: list[str] = []
    if managed_config_view(current) != managed_config_view(expected_config):
        drift.append(CONFIG_NAME)
    builder_state = inspect_builder_projection(target)
    if builder_state == "drifted":
        drift.append(BUILDER_TARGET_ROOT.as_posix())
    elif builder_state == "missing":
        drift.append(BUILDER_TARGET_ROOT.as_posix())
    return drift


def inspect_target(target: Path) -> dict[str, Any]:
    if not target.exists() and not target.is_symlink():
        return {
            "state": "missing",
            "setup_id": None,
            "drift": [],
            "builder_projection": "missing",
        }
    if target.is_symlink() or not target.is_dir():
        fail("--target must be a real directory")
    stamp = load_stamp(target)
    config_exists = (target / CONFIG_NAME).exists() or (target / CONFIG_NAME).is_symlink()
    if stamp is None:
        return {
            "state": "unmanaged" if config_exists else "empty",
            "setup_id": None,
            "drift": [],
            "builder_projection": inspect_builder_projection(target)
            if target.exists()
            else "missing",
        }
    drift = drift_for_target(target, stamp)
    builder_state = (
        "current"
        if BUILDER_TARGET_ROOT.as_posix() not in drift
        else inspect_builder_projection(target)
    )
    return {
        "state": "managed",
        "setup_id": stamp["setup_id"],
        "drift": drift,
        "builder_projection": builder_state,
    }


def require_clean_managed(target: Path) -> dict[str, Any]:
    state = inspect_target(target)
    if state["state"] != "managed":
        fail(f"target is not managed (state={state['state']})")
    if state["drift"]:
        fail(f"managed target has drift: {', '.join(state['drift'])}")
    return state


def backup_pool(target: Path) -> Path:
    return target.parent / f".{target.name}.nddev-cursor-cli-backups"


def choose_backup_slot(pool: Path) -> int:
    pool.mkdir(mode=OWNER_DIRECTORY_MODE, exist_ok=True)
    pool.chmod(OWNER_DIRECTORY_MODE)
    for slot in range(10):
        if not (pool / str(slot)).exists():
            return slot
    oldest = min(range(10), key=lambda slot: (pool / str(slot)).stat().st_mtime_ns)
    return oldest


def capture_managed_files(target: Path) -> dict[str, bytes | None]:
    captured: dict[str, bytes | None] = {}
    for relative in MANAGED_PATHS:
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


def write_backup(target: Path, source_setup_id: str) -> int:
    pool = backup_pool(target)
    slot = choose_backup_slot(pool)
    slot_path = pool / str(slot)
    if slot_path.exists():
        shutil.rmtree(slot_path)
    slot_path.mkdir(mode=OWNER_DIRECTORY_MODE)
    files = capture_managed_files(target)
    envelope = {
        "schema_version": 1,
        "product_name": PRODUCT_NAME,
        "build_version": VERSION,
        "slot": slot,
        "canonical_target": str(target.resolve(strict=False)),
        "source_setup_id": source_setup_id,
        "managed_files": [CONFIG_NAME],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": {
            relative: None if content is None else base64.b64encode(content).decode("ascii")
            for relative, content in files.items()
        },
    }
    (slot_path / BACKUP_NAME).write_bytes(canonical_json(envelope))
    (slot_path / BACKUP_NAME).chmod(OWNER_FILE_MODE)
    return slot


def load_backup(target: Path, slot: int) -> dict[str, Any]:
    path = backup_pool(target) / str(slot) / BACKUP_NAME
    envelope = load_json_object(path, f"backup slot {slot}")
    require_exact_keys(envelope, BACKUP_KEYS, f"backup slot {slot}")
    if envelope["schema_version"] != 1 or envelope["product_name"] != PRODUCT_NAME:
        fail("backup is not owned by nddev-cursor-cli-app")
    if envelope["canonical_target"] != str(target.resolve(strict=False)):
        fail("backup belongs to a different canonical target")
    if envelope["slot"] != slot:
        fail("backup slot identity mismatch")
    return envelope


def safe_relative(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        fail(f"unsafe managed relative path: {relative}")
    return path


def remove_empty_parents(target: Path, path: Path) -> None:
    parent = path.parent
    while parent != target and parent.is_relative_to(target):
        with contextlib.suppress(OSError):
            parent.rmdir()
        parent = parent.parent


def ensure_real_directory(root: Path, relative: Path) -> None:
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            try:
                info = current.lstat()
            except FileNotFoundError:
                fail(f"managed directory appeared concurrently: {current}")
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                fail(f"managed directory path is unsafe: {current}")
            continue
        current.mkdir(mode=OWNER_DIRECTORY_MODE)
        current.chmod(OWNER_DIRECTORY_MODE)


def write_exclusive_file(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, OWNER_FILE_MODE)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written == 0:
                fail(f"managed write made no progress: {path}")
            view = view[written:]
        os.fchmod(descriptor, OWNER_FILE_MODE)
    finally:
        os.close(descriptor)


def replace_managed_state(
    target: Path,
    desired: dict[str, bytes | None],
    expected: Any | None = None,
    *,
    names: tuple[str, ...] | None = None,
) -> None:
    del expected
    selected = tuple(desired) if names is None else names
    for relative_name in selected:
        relative = safe_relative(relative_name)
        destination = target / relative
        content = desired.get(relative_name)
        if content is None:
            if destination.exists() or destination.is_symlink():
                require_regular_file(
                    destination,
                    f"managed path {relative.as_posix()}",
                    max_bytes=MANAGED_PAYLOAD_MAX_BYTES,
                )
                destination.unlink()
                remove_empty_parents(target, destination)
            continue
        ensure_real_directory(target, relative.parent)
        if destination.exists() or destination.is_symlink():
            require_regular_file(
                destination,
                f"managed path {relative.as_posix()}",
                max_bytes=MANAGED_PAYLOAD_MAX_BYTES,
            )
        temporary = destination.with_name(
            f".{destination.name}.nddev-tmp-{os.getpid()}-{secrets.token_hex(8)}"
        )
        try:
            write_exclusive_file(temporary, content)
            os.replace(temporary, destination)
            destination.chmod(OWNER_FILE_MODE)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()


def desired_for_setup(
    target: Path, setup_id: str, existing_config: dict[str, Any] | None
) -> dict[str, bytes | None]:
    _, rendered = render_setup(setup_id)
    setup_config = parse_json_object(rendered[CONFIG_NAME], f"setup {setup_id}/{CONFIG_NAME}")
    desired_config = merge_config(existing_config, setup_config)
    desired: dict[str, bytes | None] = {
        CONFIG_NAME: canonical_json(desired_config),
        STAMP_NAME: stamp_bytes(target, setup_id),
    }
    desired.update(builder_projection_files())
    return desired


def restore_files_from_backup(envelope: dict[str, Any]) -> dict[str, bytes | None]:
    files = envelope.get("files")
    if not isinstance(files, dict):
        fail("backup files must be an object")
    desired: dict[str, bytes | None] = {}
    for relative, encoded in files.items():
        path = safe_relative(str(relative))
        if encoded is None:
            desired[path.as_posix()] = None
            continue
        if not isinstance(encoded, str):
            fail(f"backup payload for {relative} must be a base64 string")
        try:
            desired[path.as_posix()] = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (ValueError, UnicodeEncodeError) as exc:
            fail(f"backup payload for {relative} is invalid: {exc}")
    return desired


def plan_setup(target: Path, setup_id: str) -> dict[str, Any]:
    render_setup(setup_id)
    state = inspect_target(target)
    operation = "install"
    backup_required = False
    changes: list[str] = []
    if state["state"] == "managed":
        current_setup = state["setup_id"]
        operation = "update" if current_setup == setup_id else "switch"
        backup_required = current_setup != setup_id
        if state["drift"]:
            changes = ["blocked-by-drift"]
        elif current_setup != setup_id:
            changes = [CONFIG_NAME, STAMP_NAME, BUILDER_TARGET_ROOT.as_posix()]
    elif state["state"] in {"missing", "empty"}:
        changes = [CONFIG_NAME, STAMP_NAME, BUILDER_TARGET_ROOT.as_posix()]
    else:
        changes = ["blocked-by-unmanaged-target"]
    return {
        "schema_version": 1,
        "command": "plan",
        "operation": operation,
        "setup_id": setup_id,
        "target": str(target),
        "mutates": False,
        "backup_required": backup_required,
        "changes": changes,
        "builder_projection": "default-on",
    }


def mutate_setup(target: Path, setup_id: str, command: str) -> dict[str, Any]:
    render_setup(setup_id)
    with target_lock(target):
        ensure_target_directory(target)
        state = inspect_target(target)
        if state["state"] == "unmanaged":
            fail("unmanaged target contains Cursor CLI state; refusing to overwrite")
        if command == "switch" and state["state"] != "managed":
            fail("switch requires an existing managed target")
        if state["state"] == "managed" and state["drift"]:
            fail(f"managed target has drift: {', '.join(state['drift'])}")
        current_setup = state["setup_id"] if state["state"] == "managed" else None
        if command == "switch" and current_setup == setup_id:
            fail("switch requires a different setup")
        existing_config = load_target_config(target) if state["state"] == "managed" else None
        desired = desired_for_setup(target, setup_id, existing_config)
        before = capture_managed_files(target)
        changed = [
            relative for relative, content in desired.items() if before.get(relative) != content
        ]
        backup_slot: int | None = None
        if state["state"] == "managed" and current_setup != setup_id:
            backup_slot = write_backup(target, str(current_setup))
        try:
            if changed:
                replace_managed_state(target, desired, before)
            final = inspect_target(target)
            if final["state"] != "managed" or final["setup_id"] != setup_id or final["drift"]:
                fail("setup mutation postcondition failed")
        except BaseException:
            replace_managed_state(target, before, None)
            raise
    return {
        "schema_version": 1,
        "command": command,
        "target": str(target),
        "setup_id": setup_id,
        "changed": changed,
        "backup_slot": backup_slot,
        "builder_projection": "current",
    }


def restore_slot(target: Path, slot: int) -> dict[str, Any]:
    with target_lock(target):
        ensure_target_directory(target)
        envelope = load_backup(target, slot)
        state = inspect_target(target)
        if state["state"] == "managed" and state["drift"]:
            fail(f"managed target has drift: {', '.join(state['drift'])}")
        before = capture_managed_files(target)
        desired = restore_files_from_backup(envelope)
        try:
            replace_managed_state(target, desired, before)
            final = inspect_target(target)
            if final["state"] != "managed" or final["drift"]:
                fail("restore postcondition failed")
        except BaseException:
            replace_managed_state(target, before, None)
            raise
    return {
        "schema_version": 1,
        "command": "restore",
        "target": str(target),
        "backup_slot": slot,
        "setup_id": envelope["source_setup_id"],
        "builder_projection": "current",
    }


def remove_setup(target: Path) -> dict[str, Any]:
    with target_lock(target):
        state = require_clean_managed(target)
        before = capture_managed_files(target)
        desired = {relative.as_posix(): None for relative in MANAGED_PATHS}
        try:
            replace_managed_state(target, desired, before)
        except BaseException:
            replace_managed_state(target, before, None)
            raise
    return {
        "schema_version": 1,
        "command": "remove",
        "target": str(target),
        "removed_setup_id": state["setup_id"],
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


def software_stamp_path(target: Path) -> Path:
    return software_root(target) / SOFTWARE_STAMP_NAME


def existing_path_label(path: Path, label: str) -> str | None:
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    return label


def software_presence(target: Path) -> list[str]:
    labels = (
        (software_stamp_path(target), SOFTWARE_STAMP_NAME),
        (software_container(target), ".nddev-software"),
        (software_root(target), ".nddev-software/cursor-cli"),
        (
            software_version_dir(target),
            ".nddev-software/cursor-cli/versions/2026.07.23-e383d2b",
        ),
        (managed_agent_path(target), "bin/agent"),
    )
    return sorted(label for path, label in labels if existing_path_label(path, label) is not None)


def current_platform_asset() -> tuple[str, str, int]:
    if sys.platform.startswith("linux"):
        os_id = "linux"
    elif sys.platform == "darwin":
        os_id = "darwin"
    else:
        fail(f"unsupported Cursor CLI installer platform: {sys.platform}")
    machine = os.uname().machine.lower()
    if machine in {"arm64", "aarch64"}:
        arch = "arm64"
    elif machine in {"x86_64", "amd64"}:
        arch = "x64"
    else:
        fail(f"unsupported Cursor CLI installer architecture: {machine}")
    return CURSOR_OFFICIAL_ASSETS[(os_id, arch)]


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
    if source.startswith("file://"):
        path = Path(source[7:])
        return read_regular_file(
            path,
            f"Cursor software artifact {path}",
            max_bytes=SOFTWARE_ARTIFACT_MAX_BYTES,
        )
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


def extract_cursor_agent(archive: bytes) -> bytes:
    candidates: list[bytes] = []
    with tarfile.open(fileobj=BytesIO(archive), mode="r:gz") as tar:
        for member in tar:
            path = validate_archive_path(member.name)
            is_candidate = path.name == "cursor-agent"
            if member.issym() or member.islnk() or member.isdev() or member.isdir():
                if is_candidate:
                    fail("Cursor artifact CLI candidate must be a regular tar file")
                continue
            if not member.isfile():
                if is_candidate:
                    fail("Cursor artifact CLI candidate must be a regular tar file")
                continue
            if member.size > SOFTWARE_ARTIFACT_MAX_BYTES:
                fail("Cursor artifact CLI binary exceeds the decompressed size limit")
            if not is_candidate:
                continue
            handle = tar.extractfile(member)
            if handle is None:
                fail("Cursor artifact CLI binary could not be read")
            content = handle.read(SOFTWARE_ARTIFACT_MAX_BYTES + 1)
            if len(content) > SOFTWARE_ARTIFACT_MAX_BYTES or len(content) != member.size:
                fail("Cursor artifact CLI binary size changed while reading")
            candidates.append(content)
            if len(candidates) > 1:
                fail("Cursor artifact contains duplicate CLI binary candidates")
    if len(candidates) != 1:
        fail("Cursor artifact must contain exactly one cursor-agent binary")
    return candidates[0]


def atomic_write_with_mode(path: Path, content: bytes, mode: int) -> None:
    ensure_real_directory_path(path.parent, "software file parent")
    temporary = path.with_name(f".{path.name}.nddev.tmp.{os.getpid()}.{time.time_ns()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
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
        if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
            fail(f"{label} must have mode 0700")
        return
    path.mkdir(mode=OWNER_DIRECTORY_MODE, parents=True)
    path.chmod(OWNER_DIRECTORY_MODE)


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
        for key in ("artifact_sha256", "binary_sha256"):
            if not isinstance(stamp[key], str) or not re.fullmatch(r"[0-9a-f]{64}", stamp[key]):
                fail(f"Cursor software stamp {key} must be a lowercase SHA-256 digest")
        if not isinstance(stamp["artifact_size"], int) or stamp["artifact_size"] <= 0:
            fail("Cursor software stamp artifact_size must be a positive integer")
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


def software_file_mode_is(path: Path, mode: int) -> bool:
    info = path.lstat()
    return not stat.S_ISLNK(info.st_mode) and stat.S_IMODE(info.st_mode) == mode


def remove_empty_directory_if_created(path: Path, existed_before: bool) -> None:
    if existed_before:
        return
    with contextlib.suppress(FileNotFoundError, OSError):
        path.rmdir()


def software_status(target: Path) -> dict[str, Any]:
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
        }
    resolve_target(str(target))
    binary = managed_agent_path(target)
    version_binary = software_tree_binary(target)
    installed = False
    drift: list[str] = []
    presence = software_presence(target)
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
        binary_content = read_optional_software_file(binary, f"Cursor managed binary {binary}")
        version_content = read_optional_software_file(
            version_binary, f"Cursor managed version binary {version_binary}"
        )
        binary_digest_ok = (
            binary_content is not None and sha256_bytes(binary_content) == stamp["binary_sha256"]
        )
        version_digest_ok = (
            version_content is not None and sha256_bytes(version_content) == stamp["binary_sha256"]
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
        installed = (
            binary_digest_ok
            and version_digest_ok
            and binary_mode_ok
            and version_mode_ok
            and not directory_mode_drift
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
    }


def prepare_cursor_artifact() -> dict[str, Any]:
    asset_path, expected_sha, expected_size = current_platform_asset()
    source_url = os.environ.get(INTERNAL_ARTIFACT_ENV) or official_asset_url(asset_path)
    archive = read_artifact(source_url)
    artifact_sha = sha256_bytes(archive)
    if os.environ.get(INTERNAL_ARTIFACT_ENV) is None:
        if artifact_sha != expected_sha or len(archive) != expected_size:
            fail("official Cursor artifact digest or size mismatch")
    binary = extract_cursor_agent(archive)
    return {
        "asset_path": asset_path,
        "artifact_sha256": artifact_sha,
        "artifact_size": len(archive),
        "binary": binary,
        "binary_sha256": sha256_bytes(binary),
        "source_url": source_url,
    }


def install_cursor_cli(target: Path, command: str) -> dict[str, Any]:
    if command == "update-cli":
        preflight = software_status(target)
        if not preflight["present"]:
            fail("update-cli requires existing target-owned Cursor CLI software presence")
    before_target_exists = target.exists() or target.is_symlink()
    with target_lock(target):
        ensure_target_directory(target)
        status = software_status(target)
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
        before_container_exists = container.exists() or container.is_symlink()
        before_root_exists = root.exists() or root.is_symlink()
        before_versions_exists = versions.exists() or versions.is_symlink()
        before_bin_dir_exists = bin_dir.exists() or bin_dir.is_symlink()
        before_version_exists = version_dir.exists() or version_dir.is_symlink()
        before_binary, before_binary_mode = snapshot_optional_software_file(
            binary_path, f"Cursor managed binary {binary_path}"
        )
        before_stamp, before_stamp_mode = snapshot_optional_software_file(
            stamp_path, f"Cursor software stamp {stamp_path}"
        )
        stamp_bytes = canonical_json(
            software_stamp(
                target,
                asset_path=artifact["asset_path"],
                artifact_sha256=artifact["artifact_sha256"],
                artifact_size=artifact["artifact_size"],
                binary_sha256=artifact["binary_sha256"],
                source_url=artifact["source_url"],
            )
        )
        changed = [
            "bin/agent",
            ".nddev-software/cursor-cli/versions/2026.07.23-e383d2b/cursor-agent",
        ]
        if before_stamp != stamp_bytes:
            changed.append(f".nddev-software/cursor-cli/{SOFTWARE_STAMP_NAME}")
        staging: Path | None = None
        rollback_parent: Path | None = None
        rollback: Path | None = None
        try:
            ensure_real_directory_path(container, "Cursor software container")
            ensure_real_directory_path(root, "Cursor software root")
            ensure_real_directory_path(versions, "Cursor software versions directory")
            if before_version_exists:
                info = version_dir.lstat()
                if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                    fail("Cursor software version path is unsafe")
                if stat.S_IMODE(info.st_mode) != OWNER_DIRECTORY_MODE:
                    fail("Cursor software version directory must have mode 0700")
            staging = Path(tempfile.mkdtemp(prefix=".stage-", dir=str(versions)))
            rollback_parent = Path(tempfile.mkdtemp(prefix=".rollback-", dir=str(versions)))
            rollback = rollback_parent / CURSOR_VERSION
            atomic_write_executable(staging / "cursor-agent", artifact["binary"])
            if before_version_exists:
                version_dir.rename(rollback)
            staging.rename(version_dir)
            if os.environ.get(INTERNAL_FAIL_AFTER_VERSION_SWAP_ENV) == "1":
                fail("injected failure after Cursor version swap")
            atomic_write_executable(binary_path, artifact["binary"])
            if os.environ.get(INTERNAL_FAIL_AFTER_BINARY_SWAP_ENV) == "1":
                fail("injected failure after Cursor binary swap")
            atomic_write(stamp_path, stamp_bytes)
            final_status = software_status(target)
            if not final_status["installed"]:
                fail(
                    "Cursor software install did not produce a structurally complete target-owned CLI"
                )
            if os.environ.get(INTERNAL_ARTIFACT_ENV) is None:
                if not final_status["current"]:
                    fail("Cursor software install did not produce the current pinned CLI identity")
            else:
                tolerated_identity_drift = {"official_source", "artifact_sha256", "artifact_size"}
                structural_drift = [
                    item for item in final_status["drift"] if item not in tolerated_identity_drift
                ]
                if structural_drift:
                    fail(
                        "Cursor software test artifact produced structural drift: "
                        + ", ".join(structural_drift)
                    )
        except BaseException:
            if version_dir.exists() or version_dir.is_symlink():
                if version_dir.is_dir() and not version_dir.is_symlink():
                    shutil.rmtree(version_dir)
                else:
                    version_dir.unlink()
            if rollback is not None and rollback.exists():
                rollback.rename(version_dir)
            if before_binary is None:
                with contextlib.suppress(FileNotFoundError):
                    binary_path.unlink()
            else:
                atomic_write_with_mode(
                    binary_path, before_binary, before_binary_mode or OWNER_EXEC_MODE
                )
            if before_stamp is None:
                with contextlib.suppress(FileNotFoundError):
                    stamp_path.unlink()
            else:
                atomic_write_with_mode(
                    stamp_path, before_stamp, before_stamp_mode or OWNER_FILE_MODE
                )
            if staging is not None:
                with contextlib.suppress(FileNotFoundError):
                    shutil.rmtree(staging)
            if rollback_parent is not None:
                with contextlib.suppress(FileNotFoundError):
                    shutil.rmtree(rollback_parent)
            remove_empty_directory_if_created(bin_dir, before_bin_dir_exists)
            remove_empty_directory_if_created(versions, before_versions_exists)
            remove_empty_directory_if_created(root, before_root_exists)
            remove_empty_directory_if_created(container, before_container_exists)
            remove_empty_directory_if_created(target, before_target_exists)
            raise
        if rollback_parent is not None:
            with contextlib.suppress(FileNotFoundError):
                shutil.rmtree(rollback_parent)
        final_status = software_status(target)
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
            "managed_command": str(binary_path.resolve(strict=False)),
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


def launch_cursor(target: Path, cursor_args: list[str]) -> int:
    forwarded = cursor_args[1:] if cursor_args[:1] == ["--"] else cursor_args
    reject_managed_launch_overrides(forwarded)
    with target_lock(target):
        require_clean_managed(target)
        software = software_status(target)
        if not software["installed"] or not software["current"]:
            fail("launch requires current target-owned Cursor CLI software")
        child_home = target / ".nddev-cursor-home"
        child_home.mkdir(mode=OWNER_DIRECTORY_MODE, exist_ok=True)
        child_home.chmod(OWNER_DIRECTORY_MODE)
        environment: dict[str, str] = {
            "CURSOR_CONFIG_DIR": str(target.resolve(strict=False)),
            "HOME": str(child_home.resolve(strict=False)),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        for name in ("LANG", "LC_ALL", "LC_CTYPE", "TERM", "COLORTERM", "TMPDIR", "SYSTEMROOT"):
            value = os.environ.get(name)
            if value:
                environment[name] = value
        for name in PROVIDER_SECRET_NAMES:
            environment.pop(name, None)
        executable = managed_agent_path(target)
    completed = subprocess.run([str(executable), *forwarded], env=environment, check=False)
    if completed.returncode < 0:
        return 128 + abs(completed.returncode)
    return completed.returncode


def add_target(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", required=True, help="Absolute Cursor CLI config root.")
    parser.add_argument("--json", action="store_true", dest="output_json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nddev-cursor-cli",
        description="Manage a portable Cursor CLI setup at an explicit target.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List source setups.")
    list_parser.add_argument("--json", action="store_true", dest="output_json")

    status_parser = subparsers.add_parser("status", help="Inspect an explicit target.")
    add_target(status_parser)

    for command in ("plan", "install", "switch"):
        command_parser = subparsers.add_parser(command, help=f"{command.title()} a setup.")
        command_parser.add_argument("--setup", required=True)
        add_target(command_parser)

    software_status_parser = subparsers.add_parser(
        "software-status", help="Inspect target-owned Cursor CLI software."
    )
    add_target(software_status_parser)

    for command in ("install-cli", "update-cli"):
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


def run(args: argparse.Namespace) -> dict[str, Any] | int:
    if args.command == "list":
        return {"schema_version": 1, "command": "list", "setups": list_setups()}
    target = resolve_target(args.target)
    if args.command == "status":
        return {
            "schema_version": 1,
            "command": "status",
            "target": str(target),
            **inspect_target(target),
        }
    if args.command == "plan":
        return plan_setup(target, args.setup)
    if args.command in {"install", "switch"}:
        return mutate_setup(target, args.setup, args.command)
    if args.command == "software-status":
        return software_status(target)
    if args.command in {"install-cli", "update-cli"}:
        return install_cursor_cli(target, args.command)
    if args.command == "restore":
        return restore_slot(target, args.backup)
    if args.command == "remove":
        return remove_setup(target)
    if args.command == "launch":
        return launch_cursor(target, list(args.cursor_args))
    fail(f"unsupported command: {args.command}")


def human_output(value: dict[str, Any]) -> str:
    command = value.get("command")
    if command == "list":
        return "\n".join(f"{item['id']}: {item['description']}" for item in value["setups"])
    if command == "status":
        setup = f" ({value['setup_id']})" if value["setup_id"] else ""
        drift = f"; drift={','.join(value['drift'])}" if value["drift"] else ""
        builder = f"; builder={value['builder_projection']}"
        return f"{value['state']}{setup}: {value['target']}{drift}{builder}"
    if command == "plan":
        changes = ", ".join(value["changes"]) or "none"
        return f"{value['operation']} {value['setup_id']} at {value['target']}; changes: {changes}"
    return json.dumps(value, indent=2, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except (CursorSetupError, OSError) as exc:
        if isinstance(exc, OSError):
            error_message = exc.strerror or type(exc).__name__
            if exc.filename is not None:
                error_message += f" ({exc.filename})"
        else:
            error_message = str(exc)
        if getattr(args, "output_json", False):
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
