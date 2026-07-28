#!/usr/bin/env python3
"""Validate public nddev-cursor-cli-app contracts without private inputs."""

from __future__ import annotations

import ast
import base64
import contextlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CURSOR_RELEASE_ID = "2026.07.23-e383d2b"
PYTHON_REQUIRES = ">=3.9"
BOOTSTRAP_LOCK_SCOPE = (
    "external product-and-lexical-target flock before target creation or inspection "
    "through full operation and child cleanup"
)
BOOTSTRAP_LOCK_PATH = (
    "/tmp-or-resolved-system-temp/nddev-cursor-cli-app-locks-<uid>/"
    "nddev-cursor-cli-app-<sha256(product-name NUL lexical-target)>.lock"
)
BOOTSTRAP_LOCK_BINDING = "schema/product/lexical-target/product-target-sha256 JSON"
CONTENT_SETUP_IDS = ["nddev-builder"]
PROFILE_IDS = ["full-auto", "safe"]
BUILDER_TARGET_PATH = ".nddev-cursor-home/.cursor/plugins/local/nddev-builder"
REQUIRED_VERSION_KEYS = {
    "build_version",
    "cursor_cli_identity",
    "cursor_cli_tested",
    "cursor_config_schema",
    "nddev_builder_plugin_version",
    "python_requires",
    "runtime_baseline_ref",
    "schema_version",
    "setup_contract_schema",
    "setup_model",
}
EXPECTED_ARTIFACTS = {
    "darwin/arm64/agent-cli-package.tar.gz": {
        "sha256": "f2eb25851f2079dcdf0558a816e06c402d187abfca93255d35167020439ebbf2",
        "size": 69706672,
    },
    "darwin/x64/agent-cli-package.tar.gz": {
        "sha256": "f44194dfcb41468f85bfb4e53978ac098a2a78ce629806490c32b80b40975aa2",
        "size": 71981431,
    },
    "linux/arm64/agent-cli-package.tar.gz": {
        "sha256": "f40b99647cb24e0da885e97620a2048034f1fe8961910d573d827d77c4d26dcb",
        "size": 81115960,
    },
    "linux/x64/agent-cli-package.tar.gz": {
        "sha256": "702ad595213bee5df0268be9f80a19f29fcceaa2a42fc55e39f2b5199051f0c4",
        "size": 82521188,
    },
}
OBSERVED_VENDOR_ASSETS = {
    "unsupported_windows": {
        "product_support": False,
        "unsupported_host_category": "windows",
        "source_template": (
            "https://downloads.cursor.com/lab/2026.07.23-e383d2b/{os}/{arch}/agent-cli-package.zip"
        ),
        "provenance": (
            "official Cursor current-release asset observation only; "
            "not part of supported NDDev product hosts"
        ),
        "verified_date": "2026-07-28",
        "assets": {
            "windows/x64/agent-cli-package.zip": {"size": 63067629},
            "windows/arm64/agent-cli-package.zip": {"size": 58461383},
        },
    }
}
EXPECTED_NATIVE_CAPABILITY_SURFACES = {
    "commands": {
        "official_documentation": "https://cursor.com/docs/reference/plugins",
        "plugin_manifest_key": "commands",
        "product_projection": "installed",
    },
    "hooks": {
        "official_documentation": "https://cursor.com/docs/hooks",
        "plugin_manifest_key": "hooks",
        "product_projection": "not-installed",
    },
    "mcpServers": {
        "official_documentation": "https://cursor.com/docs/mcp",
        "config_key": "mcpServers",
        "plugin_manifest_key": "mcpServers",
        "product_projection": "not-installed",
    },
    "marketplace_manifests": {
        "official_documentation": "https://cursor.com/docs/plugins",
        "plugin_manifest": ".cursor-plugin/plugin.json",
        "product_projection": "local-plugin-only",
    },
    "plugins": {
        "official_documentation": "https://cursor.com/docs/reference/plugins",
        "plugin_manifest": ".cursor-plugin/plugin.json",
        "product_projection": "installed",
    },
    "agents": {
        "official_documentation": "https://cursor.com/docs/subagents",
        "plugin_manifest_key": "agents",
        "product_projection": "installed",
    },
    "skills": {
        "official_documentation": "https://cursor.com/docs/skills",
        "plugin_manifest_key": "skills",
        "product_projection": "installed",
    },
    "rules_instructions": {
        "official_documentation": "https://cursor.com/docs/rules",
        "plugin_manifest_key": "rules",
        "workspace_instruction_file": "AGENTS.md",
        "product_projection": "installed",
    },
    "permissions_config": {
        "official_documentation": "https://cursor.com/docs/cli/reference/configuration",
        "config_file": "cli-config.json",
        "managed_keys": "profiles/<id>/cli-config.json",
        "product_projection": "installed",
    },
    "auth": {
        "official_documentation": "https://cursor.com/docs/cli/reference/configuration",
        "product_projection": "preserved-unmanaged",
    },
    "status": {
        "official_documentation": "https://cursor.com/docs/cli/reference/parameters",
        "manager_command": "status --target <absolute-target> --json",
        "software_command": "software-status --target <absolute-target> --json",
        "product_projection": "observed-by-manager",
    },
}
SOFTWARE_KEYS = {
    "artifact_reader",
    "command",
    "host_platform_preflight",
    "install_command",
    "install_precondition",
    "managed_command",
    "mechanism",
    "npm",
    "official_installer",
    "official_source",
    "pip",
    "presence_signal",
    "remove_command",
    "remove_precondition",
    "rollback_on_failure",
    "stage_and_atomic_swap",
    "status_command",
    "status_fields",
    "supported",
    "update_command",
    "update_current_behavior",
    "update_precondition",
    "version",
}
SOFTWARE_LIFECYCLE_KEYS = {
    "credential_inheritance",
    "entrypoint",
    "failure_current_behavior",
    "install_command",
    "install_precondition",
    "presence_signal",
    "private_modes",
    "remove_command",
    "remove_precondition",
    "rollback_on_swap_failure",
    "software_root",
    "stage_and_atomic_swap",
    "stamp_file",
    "stamp_schema",
    "status_command",
    "status_executes_binary",
    "target_owned",
    "transaction_marker",
    "update_command",
    "update_precondition",
}
STATUS_FIELDS = ["installed", "current", "present", "presence", "drift"]
SUPPORTED_HOST_IDS = [
    "macos-arm64",
    "macos-x64",
    "ubuntu-glibc-arm64",
    "ubuntu-glibc-x64",
]
UNSUPPORTED_HOST_CATEGORIES = [
    "windows",
    "non-ubuntu-linux",
    "linux-musl",
    "unsupported-architecture",
]
VENDOR_ASSET_MAPPING = {
    "macos-arm64": {
        "vendor_os": "darwin",
        "vendor_arch": "arm64",
        "asset_path": "darwin/arm64/agent-cli-package.tar.gz",
    },
    "macos-x64": {
        "vendor_os": "darwin",
        "vendor_arch": "x64",
        "asset_path": "darwin/x64/agent-cli-package.tar.gz",
    },
    "ubuntu-glibc-arm64": {
        "vendor_os": "linux",
        "vendor_arch": "arm64",
        "asset_path": "linux/arm64/agent-cli-package.tar.gz",
    },
    "ubuntu-glibc-x64": {
        "vendor_os": "linux",
        "vendor_arch": "x64",
        "asset_path": "linux/x64/agent-cli-package.tar.gz",
    },
}
PLATFORM_SCOPE = {
    "supported_host_ids": SUPPORTED_HOST_IDS,
    "ubuntu_distribution_id": "ubuntu",
    "ubuntu_libc": "glibc",
    "ubuntu_glibc_version_floor": None,
    "ubuntu_glibc_version_floor_status": "no-official-floor",
    "ubuntu_systems": ["desktop", "server"],
    "unsupported_host_categories": UNSUPPORTED_HOST_CATEGORIES,
    "vendor_asset_mapping": VENDOR_ASSET_MAPPING,
}
BASELINE_PLATFORM_SCOPE = {
    "supported_host_ids": SUPPORTED_HOST_IDS,
    "ubuntu": {
        "distribution_id": "ubuntu",
        "libc": "glibc",
        "glibc_version_floor": None,
        "glibc_version_floor_status": "no-official-floor",
        "systems": ["desktop", "server"],
    },
    "unsupported_host_categories": UNSUPPORTED_HOST_CATEGORIES,
    "vendor_asset_mapping": VENDOR_ASSET_MAPPING,
}
HOST_PLATFORM_PREFLIGHT = (
    "Supported NDDev host IDs are macos-arm64, macos-x64, ubuntu-glibc-arm64, "
    "and ubuntu-glibc-x64. Ubuntu desktop/server hosts must report ID=ubuntu "
    "and glibc; Cursor publishes no official Ubuntu/glibc version floor. "
    "Upstream darwin/* and linux/* artifact paths remain vendor IDs. windows, "
    "non-ubuntu-linux, linux-musl, and unsupported-architecture fail before "
    "bootstrap lock, target lock, target creation, download, stage, or launch"
)
BLOCKED_LAUNCH_OVERRIDES = [
    "--approve-mcps",
    "--force",
    "-f",
    "--network",
    "--sandbox",
    "--skip-worktree-setup",
    "--trust",
    "--worktree",
    "-w",
    "--yolo",
    "acp",
    "install-shell-integration",
    "sandbox",
    "uninstall-shell-integration",
    "update",
    "worker",
]
REQUIRED_BUILDER_REFERENCES = {
    "agents-subagents.md",
    "configuration-profiles.md",
    "hooks.md",
    "installation-lifecycle.md",
    "mcp.md",
    "permissions-sandbox.md",
    "plugins-marketplace.md",
    "skills-instructions.md",
    "validation-release.md",
}
REQUIRED_BUILDER_COMMANDS = {
    "nddev-agent.md",
    "nddev-hook-plan.md",
    "nddev-lifecycle.md",
    "nddev-mcp-plan.md",
    "nddev-permissions.md",
    "nddev-plugin-plan.md",
    "nddev-profile.md",
    "nddev-skill.md",
    "nddev-validate.md",
}
BUILDER_ROOT_FILES = {"README.md"}
BUILDER_COMPONENT_ROOTS = {".cursor-plugin", "agents", "commands", "rules", "skills"}
REQUIRED_ARCHIVE_ROOTS = {
    ".github",
    ".claude",
    "AGENTS.md",
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "SECURITY.md",
    "VERSION",
    "build",
    "cli-tools",
    "config",
    "docs",
    "plugins",
    "profiles",
    "references",
    "setups",
}
REQUIRED_RUNTIME_ROOTS = {
    ".claude",
    "AGENTS.md",
    "LICENSE",
    "README.md",
    "VERSION",
    "build",
    "cli-tools",
    "config",
    "plugins",
    "profiles",
    "references",
    "setups",
}


def load_json(relative: str, errors: list[str]) -> dict | None:
    path = ROOT / relative
    if not path.is_file():
        errors.append(f"missing required contract file: {relative}")
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{relative}: unreadable or invalid JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{relative}: top-level value must be an object")
        return None
    return value


def load_build_version(errors: list[str]) -> str:
    path = ROOT / "VERSION"
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        errors.append(f"VERSION: unreadable: {exc}")
        return ""
    if not value:
        errors.append("VERSION: must not be empty")
    return value


def validate_python39_syntax(errors: list[str]) -> None:
    for path in sorted(ROOT.rglob("*.py"), key=lambda item: item.relative_to(ROOT).as_posix()):
        if "__pycache__" in path.parts:
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{path.relative_to(ROOT)}: unreadable for Python 3.9 syntax check: {exc}")
            continue
        try:
            ast.parse(source, filename=str(path), feature_version=(3, 9))
        except SyntaxError as exc:
            errors.append(
                f"{path.relative_to(ROOT)}: not valid Python 3.9 syntax: "
                f"{exc.msg} at line {exc.lineno}"
            )


def real_dirs(root: Path) -> list[str]:
    if not root.is_dir() or root.is_symlink():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir() and not path.is_symlink())


def validate_launch_contract(owner: str, launch: dict, errors: list[str]) -> None:
    if launch.get("command") != "agent" or launch.get("managed_command") != "bin/agent":
        errors.append(f"{owner}: runtime_launch must use managed bin/agent")
    if launch.get("isolated_home") != ".nddev-cursor-home":
        errors.append(f"{owner}: runtime_launch isolated_home mismatch")
    if (
        launch.get("isolated_home_parent_validation")
        != "component real current-user-owned 0700 before subprocess"
    ):
        errors.append(f"{owner}: runtime_launch isolated_home parent validation mismatch")
    if launch.get("tmpdir") != ".nddev-cursor-runtime/tmp":
        errors.append(f"{owner}: runtime_launch TMPDIR mismatch")
    if (
        launch.get("tmpdir_source")
        != "target-internal real current-user-owned 0700 directory; ambient TMPDIR is not inherited"
    ):
        errors.append(f"{owner}: runtime_launch TMPDIR source mismatch")
    if launch.get("path_policy") != "fixed-minimal-system-path":
        errors.append(f"{owner}: runtime_launch path_policy mismatch")
    if launch.get("path_value") != "/usr/bin:/bin":
        errors.append(f"{owner}: runtime_launch path_value mismatch")
    if launch.get("launcher_shell") != "/bin/bash":
        errors.append(f"{owner}: runtime_launch launcher_shell mismatch")
    if launch.get("path_fallback") is not False:
        errors.append(f"{owner}: runtime_launch.path_fallback must be false")
    if launch.get("requires_current_target_owned_software") is not True:
        errors.append(f"{owner}: runtime_launch must require current target-owned software")
    if launch.get("requires_non_legacy_setup_stamp") is not True:
        errors.append(f"{owner}: runtime_launch must reject legacy setup stamps")
    if launch.get("managed_override_args_blocked") != BLOCKED_LAUNCH_OVERRIDES:
        errors.append(f"{owner}: runtime_launch managed override block list mismatch")
    if launch.get("target_lock_scope") != "preflight-through-child-and-managed-config-restore":
        errors.append(f"{owner}: runtime_launch target lock scope mismatch")
    if (
        launch.get("bootstrap_lock_scope")
        != BOOTSTRAP_LOCK_SCOPE
    ):
        errors.append(f"{owner}: runtime_launch bootstrap lock scope mismatch")
    if launch.get("bootstrap_lock_exposed_to_child") is not False:
        errors.append(f"{owner}: runtime_launch bootstrap lock must not be exposed to child")
    if (
        launch.get("lock_mechanism")
        != "persistent 0600 file opened with O_NOFOLLOW and held by nonblocking fcntl.flock"
    ):
        errors.append(f"{owner}: runtime_launch lock mechanism mismatch")
    if launch.get("lock_parent_mode_while_launching") != "0500":
        errors.append(f"{owner}: runtime_launch lock parent mode mismatch")
    if (
        launch.get("protected_directory_scope")
        != "dedicated lock parent and ephemeral verified launch image only; control root, backup pool, target root, isolated HOME, TMPDIR, config/session paths, and installed runtime tree remain writable"
    ):
        errors.append(f"{owner}: runtime_launch protected directory scope mismatch")
    if launch.get("launch_image") != ".nddev-software/cursor-cli/launch-images/<ephemeral>":
        errors.append(f"{owner}: runtime_launch launch image mismatch")
    if launch.get("launch_image_mode_while_launching") != "0500":
        errors.append(f"{owner}: runtime_launch launch image mode mismatch")
    if (
        launch.get("exec_handoff_revalidation")
        != "verified launch-image executable inode and digest immediately before subprocess"
    ):
        errors.append(f"{owner}: runtime_launch exec handoff revalidation mismatch")
    if (
        launch.get("exec_handoff_boundary")
        != "write-protected verified-path handoff under no-sandbox same-UID limits; no portable fd execution claimed"
    ):
        errors.append(f"{owner}: runtime_launch exec handoff boundary mismatch")


