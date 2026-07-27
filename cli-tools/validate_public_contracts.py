#!/usr/bin/env python3
"""Validate public nddev-cursor-cli-app contracts without private inputs."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURSOR_RELEASE_ID = "2026.07.23-e383d2b"
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
SOFTWARE_KEYS = {
    "artifact_reader",
    "command",
    "install_command",
    "install_precondition",
    "managed_command",
    "mechanism",
    "npm",
    "official_installer",
    "official_source",
    "pip",
    "presence_signal",
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
    "install_command",
    "install_precondition",
    "presence_signal",
    "private_modes",
    "rollback_on_swap_failure",
    "software_root",
    "stage_and_atomic_swap",
    "stamp_file",
    "stamp_schema",
    "status_command",
    "status_executes_binary",
    "target_owned",
    "update_command",
    "update_precondition",
}
STATUS_FIELDS = ["installed", "current", "present", "presence", "drift"]
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


def real_dirs(root: Path) -> list[str]:
    if not root.is_dir() or root.is_symlink():
        return []
    return sorted(path.name for path in root.iterdir() if path.is_dir() and not path.is_symlink())


def validate_launch_contract(owner: str, launch: dict, errors: list[str]) -> None:
    if launch.get("command") != "agent" or launch.get("managed_command") != "bin/agent":
        errors.append(f"{owner}: runtime_launch must use managed bin/agent")
    if launch.get("isolated_home") != ".nddev-cursor-home":
        errors.append(f"{owner}: runtime_launch isolated_home mismatch")
    if launch.get("path_fallback") is not False:
        errors.append(f"{owner}: runtime_launch.path_fallback must be false")
    if launch.get("requires_current_target_owned_software") is not True:
        errors.append(f"{owner}: runtime_launch must require current target-owned software")
    if launch.get("requires_non_legacy_setup_stamp") is not True:
        errors.append(f"{owner}: runtime_launch must reject legacy setup stamps")
    if launch.get("managed_override_args_blocked") != BLOCKED_LAUNCH_OVERRIDES:
        errors.append(f"{owner}: runtime_launch managed override block list mismatch")


def validate_software(owner: str, software: dict, errors: list[str]) -> None:
    if software.get("version") != CURSOR_RELEASE_ID:
        errors.append(f"{owner}: software_install.version mismatch")
    if software.get("command") != "agent" or software.get("managed_command") != "bin/agent":
        errors.append(f"{owner}: software_install must manage bin/agent")
    if software.get("npm") is not None or software.get("pip") is not None:
        errors.append(f"{owner}: software_install must not declare npm/pip install")
    if "present=true" not in str(software.get("presence_signal", "")):
        errors.append(f"{owner}: software_install.presence_signal mismatch")
    if software.get("status_fields") != STATUS_FIELDS:
        errors.append(f"{owner}: software_install.status_fields mismatch")


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


def validate_builder_toolkit(
    version: dict | None, build_version: str, errors: list[str]
) -> None:
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
                text = candidate.read_text(encoding="utf-8")
                if unsupported_os in text:
                    errors.append(f"{candidate.relative_to(ROOT)}: unsupported OS contract text")


def main() -> int:
    errors: list[str] = []
    build_version = load_build_version(errors)
    version = load_json("build/version.json", errors)
    manifest = load_json("build/manifest.json", errors)
    contract = load_json("config/nddev-contract.json", errors)
    baseline = load_json("references/cursor-cli-baseline.json", errors)
    docs = ROOT / "docs" / "software-lifecycle.md"

    if version is not None:
        missing = REQUIRED_VERSION_KEYS - set(version)
        if missing:
            errors.append(f"build/version.json: missing required keys {sorted(missing)}")
        if version.get("schema_version") != 3:
            errors.append("build/version.json: schema_version must be 3")
        if version.get("build_version") != build_version:
            errors.append("build/version.json:build_version must match VERSION")
        if version.get("cursor_cli_identity") != "agent":
            errors.append("build/version.json: cursor_cli_identity must be agent")
        if version.get("cursor_cli_tested") != CURSOR_RELEASE_ID:
            errors.append("build/version.json: cursor_cli_tested mismatch")
        if version.get("cursor_config_schema") != 1:
            errors.append("build/version.json: cursor_config_schema must be 1")
        if version.get("setup_contract_schema") != 2:
            errors.append("build/version.json: setup_contract_schema must be 2")
        if version.get("nddev_builder_plugin_version") != build_version:
            errors.append(
                "build/version.json: nddev_builder_plugin_version must match VERSION"
            )

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
        validate_launch_contract("build/manifest.json", manifest.get("runtime_launch", {}), errors)
        validate_software("build/manifest.json", manifest.get("software_install", {}), errors)
        commands = manifest.get("command_policy", {}).get("json_supported", [])
        if "migrate" not in commands:
            errors.append("build/manifest.json: command_policy must include migrate")

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
        validate_launch_contract("config/nddev-contract.json", contract.get("runtime_launch", {}), errors)
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
            if lifecycle.get("status_executes_binary") is not False:
                errors.append("config/nddev-contract.json: software_status must not execute")
            if lifecycle.get("target_owned") is not True:
                errors.append("config/nddev-contract.json: software_lifecycle must be target-owned")
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
            errors.append("references/cursor-cli-baseline.json: software_install must not use npm/pip")

    if not docs.is_file():
        errors.append("missing docs/software-lifecycle.md")
    else:
        text = docs.read_text(encoding="utf-8")
        for needle in (
            "install-cli",
            "update-cli",
            "software-status",
            "bin/agent",
            CURSOR_RELEASE_ID,
            BUILDER_TARGET_PATH,
        ):
            if needle not in text:
                errors.append(f"docs/software-lifecycle.md: missing {needle}")

    validate_profiles(errors)
    validate_builder_toolkit(version, build_version, errors)
    validate_no_forbidden_public_paths(errors)

    if errors:
        print(f"validate_public_contracts.py: FAIL ({len(errors)} error(s))")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
