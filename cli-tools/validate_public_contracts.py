#!/usr/bin/env python3
"""Validate public nddev-cursor-cli-app contracts without private inputs."""

from __future__ import annotations

import ast
import base64
import json
import re
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURSOR_RELEASE_ID = "2026.07.23-e383d2b"
PYTHON_REQUIRES = ">=3.9"
BOOTSTRAP_LOCK_SCOPE = (
    "mutations publish or open the product anchor before target observation, then hand off to "
    "the canonical mutation anchor; read-only commands create no anchors and use cold no-anchor "
    "double-check with whole product-namespace emptiness or shared product/canonical coordination"
)
BOOTSTRAP_PRODUCT_ANCHOR = (
    "/tmp-or-resolved-system-temp/nddev-cursor-cli-app-locks-<uid>/global.lock"
)
BOOTSTRAP_CANONICAL_ANCHOR = (
    "/tmp-or-resolved-system-temp/nddev-cursor-cli-app-locks-<uid>/"
    "nddev-cursor-cli-app-<sha256(product-name NUL canonical-target-key)>.lock"
)
BOOTSTRAP_LOCK_BINDING = "schema/product/lock-key/product-target-sha256 JSON"
BOOTSTRAP_PUBLICATION = (
    "atomic no-replace final-path publication of a complete fsynced binding; final anchor "
    "is monotonic immediately when visible, parent sync or handoff failure leaves it in "
    "place and removes only unpublished temporary aliases; existing anchors open "
    "no-create/no-follow and are never truncated, rebound, replaced, or unlinked; a "
    "crashed hard-link publication alias is recovered only after locking final and proving "
    "one bounded machine-named same-inode alias in the same private parent"
)
READ_ONLY_ANCHOR_COMMANDS = ["status", "plan", "software-status"]
CLEANUP_PENDING_PATH = ".nddev-cursor-cli/cleanup-pending"
CLEANUP_PENDING_JOURNAL = ".nddev-cursor-cli/cleanup-pending/journal.json"
CLEANUP_PENDING_INTENT = ".nddev-cursor-cli/cleanup-pending/intent.json"
CLEANUP_JOURNAL_MAX_BYTES = 2 * 1024 * 1024
CLEANUP_PENDING_SEMANTICS = (
    "schema-1 cleanup journal plus durable pre-move intent with fixed-anchor relative sources; "
    "read-only validates and reports cleanup_pending without mutation; mutations drain before "
    "active changes; malformed or orphaned cleanup state fails closed"
)
LAUNCH_IMAGE_PATH = ".nddev-software/cursor-cli/launch-images/.launch-<bounded>"
LAUNCH_IMAGE_LEASE = f"{LAUNCH_IMAGE_PATH}/.lease.lock"
LAUNCH_IMAGE_METADATA = f"{LAUNCH_IMAGE_PATH}/NDDEV-CURSOR-CLI-LAUNCH.json"
LAUNCH_IMAGE_MAX_COUNT = 8
LAUNCH_IMAGE_MAX_TOTAL_SIZE = 300 * 1024 * 1024
LAUNCH_IMAGE_RESIDUE_SEMANTICS = (
    "read-only status validates and exposes active/stale lease-bound images without mutation; "
    "mutations drain stale images with bounded no-follow cleanup before active work and fail "
    "closed while a lease is active"
)
SOFTWARE_PRESENCE_SIGNAL = (
    "software-status JSON exposes present=true and presence entries for "
    "NDDEV-CURSOR-CLI-SOFTWARE.json, .nddev-software/cursor-cli, "
    ".nddev-software/cursor-cli/launch-images, "
    ".nddev-software/cursor-cli/versions/2026.07.23-e383d2b, or bin/agent"
)
SOFTWARE_STATUS_FIELDS = [
    "installed",
    "current",
    "present",
    "presence",
    "drift",
    "cleanup_pending",
    "cleanup",
    "launch_image_residue_pending",
    "launch_image_residue",
]
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
    "status_fields",
    "target_owned",
    "transaction_marker",
    "update_command",
    "update_precondition",
}
STATUS_FIELDS = SOFTWARE_STATUS_FIELDS
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
            errors.append(
                f"{path.relative_to(ROOT)}: unreadable for Python 3.9 syntax check: {exc}"
            )
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
    if launch.get("bootstrap_lock_scope") != BOOTSTRAP_LOCK_SCOPE:
        errors.append(f"{owner}: runtime_launch bootstrap lock scope mismatch")
    if launch.get("bootstrap_lock_exposed_to_child") is not False:
        errors.append(f"{owner}: runtime_launch bootstrap lock must not be exposed to child")
    if (
        launch.get("lock_mechanism")
        != "persistent 0600 monotonic anchors opened with O_NOFOLLOW and held by nonblocking fcntl.flock; product anchor uses exclusive/shared coordination and canonical target anchors use exclusive mutation/shared read coordination"
    ):
        errors.append(f"{owner}: runtime_launch lock mechanism mismatch")
    if launch.get("lock_parent_mode_while_launching") != "0500":
        errors.append(f"{owner}: runtime_launch lock parent mode mismatch")
    if (
        launch.get("protected_directory_scope")
        != "dedicated lock parent and lease-bound verified launch image only; control root, backup pool, target root, isolated HOME, TMPDIR, config/session paths, and installed runtime tree remain writable"
    ):
        errors.append(f"{owner}: runtime_launch protected directory scope mismatch")
    if launch.get("launch_image") != LAUNCH_IMAGE_PATH:
        errors.append(f"{owner}: runtime_launch launch image mismatch")
    if launch.get("launch_image_lease") != LAUNCH_IMAGE_LEASE:
        errors.append(f"{owner}: runtime_launch launch image lease mismatch")
    if launch.get("launch_image_metadata") != LAUNCH_IMAGE_METADATA:
        errors.append(f"{owner}: runtime_launch launch image metadata mismatch")
    if launch.get("launch_image_mode_while_launching") != "0500":
        errors.append(f"{owner}: runtime_launch launch image mode mismatch")
    if launch.get("launch_image_max_count") != LAUNCH_IMAGE_MAX_COUNT:
        errors.append(f"{owner}: runtime_launch launch image count bound mismatch")
    if launch.get("launch_image_max_total_size") != LAUNCH_IMAGE_MAX_TOTAL_SIZE:
        errors.append(f"{owner}: runtime_launch launch image size bound mismatch")
    if launch.get("launch_image_residue_semantics") != LAUNCH_IMAGE_RESIDUE_SEMANTICS:
        errors.append(f"{owner}: runtime_launch launch image residue semantics mismatch")
    if (
        launch.get("exec_handoff_revalidation")
        != "verified launch-image executable inode and digest immediately before subprocess"
    ):
        errors.append(f"{owner}: runtime_launch exec handoff revalidation mismatch")
    if (
        launch.get("exec_handoff_boundary")
        != "write-protected verified-path handoff with child-held launch-image lease fd under no-sandbox same-UID limits; no portable fd execution claimed"
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
    if software.get("presence_signal") != SOFTWARE_PRESENCE_SIGNAL:
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
        expected = expected | {f"{BUILDER_TARGET_PATH}/{name}"}
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
                expected = expected | {
                    f"{BUILDER_TARGET_PATH}/{source.relative_to(plugin_root).as_posix()}"
                }
    return expected


def validate_builder_projection_parity(errors: list[str]) -> None:
    expected = expected_builder_projection_files(errors)
    manager_path = ROOT / "cli-tools" / "nddev_cursor_cli.py"
    try:
        source = manager_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(manager_path))
    except (OSError, SyntaxError) as exc:
        errors.append(f"cannot parse nddev_cursor_cli.py for projection parity: {exc}")
        return
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    projection = functions.get("builder_projection_files")
    source_inventory = functions.get("builder_source_files")
    if projection is None or source_inventory is None:
        errors.append("manager builder projection functions are missing")
        return
    projection_source = "\n".join(
        ast.get_source_segment(source, node) or ""
        for node in (source_inventory, projection)
    )
    for token in (
        "BUILDER_SOURCE_ROOT",
        "BUILDER_TARGET_ROOT",
        "BUILDER_ROOT_FILES",
        "BUILDER_COMPONENT_ROOTS",
        "rglob",
        "relative_to",
    ):
        if token not in projection_source:
            errors.append(f"manager builder projection omits static source token: {token}")
    if not expected:
        errors.append("builder projection source inventory is empty")


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
        if transaction.get("bootstrap_product_anchor") != BOOTSTRAP_PRODUCT_ANCHOR:
            errors.append("build/manifest.json: bootstrap product anchor mismatch")
        if transaction.get("bootstrap_canonical_mutation_anchor") != BOOTSTRAP_CANONICAL_ANCHOR:
            errors.append("build/manifest.json: bootstrap canonical anchor mismatch")
        if transaction.get("bootstrap_lock_file_mode") != "0600":
            errors.append("build/manifest.json: bootstrap lock mode mismatch")
        if transaction.get("bootstrap_lock_binding") != BOOTSTRAP_LOCK_BINDING:
            errors.append("build/manifest.json: bootstrap lock binding mismatch")
        if transaction.get("bootstrap_anchor_publication") != BOOTSTRAP_PUBLICATION:
            errors.append("build/manifest.json: bootstrap anchor publication mismatch")
        if transaction.get("read_only_anchor_creation") is not False:
            errors.append("build/manifest.json: read-only anchor creation policy mismatch")
        if transaction.get("read_only_anchor_commands") != READ_ONLY_ANCHOR_COMMANDS:
            errors.append("build/manifest.json: read-only anchor commands mismatch")
        if transaction.get("read_only_cold_no_anchor_double_check") is not True:
            errors.append("build/manifest.json: read-only cold double-check mismatch")
        if transaction.get("read_only_orphan_canonical_anchor") != "fail-closed":
            errors.append("build/manifest.json: orphan canonical anchor policy mismatch")
        if transaction.get("cleanup_pending_path") != CLEANUP_PENDING_PATH:
            errors.append("build/manifest.json: cleanup pending path mismatch")
        if transaction.get("cleanup_pending_journal") != CLEANUP_PENDING_JOURNAL:
            errors.append("build/manifest.json: cleanup pending journal mismatch")
        if transaction.get("cleanup_pending_intent") != CLEANUP_PENDING_INTENT:
            errors.append("build/manifest.json: cleanup pending intent mismatch")
        if transaction.get("cleanup_journal_max_bytes") != CLEANUP_JOURNAL_MAX_BYTES:
            errors.append("build/manifest.json: cleanup journal max bytes mismatch")
        if transaction.get("cleanup_pending_semantics") != CLEANUP_PENDING_SEMANTICS:
            errors.append("build/manifest.json: cleanup pending semantics mismatch")
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
        if "--setup" in str(setup_system.get("update_command", "")) or "--profile" in str(
            setup_system.get("update_command", "")
        ):
            errors.append("config/nddev-contract.json: setup update_command must be target-only")
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
        if safety.get("bootstrap_product_anchor") != BOOTSTRAP_PRODUCT_ANCHOR:
            errors.append("config/nddev-contract.json: bootstrap product anchor mismatch")
        if safety.get("bootstrap_canonical_mutation_anchor") != BOOTSTRAP_CANONICAL_ANCHOR:
            errors.append("config/nddev-contract.json: bootstrap canonical anchor mismatch")
        if safety.get("bootstrap_lock_file_mode") != "0600":
            errors.append("config/nddev-contract.json: bootstrap lock mode mismatch")
        if safety.get("bootstrap_lock_binding") != BOOTSTRAP_LOCK_BINDING:
            errors.append("config/nddev-contract.json: bootstrap lock binding mismatch")
        if safety.get("bootstrap_anchor_publication") != BOOTSTRAP_PUBLICATION:
            errors.append("config/nddev-contract.json: bootstrap anchor publication mismatch")
        if safety.get("read_only_anchor_creation") is not False:
            errors.append("config/nddev-contract.json: read-only anchor creation policy mismatch")
        if safety.get("read_only_anchor_commands") != READ_ONLY_ANCHOR_COMMANDS:
            errors.append("config/nddev-contract.json: read-only anchor commands mismatch")
        if safety.get("read_only_cold_no_anchor_double_check") is not True:
            errors.append("config/nddev-contract.json: read-only cold double-check mismatch")
        if safety.get("read_only_orphan_canonical_anchor") != "fail-closed":
            errors.append("config/nddev-contract.json: orphan canonical anchor policy mismatch")
        if safety.get("cleanup_pending_path") != CLEANUP_PENDING_PATH:
            errors.append("config/nddev-contract.json: cleanup pending path mismatch")
        if safety.get("cleanup_pending_journal") != CLEANUP_PENDING_JOURNAL:
            errors.append("config/nddev-contract.json: cleanup pending journal mismatch")
        if safety.get("cleanup_pending_intent") != CLEANUP_PENDING_INTENT:
            errors.append("config/nddev-contract.json: cleanup pending intent mismatch")
        if safety.get("cleanup_journal_max_bytes") != CLEANUP_JOURNAL_MAX_BYTES:
            errors.append("config/nddev-contract.json: cleanup journal max bytes mismatch")
        if safety.get("cleanup_pending_semantics") != CLEANUP_PENDING_SEMANTICS:
            errors.append("config/nddev-contract.json: cleanup pending semantics mismatch")
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
            if lifecycle.get("presence_signal") != SOFTWARE_PRESENCE_SIGNAL:
                errors.append(
                    "config/nddev-contract.json: software_lifecycle presence signal mismatch"
                )
            if lifecycle.get("status_fields") != STATUS_FIELDS:
                errors.append(
                    "config/nddev-contract.json: software_lifecycle status fields mismatch"
                )
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
        if "observed_vendor_assets" in baseline:
            errors.append(
                "references/cursor-cli-baseline.json: observation-only vendor assets are public"
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
