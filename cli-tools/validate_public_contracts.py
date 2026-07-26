#!/usr/bin/env python3
"""Validate public nddev-cursor-cli-app contracts without private inputs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIRED_VERSION_KEYS = {
    "build_version",
    "cursor_cli_identity",
    "cursor_cli_tested",
    "cursor_config_schema",
    "nddev_builder_plugin_version",
    "python_requires",
    "runtime_baseline_ref",
    "schema_version",
}
CURSOR_RELEASE_ID = "2026.07.23-e383d2b"
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


def main() -> int:
    errors: list[str] = []
    version = load_json("build/version.json", errors)
    manifest = load_json("build/manifest.json", errors)
    contract = load_json("config/nddev-contract.json", errors)
    baseline = load_json("references/cursor-cli-baseline.json", errors)
    plugin = load_json("plugins/nddev-builder/.cursor-plugin/plugin.json", errors)
    docs = ROOT / "docs" / "software-lifecycle.md"

    version_text = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if version is not None:
        missing = REQUIRED_VERSION_KEYS - set(version)
        if missing:
            errors.append(f"build/version.json: missing required keys {sorted(missing)}")
        if version.get("build_version") != version_text:
            errors.append("VERSION and build/version.json:build_version disagree")
        if version.get("cursor_cli_identity") != "agent":
            errors.append("build/version.json: cursor_cli_identity must be agent")
        if version.get("cursor_cli_tested") != CURSOR_RELEASE_ID:
            errors.append(
                "build/version.json: cursor_cli_tested must be the current Cursor release id"
            )
        if version.get("cursor_config_schema") != 1:
            errors.append("build/version.json: cursor_config_schema must be 1")

    if manifest is not None and version is not None:
        if manifest.get("build_version") != version.get("build_version"):
            errors.append("build/manifest.json:build_version disagrees with build/version.json")
        if manifest.get("setup_ids") != ["full-auto", "review", "safe"]:
            errors.append("build/manifest.json: unexpected setup_ids")
        projection = manifest.get("builder_projection")
        if not isinstance(projection, dict) or projection.get("default_on") is not True:
            errors.append("build/manifest.json: builder_projection.default_on must be true")
        launch = manifest.get("runtime_launch", {})
        if launch.get("command") != "agent" or launch.get("managed_command") != "bin/agent":
            errors.append("build/manifest.json: runtime_launch must use managed bin/agent")
        if launch.get("path_fallback") is not False:
            errors.append("build/manifest.json: runtime_launch.path_fallback must be false")
        if launch.get("requires_current_target_owned_software") is not True:
            errors.append(
                "build/manifest.json: runtime_launch must require current target-owned software"
            )
        software = manifest.get("software_install", {})
        if software.get("version") != CURSOR_RELEASE_ID:
            errors.append("build/manifest.json: software_install.version mismatch")
        if software.get("command") != "agent" or software.get("managed_command") != "bin/agent":
            errors.append("build/manifest.json: software_install must manage bin/agent")
        if software.get("npm") is not None or software.get("pip") is not None:
            errors.append("build/manifest.json: software_install must not declare npm/pip install")
        if "present=true" not in str(software.get("presence_signal", "")):
            errors.append("build/manifest.json: software_install.presence_signal mismatch")
        if software.get("status_fields") != STATUS_FIELDS:
            errors.append("build/manifest.json: software_install.status_fields mismatch")

    if contract is not None:
        if contract.get("contract_version") != 2:
            errors.append("config/nddev-contract.json: contract_version must be 2")
        if contract.get("github_repository") != "NDDev-it-com/nddev-cursor-cli-app":
            errors.append("config/nddev-contract.json: unexpected github_repository")
        if "skeleton" in contract:
            errors.append("config/nddev-contract.json: skeleton must be removed")
        managed = contract.get("managed_state", {}).get("managed_files")
        if managed != ["cli-config.json"]:
            errors.append("config/nddev-contract.json: managed_state.managed_files mismatch")
        launch = contract.get("runtime_launch", {})
        if launch.get("command") != "agent" or launch.get("managed_command") != "bin/agent":
            errors.append("config/nddev-contract.json: runtime_launch must use managed bin/agent")
        if launch.get("path_fallback") is not False:
            errors.append("config/nddev-contract.json: runtime_launch.path_fallback must be false")
        if launch.get("requires_current_target_owned_software") is not True:
            errors.append(
                "config/nddev-contract.json: runtime_launch must require current target-owned software"
            )
        software = contract.get("software_install")
        if not isinstance(software, dict):
            errors.append("config/nddev-contract.json: missing software_install")
        else:
            if set(software) != SOFTWARE_KEYS:
                errors.append("config/nddev-contract.json: software_install keys mismatch")
            if software.get("version") != CURSOR_RELEASE_ID:
                errors.append("config/nddev-contract.json: software_install.version mismatch")
            if software.get("mechanism") != "official-cursor-agent-artifact":
                errors.append("config/nddev-contract.json: software_install.mechanism mismatch")
            if software.get("command") != "agent" or software.get("managed_command") != "bin/agent":
                errors.append("config/nddev-contract.json: software_install must manage bin/agent")
            if software.get("npm") is not None or software.get("pip") is not None:
                errors.append("config/nddev-contract.json: software_install must not allow npm/pip")
            if "present=true" not in str(software.get("presence_signal", "")):
                errors.append(
                    "config/nddev-contract.json: software_install.presence_signal mismatch"
                )
            if software.get("status_fields") != STATUS_FIELDS:
                errors.append("config/nddev-contract.json: software_install.status_fields mismatch")
            if software.get("stage_and_atomic_swap") is not True:
                errors.append(
                    "config/nddev-contract.json: software_install must stage atomic swaps"
                )
            if software.get("rollback_on_failure") is not True:
                errors.append(
                    "config/nddev-contract.json: software_install must rollback on failure"
                )
        lifecycle = contract.get("software_lifecycle")
        if not isinstance(lifecycle, dict):
            errors.append("config/nddev-contract.json: missing software_lifecycle")
        else:
            if set(lifecycle) != SOFTWARE_LIFECYCLE_KEYS:
                errors.append("config/nddev-contract.json: software_lifecycle keys mismatch")
            if "present=true" not in str(lifecycle.get("presence_signal", "")):
                errors.append(
                    "config/nddev-contract.json: software_lifecycle.presence_signal mismatch"
                )
            if lifecycle.get("stamp_file") != "NDDEV-CURSOR-CLI-SOFTWARE.json":
                errors.append("config/nddev-contract.json: software_lifecycle stamp mismatch")
            if lifecycle.get("entrypoint") != "bin/agent":
                errors.append("config/nddev-contract.json: software_lifecycle entrypoint mismatch")
            if lifecycle.get("status_executes_binary") is not False:
                errors.append(
                    "config/nddev-contract.json: software_status must not execute binaries"
                )
            if lifecycle.get("target_owned") is not True:
                errors.append("config/nddev-contract.json: software_lifecycle must be target-owned")

    if baseline is not None:
        if version is not None and baseline.get("release", {}).get("id") != version.get(
            "cursor_cli_tested"
        ):
            errors.append("references/cursor-cli-baseline.json: release id disagrees with version")
        if baseline.get("release", {}).get("id") != CURSOR_RELEASE_ID:
            errors.append("references/cursor-cli-baseline.json: release id mismatch")
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
            errors.append(
                "references/cursor-cli-baseline.json: software_install.managed_command mismatch"
            )
        if install.get("npm") is not None or install.get("pip") is not None:
            errors.append(
                "references/cursor-cli-baseline.json: software_install must not use npm/pip"
            )

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
        ):
            if needle not in text:
                errors.append(f"docs/software-lifecycle.md: missing {needle}")

    setup_ids: list[str] = []
    for setup_dir in sorted((ROOT / "setups").iterdir()):
        if not setup_dir.is_dir():
            continue
        setup = load_json(f"setups/{setup_dir.name}/setup.json", errors)
        config = load_json(f"setups/{setup_dir.name}/cli-config.json", errors)
        if setup is not None:
            if setup.get("id") != setup_dir.name:
                errors.append(f"setups/{setup_dir.name}/setup.json: id mismatch")
            if setup.get("managed_files") != ["cli-config.json"]:
                errors.append(f"setups/{setup_dir.name}/setup.json: managed_files mismatch")
            if setup.get("builder_projection") != "default-on":
                errors.append(f"setups/{setup_dir.name}/setup.json: builder must be default-on")
            setup_ids.append(setup_dir.name)
        if config is not None:
            if config.get("version") != 1:
                errors.append(f"setups/{setup_dir.name}/cli-config.json: version must be 1")
            if "permissions" not in config:
                errors.append(f"setups/{setup_dir.name}/cli-config.json: missing permissions")

    if setup_ids != ["full-auto", "review", "safe"]:
        errors.append(f"setups/: unexpected setup directories {setup_ids}")

    if plugin is not None and version is not None:
        if plugin.get("name") != "nddev-builder":
            errors.append("plugins/nddev-builder: plugin name must be nddev-builder")
        if plugin.get("version") != version.get("nddev_builder_plugin_version"):
            errors.append("plugins/nddev-builder: version disagrees with build/version.json")
    for relative in (
        "plugins/nddev-builder/rules/nddev-builder.mdc",
        "plugins/nddev-builder/skills/nddev-builder/SKILL.md",
        "plugins/nddev-builder/agents/nddev-builder.md",
    ):
        if not (ROOT / relative).is_file():
            errors.append(f"missing builder projection source: {relative}")

    if errors:
        print(f"validate_public_contracts.py: FAIL ({len(errors)} error(s))")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("validate_public_contracts.py: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
