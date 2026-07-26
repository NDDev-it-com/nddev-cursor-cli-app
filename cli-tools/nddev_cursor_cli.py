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
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NoReturn

ROOT = Path(__file__).resolve().parents[1]
CATALOG_ROOT = ROOT / "setups"
VERSION = (ROOT / "VERSION").read_text(encoding="ascii").strip()
PRODUCT_NAME = "nddev-cursor-cli-app"
CURSOR_COMMAND = "agent"
CONFIG_NAME = "cli-config.json"
STAMP_NAME = "NDDEV-CURSOR-CLI-SETUP.json"
BACKUP_NAME = "NDDEV-CURSOR-CLI-BACKUP.json"
OWNER_FILE_MODE = 0o600
OWNER_DIRECTORY_MODE = 0o700
METADATA_MAX_BYTES = 256 * 1024
MANAGED_PAYLOAD_MAX_BYTES = 8 * 1024 * 1024
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


def launch_cursor(target: Path, cursor_args: list[str]) -> int:
    forwarded = cursor_args[1:] if cursor_args[:1] == ["--"] else cursor_args
    with target_lock(target):
        require_clean_managed(target)
        child_home = target / ".nddev-cursor-home"
        child_home.mkdir(mode=OWNER_DIRECTORY_MODE, exist_ok=True)
        child_home.chmod(OWNER_DIRECTORY_MODE)
        environment = os.environ.copy()
        environment["CURSOR_CONFIG_DIR"] = str(target)
        environment["HOME"] = str(child_home.resolve(strict=False))
        try:
            completed = subprocess.run([CURSOR_COMMAND, *forwarded], env=environment, check=False)
        except FileNotFoundError:
            fail("Cursor CLI `agent` executable was not found on PATH")
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