def validate_software(owner: str, software: dict, errors: list[str]) -> None:
    if software.get("version") != CURSOR_RELEASE_ID:
        errors.append(f"{owner}: software_install.version mismatch")
    if software.get("command") != "agent" or software.get("managed_command") != "bin/agent":
        errors.append(f"{owner}: software_install must manage bin/agent")
    for command_key, command_name in (
        ("status_command", "software-status"),
        ("install_command", "install-cli"),
        ("update_command", "update-cli"),
        ("remove_command", "remove-cli"),
    ):
        if command_name not in str(software.get(command_key, "")):
            errors.append(f"{owner}: software_install.{command_key} mismatch")
    if software.get("npm") is not None or software.get("pip") is not None:
        errors.append(f"{owner}: software_install must not declare npm/pip install")
    if "present=true" not in str(software.get("presence_signal", "")):
        errors.append(f"{owner}: software_install.presence_signal mismatch")
    if software.get("status_fields") != STATUS_FIELDS:
        errors.append(f"{owner}: software_install.status_fields mismatch")
    if software.get("host_platform_preflight") != HOST_PLATFORM_PREFLIGHT:
        errors.append(f"{owner}: software_install host platform preflight mismatch")


def validate_runtime_compatibility(owner: str, compatibility: dict, errors: list[str]) -> None:
    expected_keys = {"baseline_ref", "version_ref", *PLATFORM_SCOPE}
    if set(compatibility) != expected_keys:
        errors.append(f"{owner}: runtime_compatibility keys mismatch")
    if compatibility.get("baseline_ref") != "references/cursor-cli-baseline.json":
        errors.append(f"{owner}: runtime_compatibility baseline mismatch")
    if compatibility.get("version_ref") != "build/version.json":
        errors.append(f"{owner}: runtime_compatibility version ref mismatch")
    for key, expected in PLATFORM_SCOPE.items():
        if compatibility.get(key) != expected:
            errors.append(f"{owner}: runtime_compatibility {key} mismatch")


def validate_profiles(errors: list[str]) -> None:
    setup_dirs = real_dirs(ROOT / "setups")
    profile_dirs = real_dirs(ROOT / "profiles")
    if setup_dirs != CONTENT_SETUP_IDS:
        errors.append(f"setups/: expected {CONTENT_SETUP_IDS}, got {setup_dirs}")
    if profile_dirs != PROFILE_IDS:
        errors.append(f"profiles/: expected {PROFILE_IDS}, got {profile_dirs}")
    setup = load_json("setups/nddev-builder/setup.json", errors)
    if setup is not None:
        if setup.get("id") != "nddev-builder":
            errors.append("setups/nddev-builder/setup.json: id mismatch")
        if setup.get("managed_files") != ["cli-config.json"]:
            errors.append("setups/nddev-builder/setup.json: managed_files mismatch")
        if setup.get("builder_projection") != "default-on":
            errors.append("setups/nddev-builder/setup.json: builder must be default-on")
        if setup.get("plugin_id") != "nddev-builder":
            errors.append("setups/nddev-builder/setup.json: plugin_id mismatch")
    expectations = {
        "full-auto": {
            "approvalMode": "unrestricted",
            "sandbox": {"mode": "disabled", "networkAccess": "enabled"},
            "allow": [],
            "deny": [],
        },
        "safe": {
            "approvalMode": "allowlist",
            "sandbox": {"mode": "enabled", "networkAccess": "disabled"},
            "allow": ["Shell(cat)", "Shell(git status)", "Shell(ls)", "Shell(pwd)"],
            "deny": ["Shell(curl)", "Shell(rm)", "Shell(sudo)", "Shell(wget)"],
        },
    }
    for profile_id, expected in expectations.items():
        metadata = load_json(f"profiles/{profile_id}/profile.json", errors)
        config = load_json(f"profiles/{profile_id}/cli-config.json", errors)
        if metadata is not None:
            if metadata.get("id") != profile_id:
                errors.append(f"profiles/{profile_id}/profile.json: id mismatch")
            if metadata.get("managed_files") != ["cli-config.json"]:
                errors.append(f"profiles/{profile_id}/profile.json: managed_files mismatch")
            if metadata.get("approval_mode") != expected["approvalMode"]:
                errors.append(f"profiles/{profile_id}/profile.json: approval_mode mismatch")
            if metadata.get("sandbox_mode") != expected["sandbox"]["mode"]:
                errors.append(f"profiles/{profile_id}/profile.json: sandbox_mode mismatch")
            if metadata.get("network_access") != expected["sandbox"]["networkAccess"]:
                errors.append(f"profiles/{profile_id}/profile.json: network_access mismatch")
        if config is not None:
            if config.get("version") != 1:
                errors.append(f"profiles/{profile_id}/cli-config.json: version must be 1")
            if config.get("approvalMode") != expected["approvalMode"]:
                errors.append(f"profiles/{profile_id}/cli-config.json: approvalMode mismatch")
            if config.get("sandbox") != expected["sandbox"]:
                errors.append(f"profiles/{profile_id}/cli-config.json: sandbox mismatch")
            permissions = config.get("permissions", {})
            if permissions.get("allow") != expected["allow"]:
                errors.append(f"profiles/{profile_id}/cli-config.json: allow mismatch")
            if permissions.get("deny") != expected["deny"]:
                errors.append(f"profiles/{profile_id}/cli-config.json: deny mismatch")
            if config.get("approvalMode") == "auto-review":
                errors.append(f"profiles/{profile_id}/cli-config.json: unsupported approvalMode")


def validate_builder_toolkit(version: dict | None, build_version: str, errors: list[str]) -> None:
    plugin = load_json("plugins/nddev-builder/.cursor-plugin/plugin.json", errors)
    if plugin is not None:
        if plugin.get("name") != "nddev-builder":
            errors.append("plugins/nddev-builder: plugin name must be nddev-builder")
        if plugin.get("version") != build_version:
            errors.append("plugins/nddev-builder: version disagrees with VERSION")
        if version is not None and plugin.get("version") != version.get(
            "nddev_builder_plugin_version"
        ):
            errors.append(
                "plugins/nddev-builder: version disagrees with "
                "build/version.json:nddev_builder_plugin_version"
            )
        for key in ("rules", "skills", "agents", "commands"):
            if key not in plugin:
                errors.append(f"plugins/nddev-builder: missing component key {key}")
        for unsupported_key in ("hooks", "mcpServers"):
            if unsupported_key in plugin:
                errors.append(f"plugins/nddev-builder: must not activate {unsupported_key}")
    required_files = [
        "plugins/nddev-builder/README.md",
        "plugins/nddev-builder/rules/nddev-builder.mdc",
        "plugins/nddev-builder/skills/nddev-builder/SKILL.md",
        "plugins/nddev-builder/agents/nddev-builder.md",
        "plugins/nddev-builder/skills/nddev-builder/scripts/validate-toolkit.py",
    ]
    required_files.extend(
        f"plugins/nddev-builder/skills/nddev-builder/references/{name}"
        for name in sorted(REQUIRED_BUILDER_REFERENCES)
    )
    required_files.extend(
        f"plugins/nddev-builder/commands/{name}" for name in sorted(REQUIRED_BUILDER_COMMANDS)
    )
    for relative in required_files:
        if not (ROOT / relative).is_file():
            errors.append(f"missing builder toolkit file: {relative}")
    entry = ROOT / "plugins/nddev-builder/skills/nddev-builder/SKILL.md"
    if entry.is_file():
        text = entry.read_text(encoding="utf-8")
        for name in REQUIRED_BUILDER_REFERENCES:
            if f"references/{name}" not in text:
                errors.append(f"builder SKILL.md does not route to references/{name}")

    validate_builder_projection_parity(errors)


def expected_builder_projection_files(errors: list[str]) -> set[str]:
    plugin_root = ROOT / "plugins" / "nddev-builder"
    expected: set[str] = set()
    for name in BUILDER_ROOT_FILES:
        source = plugin_root / name
        if not source.is_file() or source.is_symlink():
            errors.append(f"missing projected builder root file: plugins/nddev-builder/{name}")
            continue
        expected.add(f"{BUILDER_TARGET_PATH}/{name}")
    for component in BUILDER_COMPONENT_ROOTS:
        root = plugin_root / component
        if not root.is_dir() or root.is_symlink():
            errors.append(f"missing projected builder component directory: {component}")
            continue
        for source in sorted(root.rglob("*")):
            if source.is_symlink():
                errors.append(f"builder source must not be a symlink: {source.relative_to(ROOT)}")
                continue
            if source.is_file():
                expected.add(f"{BUILDER_TARGET_PATH}/{source.relative_to(plugin_root).as_posix()}")
    return expected


def validate_builder_projection_parity(errors: list[str]) -> None:
    expected = expected_builder_projection_files(errors)
    sys.dont_write_bytecode = True
    manager_path = ROOT / "cli-tools" / "nddev_cursor_cli.py"
    spec = importlib.util.spec_from_file_location("_nddev_cursor_cli_contract", manager_path)
    if spec is None or spec.loader is None:
        errors.append("cannot load nddev_cursor_cli.py for projection parity")
        return
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        actual = set(module.builder_projection_files())
    except Exception as exc:  # noqa: BLE001 - validator must report safe public errors.
        errors.append(f"cannot evaluate manager builder projection: {exc}")
        return
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        errors.append(
            "manager builder projection does not match toolkit files "
            f"(missing={missing}, extra={extra})"
        )


def release_workflow_roots(field: str, errors: list[str]) -> set[str]:
    path = ROOT / ".github" / "workflows" / "release.yml"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f".github/workflows/release.yml: unreadable: {exc}")
        return set()
    roots: list[str] = []
    collecting = False
    for line in lines:
        if not collecting:
            if line.strip() == f"{field}: >-":
                collecting = True
            continue
        if line.startswith("        "):
            roots.extend(line.split())
            continue
        break
    if not collecting:
        errors.append(f".github/workflows/release.yml: missing {field}")
    return set(roots)


def validate_release_roots(errors: list[str]) -> None:
    for field, required in (
        ("archive_paths", REQUIRED_ARCHIVE_ROOTS),
        ("runtime_paths", REQUIRED_RUNTIME_ROOTS),
    ):
        roots = release_workflow_roots(field, errors)
        missing = sorted(required - roots)
        if missing:
            errors.append(f".github/workflows/release.yml: {field} missing {missing}")
        for root in sorted(roots):
            if not (ROOT / root).exists():
                errors.append(f".github/workflows/release.yml: {field} root missing: {root}")
    runtime_roots = release_workflow_roots("runtime_paths", errors)
    for root in ("AGENTS.md", ".claude"):
        if root not in runtime_roots:
            errors.append(f".github/workflows/release.yml: runtime_paths missing {root}")


def validate_agents_onboarding_contract(errors: list[str]) -> None:
    path = ROOT / "AGENTS.md"
    try:
        info = path.lstat()
    except OSError as exc:
        errors.append(f"AGENTS.md: cannot lstat: {exc}")
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        errors.append("AGENTS.md: must be a real regular file")
        return
    try:
        content = path.read_bytes()
    except OSError as exc:
        errors.append(f"AGENTS.md: unreadable: {exc}")
        return
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"AGENTS.md: not UTF-8: {exc}")
        return
    if "GDS repository contract" in text or "GENERATED FILE - DO NOT EDIT DIRECTLY" in text:
        errors.append("AGENTS.md: must not duplicate generated GDS policy")
    bridge_root = ROOT / ".claude"
    try:
        bridge_root_info = bridge_root.lstat()
    except OSError as exc:
        errors.append(f".claude: cannot lstat: {exc}")
        return
    if stat.S_ISLNK(bridge_root_info.st_mode) or not stat.S_ISDIR(bridge_root_info.st_mode):
        errors.append(".claude: must be a real directory")
        return
    entries = sorted(path.name for path in bridge_root.iterdir())
    if entries != ["CLAUDE.md"]:
        errors.append(f".claude: entries must be exactly ['CLAUDE.md'], got {entries}")
    bridge = bridge_root / "CLAUDE.md"
    try:
        bridge_info = bridge.lstat()
    except OSError as exc:
        errors.append(f".claude/CLAUDE.md: cannot lstat: {exc}")
        return
    if stat.S_ISLNK(bridge_info.st_mode) or not stat.S_ISREG(bridge_info.st_mode):
        errors.append(".claude/CLAUDE.md: must be a real regular file")
        return
    try:
        bridge_content = bridge.read_bytes()
    except OSError as exc:
        errors.append(f".claude/CLAUDE.md: unreadable: {exc}")
        return
    if bridge_content != b"@../AGENTS.md\n":
        errors.append(".claude/CLAUDE.md: exact import bytes mismatch")


def load_manager(errors: list[str]) -> Any | None:
    sys.dont_write_bytecode = True
    manager_path = ROOT / "cli-tools" / "nddev_cursor_cli.py"
    spec = importlib.util.spec_from_file_location("_nddev_cursor_cli_public_smoke", manager_path)
    if spec is None or spec.loader is None:
        errors.append("cannot load nddev_cursor_cli.py")
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - validator must report safe public errors.
        errors.append(f"cannot import nddev_cursor_cli.py: {exc}")
        return None
    return module


def with_restored_attr(module: Any, name: str, value: Any):
    class RestoreAttr:
        def __enter__(self) -> None:
            self.original = getattr(module, name)
            setattr(module, name, value)

        def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
            setattr(module, name, self.original)

    return RestoreAttr()


def real_bootstrap_artifact_snapshot(module: Any, errors: list[str]) -> tuple[tuple, ...]:
    try:
        system_root = module.bootstrap_lock_system_root()
    except Exception as exc:  # noqa: BLE001 - validator must report safe public errors.
        errors.append(f"cannot resolve production bootstrap system root: {exc}")
        return tuple()
    product_root = system_root / f"{module.BOOTSTRAP_LOCK_ROOT_PREFIX}-{os.getuid()}"
    try:
        root_info = product_root.lstat()
    except FileNotFoundError:
        return tuple()
    except OSError as exc:
        errors.append(f"cannot inspect production bootstrap root: {exc}")
        return tuple()
    records: list[tuple] = [
        (
            "root",
            product_root.name,
            root_info.st_dev,
            root_info.st_ino,
            root_info.st_uid,
            stat.S_IMODE(root_info.st_mode),
            root_info.st_size,
        )
    ]
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        return tuple(records)
    try:
        children = sorted(product_root.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        errors.append(f"cannot list production bootstrap root: {exc}")
        return tuple(records)
    for child in children:
        try:
            child_info = child.lstat()
        except OSError as exc:
            records.append(("unreadable", child.name, str(exc)))
            continue
        records.append(
            (
                "entry",
                child.name,
                child_info.st_dev,
                child_info.st_ino,
                child_info.st_uid,
                stat.S_IMODE(child_info.st_mode),
                child_info.st_size,
            )
        )
    return tuple(records)


def run_manager_smoke(name: str, action: Any, errors: list[str]) -> None:
    try:
        action()
    except Exception as exc:  # noqa: BLE001 - public validator reports instead of traceback.
        errors.append(f"{name} smoke raised unexpectedly: {exc}")


def run_forked_action(action: Any) -> subprocess.CompletedProcess[str]:
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            action()
        except BaseException as exc:  # noqa: BLE001 - serialize public smoke failure.
            payload = {"returncode": 1, "stdout": "", "stderr": str(exc)}
        else:
            payload = {"returncode": 0, "stdout": "ok", "stderr": ""}
        os.write(write_fd, (json.dumps(payload) + "\n").encode("utf-8"))
        os.close(write_fd)
        os._exit(0)
    os.close(write_fd)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(read_fd, 65536)
        if not chunk:
            break
        chunks.append(chunk)
    os.close(read_fd)
    _, status = os.waitpid(pid, 0)
    if os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0:
        payload = json.loads(b"".join(chunks).decode("utf-8"))
        return subprocess.CompletedProcess(
            args=["forked-action"],
            returncode=int(payload["returncode"]),
            stdout=str(payload["stdout"]),
            stderr=str(payload["stderr"]),
        )
    return subprocess.CompletedProcess(
        args=["forked-action"],
        returncode=1,
        stdout="",
        stderr=f"forked action exited abnormally: {status}",
    )


def start_deferred_forked_action(
    action: Any, ready: Path, trigger: Path, result: Path, error: Path
) -> int:
    pid = os.fork()
    if pid == 0:
        try:
            ready.write_text("ready\n", encoding="utf-8")
            deadline = time.time() + 10
            while not trigger.exists():
                if time.time() > deadline:
                    raise TimeoutError("deferred action trigger timeout")
                time.sleep(0.02)
            try:
                action()
            except BaseException as exc:  # noqa: BLE001 - serialize public smoke failure.
                payload = {"returncode": 1, "stdout": "", "stderr": str(exc)}
            else:
                payload = {"returncode": 0, "stdout": "ok", "stderr": ""}
            result.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        except BaseException as exc:  # noqa: BLE001 - serialize public smoke failure.
            error.write_text(str(exc), encoding="utf-8")
            os._exit(1)
        os._exit(0)
    return pid


def wait_for_process_ready(
    pid: int, ready: Path, error: Path, errors: list[str], label: str
) -> bool:
    deadline = time.time() + 5
    while time.time() < deadline:
        if ready.exists():
            return True
        exited, status = os.waitpid(pid, os.WNOHANG)
        if exited:
            message = error.read_text(encoding="utf-8") if error.exists() else str(status)
            errors.append(f"{label} exited before ready: {message}")
            return False
        time.sleep(0.02)
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    errors.append(f"{label} did not become ready")
    return False


def trigger_deferred_action(
    pid: int, trigger: Path, result: Path, error: Path, errors: list[str], label: str
) -> subprocess.CompletedProcess[str]:
    trigger.write_text("go\n", encoding="utf-8")
    deadline = time.time() + 5
    while time.time() < deadline:
        exited, status = os.waitpid(pid, os.WNOHANG)
        if not exited:
            time.sleep(0.02)
            continue
        if os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0:
            try:
                payload = json.loads(result.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return subprocess.CompletedProcess(
                    args=[label],
                    returncode=1,
                    stdout="",
                    stderr=f"deferred action result unreadable: {exc}",
                )
            return subprocess.CompletedProcess(
                args=[label],
                returncode=int(payload["returncode"]),
                stdout=str(payload["stdout"]),
                stderr=str(payload["stderr"]),
            )
        message = error.read_text(encoding="utf-8") if error.exists() else str(status)
        return subprocess.CompletedProcess(
            args=[label],
            returncode=1,
            stdout="",
            stderr=f"deferred action exited abnormally: {message}",
        )
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    errors.append(f"{label} did not finish after trigger")
    return subprocess.CompletedProcess(args=[label], returncode=1, stdout="", stderr="timeout")


def prepare_deferred_action(
    action: Any, root: Path, name: str, errors: list[str]
) -> tuple[int, Path, Path, Path]:
    ready = root / f"{name}.ready"
    trigger = root / f"{name}.trigger"
    result = root / f"{name}.json"
    error = root / f"{name}.error"
    pid = start_deferred_forked_action(action, ready, trigger, result, error)
    if not wait_for_process_ready(pid, ready, error, errors, name):
        pid = 0
    return pid, trigger, result, error


def assert_deferred_action_denied(
    deferred: tuple[int, Path, Path, Path],
    errors: list[str],
    label: str,
    command: str,
) -> None:
    pid, trigger, result, error = deferred
    if pid <= 0:
        return
    completed = trigger_deferred_action(pid, trigger, result, error, errors, label)
    output = f"{completed.stdout}\n{completed.stderr}"
    if completed.returncode == 0:
        errors.append(f"{label} allowed concurrent lifecycle {command}")
    elif "already locked" not in output:
        errors.append(f"{label} concurrent {command} failed with unexpected output: {output}")


def run_concurrent_switch(
    module: Any, target: Path, profile: str = "safe"
) -> subprocess.CompletedProcess[str]:
    return run_forked_action(
        lambda: module.mutate_setup(target, "nddev-builder", profile, "switch")
    )


def run_concurrent_install(
    module: Any, target: Path, profile: str = "safe"
) -> subprocess.CompletedProcess[str]:
    return run_forked_action(
        lambda: module.mutate_setup(target, "nddev-builder", profile, "install")
    )


def run_concurrent_remove(module: Any, target: Path) -> subprocess.CompletedProcess[str]:
    return run_forked_action(lambda: module.remove_setup(target))


def run_concurrent_status(module: Any, target: Path) -> subprocess.CompletedProcess[str]:
    return run_forked_action(lambda: module.inspect_target(target))


def assert_concurrent_switch_denied(
    module: Any, target: Path, errors: list[str], label: str
) -> None:
    result = run_concurrent_switch(module, target)
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode == 0:
        errors.append(f"{label} allowed concurrent lifecycle switch")
    elif "already locked" not in output:
        errors.append(f"{label} concurrent switch failed with unexpected output: {output}")


def assert_concurrent_command_denied(
    action: Any, errors: list[str], label: str, command: str
) -> None:
    result = action()
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode == 0:
        errors.append(f"{label} allowed concurrent lifecycle {command}")
    elif "already locked" not in output:
        errors.append(f"{label} concurrent {command} failed with unexpected output: {output}")


def wait_for_holder_ready(
    pid: int, ready: Path, error: Path, errors: list[str], label: str
) -> bool:
    deadline = time.time() + 5
    while time.time() < deadline:
        if ready.exists():
            return True
        exited, status = os.waitpid(pid, os.WNOHANG)
        if exited:
            message = error.read_text(encoding="utf-8") if error.exists() else str(status)
            errors.append(f"{label} holder exited early: {message}")
            return False
        time.sleep(0.02)
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    errors.append(f"{label} holder did not become ready")
    return False


def wait_for_holder_exit(pid: int, error: Path, errors: list[str], label: str) -> bool:
    deadline = time.time() + 5
    while time.time() < deadline:
        exited, status = os.waitpid(pid, os.WNOHANG)
        if not exited:
            time.sleep(0.02)
            continue
        if os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0:
            return True
        message = error.read_text(encoding="utf-8") if error.exists() else str(status)
        errors.append(f"{label} failed: {message}")
        return False
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    errors.append(f"{label} did not exit after release")
    return False


def start_bootstrap_lock_holder(
    module: Any, target: Path, ready: Path, release: Path, result: Path, error: Path
) -> int:
    pid = os.fork()
    if pid == 0:
        try:
            with module.bootstrap_lifecycle_lock(target):
                path, lexical, digest = module.bootstrap_lock_path(target)
                info = path.lstat()
                result.write_text(
                    json.dumps(
                        {
                            "path": str(path),
                            "lexical": lexical,
                            "digest": digest,
                            "device": info.st_dev,
                            "inode": info.st_ino,
                        },
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                ready.write_text("ready\n", encoding="utf-8")
                while not release.exists():
                    time.sleep(0.02)
        except BaseException as exc:  # noqa: BLE001 - serialize public smoke failure.
            error.write_text(str(exc), encoding="utf-8")
            os._exit(1)
        os._exit(0)
    return pid


def validate_artifact_source_smokes(module: Any, errors: list[str]) -> None:
    manager_source = (ROOT / "cli-tools" / "nddev_cursor_cli.py").read_text(encoding="utf-8")
    disallowed_source_patterns = {
        "NDDEV test switch": r"NDDEV_[A-Z0-9_]*TEST[A-Z0-9_]*",
        "ALLOW_TEST switch": r"ALLOW_TEST[A-Z0-9_]*",
        "fixture override": r"(?:FIXTURE|SOURCE_OVERRIDE|ARTIFACT_URL|TEST_TIMEOUT)",
        "artificial failure switch": r"(?:FAIL_AFTER|INTERNAL_FAIL)",
        "local artifact scheme": r"file://",
    }
    for label, pattern in disallowed_source_patterns.items():
        if re.search(pattern, manager_source):
            errors.append(f"nddev_cursor_cli.py must not expose {label}")
    for needle in ("fcntl.flock", "fcntl.LOCK_EX | fcntl.LOCK_NB", "O_NOFOLLOW"):
        if needle not in manager_source:
            errors.append(f"nddev_cursor_cli.py must keep verified lock fd evidence: {needle}")
    for needle in (
        "bootstrap_lifecycle_lock",
        "BOOTSTRAP_LOCK_ROOT_PREFIX",
        "CONTROL_LOCKS_NAME",
        "control_lock_root",
        "open_control_lock_root_fd",
        "set_owner_directory_fd_mode",
        "validate_or_write_bootstrap_binding",
        "read_valid_bootstrap_binding",
        'require_lock_file_matches_fd(path, descriptor, "bootstrap lock")',
        "require_directory_matches_fd",
        "threading.get_ident()",
        'PRODUCT_NAME.encode("utf-8") + b"\\0" + lexical.encode("utf-8")',
        'Path("/tmp").resolve(strict=True)',
        "stat.S_ISVTX",
        'f"{PRODUCT_NAME}-{digest}.lock"',
    ):
        if needle not in manager_source:
            errors.append(f"nddev_cursor_cli.py must keep bootstrap lock evidence: {needle}")
    if re.search(r"bootstrap.*unlink|unlink.*bootstrap", manager_source, re.IGNORECASE):
        errors.append("nddev_cursor_cli.py must not unlink bootstrap lock files")
    if re.search(r"os\.environ[^\n]*BOOTSTRAP|BOOTSTRAP[^\n]*os\.environ", manager_source):
        errors.append("nddev_cursor_cli.py must not expose a bootstrap lock env override")

    artifact = b"official artifact bytes"
    asset_path = "linux/x64/agent-cli-package.tar.gz"
    expected_sha = module.sha256_bytes(artifact)
    seen_sources: list[str] = []

    def fake_current_platform_asset() -> tuple[str, str, int]:
        return asset_path, expected_sha, len(artifact)

    def fake_read_artifact(source: str) -> bytes:
        seen_sources.append(source)
        return artifact

    runtime = {
        "files": {"cursor-agent": (b"agent", module.OWNER_EXEC_MODE)},
        "binary": b"agent",
        "binary_sha256": module.sha256_bytes(b"agent"),
        "runtime_tree_sha256": module.sha256_bytes(b"tree"),
        "runtime_size": 1,
        "runtime_file_count": 3,
    }
    old_env = os.environ.get("NDDEV_CURSOR_CLI_TEST_ARTIFACT_URL")
    os.environ["NDDEV_CURSOR_CLI_TEST_ARTIFACT_URL"] = "file:///tmp/unpinned.tar.gz"
    try:
        with (
            with_restored_attr(module, "current_platform_asset", fake_current_platform_asset),
            with_restored_attr(module, "read_artifact", fake_read_artifact),
            with_restored_attr(module, "extract_cursor_runtime", lambda archive: runtime),
        ):
            result = module.prepare_cursor_artifact()
    finally:
        if old_env is None:
            os.environ.pop("NDDEV_CURSOR_CLI_TEST_ARTIFACT_URL", None)
        else:
            os.environ["NDDEV_CURSOR_CLI_TEST_ARTIFACT_URL"] = old_env
    expected_source = module.official_asset_url(asset_path)
    if seen_sources != [expected_source]:
        errors.append("prepare_cursor_artifact did not ignore untrusted artifact env override")
    if result.get("source_url") != expected_source:
        errors.append("prepare_cursor_artifact returned a non-official artifact source")

    def fake_wrong_read_artifact(source: str) -> bytes:
        del source
        return b"wrong artifact bytes"

    with (
        with_restored_attr(module, "current_platform_asset", fake_current_platform_asset),
        with_restored_attr(module, "read_artifact", fake_wrong_read_artifact),
    ):
        try:
            module.prepare_cursor_artifact()
        except module.CursorSetupError as exc:
            if "digest or size mismatch" not in str(exc):
                errors.append("wrong artifact failure did not report digest/size mismatch")
        else:
            errors.append("prepare_cursor_artifact accepted wrong artifact bytes")

    try:
        module.read_artifact("file:///tmp/unpinned.tar.gz")
    except module.CursorSetupError:
        pass
    else:
        errors.append("read_artifact accepted a non-official artifact source")


def validate_sibling_control_state_ignored_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-sibling-control-smoke-") as tmp:
        root = Path(tmp)
        target = root / "target"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        external = root / "external"
        external.mkdir(mode=0o700)
        marker = external / "marker"
        marker.write_text("preserve\n", encoding="utf-8")
        sibling_lock = target.parent / f".{target.name}.nddev-cursor-cli-lock"
        sibling_lock.mkdir(mode=0o700)
        os.symlink(external, target.parent / f".{target.name}.nddev-cursor-cli-backups")
        result = module.mutate_setup(target, "nddev-builder", "safe", "switch")
        if result.get("backup_slot") != 0:
            errors.append("sibling control smoke did not create internal backup slot 0")
        if not (module.backup_pool(target) / "0" / module.BACKUP_NAME).is_file():
            errors.append("sibling control smoke did not use target-internal backup pool")
        if not marker.is_file():
            errors.append("sibling control smoke removed external marker")
        if not sibling_lock.is_dir():
            errors.append("sibling control smoke removed sibling lock")


def validate_insecure_internal_control_state_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-internal-control-smoke-") as tmp:
        root = Path(tmp)

        target = root / "root-symlink"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        external = root / "external-root"
        external.mkdir(mode=0o700)
        control = module.control_root(target)
        lock_root = module.control_lock_root(target)
        module.target_lock_path(target).unlink()
        lock_root.rmdir()
        control.rmdir()
        os.symlink(external, module.control_root(target))
        try:
            module.mutate_setup(target, "nddev-builder", "safe", "switch")
        except module.CursorSetupError as exc:
            if "control root" not in str(exc):
                errors.append("internal control root symlink failed with unexpected error")
        else:
            errors.append("internal control root symlink was accepted")

        target = root / "lock-root-symlink"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        lock_root = module.control_lock_root(target)
        module.target_lock_path(target).unlink()
        lock_root.rmdir()
        os.symlink(external, lock_root)
        state = module.inspect_target(target)
        if ".nddev-cursor-cli/locks:unsafe" not in state["drift"] or state["launchable"]:
            errors.append("internal lock directory symlink did not block launchable status")
        try:
            module.mutate_setup(target, "nddev-builder", "safe", "switch")
        except module.CursorSetupError as exc:
            if "target lock directory" not in str(exc):
                errors.append("internal lock directory symlink failed with unexpected error")
        else:
            errors.append("internal lock directory symlink was accepted")

        target = root / "lock-symlink"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        lock = module.target_lock_path(target)
        lock.unlink()
        os.symlink(external, lock)
        try:
            module.mutate_setup(target, "nddev-builder", "safe", "switch")
        except module.CursorSetupError as exc:
            if "target lock path is unsafe" not in str(exc):
                errors.append("internal lock symlink failed with unexpected error")
        else:
            errors.append("internal lock symlink was accepted")

        target = root / "lock-root-mode"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        lock_root = module.control_lock_root(target)
        lock_root.chmod(0o755)
        state = module.inspect_target(target)
        if ".nddev-cursor-cli/locks:mode" not in state["drift"] or state["launchable"]:
            errors.append("internal lock directory mode did not block launchable status")
        try:
            module.mutate_setup(target, "nddev-builder", "safe", "switch")
        except module.CursorSetupError as exc:
            if "target lock directory must have mode 0500 or 0700" not in str(exc):
                errors.append("internal lock directory mode failed with unexpected error")
        else:
            errors.append("internal lock directory mode was accepted")

        target = root / "backup-symlink"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        control = module.ensure_control_root(target)
        os.symlink(external, control / module.CONTROL_BACKUPS_NAME)
        try:
            module.mutate_setup(target, "nddev-builder", "safe", "switch")
        except module.CursorSetupError as exc:
            if "backup pool" not in str(exc):
                errors.append("internal backup symlink failed with unexpected error")
        else:
            errors.append("internal backup symlink was accepted")

        target = root / "backup-mode"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        control = module.ensure_control_root(target)
        backups = control / module.CONTROL_BACKUPS_NAME
        backups.mkdir(mode=0o700)
        backups.chmod(0o755)
        try:
            module.mutate_setup(target, "nddev-builder", "safe", "switch")
        except module.CursorSetupError as exc:
            if "backup pool must have mode 0700" not in str(exc):
                errors.append("internal backup mode failed with unexpected error")
        else:
            errors.append("internal backup mode was accepted")

        target = root / "backup-hardlink"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        control = module.ensure_control_root(target)
        backups = control / module.CONTROL_BACKUPS_NAME
        module.ensure_backup_pool(backups)
        slot = backups / "0"
        slot.mkdir(mode=module.OWNER_DIRECTORY_MODE)
        slot.chmod(module.OWNER_DIRECTORY_MODE)
        original = root / "hardlink-source"
        original.write_bytes(b"{}\n")
        original.chmod(module.OWNER_FILE_MODE)
        os.link(original, slot / module.BACKUP_NAME)
        try:
            module.restore_slot(target, 0)
        except module.CursorSetupError as exc:
            if "hard-link aliases" not in str(exc):
                errors.append("internal backup hardlink failed with unexpected error")
        else:
            errors.append("internal backup hardlink was accepted")


def validate_backup_rotation_and_binding_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-backup-rotation-smoke-") as tmp:
        root = Path(tmp)
        target = root / "target"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        slots: list[int] = []
        profile = "safe"
        for _ in range(11):
            result = module.mutate_setup(target, "nddev-builder", profile, "switch")
            slot = result.get("backup_slot")
            if not isinstance(slot, int):
                errors.append("backup rotation smoke did not report an integer backup slot")
                return
            slots.append(slot)
            profile = "full-auto" if profile == "safe" else "safe"
        pool = module.backup_pool(target)
        if pool.parent != module.control_root(target):
            errors.append("backup rotation smoke backup pool is not control-root internal")
        real_slots = sorted(
            path.name for path in pool.iterdir() if path.is_dir() and not path.is_symlink()
        )
        if real_slots != [str(slot) for slot in range(10)]:
            errors.append(f"backup rotation smoke expected slots 0..9, got {real_slots}")
        if len(set(slots)) != 10 or len(slots) != 11:
            errors.append(f"backup rotation smoke did not rotate bounded slots: {slots}")
        for slot in range(10):
            try:
                envelope = module.load_backup(target, slot)
            except module.CursorSetupError as exc:
                errors.append(f"backup rotation smoke could not load slot {slot}: {exc}")
                continue
            if envelope.get("canonical_target") != str(target.resolve(strict=False)):
                errors.append(f"backup slot {slot} canonical target mismatch")
        other = root / "other"
        module.mutate_setup(other, "nddev-builder", "full-auto", "install")
        module.ensure_control_root(other)
        other_pool = module.backup_pool(other)
        module.ensure_backup_pool(other_pool)
        other_slot = other_pool / "0"
        other_slot.mkdir(mode=module.OWNER_DIRECTORY_MODE)
        other_slot.chmod(module.OWNER_DIRECTORY_MODE)
        copied = (pool / "0" / module.BACKUP_NAME).read_bytes()
        copied_path = other_slot / module.BACKUP_NAME
        copied_path.write_bytes(copied)
        copied_path.chmod(module.OWNER_FILE_MODE)
        try:
            module.load_backup(other, 0)
        except module.CursorSetupError as exc:
            if "different canonical target" not in str(exc):
                errors.append("backup canonical binding failed with unexpected error")
        else:
            errors.append("backup canonical binding accepted another target's backup")


def validate_backup_digest_rejection_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-backup-digest-smoke-") as tmp:
        root = Path(tmp)
        target = root / "target"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        config_path = target / module.CONFIG_NAME
        config = module.load_target_config(target)
        if config is None:
            errors.append("backup digest smoke could not load installed config")
            return
        config["model"] = "auditor-preserved-model"
        config_path.write_bytes(module.canonical_json(config))
        config_path.chmod(module.OWNER_FILE_MODE)
        result = module.mutate_setup(target, "nddev-builder", "safe", "switch")
        slot = result.get("backup_slot")
        if not isinstance(slot, int):
            errors.append("backup digest smoke did not create a backup slot")
            return
        envelope_path = module.backup_pool(target) / str(slot) / module.BACKUP_NAME
        original_envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        before_bytes = config_path.read_bytes()
        before_mode = stat.S_IMODE(config_path.lstat().st_mode)

        def write_envelope(envelope: dict[str, Any]) -> None:
            envelope_path.write_bytes(module.canonical_json(envelope))
            envelope_path.chmod(module.OWNER_FILE_MODE)

        def expect_rejected(label: str, mutate: Any) -> None:
            envelope = json.loads(json.dumps(original_envelope))
            mutate(envelope)
            write_envelope(envelope)
            try:
                module.restore_slot(target, slot)
            except module.CursorSetupError:
                pass
            else:
                errors.append(f"backup digest smoke accepted {label}")
            after_bytes = config_path.read_bytes()
            after_mode = stat.S_IMODE(config_path.lstat().st_mode)
            if after_bytes != before_bytes or after_mode != before_mode:
                errors.append(f"backup digest smoke mutated target after rejecting {label}")

        def tamper_payload(envelope: dict[str, Any]) -> None:
            payload = envelope["files"][module.CONFIG_NAME]["payload"]
            config_bytes = base64.b64decode(payload.encode("ascii"), validate=True)
            restored_config = json.loads(config_bytes.decode("utf-8"))
            restored_config["model"] = "tampered-model"
            envelope["files"][module.CONFIG_NAME]["payload"] = base64.b64encode(
                module.canonical_json(restored_config)
            ).decode("ascii")

        def remove_digest(envelope: dict[str, Any]) -> None:
            del envelope["files"][module.CONFIG_NAME]["sha256"]

        def remove_record(envelope: dict[str, Any]) -> None:
            del envelope["files"][module.STAMP_NAME]

        def add_extra_record(envelope: dict[str, Any]) -> None:
            extra_path = "extra.json"
            envelope["files"][extra_path] = module.backup_file_record(extra_path, b"extra\n")

        for label, mutate in (
            ("tampered payload", tamper_payload),
            ("missing digest", remove_digest),
            ("missing file record", remove_record),
            ("extra file record", add_extra_record),
        ):
            expect_rejected(label, mutate)
        write_envelope(original_envelope)
        extra = envelope_path.parent / "unrecorded-extra.bin"
        extra.write_bytes(b"unrecorded\n")
        try:
            module.restore_slot(target, slot)
        except module.CursorSetupError:
            pass
        else:
            errors.append("backup digest smoke accepted unrecorded slot sibling")
        after_bytes = config_path.read_bytes()
        after_mode = stat.S_IMODE(config_path.lstat().st_mode)
        if after_bytes != before_bytes or after_mode != before_mode:
            errors.append("backup digest smoke mutated target after rejecting slot sibling")
        extra.unlink()


def managed_snapshot(module: Any, target: Path) -> dict[str, tuple[bytes | None, int | None]]:
    snapshot: dict[str, tuple[bytes | None, int | None]] = {}
    for relative in module.managed_paths():
        path = target / relative
        if not (path.exists() or path.is_symlink()):
            snapshot[relative.as_posix()] = (None, None)
            continue
        snapshot[relative.as_posix()] = (
            path.read_bytes(),
            stat.S_IMODE(path.lstat().st_mode),
        )
    return snapshot


def managed_object_snapshot(module: Any, target: Path) -> dict[str, tuple[Any, ...]]:
    snapshot: dict[str, tuple[Any, ...]] = {}
    for relative in module.managed_paths():
        path = target / relative
        if not (path.exists() or path.is_symlink()):
            snapshot[relative.as_posix()] = ("absent",)
            continue
        info = path.lstat()
        snapshot[relative.as_posix()] = (
            "file",
            info.st_dev,
            info.st_ino,
            stat.S_IMODE(info.st_mode),
            info.st_mtime_ns,
            module.sha256_bytes(path.read_bytes()),
        )
    return snapshot


def hidden_residue_names(root: Path, prefixes: tuple[str, ...]) -> list[str]:
    if not root.exists() or root.is_symlink():
        return []
    return sorted(path.name for path in root.iterdir() if path.name.startswith(prefixes))


def validate_managed_transaction_rollback_fault_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-managed-txn-smoke-") as tmp:
        target = Path(tmp) / "target"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        before = managed_object_snapshot(module, target)
        real_rename = module.os.rename
        injected = {"done": False}

        def flaky_rename(source: Any, destination: Any) -> None:
            if Path(destination) == target / module.CONFIG_NAME and not injected["done"]:
                injected["done"] = True
                raise OSError("injected managed rename fault")
            real_rename(source, destination)

        with with_restored_attr(module.os, "rename", flaky_rename):
            try:
                module.mutate_setup(target, "nddev-builder", "safe", "switch")
            except (module.CursorSetupError, OSError):
                pass
            else:
                errors.append("managed transaction smoke did not inject a failure")
        after = managed_object_snapshot(module, target)
        if after != before:
            errors.append("managed transaction rollback did not restore exact prior objects")
        control = module.control_root(target)
        residue = hidden_residue_names(control, (module.MANAGED_TRANSACTION_PREFIX,))
        if residue:
            errors.append(f"managed transaction rollback left residue: {residue}")
        state = module.inspect_target(target)
        if state["state"] != "managed" or state["profile_id"] != "full-auto" or state["drift"]:
            errors.append("managed transaction rollback left target in an unexpected state")


def validate_managed_transaction_stale_expected_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-managed-stale-smoke-") as tmp:
        target = Path(tmp) / "target"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        before = module.capture_managed_files(target)
        config_path = target / module.CONFIG_NAME
        config = module.load_target_config(target)
        if config is None:
            errors.append("managed stale smoke could not load config")
            return
        config["model"] = "concurrent-change"
        changed_bytes = module.canonical_json(config)
        config_path.write_bytes(changed_bytes)
        config_path.chmod(module.OWNER_FILE_MODE)
        desired = module.desired_for_selection(target, "nddev-builder", "safe", config)
        try:
            module.replace_managed_state(target, desired, before)
        except module.CursorSetupError as exc:
            if "pre-state changed before write" not in str(exc):
                errors.append("managed stale smoke failed with unexpected error")
        else:
            errors.append("managed stale smoke accepted stale expected state")
        if config_path.read_bytes() != changed_bytes:
            errors.append("managed stale smoke mutated target after stale rejection")
        control = module.control_root(target)
        residue = hidden_residue_names(control, (module.MANAGED_TRANSACTION_PREFIX,))
        if residue:
            errors.append(f"managed stale smoke created transaction residue: {residue}")


def validate_setup_update_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-setup-update-smoke-") as tmp:
        root = Path(tmp)
        missing = root / "missing"
        try:
            module.mutate_setup(missing, "nddev-builder", "full-auto", "update")
        except module.CursorSetupError as exc:
            if "update requires an existing managed target" not in str(exc):
                errors.append(f"setup update missing target failed unexpectedly: {exc}")
        else:
            errors.append("setup update accepted a missing target")
        if missing.exists() or missing.is_symlink():
            errors.append("setup update created a missing target")

        target = root / "target"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        wrong_profile = module.mutate_setup(target, "nddev-builder", "full-auto", "update")
        if wrong_profile.get("command") != "update" or wrong_profile.get("changed") != []:
            errors.append(
                f"setup update current no-op returned unexpected payload: {wrong_profile}"
            )
        try:
            module.mutate_setup(target, "nddev-builder", "safe", "update")
        except module.CursorSetupError as exc:
            if "match the installed identity" not in str(exc):
                errors.append(f"setup update wrong identity failed unexpectedly: {exc}")
        else:
            errors.append("setup update accepted a different selected identity")

        builder_readme = target / module.BUILDER_TARGET_ROOT / "README.md"
        builder_readme.write_bytes(b"stale builder projection\n")
        refreshed = module.mutate_setup(target, "nddev-builder", "full-auto", "update")
        if builder_readme.relative_to(target).as_posix() not in refreshed["changed"]:
            errors.append("setup update did not report refreshed builder projection")
        state = module.inspect_target(target)
        if state["state"] != "managed" or state["drift"] or state["profile_id"] != "full-auto":
            errors.append(f"setup update did not restore clean installed identity: {state}")


def fake_runtime(module: Any, seed: bytes) -> dict[str, Any]:
    files = {
        "cursor-agent": (b"agent-" + seed, module.OWNER_EXEC_MODE),
        "node": (b"node-" + seed, module.OWNER_EXEC_MODE),
        "index.js": (b"index-" + seed, module.OWNER_FILE_MODE),
    }
    runtime_sha256, runtime_size, runtime_file_count = module.runtime_tree_digest(files)
    return {
        "files": files,
        "binary": files["cursor-agent"][0],
        "binary_sha256": module.sha256_bytes(files["cursor-agent"][0]),
        "runtime_tree_sha256": runtime_sha256,
        "runtime_size": runtime_size,
        "runtime_file_count": runtime_file_count,
    }


def validate_software_transaction_rollback_fault_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-software-txn-smoke-") as tmp:
        target = Path(tmp) / "target"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        install_smoke_current_software(module, target)
        binary_path = module.managed_agent_path(target)
        stamp_path = module.software_stamp_path(target)
        before_binary = binary_path.read_bytes()
        before_stamp = stamp_path.read_bytes()
        before_version = module.path_tree_signature(
            module.software_version_dir(target), "smoke version tree"
        )
        artifact = b"new official artifact"
        asset_path = "linux/x64/agent-cli-package.tar.gz"
        expected_sha = module.sha256_bytes(artifact)
        runtime = fake_runtime(module, b"new")
        real_atomic_with_mode = module.atomic_write_with_mode
        faults = {"stamp": True, "binary_restore": True}

        def fake_current_platform_asset() -> tuple[str, str, int]:
            return asset_path, expected_sha, len(artifact)

        def fake_read_artifact(source: str) -> bytes:
            del source
            return artifact

        def flaky_atomic(path: Path, content: bytes) -> None:
            if Path(path) == stamp_path and faults["stamp"]:
                faults["stamp"] = False
                raise OSError("injected stamp write fault")
            real_atomic_with_mode(path, content, module.OWNER_FILE_MODE)

        def flaky_atomic_with_mode(path: Path, content: bytes, mode: int) -> None:
            if Path(path) == binary_path and content == before_binary and faults["binary_restore"]:
                faults["binary_restore"] = False
                raise OSError("injected binary rollback fault")
            real_atomic_with_mode(path, content, mode)

        with (
            with_restored_attr(module, "current_platform_asset", fake_current_platform_asset),
            with_restored_attr(module, "read_artifact", fake_read_artifact),
            with_restored_attr(module, "extract_cursor_runtime", lambda archive: runtime),
            with_restored_attr(module, "atomic_write", flaky_atomic),
            with_restored_attr(module, "atomic_write_with_mode", flaky_atomic_with_mode),
        ):
            try:
                module.install_cursor_cli(target, "update-cli")
            except (module.CursorSetupError, OSError):
                pass
            else:
                errors.append("software transaction smoke did not inject a failure")
        after_version = module.path_tree_signature(
            module.software_version_dir(target), "smoke version tree"
        )
        if (
            binary_path.read_bytes() != before_binary
            or stamp_path.read_bytes() != before_stamp
            or after_version != before_version
        ):
            errors.append("software transaction rollback did not restore exact prior state")
        marker = module.software_transaction_path(target)
        status = module.software_status(target)
        if (marker.exists() or marker.is_symlink()) and status["current"]:
            errors.append("software transaction marker did not force non-current status")
        residue = hidden_residue_names(
            module.software_root(target) / "versions", (".stage-", ".rollback-")
        )
        if residue:
            errors.append(f"software transaction rollback left staging residue: {residue}")


def backup_slot_bytes(module: Any, target: Path) -> dict[str, bytes]:
    pool = module.backup_pool(target)
    return {
        path.name: (path / module.BACKUP_NAME).read_bytes()
        for path in sorted(pool.iterdir(), key=lambda item: item.name)
        if path.is_dir() and not path.is_symlink() and path.name.isdecimal()
    }


def backup_pool_object_snapshot(module: Any, target: Path) -> dict[str, tuple[Any, ...]]:
    pool = module.backup_pool(target)
    if not (pool.exists() or pool.is_symlink()):
        return {"__pool__": ("absent",)}
    snapshot: dict[str, tuple[Any, ...]] = {}
    for path in sorted(pool.rglob("*"), key=lambda item: item.relative_to(pool).as_posix()):
        relative = path.relative_to(pool).as_posix()
        info = path.lstat()
        if path.is_symlink():
            snapshot[relative] = ("symlink", info.st_mode, info.st_mtime_ns)
        elif path.is_dir():
            snapshot[relative] = (
                "dir",
                info.st_dev,
                info.st_ino,
                stat.S_IMODE(info.st_mode),
                info.st_mtime_ns,
            )
        else:
            snapshot[relative] = (
                "file",
                info.st_dev,
                info.st_ino,
                stat.S_IMODE(info.st_mode),
                info.st_mtime_ns,
                module.sha256_bytes(path.read_bytes()),
            )
    return snapshot


def backup_residue(module: Any, target: Path) -> list[str]:
    pool = module.backup_pool(target)
    return hidden_residue_names(
        pool,
        (module.BACKUP_STAGE_PREFIX, module.BACKUP_RETIRED_PREFIX, module.BACKUP_CLEANUP_PREFIX),
    )


def validate_backup_publication_transaction_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-backup-publish-smoke-") as tmp:
        target = Path(tmp) / "target"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        profile = "safe"
        for _ in range(10):
            module.mutate_setup(target, "nddev-builder", profile, "switch")
            profile = "full-auto" if profile == "safe" else "safe"
        before_slots = backup_pool_object_snapshot(module, target)
        real_write_exclusive = module.write_exclusive_file

        def failing_backup_write(path: Path, content: bytes) -> None:
            if Path(path).name == module.BACKUP_NAME:
                raise OSError("injected backup envelope write fault")
            real_write_exclusive(path, content)

        with with_restored_attr(module, "write_exclusive_file", failing_backup_write):
            try:
                module.mutate_setup(target, "nddev-builder", profile, "switch")
            except (module.CursorSetupError, OSError):
                pass
            else:
                errors.append("backup publication smoke did not inject envelope failure")
        if backup_pool_object_snapshot(module, target) != before_slots:
            errors.append("backup envelope failure changed published backup slots")
        residue = backup_residue(module, target)
        if residue:
            errors.append(f"backup envelope failure left staging residue: {residue}")

        real_rename = module.os.rename
        injected = {"done": False}

        def flaky_rename(source: Any, destination: Any) -> None:
            if Path(destination) == target / module.CONFIG_NAME and not injected["done"]:
                injected["done"] = True
                raise OSError("injected managed failure after backup publish")
            real_rename(source, destination)

        with with_restored_attr(module.os, "rename", flaky_rename):
            try:
                module.mutate_setup(target, "nddev-builder", profile, "switch")
            except (module.CursorSetupError, OSError):
                pass
            else:
                errors.append("backup rollback smoke did not inject lifecycle failure")
        if backup_pool_object_snapshot(module, target) != before_slots:
            errors.append("lifecycle failure did not restore prior backup slots")
        residue = backup_residue(module, target)
        if residue:
            errors.append(f"backup lifecycle rollback left staging residue: {residue}")


def install_smoke_current_software(module: Any, target: Path) -> None:
    files = {
        "cursor-agent": (b"cursor-agent smoke\n", module.OWNER_EXEC_MODE),
        "node": (b"node smoke\n", module.OWNER_EXEC_MODE),
        "index.js": (b"index smoke\n", module.OWNER_FILE_MODE),
    }
    module.ensure_real_directory_path(module.software_container(target), "smoke software container")
    module.ensure_real_directory_path(module.software_root(target), "smoke software root")
    module.ensure_real_directory_path(
        module.software_root(target) / "versions", "smoke software versions"
    )
    module.ensure_real_directory_path(module.software_version_dir(target), "smoke runtime root")
    module.write_cursor_runtime_tree(module.software_version_dir(target), files)
    entrypoint = module.managed_agent_launcher_bytes(target)
    module.atomic_write_executable(module.managed_agent_path(target), entrypoint)
    asset_path, artifact_sha256, artifact_size = module.current_platform_asset()
    runtime_sha256, runtime_size, runtime_file_count = module.runtime_tree_digest(files)
    stamp = module.canonical_json(
        module.software_stamp(
            target,
            asset_path=asset_path,
            artifact_sha256=artifact_sha256,
            artifact_size=artifact_size,
            binary_sha256=module.sha256_bytes(files["cursor-agent"][0]),
            entrypoint_sha256=module.sha256_bytes(entrypoint),
            runtime_tree_sha256=runtime_sha256,
            runtime_size=runtime_size,
            runtime_file_count=runtime_file_count,
            source_url=module.official_asset_url(asset_path),
        )
    )
    module.atomic_write(module.software_stamp_path(target), stamp)


def validate_remove_cli_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-remove-cli-smoke-") as tmp:
        root = Path(tmp)
        target = root / "target"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        auth = target / module.ISOLATED_HOME_ROOT / "auth.json"
        auth.parent.mkdir(mode=module.OWNER_DIRECTORY_MODE, parents=True, exist_ok=True)
        auth.write_text("auth\n", encoding="utf-8")
        unrelated = target / "unrelated.txt"
        unrelated.write_text("preserve\n", encoding="utf-8")
        bin_keep = target / "bin" / "keep"
        bin_keep.parent.mkdir(mode=module.OWNER_DIRECTORY_MODE, exist_ok=True)
        bin_keep.write_text("preserve\n", encoding="utf-8")
        install_smoke_current_software(module, target)
        launch_root = module.launch_images_root(target)
        module.ensure_real_directory_path(launch_root, "smoke launch images root")
        image_file = launch_root / "image"
        image_file.write_text("ephemeral\n", encoding="utf-8")
        image_file.chmod(module.OWNER_FILE_MODE)
        removed = module.remove_cursor_cli(target)
        if removed.get("command") != "remove-cli" or removed.get("operation") != "remove":
            errors.append(f"remove-cli smoke returned unexpected payload: {removed}")
        for path, label in (
            (module.managed_agent_path(target), "bin/agent"),
            (module.software_stamp_path(target), "software stamp"),
            (module.software_transaction_path(target), "software transaction marker"),
            (module.software_version_dir(target), "version runtime"),
            (module.launch_images_root(target), "launch images"),
        ):
            if path.exists() or path.is_symlink():
                errors.append(f"remove-cli smoke left {label}")
        if (
            not (target / module.CONFIG_NAME).is_file()
            or not (target / module.STAMP_NAME).is_file()
        ):
            errors.append("remove-cli smoke removed setup state")
        for preserved in (auth, unrelated, bin_keep):
            if not preserved.is_file():
                errors.append(f"remove-cli smoke removed unrelated state: {preserved.name}")
        status = module.software_status(target)
        if status["installed"] or status["current"] or status["present"]:
            errors.append(f"remove-cli smoke left software present: {status}")
        residue = hidden_residue_names(
            module.software_root(target), (module.SOFTWARE_REMOVE_ROLLBACK_PREFIX,)
        )
        if residue:
            errors.append(f"remove-cli smoke left rollback residue: {residue}")

        absent_target = root / "absent-target"
        absent = module.remove_cursor_cli(absent_target)
        if absent.get("operation") != "absent" or absent_target.exists():
            errors.append("remove-cli smoke absent operation was not a no-op")

        partial = root / "partial-target"
        partial.mkdir(mode=module.OWNER_DIRECTORY_MODE)
        partial.chmod(module.OWNER_DIRECTORY_MODE)
        partial_keep = partial / "bin" / "keep"
        partial_agent = partial / "bin" / "agent"
        partial_keep.parent.mkdir(mode=module.OWNER_DIRECTORY_MODE)
        partial_keep.write_text("preserve\n", encoding="utf-8")
        partial_agent.write_text("partial\n", encoding="utf-8")
        partial_agent.chmod(module.OWNER_EXEC_MODE)
        partial_removed = module.remove_cursor_cli(partial)
        if partial_removed.get("operation") != "remove":
            errors.append("remove-cli smoke did not remove partial software")
        if partial_agent.exists() or not partial_keep.is_file():
            errors.append("remove-cli smoke did not preserve partial target sibling")
        partial_status = module.software_status(partial)
        if partial_status["present"] or partial_status["current"]:
            errors.append(f"remove-cli smoke partial target still present: {partial_status}")


def validate_target_mode_smokes(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-target-mode-smoke-") as tmp:
        root = Path(tmp)
        for mode in (0o755, 0o777):
            target = root / f"target-{oct(mode)[2:]}"
            target.mkdir(mode=0o700)
            target.chmod(mode)
            state = module.inspect_target(target)
            if "target:mode" not in state["drift"]:
                errors.append(f"status smoke did not report target:mode for {oct(mode)}")
            software = module.software_status(target)
            if "target:mode" not in software["drift"]:
                errors.append(f"software-status smoke did not report target:mode for {oct(mode)}")
            for label, action in (
                (
                    "install",
                    lambda target=target: module.mutate_setup(
                        target, "nddev-builder", "full-auto", "install"
                    ),
                ),
                (
                    "update",
                    lambda target=target: module.mutate_setup(
                        target, "nddev-builder", "full-auto", "update"
                    ),
                ),
                (
                    "migrate",
                    lambda target=target: module.migrate_setup(target, "nddev-builder", None),
                ),
                ("restore", lambda target=target: module.restore_slot(target, 0)),
                ("remove", lambda target=target: module.remove_setup(target)),
                ("launch", lambda target=target: module.launch_cursor(target, ["--help"])),
            ):
                try:
                    action()
                except module.CursorSetupError as exc:
                    if "mode 0700" not in str(exc):
                        errors.append(
                            f"{label} unsafe target smoke failed with unexpected error: {exc}"
                        )
                else:
                    errors.append(f"{label} unsafe target smoke unexpectedly succeeded")
            if stat.S_IMODE(target.lstat().st_mode) != mode:
                errors.append(f"unsafe target smoke silently chmodded target {oct(mode)}")


def validate_initial_target_parent_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-parent-smoke-") as tmp:
        root = Path(tmp)
        parent = root / "unsafe-parent"
        parent.mkdir(mode=0o700)
        parent.chmod(0o777)
        target = parent / "target"
        try:
            module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        except module.CursorSetupError as exc:
            if "target parent" not in str(exc):
                errors.append("initial target parent smoke failed with unexpected error")
        else:
            errors.append("initial target parent smoke accepted unsafe parent")
        finally:
            parent.chmod(0o700)
        if target.exists() or target.is_symlink():
            errors.append("initial target parent smoke created target after unsafe-parent failure")


def validate_launch_exception_restore_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-launch-smoke-") as tmp:
        target = Path(tmp) / "target"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        install_smoke_current_software(module, target)
        expected = module.managed_config_view(
            module.parse_json_object(
                module.render_profile("full-auto")[1][module.CONFIG_NAME],
                "profile full-auto config",
            )
        )
        seen_environment: dict[str, str] = {}
        deferred_switch = prepare_deferred_action(
            lambda: module.mutate_setup(target, "nddev-builder", "safe", "switch"),
            Path(tmp),
            "launch-lock-switch",
            errors,
        )

        def fake_run_cursor_child(
            executable: Path, forwarded: list[str], environment: dict[str, str]
        ) -> Any:
            del executable, forwarded
            seen_environment.update(environment)
            control = module.control_root(target)
            lock_root = module.control_lock_root(target)
            lock = module.target_lock_path(target)
            if not lock.is_file() or lock.is_symlink():
                errors.append("launch smoke did not expose a persistent lock file")
            else:
                mode = stat.S_IMODE(lock.lstat().st_mode)
                if mode != module.OWNER_FILE_MODE:
                    errors.append(f"launch smoke lock file mode mismatch: {oct(mode)}")
            control_mode = stat.S_IMODE(control.lstat().st_mode)
            if control_mode != module.OWNER_DIRECTORY_MODE:
                errors.append(f"launch smoke control root mode drifted: {oct(control_mode)}")
            lock_root_mode = stat.S_IMODE(lock_root.lstat().st_mode)
            if lock_root_mode != module.LOCK_HELD_DIRECTORY_MODE:
                errors.append(f"launch smoke lock directory was writable: {oct(lock_root_mode)}")
            assert_deferred_action_denied(deferred_switch, errors, "launch lock smoke", "switch")
            config = module.load_target_config(target)
            assert config is not None
            config["approvalMode"] = "allowlist"
            (target / module.CONFIG_NAME).write_bytes(module.canonical_json(config))
            raise OSError("simulated child failure")

        fake_path = str(Path(tmp) / "fake-bin")
        old_path = os.environ.get("PATH")
        os.environ["PATH"] = fake_path
        try:
            with with_restored_attr(module, "run_cursor_child", fake_run_cursor_child):
                try:
                    module.launch_cursor(target, ["-p", "noop"])
                except OSError as exc:
                    if "simulated child failure" not in str(exc):
                        errors.append("launch smoke raised unexpected OSError")
                else:
                    errors.append("launch smoke did not preserve child OSError")
        finally:
            if old_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = old_path
        restored = module.load_target_config(target)
        if restored is None or module.managed_config_view(restored) != expected:
            errors.append("launch smoke did not restore managed config after child exception")
        if seen_environment.get("PATH") != "/usr/bin:/bin":
            errors.append("launch smoke inherited ambient PATH")
        launcher = module.managed_agent_launcher_bytes(target)
        if not launcher.startswith(b"#!/bin/bash\n"):
            errors.append("managed launcher must use /bin/bash")


def validate_launch_swap_at_exec_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-launch-swap-smoke-") as tmp:
        target = Path(tmp) / "target"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        install_smoke_current_software(module, target)
        real_create_launch_image = module.create_launch_image
        child_ran = False

        def swapped_create_launch_image(path: Path) -> dict[str, Any]:
            image = real_create_launch_image(path)
            module.atomic_write_executable(
                image["executable"],
                b"#!/bin/bash\necho swapped\n",
            )
            return image

        def fake_run_cursor_child(
            executable: Path, forwarded: list[str], environment: dict[str, str]
        ) -> Any:
            nonlocal child_ran
            del executable, forwarded, environment
            child_ran = True
            return type("Completed", (), {"returncode": 0})()

        with (
            with_restored_attr(module, "create_launch_image", swapped_create_launch_image),
            with_restored_attr(module, "run_cursor_child", fake_run_cursor_child),
        ):
            try:
                module.launch_cursor(target, ["--help"])
            except module.CursorSetupError as exc:
                if "exec handoff" not in str(exc):
                    errors.append(f"swap-at-exec smoke failed with unexpected error: {exc}")
            else:
                errors.append("swap-at-exec smoke unexpectedly allowed launch")
        if child_ran:
            errors.append("swap-at-exec smoke executed the replaced agent")


def permission_denials_are_observable() -> bool:
    geteuid = getattr(os, "geteuid", None)
    return geteuid is None or geteuid() != 0


def expect_permission_denied(action: Any, errors: list[str], label: str) -> None:
    if not permission_denials_are_observable():
        return
    try:
        action()
    except PermissionError:
        return
    except OSError as exc:
        errors.append(f"{label} failed with unexpected OSError: {exc}")
    else:
        errors.append(f"{label} unexpectedly succeeded")


def validate_launch_lock_file_and_write_protection_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-launch-protection-smoke-") as tmp:
        root = Path(tmp)
        target = root / "target"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        install_smoke_current_software(module, target)
        ambient_tmp = root / "ambient-tmp"
        ambient_tmp.mkdir(mode=0o700)
        writes = {
            "config": target / "stub-session-state",
            "home": target / module.ISOLATED_HOME_ROOT / "stub-home-state",
            "tmp": target / module.MUTABLE_RUNTIME_TMP_ROOT / "stub-tmp-state",
            "runtime": module.software_version_dir(target) / ".running" / "stub-runtime-state",
            "image": None,
        }
        seen_image_root: Path | None = None
        deferred_switch = prepare_deferred_action(
            lambda: module.mutate_setup(target, "nddev-builder", "safe", "switch"),
            root,
            "launch-protection-switch",
            errors,
        )

        def fake_run_cursor_child(
            executable: Path, forwarded: list[str], environment: dict[str, str]
        ) -> Any:
            nonlocal seen_image_root
            del forwarded
            control = module.control_root(target)
            lock_root = module.control_lock_root(target)
            lock = module.target_lock_path(target)
            seen_image_root = executable.parent
            if not lock.is_file() or lock.is_symlink():
                errors.append("launch protection smoke did not expose lock as regular file")
            if stat.S_IMODE(control.lstat().st_mode) != module.OWNER_DIRECTORY_MODE:
                errors.append("launch protection smoke changed control root mode")
            if stat.S_IMODE(lock_root.lstat().st_mode) != module.LOCK_HELD_DIRECTORY_MODE:
                errors.append("launch protection smoke did not protect lock directory")
            if stat.S_IMODE(executable.parent.lstat().st_mode) != module.LOCK_HELD_DIRECTORY_MODE:
                errors.append("launch protection smoke did not protect launch image")
            for path, label in (
                (target, "target root"),
                (control, "control root"),
                (Path(environment["CURSOR_CONFIG_DIR"]), "CURSOR_CONFIG_DIR"),
                (Path(environment["HOME"]), "isolated HOME"),
                (Path(environment["TMPDIR"]), "TMPDIR"),
                (module.software_container(target), "software container"),
                (module.software_root(target), "software root"),
                (module.software_version_dir(target), "installed runtime root"),
            ):
                mode = stat.S_IMODE(path.lstat().st_mode)
                if mode != module.OWNER_DIRECTORY_MODE:
                    errors.append(f"launch protection smoke made {label} read-only: {oct(mode)}")
            tmpdir = Path(environment["TMPDIR"])
            expected_tmpdir = (target / module.MUTABLE_RUNTIME_TMP_ROOT).resolve(strict=False)
            if tmpdir.resolve(strict=False) != expected_tmpdir:
                errors.append(f"launch protection smoke used wrong TMPDIR: {tmpdir}")
            if tmpdir.resolve(strict=False) == ambient_tmp.resolve(strict=False):
                errors.append("launch protection smoke inherited ambient TMPDIR")
            writes["config"].write_text("config write\n", encoding="utf-8")
            writes["home"].write_text("home write\n", encoding="utf-8")
            writes["tmp"].write_text("tmp write\n", encoding="utf-8")
            writes["runtime"].parent.mkdir(mode=module.OWNER_DIRECTORY_MODE, exist_ok=True)
            writes["runtime"].write_text("runtime write\n", encoding="utf-8")
            image_running = executable.parent / ".running" / "stub-image-state"
            image_running.write_text("image write\n", encoding="utf-8")
            writes["image"] = image_running
            expect_permission_denied(lambda: lock.unlink(), errors, "launch protection lock unlink")

            replacement = target / "replacement-agent"
            replacement.write_bytes(b"replacement\n")
            replacement.chmod(module.OWNER_EXEC_MODE)
            expect_permission_denied(
                lambda: executable.unlink(),
                errors,
                "launch protection executable unlink",
            )
            expect_permission_denied(
                lambda: os.replace(replacement, executable),
                errors,
                "launch protection executable replace",
            )
            if replacement.exists():
                replacement.unlink()

            assert_deferred_action_denied(
                deferred_switch, errors, "launch protection smoke", "switch"
            )
            return type("Completed", (), {"returncode": 0})()

        old_tmp = os.environ.get("TMPDIR")
        os.environ["TMPDIR"] = str(ambient_tmp)
        try:
            with with_restored_attr(module, "run_cursor_child", fake_run_cursor_child):
                result = module.launch_cursor(target, ["-p", "noop"])
        finally:
            if old_tmp is None:
                os.environ.pop("TMPDIR", None)
            else:
                os.environ["TMPDIR"] = old_tmp
        if result != 0:
            errors.append(f"launch protection smoke returned {result}")
        if stat.S_IMODE(module.control_root(target).lstat().st_mode) != module.OWNER_DIRECTORY_MODE:
            errors.append("launch protection smoke did not restore control root mode")
        if (
            stat.S_IMODE(module.control_lock_root(target).lstat().st_mode)
            != module.OWNER_DIRECTORY_MODE
        ):
            errors.append("launch protection smoke did not restore lock directory mode")
        if seen_image_root is None:
            errors.append("launch protection smoke never observed a launch image")
        elif seen_image_root.exists() or seen_image_root.is_symlink():
            errors.append("launch protection smoke did not remove the launch image")
        for name, path in writes.items():
            if name == "image":
                continue
            if path is None or not path.is_file():
                errors.append(f"launch protection smoke did not persist {name} runtime write")
        if writes["image"] is not None and writes["image"].exists():
            errors.append("launch protection smoke left launch-image runtime state behind")
        status = module.software_status(target)
        if not status["current"]:
            errors.append(f"launch protection smoke left software drift: {status['drift']}")


def validate_external_bootstrap_lock_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-bootstrap-lock-smoke-") as tmp:
        root = Path(tmp)
        target = root / "target"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        install_smoke_current_software(module, target)
        moved = target / ".renamed-nddev-cursor-cli"
        deferred_switch = prepare_deferred_action(
            lambda: module.mutate_setup(target, "nddev-builder", "safe", "switch"),
            root,
            "bootstrap-switch",
            errors,
        )
        deferred_remove = prepare_deferred_action(
            lambda: module.remove_setup(target),
            root,
            "bootstrap-remove",
            errors,
        )
        deferred_install = prepare_deferred_action(
            lambda: module.mutate_setup(target, "nddev-builder", "safe", "install"),
            root,
            "bootstrap-install",
            errors,
        )

        def fake_run_cursor_child(
            executable: Path, forwarded: list[str], environment: dict[str, str]
        ) -> Any:
            del executable, forwarded
            if any(module.BOOTSTRAP_LOCK_ROOT_PREFIX in value for value in environment.values()):
                errors.append("bootstrap lock path leaked into child environment")
            control = module.control_root(target)
            control.rename(moved)
            try:
                assert_deferred_action_denied(
                    deferred_switch, errors, "external bootstrap lock smoke", "switch"
                )
                assert_deferred_action_denied(
                    deferred_remove, errors, "external bootstrap lock smoke", "remove"
                )
                assert_deferred_action_denied(
                    deferred_install, errors, "external bootstrap lock smoke", "install"
                )
            finally:
                moved.rename(control)
            return type("Completed", (), {"returncode": 0})()

        with with_restored_attr(module, "run_cursor_child", fake_run_cursor_child):
            result = module.launch_cursor(target, ["-p", "noop"])
        if result != 0:
            errors.append(f"external bootstrap lock smoke returned {result}")
        control = module.control_root(target)
        if moved.exists():
            errors.append("external bootstrap lock smoke left renamed control root")
        if not control.exists():
            errors.append("external bootstrap lock smoke lost the control root")
        state = module.inspect_target(target)
        if state["drift"]:
            errors.append(f"external bootstrap lock smoke left setup drift: {state['drift']}")


def validate_launch_separator_argv_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-launch-argv-smoke-") as tmp:
        root = Path(tmp)
        target = root / "target"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        install_smoke_current_software(module, target)
        parsed = module.parse_args(
            [
                "launch",
                "--target",
                str(target),
                "--",
                "--",
                "-p",
                "literal",
            ]
        )
        if list(parsed.cursor_args) != ["--", "--", "-p", "literal"]:
            errors.append(f"launch argv smoke parsed unexpected args: {parsed.cursor_args}")
        seen: list[str] = []

        def fake_run_cursor_child(
            executable: Path, forwarded: list[str], environment: dict[str, str]
        ) -> Any:
            del executable, environment
            seen.extend(forwarded)
            return type("Completed", (), {"returncode": 0})()

        with with_restored_attr(module, "run_cursor_child", fake_run_cursor_child):
            result = module.run(parsed)
        if result != 0:
            errors.append(f"launch argv smoke returned {result}")
        if seen != ["--", "-p", "literal"]:
            errors.append(f"launch argv smoke forwarded unexpected args: {seen}")


def validate_bootstrap_lock_handover_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-bootstrap-handover-smoke-") as tmp:
        root = Path(tmp)
        target = root / "target"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")

        def read_result(path: Path) -> dict[str, Any]:
            return json.loads(path.read_text(encoding="utf-8"))

        ready_a = root / "ready-a"
        release_a = root / "release-a"
        result_a = root / "result-a.json"
        error_a = root / "error-a.txt"
        holder_a = start_bootstrap_lock_holder(
            module, target, ready_a, release_a, result_a, error_a
        )
        if not wait_for_holder_ready(holder_a, ready_a, error_a, errors, "bootstrap handover A"):
            return
        first = read_result(result_a)
        lock_path = Path(first["path"])
        system_tmp = module.bootstrap_lock_system_root()
        try:
            lock_path.relative_to(system_tmp)
        except ValueError:
            errors.append(f"bootstrap handover lock path is outside system temp: {lock_path}")
        with contextlib.suppress(ValueError):
            lock_path.relative_to(target)
            errors.append("bootstrap handover lock path is inside target")
        with contextlib.suppress(ValueError):
            lock_path.relative_to(target.parent)
            errors.append("bootstrap handover lock path is inside target parent")
        if not lock_path.name.startswith(f"{module.PRODUCT_NAME}-"):
            errors.append("bootstrap handover lock filename lacks product namespace")
        expected_digest = module.sha256_bytes(
            module.PRODUCT_NAME.encode("utf-8") + b"\0" + first["lexical"].encode("utf-8")
        )
        if first["digest"] != expected_digest:
            errors.append("bootstrap handover digest did not bind product and target")
        if lock_path.name != f"{module.PRODUCT_NAME}-{expected_digest}.lock":
            errors.append("bootstrap handover lock filename digest mismatch")
        release_a.write_text("release\n", encoding="utf-8")
        if not wait_for_holder_exit(holder_a, error_a, errors, "bootstrap handover A"):
            return

        ready_b = root / "ready-b"
        release_b = root / "release-b"
        result_b = root / "result-b.json"
        error_b = root / "error-b.txt"
        holder_b = start_bootstrap_lock_holder(
            module, target, ready_b, release_b, result_b, error_b
        )
        if not wait_for_holder_ready(holder_b, ready_b, error_b, errors, "bootstrap handover B"):
            return
        second = read_result(result_b)
        if (first["device"], first["inode"]) != (second["device"], second["inode"]):
            errors.append("bootstrap handover did not reuse the persistent lock inode")
        assert_concurrent_command_denied(
            lambda: run_concurrent_switch(module, target, "safe"),
            errors,
            "bootstrap handover smoke",
            "switch",
        )
        release_b.write_text("release\n", encoding="utf-8")
        if not wait_for_holder_exit(holder_b, error_b, errors, "bootstrap handover B"):
            return
        result = run_concurrent_switch(module, target, "safe")
        if result.returncode != 0:
            errors.append(
                "bootstrap handover switch after release failed: "
                f"stdout={result.stdout} stderr={result.stderr}"
            )
        final_info = lock_path.lstat()
        if (final_info.st_dev, final_info.st_ino) != (first["device"], first["inode"]):
            errors.append("bootstrap handover changed the persistent lock inode after release")
        if stat.S_IMODE(final_info.st_mode) != module.OWNER_FILE_MODE:
            errors.append("bootstrap handover lock mode drifted")
        lock_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "product_name": module.PRODUCT_NAME,
                    "lexical_target": first["lexical"],
                    "target_sha256": "0" * 64,
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        result = run_concurrent_switch(module, target, "full-auto")
        if result.returncode == 0:
            errors.append("bootstrap handover accepted mismatched persistent binding")
        elif "bootstrap lock target binding mismatch" not in (f"{result.stdout}\n{result.stderr}"):
            errors.append(
                "bootstrap handover binding mismatch failed with unexpected output: "
                f"stdout={result.stdout} stderr={result.stderr}"
            )


def validate_same_process_thread_bootstrap_denial_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-bootstrap-thread-smoke-") as tmp:
        root = Path(tmp)
        target = root / "target"
        outcomes: list[str] = []

        def contender() -> None:
            try:
                with module.bootstrap_lifecycle_lock(target):
                    outcomes.append("accepted")
            except module.CursorSetupError as exc:
                outcomes.append(str(exc))
            except BaseException as exc:  # noqa: BLE001 - serialize public smoke failure.
                outcomes.append(f"unexpected: {exc}")

        with module.bootstrap_lifecycle_lock(target):
            thread = threading.Thread(target=contender)
            thread.start()
            thread.join(timeout=5)
            if thread.is_alive():
                errors.append("bootstrap thread smoke did not finish")
                return
        if outcomes != ["target is already locked"]:
            errors.append(f"bootstrap thread smoke had unexpected outcome: {outcomes}")
        with module.bootstrap_lifecycle_lock(target):
            pass


def expect_launch_blocked_without_child(
    module: Any,
    target: Path,
    expected_fragment: str,
    errors: list[str],
    label: str,
) -> None:
    child_ran = False

    def fake_run_cursor_child(
        executable: Path, forwarded: list[str], environment: dict[str, str]
    ) -> Any:
        nonlocal child_ran
        del executable, forwarded, environment
        child_ran = True
        return type("Completed", (), {"returncode": 0})()

    with with_restored_attr(module, "run_cursor_child", fake_run_cursor_child):
        try:
            module.launch_cursor(target, ["--help"])
        except module.CursorSetupError as exc:
            if expected_fragment not in str(exc):
                errors.append(f"{label} launch failed with unexpected error: {exc}")
        else:
            errors.append(f"{label} launch unexpectedly succeeded")
    if child_ran:
        errors.append(f"{label} launch reached child subprocess")


def replace_with_external_symlink(path: Path, external: Path) -> None:
    path.rename(external)
    os.symlink(external, path)


def validate_target_local_parent_symlink_smokes(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-parent-symlink-smoke-") as tmp:
        root = Path(tmp)

        target = root / "isolated-home"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        install_smoke_current_software(module, target)
        isolated_home = target / module.ISOLATED_HOME_ROOT
        external_home = root / "external-home"
        replace_with_external_symlink(isolated_home, external_home)
        external_home.chmod(0o755)
        state = module.inspect_target(target)
        if ".nddev-cursor-home:unsafe" not in state["drift"]:
            errors.append("isolated HOME symlink smoke did not report setup drift")
        if state["builder_projection"] != "unsafe" or state["launchable"]:
            errors.append("isolated HOME symlink smoke left target launchable")
        software = module.software_status(target)
        if ".nddev-cursor-home:unsafe" not in software["drift"] or software["current"]:
            errors.append("isolated HOME symlink smoke did not block software current status")
        expect_launch_blocked_without_child(
            module, target, ".nddev-cursor-home:unsafe", errors, "isolated HOME symlink"
        )
        if stat.S_IMODE(external_home.lstat().st_mode) != 0o755:
            errors.append("isolated HOME symlink smoke chmodded the external directory")

        target = root / "builder-parent"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        install_smoke_current_software(module, target)
        builder_parent = target / module.ISOLATED_HOME_ROOT / ".cursor" / "plugins" / "local"
        external_builder_parent = root / "external-builder-parent"
        replace_with_external_symlink(builder_parent, external_builder_parent)
        state = module.inspect_target(target)
        expected = ".nddev-cursor-home/.cursor/plugins/local:unsafe"
        if expected not in state["drift"]:
            errors.append("builder parent symlink smoke did not report setup drift")
        if state["builder_projection"] != "unsafe" or state["launchable"]:
            errors.append("builder parent symlink smoke left target launchable")
        expect_launch_blocked_without_child(
            module, target, expected, errors, "builder parent symlink"
        )

        target = root / "runtime-parent"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        install_smoke_current_software(module, target)
        runtime_parent = target / ".nddev-software"
        external_runtime_parent = root / "external-runtime-parent"
        replace_with_external_symlink(runtime_parent, external_runtime_parent)
        state = module.inspect_target(target)
        if ".nddev-software:unsafe" not in state["drift"] or state["launchable"]:
            errors.append("runtime parent symlink smoke left setup status launchable")
        software = module.software_status(target)
        if ".nddev-software:unsafe" not in software["drift"] or software["current"]:
            errors.append("runtime parent symlink smoke did not block software current status")
        expect_launch_blocked_without_child(
            module, target, ".nddev-software:unsafe", errors, "runtime parent symlink"
        )

        target = root / "runtime-tmp"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        install_smoke_current_software(module, target)
        runtime_tmp_root = target / module.MUTABLE_RUNTIME_ROOT
        external_runtime_tmp = root / "external-runtime-tmp"
        external_runtime_tmp.mkdir(mode=0o700)
        os.symlink(external_runtime_tmp, runtime_tmp_root)
        external_runtime_tmp.chmod(0o755)
        state = module.inspect_target(target)
        if ".nddev-cursor-runtime:unsafe" not in state["drift"] or state["launchable"]:
            errors.append("runtime TMP symlink smoke left setup status launchable")
        software = module.software_status(target)
        if ".nddev-cursor-runtime:unsafe" not in software["drift"] or software["current"]:
            errors.append("runtime TMP symlink smoke did not block software current status")
        expect_launch_blocked_without_child(
            module, target, ".nddev-cursor-runtime:unsafe", errors, "runtime TMP symlink"
        )
        if stat.S_IMODE(external_runtime_tmp.lstat().st_mode) != 0o755:
            errors.append("runtime TMP symlink smoke chmodded the external directory")


def validate_unsupported_host_preflight_no_touch_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-host-preflight-smoke-") as tmp:
        root = Path(tmp)
        bootstrap_root = root / "system-tmp"
        bootstrap_root.mkdir(mode=0o700)
        bootstrap_root.chmod(0o1777)

        def forbidden(name: str) -> Any:
            def fail_forbidden(*args: Any, **kwargs: Any) -> Any:
                del args, kwargs
                calls.append(name)
                raise AssertionError(f"{name} must not run on unsupported hosts")

            return fail_forbidden

        command_argvs: tuple[tuple[str, list[str], list[str]], ...] = (
            ("status", ["status"], []),
            ("plan", ["plan"], []),
            ("install", ["install"], []),
            ("update", ["update"], []),
            ("switch", ["switch"], []),
            ("migrate", ["migrate", "--profile", "safe"], []),
            ("restore", ["restore", "--backup", "0"], []),
            ("remove", ["remove"], []),
            ("software-status", ["software-status"], []),
            ("install-cli", ["install-cli"], []),
            ("update-cli", ["update-cli"], []),
            ("remove-cli", ["remove-cli"], []),
            ("launch", ["launch"], ["--", "--help"]),
        )
        unsupported_hosts: tuple[tuple[str, str, str, dict[str, str], str, str], ...] = (
            (
                "windows",
                "win32",
                "x86_64",
                {"ID": "ubuntu"},
                "glibc",
                "unsupported Cursor CLI host category windows",
            ),
            (
                "non-ubuntu-linux",
                "linux",
                "x86_64",
                {"ID": "debian"},
                "glibc",
                "unsupported Cursor CLI Linux distribution",
            ),
            (
                "linux-musl",
                "linux",
                "x86_64",
                {"ID": "ubuntu"},
                "musl",
                "unsupported Cursor CLI Linux libc",
            ),
            (
                "unsupported-architecture",
                "darwin",
                "sparc64",
                {"ID": "ubuntu"},
                "glibc",
                "unsupported Cursor CLI host category unsupported-architecture",
            ),
        )
        for category, platform_name, machine, os_release, libc, expected in unsupported_hosts:
            target = root / f"target-{category}"
            calls: list[str] = []

            def unsupported_uname(machine: str = machine) -> Any:
                class Uname:
                    pass

                result = Uname()
                result.machine = machine
                return result

            with (
                with_restored_attr(module, "bootstrap_lock_system_root", lambda: bootstrap_root),
                with_restored_attr(module.sys, "platform", platform_name),
                with_restored_attr(module.os, "uname", unsupported_uname),
                with_restored_attr(module, "read_linux_os_release", lambda: os_release),
                with_restored_attr(module, "detect_linux_libc", lambda: libc),
                with_restored_attr(module, "resolve_target", forbidden("resolve target")),
                with_restored_attr(module, "prepare_lifecycle_target", forbidden("target")),
                with_restored_attr(module, "target_lock", forbidden("target lock")),
                with_restored_attr(module, "read_artifact", forbidden("network")),
                with_restored_attr(module, "prepare_cursor_artifact", forbidden("stage")),
                with_restored_attr(module, "run_cursor_child", forbidden("child")),
            ):
                for name, argv_prefix, argv_suffix in command_argvs:
                    argv = [*argv_prefix, "--target", str(target), *argv_suffix]
                    try:
                        module.run(module.parse_args(argv))
                    except module.CursorSetupError as exc:
                        if expected not in str(exc):
                            errors.append(f"{category}/{name} failed with unexpected error: {exc}")
                    except AssertionError as exc:
                        errors.append(
                            f"{category}/{name} touched forbidden path before host preflight: {exc}"
                        )
                    else:
                        errors.append(f"{category}/{name} accepted unsupported host")
            product_roots = list(bootstrap_root.iterdir()) if bootstrap_root.exists() else []
            if product_roots:
                errors.append(
                    f"{category} unsupported preflight touched bootstrap root: {product_roots}"
                )
            if target.exists() or target.is_symlink():
                errors.append(f"{category} unsupported preflight touched target")
            if calls:
                errors.append(
                    f"{category} unsupported preflight touched forbidden operations: {calls}"
                )


def validate_target_command_external_lock_order_smoke(module: Any, errors: list[str]) -> None:
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-lock-order-smoke-") as tmp:
        root = Path(tmp)
        target = root / "target"
        command_argvs: tuple[tuple[str, list[str], str], ...] = (
            ("status", ["status", "--target", str(target)], "inspect_target"),
            ("plan", ["plan", "--target", str(target)], "plan_setup"),
            ("install", ["install", "--target", str(target)], "mutate_setup"),
            ("update", ["update", "--target", str(target)], "mutate_setup"),
            ("switch", ["switch", "--target", str(target)], "mutate_setup"),
            (
                "migrate",
                ["migrate", "--profile", "safe", "--target", str(target)],
                "migrate_setup",
            ),
            ("restore", ["restore", "--backup", "0", "--target", str(target)], "restore_slot"),
            ("remove", ["remove", "--target", str(target)], "remove_setup"),
            ("software-status", ["software-status", "--target", str(target)], "software_status"),
            ("install-cli", ["install-cli", "--target", str(target)], "install_cursor_cli"),
            ("update-cli", ["update-cli", "--target", str(target)], "install_cursor_cli"),
            ("remove-cli", ["remove-cli", "--target", str(target)], "remove_cursor_cli"),
            ("launch", ["launch", "--target", str(target), "--", "--help"], "launch_cursor"),
        )

        for command, argv, work_attr in command_argvs:
            events: list[str] = []
            locked = {"value": False}

            def fake_host() -> None:
                events.append("host")

            def fake_lexical(raw: Any) -> str:
                if events != ["host"]:
                    errors.append(f"{command}: lexical target validation ran out of order: {events}")
                events.append("lexical")
                return os.fspath(raw)

            @contextlib.contextmanager
            def fake_bootstrap(raw: Any) -> Any:
                if events != ["host", "lexical"]:
                    errors.append(f"{command}: bootstrap lock ran out of order: {events}")
                events.append("bootstrap-enter")
                locked["value"] = True
                try:
                    yield
                finally:
                    locked["value"] = False
                    events.append("bootstrap-exit")

            def fake_resolve(raw: str) -> Path:
                if not locked["value"]:
                    raise AssertionError("resolve_target ran before bootstrap lock")
                events.append("resolve")
                return Path(raw)

            def fake_work(*args: Any, **kwargs: Any) -> Any:
                del args, kwargs
                if not locked["value"]:
                    raise AssertionError(f"{work_attr} ran before bootstrap lock")
                events.append(work_attr)
                if work_attr == "inspect_target":
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
                    }
                raise module.CursorSetupError("lock-order trace stop")

            with (
                with_restored_attr(module, "require_current_host_supported", fake_host),
                with_restored_attr(module, "lexical_target_text", fake_lexical),
                with_restored_attr(module, "bootstrap_lifecycle_lock", fake_bootstrap),
                with_restored_attr(module, "resolve_target", fake_resolve),
                with_restored_attr(module, work_attr, fake_work),
            ):
                try:
                    module.run(module.parse_args(argv))
                except module.CursorSetupError as exc:
                    if "lock-order trace stop" not in str(exc):
                        errors.append(f"{command}: failed with unexpected trace error: {exc}")
                except AssertionError as exc:
                    errors.append(f"{command}: {exc}")
                except BaseException as exc:  # noqa: BLE001 - public smoke serializes failures.
                    errors.append(f"{command}: lock-order trace raised unexpectedly: {exc}")
            expected_events = ["host", "lexical", "bootstrap-enter", "resolve", work_attr]
            if events[:5] != expected_events or events[-1:] != ["bootstrap-exit"]:
                errors.append(f"{command}: target command lock order mismatch: {events}")


def validate_parser_json_error_smoke(errors: list[str]) -> None:
    help_completed = subprocess.run(
        [sys.executable, str(ROOT / "cli-tools" / "nddev_cursor_cli.py"), "--help"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        check=False,
        close_fds=True,
        timeout=10,
    )
    if (
        help_completed.returncode != 0
        or " update " not in help_completed.stdout
        or "remove-cli" not in help_completed.stdout
    ):
        errors.append("parser help smoke did not expose update/remove-cli")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "cli-tools" / "nddev_cursor_cli.py"), "status", "--json"],
        cwd=ROOT,
        env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        check=False,
        close_fds=True,
        timeout=10,
    )
    if completed.returncode != 2:
        errors.append(f"JSON parser smoke returned {completed.returncode}, expected 2")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        errors.append(f"JSON parser smoke stdout was not JSON: {exc}; {completed.stdout!r}")
        return
    if payload.get("schema_version") != 1 or "--target" not in str(payload.get("error", "")):
        errors.append(f"JSON parser smoke error payload mismatch: {payload}")
    if completed.stderr.strip():
        errors.append(f"JSON parser smoke emitted stderr usage: {completed.stderr!r}")


def validate_public_manager_smokes(errors: list[str]) -> None:
    module = load_manager(errors)
    if module is None:
        return
    production_bootstrap_before = real_bootstrap_artifact_snapshot(module, errors)
    with tempfile.TemporaryDirectory(prefix="nddev-cursor-bootstrap-system-root-") as tmp:
        injected_system_root = Path(tmp) / "system-tmp"
        injected_system_root.mkdir(mode=0o700)
        injected_system_root.chmod(0o1777)

        def injected_bootstrap_system_root() -> Path:
            return injected_system_root.resolve(strict=True)

        with with_restored_attr(
            module, "bootstrap_lock_system_root", injected_bootstrap_system_root
        ):
            smokes: list[tuple[str, Any]] = [
                (
                    "artifact source",
                    lambda: validate_artifact_source_smokes(module, errors),
                ),
                (
                    "sibling control state ignored",
                    lambda: validate_sibling_control_state_ignored_smoke(module, errors),
                ),
                (
                    "insecure internal control state",
                    lambda: validate_insecure_internal_control_state_smoke(module, errors),
                ),
                (
                    "backup rotation and binding",
                    lambda: validate_backup_rotation_and_binding_smoke(module, errors),
                ),
                (
                    "backup digest rejection",
                    lambda: validate_backup_digest_rejection_smoke(module, errors),
                ),
                (
                    "managed transaction rollback fault",
                    lambda: validate_managed_transaction_rollback_fault_smoke(module, errors),
                ),
                (
                    "managed transaction stale expected",
                    lambda: validate_managed_transaction_stale_expected_smoke(module, errors),
                ),
                (
                    "setup update",
                    lambda: validate_setup_update_smoke(module, errors),
                ),
                (
                    "software transaction rollback fault",
                    lambda: validate_software_transaction_rollback_fault_smoke(module, errors),
                ),
                (
                    "remove cli",
                    lambda: validate_remove_cli_smoke(module, errors),
                ),
                (
                    "backup publication transaction",
                    lambda: validate_backup_publication_transaction_smoke(module, errors),
                ),
                ("target mode", lambda: validate_target_mode_smokes(module, errors)),
                (
                    "initial target parent",
                    lambda: validate_initial_target_parent_smoke(module, errors),
                ),
                (
                    "launch exception restore",
                    lambda: validate_launch_exception_restore_smoke(module, errors),
                ),
                (
                    "launch swap at exec",
                    lambda: validate_launch_swap_at_exec_smoke(module, errors),
                ),
                (
                    "launch lock file and write protection",
                    lambda: validate_launch_lock_file_and_write_protection_smoke(module, errors),
                ),
                (
                    "external bootstrap lock",
                    lambda: validate_external_bootstrap_lock_smoke(module, errors),
                ),
                (
                    "launch separator argv",
                    lambda: validate_launch_separator_argv_smoke(module, errors),
                ),
                (
                    "bootstrap lock handover",
                    lambda: validate_bootstrap_lock_handover_smoke(module, errors),
                ),
                (
                    "same-process bootstrap thread denial",
                    lambda: validate_same_process_thread_bootstrap_denial_smoke(module, errors),
                ),
                (
                    "target local parent symlink",
                    lambda: validate_target_local_parent_symlink_smokes(module, errors),
                ),
                (
                    "unsupported host preflight no touch",
                    lambda: validate_unsupported_host_preflight_no_touch_smoke(module, errors),
                ),
                (
                    "target command external lock order",
                    lambda: validate_target_command_external_lock_order_smoke(module, errors),
                ),
                (
                    "parser JSON error",
                    lambda: validate_parser_json_error_smoke(errors),
                ),
            ]
            for name, action in smokes:
                run_manager_smoke(name, action, errors)
    production_bootstrap_after = real_bootstrap_artifact_snapshot(module, errors)
    if production_bootstrap_after != production_bootstrap_before:
        errors.append(
            "public manager smokes created or changed production system bootstrap artifacts"
        )


def validate_no_forbidden_public_paths(errors: list[str]) -> None:
    unsupported_os = "Win" + "dows"
    forbidden = (
        ROOT / "setups" / "review",
        ROOT / "profiles" / "review",
        ROOT / "profiles" / "balanced",
    )
    for path in forbidden:
        if path.exists() or path.is_symlink():
            errors.append(f"unsupported public setup/profile path exists: {path}")
    for path in [
        ROOT / "README.md",
        ROOT / "docs",
        ROOT / "config",
        ROOT / "build",
        ROOT / "profiles",
        ROOT / "setups",
        ROOT / "plugins",
    ]:
        paths = [path] if path.is_file() else sorted(path.rglob("*"))
        for candidate in paths:
            if candidate.is_file() and not candidate.is_symlink():
                if "__pycache__" in candidate.parts or candidate.suffix == ".pyc":
                    errors.append(f"{candidate.relative_to(ROOT)}: cache file must not exist")
                    continue
                try:
                    text = candidate.read_text(encoding="utf-8")
                except UnicodeDecodeError as exc:
                    errors.append(f"{candidate.relative_to(ROOT)}: non-UTF-8 public text: {exc}")
                    continue
                if unsupported_os in text:
                    errors.append(f"{candidate.relative_to(ROOT)}: unsupported OS contract text")


def validate_public_doc_hygiene(errors: list[str]) -> None:
    docs = {
        "README.md": ROOT / "README.md",
        "docs/software-lifecycle.md": ROOT / "docs" / "software-lifecycle.md",
    }
    required_needles = (
        "cli-tools/nddev_cursor_cli.py",
        "config/nddev-contract.json",
        "references/cursor-cli-baseline.json",
        "build/manifest.json",
        "status --target",
        "software-status --target",
        "--json",
    )
    volatile_needles = (
        CURSOR_RELEASE_ID,
        "downloads.cursor.com",
        "`0700`",
        "`0600`",
        "`0500`",
        ".nddev-cursor-cli/locks/target.lock",
        ".nddev-cursor-runtime/tmp",
        ".nddev-software/cursor-cli/versions/",
        ".nddev-cursor-home/.cursor/plugins/local/nddev-builder",
        "`/bin/bash`",
        "`/usr/bin:/bin`",
        "`Popen`",
    )
    for label, path in docs.items():
        if not path.is_file():
            errors.append(f"missing {label}")
            continue
        text = path.read_text(encoding="utf-8")
        for needle in required_needles:
            if needle not in text:
                errors.append(f"{label}: missing source-owner pointer {needle}")
        for needle in volatile_needles:
            if needle in text:
                errors.append(f"{label}: copies volatile source-owned fact {needle}")
        if "same-UID" not in text:
            errors.append(f"{label}: missing same-UID boundary note")


def main() -> int:
    errors: list[str] = []
    build_version = load_build_version(errors)
    version = load_json("build/version.json", errors)
    manifest = load_json("build/manifest.json", errors)
    contract = load_json("config/nddev-contract.json", errors)
    baseline = load_json("references/cursor-cli-baseline.json", errors)

    if version is not None:
        missing = REQUIRED_VERSION_KEYS - set(version)
        extra = set(version) - REQUIRED_VERSION_KEYS
        if missing:
            errors.append(f"build/version.json: missing required keys {sorted(missing)}")
        if extra:
            errors.append(f"build/version.json: unexpected keys {sorted(extra)}")
        if version.get("schema_version") != 3:
            errors.append("build/version.json: schema_version must be 3")
        if version.get("build_version") != build_version:
            errors.append("build/version.json:build_version must match VERSION")
        if version.get("python_requires") != PYTHON_REQUIRES:
            errors.append("build/version.json: python_requires must include macOS Python 3.9")
        if version.get("cursor_cli_identity") != "agent":
            errors.append("build/version.json: cursor_cli_identity must be agent")
        if version.get("cursor_cli_tested") != CURSOR_RELEASE_ID:
            errors.append("build/version.json: cursor_cli_tested mismatch")
        if version.get("cursor_config_schema") != 1:
            errors.append("build/version.json: cursor_config_schema must be 1")
        if version.get("setup_contract_schema") != 2:
            errors.append("build/version.json: setup_contract_schema must be 2")
        if version.get("nddev_builder_plugin_version") != build_version:
            errors.append("build/version.json: nddev_builder_plugin_version must match VERSION")

    if manifest is not None and version is not None:
        if manifest.get("schema_version") != 3:
            errors.append("build/manifest.json: schema_version must be 3")
        if manifest.get("build_version") != build_version:
            errors.append("build/manifest.json:build_version must match VERSION")
        if manifest.get("build_version") != version.get("build_version"):
            errors.append("build/manifest.json:build_version disagrees with build/version.json")
        if manifest.get("content_setup_ids") != CONTENT_SETUP_IDS:
            errors.append("build/manifest.json: unexpected content_setup_ids")
        if manifest.get("profile_ids") != PROFILE_IDS:
            errors.append("build/manifest.json: unexpected profile_ids")
        if "setup_ids" in manifest:
            errors.append("build/manifest.json: setup_ids must not be used by current contract")
        projection = manifest.get("builder_projection", {})
        if projection.get("target_plugin_path") != BUILDER_TARGET_PATH:
            errors.append("build/manifest.json: builder target path mismatch")
        if projection.get("surfaces") != ["plugin", "rules", "skills", "agents", "commands"]:
            errors.append("build/manifest.json: builder surfaces mismatch")
        if projection.get("hooks_installed") is not False:
            errors.append("build/manifest.json: hooks must not be installed")
        if projection.get("mcp_servers_installed") is not False:
            errors.append("build/manifest.json: MCP servers must not be installed")
        backup = manifest.get("backup_policy", {})
        if backup.get("control_root") != ".nddev-cursor-cli":
            errors.append("build/manifest.json: backup control root mismatch")
        if backup.get("location") != ".nddev-cursor-cli/backups":
            errors.append("build/manifest.json: backup location mismatch")
        if backup.get("envelope_schema") != 3:
            errors.append("build/manifest.json: backup envelope schema mismatch")
        if (
            backup.get("file_record_schema")
            != "payload plus sha256 over canonical declared path and payload bytes"
        ):
            errors.append("build/manifest.json: backup file record schema mismatch")
        if backup.get("restore_digest_required") is not True:
            errors.append("build/manifest.json: backup restore digest requirement mismatch")
        if backup.get("digest_capability") != "corruption-and-incoherent-tamper-detection":
            errors.append("build/manifest.json: backup digest capability mismatch")
        if backup.get("digest_authenticates_same_uid_payloads") is not False:
            errors.append("build/manifest.json: backup digest must not claim authenticity")
        validate_runtime_compatibility(
            "build/manifest.json", manifest.get("runtime_compatibility", {}), errors
        )
        validate_launch_contract("build/manifest.json", manifest.get("runtime_launch", {}), errors)
        validate_software("build/manifest.json", manifest.get("software_install", {}), errors)
        transaction = manifest.get("transaction_policy", {})
        if transaction.get("new_target_mode") != "0700":
            errors.append("build/manifest.json: new target mode mismatch")
        if (
            transaction.get("initial_target_parent")
            != "current-user non-writable-by-others or sticky"
        ):
            errors.append("build/manifest.json: initial target parent policy mismatch")
        if transaction.get("existing_target_required_owner") != "current-user":
            errors.append("build/manifest.json: existing target owner policy mismatch")
        if transaction.get("existing_target_required_mode") != "0700":
            errors.append("build/manifest.json: existing target mode policy mismatch")
        if transaction.get("control_root") != ".nddev-cursor-cli":
            errors.append("build/manifest.json: control root mismatch")
        if transaction.get("lock_parent") != ".nddev-cursor-cli/locks":
            errors.append("build/manifest.json: lock parent mismatch")
        if transaction.get("lock") != ".nddev-cursor-cli/locks/target.lock":
            errors.append("build/manifest.json: lock path mismatch")
        if transaction.get("lock_type") != "persistent flock file":
            errors.append("build/manifest.json: lock type mismatch")
        if transaction.get("lock_file_mode") != "0600":
            errors.append("build/manifest.json: lock file mode mismatch")
        if transaction.get("lock_parent_mode_while_locked") != "0500":
            errors.append("build/manifest.json: lock parent locked mode mismatch")
        if "lock_parent_mode_while_launching" in transaction:
            errors.append("build/manifest.json: transaction lock mode must not be launch-only")
        if (
            transaction.get("bootstrap_lock")
            != BOOTSTRAP_LOCK_PATH
        ):
            errors.append("build/manifest.json: bootstrap lock path mismatch")
        if transaction.get("bootstrap_lock_file_mode") != "0600":
            errors.append("build/manifest.json: bootstrap lock mode mismatch")
        if (
            transaction.get("bootstrap_lock_binding")
            != BOOTSTRAP_LOCK_BINDING
        ):
            errors.append("build/manifest.json: bootstrap lock binding mismatch")
        if transaction.get("mutable_runtime_tmp") != ".nddev-cursor-runtime/tmp":
            errors.append("build/manifest.json: mutable runtime TMPDIR mismatch")
        if (
            transaction.get("managed_transaction_journal")
            != ".nddev-cursor-cli/.managed-txn-<unique>"
        ):
            errors.append("build/manifest.json: managed transaction journal mismatch")
        if transaction.get("managed_transaction_residue_on_failure") is not False:
            errors.append("build/manifest.json: managed transaction residue policy mismatch")
        if (
            transaction.get("target_local_directory_parents")
            != "existing builder and runtime parents must be real current-user-owned 0700; symlinks are drift/fail-closed"
        ):
            errors.append("build/manifest.json: target-local parent policy mismatch")
        if "preserve_existing_target_mode" in transaction:
            errors.append("build/manifest.json: must not preserve arbitrary target mode")
        command_policy = manifest.get("command_policy", {})
        expected_json_commands = [
            "list",
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
        ]
        expected_target_commands = [
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
        ]
        if command_policy.get("json_supported") != expected_json_commands:
            errors.append("build/manifest.json: command_policy JSON commands mismatch")
        if command_policy.get("target_required") != expected_target_commands:
            errors.append("build/manifest.json: command_policy target commands mismatch")

    if contract is not None:
        if contract.get("contract_version") != 3:
            errors.append("config/nddev-contract.json: contract_version must be 3")
        if contract.get("github_repository") != "NDDev-it-com/nddev-cursor-cli-app":
            errors.append("config/nddev-contract.json: unexpected github_repository")
        if "skeleton" in contract:
            errors.append("config/nddev-contract.json: skeleton must be removed")
        managed_state = contract.get("managed_state", {})
        if managed_state.get("managed_files") != ["cli-config.json"]:
            errors.append("config/nddev-contract.json: managed_files mismatch")
        if managed_state.get("stamp_schema") != 2:
            errors.append("config/nddev-contract.json: stamp_schema must be 2")
        setup_system = contract.get("setup_system", {})
        if setup_system.get("content_setup_ids") != CONTENT_SETUP_IDS:
            errors.append("config/nddev-contract.json: content_setup_ids mismatch")
        if setup_system.get("profile_ids") != PROFILE_IDS:
            errors.append("config/nddev-contract.json: profile_ids mismatch")
        if " update " not in f" {setup_system.get('update_command', '')} ":
            errors.append("config/nddev-contract.json: setup update_command mismatch")
        validate_runtime_compatibility(
            "config/nddev-contract.json", contract.get("runtime_compatibility", {}), errors
        )
        safety = contract.get("safety", {})
        if safety.get("new_target_mode") != "0700":
            errors.append("config/nddev-contract.json: new target mode mismatch")
        if safety.get("initial_target_parent") != "current-user non-writable-by-others or sticky":
            errors.append("config/nddev-contract.json: initial target parent policy mismatch")
        if safety.get("existing_target_required_owner") != "current-user":
            errors.append("config/nddev-contract.json: existing target owner policy mismatch")
        if safety.get("existing_target_required_mode") != "0700":
            errors.append("config/nddev-contract.json: existing target mode policy mismatch")
        if safety.get("control_root") != ".nddev-cursor-cli":
            errors.append("config/nddev-contract.json: control root mismatch")
        if safety.get("lock_parent") != ".nddev-cursor-cli/locks":
            errors.append("config/nddev-contract.json: lock parent mismatch")
        if safety.get("lock_path") != ".nddev-cursor-cli/locks/target.lock":
            errors.append("config/nddev-contract.json: lock path mismatch")
        if safety.get("explicit_target_required") != expected_target_commands:
            errors.append("config/nddev-contract.json: explicit target commands mismatch")
        if safety.get("lock_type") != "persistent flock file":
            errors.append("config/nddev-contract.json: lock type mismatch")
        if safety.get("lock_file_mode") != "0600":
            errors.append("config/nddev-contract.json: lock file mode mismatch")
        if safety.get("lock_parent_mode_while_locked") != "0500":
            errors.append("config/nddev-contract.json: lock parent locked mode mismatch")
        if "lock_parent_mode_while_launching" in safety:
            errors.append("config/nddev-contract.json: safety lock mode must not be launch-only")
        if (
            safety.get("bootstrap_lock")
            != BOOTSTRAP_LOCK_PATH
        ):
            errors.append("config/nddev-contract.json: bootstrap lock path mismatch")
        if safety.get("bootstrap_lock_file_mode") != "0600":
            errors.append("config/nddev-contract.json: bootstrap lock mode mismatch")
        if (
            safety.get("bootstrap_lock_binding")
            != BOOTSTRAP_LOCK_BINDING
        ):
            errors.append("config/nddev-contract.json: bootstrap lock binding mismatch")
        if safety.get("backup_path") != ".nddev-cursor-cli/backups":
            errors.append("config/nddev-contract.json: backup path mismatch")
        if safety.get("backup_envelope_schema") != 3:
            errors.append("config/nddev-contract.json: backup envelope schema mismatch")
        if (
            safety.get("backup_file_record_schema")
            != "payload plus sha256 over canonical declared path and payload bytes"
        ):
            errors.append("config/nddev-contract.json: backup file record schema mismatch")
        if safety.get("backup_restore_digest_required") is not True:
            errors.append("config/nddev-contract.json: backup restore digest requirement mismatch")
        if safety.get("backup_digest_capability") != "corruption-and-incoherent-tamper-detection":
            errors.append("config/nddev-contract.json: backup digest capability mismatch")
        if safety.get("backup_digest_authenticates_same_uid_payloads") is not False:
            errors.append("config/nddev-contract.json: backup digest must not claim authenticity")
        if safety.get("mutable_runtime_tmp") != ".nddev-cursor-runtime/tmp":
            errors.append("config/nddev-contract.json: mutable runtime TMPDIR mismatch")
        if (
            safety.get("target_local_directory_parents")
            != "existing builder and runtime parents must be real current-user-owned 0700; symlinks are drift/fail-closed"
        ):
            errors.append("config/nddev-contract.json: target-local parent policy mismatch")
        if "preserve_existing_target_mode" in safety:
            errors.append("config/nddev-contract.json: must not preserve arbitrary target mode")
        validate_launch_contract(
            "config/nddev-contract.json", contract.get("runtime_launch", {}), errors
        )
        software = contract.get("software_install")
        if not isinstance(software, dict):
            errors.append("config/nddev-contract.json: missing software_install")
        else:
            if set(software) != SOFTWARE_KEYS:
                errors.append("config/nddev-contract.json: software_install keys mismatch")
            validate_software("config/nddev-contract.json", software, errors)
            if software.get("mechanism") != "official-cursor-agent-artifact":
                errors.append("config/nddev-contract.json: software_install.mechanism mismatch")
            if software.get("stage_and_atomic_swap") is not True:
                errors.append("config/nddev-contract.json: software_install must stage swaps")
            if software.get("rollback_on_failure") is not True:
                errors.append("config/nddev-contract.json: software_install must rollback")
        lifecycle = contract.get("software_lifecycle")
        if not isinstance(lifecycle, dict):
            errors.append("config/nddev-contract.json: missing software_lifecycle")
        else:
            if set(lifecycle) != SOFTWARE_LIFECYCLE_KEYS:
                errors.append("config/nddev-contract.json: software_lifecycle keys mismatch")
            if lifecycle.get("stamp_file") != "NDDEV-CURSOR-CLI-SOFTWARE.json":
                errors.append("config/nddev-contract.json: software_lifecycle stamp mismatch")
            if lifecycle.get("entrypoint") != "bin/agent":
                errors.append("config/nddev-contract.json: software_lifecycle entrypoint mismatch")
            if "remove-cli" not in str(lifecycle.get("remove_command", "")):
                errors.append(
                    "config/nddev-contract.json: software_lifecycle remove command mismatch"
                )
            if lifecycle.get("status_executes_binary") is not False:
                errors.append("config/nddev-contract.json: software_status must not execute")
            if lifecycle.get("target_owned") is not True:
                errors.append("config/nddev-contract.json: software_lifecycle must be target-owned")
            if lifecycle.get("transaction_marker") != "NDDEV-CURSOR-CLI-TRANSACTION.json":
                errors.append("config/nddev-contract.json: software transaction marker mismatch")
            if (
                lifecycle.get("failure_current_behavior")
                != "exact rollback or transaction marker forces current=false"
            ):
                errors.append("config/nddev-contract.json: software failure behavior mismatch")
        projection = contract.get("builder_projection", {})
        install = projection.get("installation", {})
        if install.get("native_local_plugin_path") != BUILDER_TARGET_PATH:
            errors.append("config/nddev-contract.json: builder native path mismatch")
        if install.get("orthogonal_to_setup_switching") is not True:
            errors.append("config/nddev-contract.json: builder must be orthogonal")
        if projection.get("hooks_installed") is not False:
            errors.append("config/nddev-contract.json: hooks must not be installed")
        if projection.get("mcp_servers_installed") is not False:
            errors.append("config/nddev-contract.json: MCP servers must not be installed")

    if baseline is not None:
        if baseline.get("release", {}).get("id") != CURSOR_RELEASE_ID:
            errors.append("references/cursor-cli-baseline.json: release id mismatch")
        if baseline.get("verified_date") != "2026-07-27":
            errors.append("references/cursor-cli-baseline.json: verified_date mismatch")
        if baseline.get("release", {}).get("artifacts") != EXPECTED_ARTIFACTS:
            errors.append("references/cursor-cli-baseline.json: artifact pins mismatch")
        if baseline.get("host_platform_scope") != BASELINE_PLATFORM_SCOPE:
            errors.append("references/cursor-cli-baseline.json: host platform scope mismatch")
        if baseline.get("observed_vendor_assets") != OBSERVED_VENDOR_ASSETS:
            errors.append("references/cursor-cli-baseline.json: observed vendor assets mismatch")
        observed_assets = (
            baseline.get("observed_vendor_assets", {})
            .get("unsupported_windows", {})
            .get("assets", {})
        )
        for asset_path in observed_assets:
            if asset_path in baseline.get("release", {}).get("artifacts", {}):
                errors.append("references/cursor-cli-baseline.json: Windows asset is supported")
            if asset_path in str(
                baseline.get("host_platform_scope", {}).get("vendor_asset_mapping", {})
            ):
                errors.append(
                    "references/cursor-cli-baseline.json: Windows asset leaked into mapping"
                )
        if baseline.get("cli_identity", {}).get("command") != "agent":
            errors.append("references/cursor-cli-baseline.json: CLI command must be agent")
        if baseline.get("configuration", {}).get("environment_override") != "CURSOR_CONFIG_DIR":
            errors.append("references/cursor-cli-baseline.json: missing CURSOR_CONFIG_DIR")
        install = baseline.get("software_install", {})
        if install.get("version") != CURSOR_RELEASE_ID:
            errors.append("references/cursor-cli-baseline.json: software_install.version mismatch")
        if install.get("managed_command") != "bin/agent":
            errors.append("references/cursor-cli-baseline.json: managed_command mismatch")
        if install.get("npm") is not None or install.get("pip") is not None:
            errors.append(
                "references/cursor-cli-baseline.json: software_install must not use npm/pip"
            )
        if baseline.get("native_capability_surfaces") != EXPECTED_NATIVE_CAPABILITY_SURFACES:
            errors.append(
                "references/cursor-cli-baseline.json: native capability surfaces mismatch"
            )

    validate_profiles(errors)
    validate_builder_toolkit(version, build_version, errors)
    validate_release_roots(errors)
    validate_agents_onboarding_contract(errors)
    validate_public_doc_hygiene(errors)
    validate_public_manager_smokes(errors)
    validate_no_forbidden_public_paths(errors)
    validate_python39_syntax(errors)

    if errors:
        print(f"validate_public_contracts.py: FAIL ({len(errors)} error(s))")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
