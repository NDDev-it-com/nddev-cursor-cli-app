#!/usr/bin/env python3
"""Validate public nddev-cursor-cli-app contracts without private inputs."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

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
REQUIRED_ARCHIVE_ROOTS = {
    ".github",
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
        launch.get("lock_mechanism")
        != "persistent 0600 file opened with O_NOFOLLOW and held by nonblocking fcntl.flock"
    ):
        errors.append(f"{owner}: runtime_launch lock mechanism mismatch")
    if launch.get("lock_parent_mode_while_launching") != "0500":
        errors.append(f"{owner}: runtime_launch lock parent mode mismatch")
    if launch.get("software_parent_mode_while_launching") != "0500":
        errors.append(f"{owner}: runtime_launch software parent mode mismatch")
    if (
        launch.get("exec_handoff_revalidation")
        != "verified-path bin/agent inode and digest immediately before subprocess"
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


def run_concurrent_switch(target: Path, profile: str = "safe") -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "cli-tools" / "nddev_cursor_cli.py"),
            "switch",
            "--setup",
            "nddev-builder",
            "--profile",
            profile,
            "--target",
            str(target),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def assert_concurrent_switch_denied(target: Path, errors: list[str], label: str) -> None:
    result = run_concurrent_switch(target)
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode == 0:
        errors.append(f"{label} allowed concurrent lifecycle switch")
    elif "already locked" not in output:
        errors.append(f"{label} concurrent switch failed with unexpected output: {output}")


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
        (control / module.CONTROL_LOCK_NAME).unlink()
        control.rmdir()
        os.symlink(external, module.control_root(target))
        try:
            module.mutate_setup(target, "nddev-builder", "safe", "switch")
        except module.CursorSetupError as exc:
            if "control root" not in str(exc):
                errors.append("internal control root symlink failed with unexpected error")
        else:
            errors.append("internal control root symlink was accepted")

        target = root / "lock-symlink"
        module.mutate_setup(target, "nddev-builder", "full-auto", "install")
        control = module.ensure_control_root(target)
        (control / module.CONTROL_LOCK_NAME).unlink()
        os.symlink(external, control / module.CONTROL_LOCK_NAME)
        try:
            module.mutate_setup(target, "nddev-builder", "safe", "switch")
        except module.CursorSetupError as exc:
            if "target lock path is unsafe" not in str(exc):
                errors.append("internal lock symlink failed with unexpected error")
        else:
            errors.append("internal lock symlink was accepted")

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
        real_slots = sorted(path.name for path in pool.iterdir() if path.is_dir() and not path.is_symlink())
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
                ("migrate", lambda target=target: module.migrate_setup(target, "nddev-builder", None)),
                ("restore", lambda target=target: module.restore_slot(target, 0)),
                ("remove", lambda target=target: module.remove_setup(target)),
                ("launch", lambda target=target: module.launch_cursor(target, ["--", "--help"])),
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

        def fake_run_cursor_child(
            executable: Path, forwarded: list[str], environment: dict[str, str]
        ) -> Any:
            del executable, forwarded
            seen_environment.update(environment)
            control = module.control_root(target)
            lock = module.control_root(target) / module.CONTROL_LOCK_NAME
            if not lock.is_file() or lock.is_symlink():
                errors.append("launch smoke did not expose a persistent lock file")
            else:
                mode = stat.S_IMODE(lock.lstat().st_mode)
                if mode != module.OWNER_FILE_MODE:
                    errors.append(f"launch smoke lock file mode mismatch: {oct(mode)}")
            control_mode = stat.S_IMODE(control.lstat().st_mode)
            if control_mode != module.LOCK_HELD_DIRECTORY_MODE:
                errors.append(f"launch smoke control root was writable: {oct(control_mode)}")
            assert_concurrent_switch_denied(target, errors, "launch lock smoke")
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
                    module.launch_cursor(target, ["--", "-p", "noop"])
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
        real_software_status = module.software_status
        calls = 0
        child_ran = False

        def swapping_software_status(path: Path) -> dict[str, Any]:
            nonlocal calls
            result = real_software_status(path)
            calls += 1
            if calls == 1:
                module.atomic_write_executable(
                    module.managed_agent_path(target),
                    b"#!/bin/bash\necho swapped\n",
                )
            return result

        def fake_run_cursor_child(
            executable: Path, forwarded: list[str], environment: dict[str, str]
        ) -> Any:
            nonlocal child_ran
            del executable, forwarded, environment
            child_ran = True
            return type("Completed", (), {"returncode": 0})()

        with (
            with_restored_attr(module, "software_status", swapping_software_status),
            with_restored_attr(module, "run_cursor_child", fake_run_cursor_child),
        ):
            try:
                module.launch_cursor(target, ["--", "--help"])
            except module.CursorSetupError as exc:
                if "exec handoff" not in str(exc):
                    errors.append(f"swap-at-exec smoke failed with unexpected error: {exc}")
            else:
                errors.append("swap-at-exec smoke unexpectedly allowed launch")
        if calls < 1:
            errors.append("swap-at-exec smoke did not run software status preflight")
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

        def fake_run_cursor_child(
            executable: Path, forwarded: list[str], environment: dict[str, str]
        ) -> Any:
            del executable, forwarded, environment
            control = module.control_root(target)
            lock = control / module.CONTROL_LOCK_NAME
            if not lock.is_file() or lock.is_symlink():
                errors.append("launch protection smoke did not expose lock as regular file")
            if stat.S_IMODE(control.lstat().st_mode) != module.LOCK_HELD_DIRECTORY_MODE:
                errors.append("launch protection smoke did not protect control root")
            expect_permission_denied(
                lambda: lock.unlink(), errors, "launch protection lock unlink"
            )

            replacement = target / "replacement-agent"
            replacement.write_bytes(b"replacement\n")
            replacement.chmod(module.OWNER_EXEC_MODE)
            expect_permission_denied(
                lambda: module.managed_agent_path(target).unlink(),
                errors,
                "launch protection bin/agent unlink",
            )
            expect_permission_denied(
                lambda: os.replace(replacement, module.managed_agent_path(target)),
                errors,
                "launch protection bin/agent replace",
            )
            if replacement.exists():
                replacement.unlink()

            runtime_replacement = target / "replacement-runtime-agent"
            runtime_replacement.write_bytes(b"replacement runtime\n")
            runtime_replacement.chmod(module.OWNER_EXEC_MODE)
            expect_permission_denied(
                lambda: os.replace(runtime_replacement, module.software_tree_binary(target)),
                errors,
                "launch protection runtime binary replace",
            )
            if runtime_replacement.exists():
                runtime_replacement.unlink()

            assert_concurrent_switch_denied(target, errors, "launch protection smoke")
            return type("Completed", (), {"returncode": 0})()

        with with_restored_attr(module, "run_cursor_child", fake_run_cursor_child):
            result = module.launch_cursor(target, ["--", "-p", "noop"])
        if result != 0:
            errors.append(f"launch protection smoke returned {result}")
        if stat.S_IMODE(module.control_root(target).lstat().st_mode) != module.OWNER_DIRECTORY_MODE:
            errors.append("launch protection smoke did not restore control root mode")
        for directory in module.launch_protected_directories(target):
            if stat.S_IMODE(directory.lstat().st_mode) != module.OWNER_DIRECTORY_MODE:
                errors.append(f"launch protection smoke did not restore {directory}")
        status = module.software_status(target)
        if not status["current"]:
            errors.append(f"launch protection smoke left software drift: {status['drift']}")


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
            module.launch_cursor(target, ["--", "--help"])
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


def validate_public_manager_smokes(errors: list[str]) -> None:
    module = load_manager(errors)
    if module is None:
        return
    validate_artifact_source_smokes(module, errors)
    validate_sibling_control_state_ignored_smoke(module, errors)
    validate_insecure_internal_control_state_smoke(module, errors)
    validate_backup_rotation_and_binding_smoke(module, errors)
    validate_target_mode_smokes(module, errors)
    validate_initial_target_parent_smoke(module, errors)
    validate_launch_exception_restore_smoke(module, errors)
    validate_launch_swap_at_exec_smoke(module, errors)
    validate_launch_lock_file_and_write_protection_smoke(module, errors)
    validate_target_local_parent_symlink_smokes(module, errors)


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
        backup = manifest.get("backup_policy", {})
        if backup.get("control_root") != ".nddev-cursor-cli":
            errors.append("build/manifest.json: backup control root mismatch")
        if backup.get("location") != ".nddev-cursor-cli/backups":
            errors.append("build/manifest.json: backup location mismatch")
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
        if transaction.get("lock") != ".nddev-cursor-cli/lock":
            errors.append("build/manifest.json: lock path mismatch")
        if transaction.get("lock_type") != "persistent flock file":
            errors.append("build/manifest.json: lock type mismatch")
        if transaction.get("lock_file_mode") != "0600":
            errors.append("build/manifest.json: lock file mode mismatch")
        if transaction.get("lock_parent_mode_while_launching") != "0500":
            errors.append("build/manifest.json: lock parent launch mode mismatch")
        if (
            transaction.get("target_local_directory_parents")
            != "existing builder and runtime parents must be real current-user-owned 0700; symlinks are drift/fail-closed"
        ):
            errors.append("build/manifest.json: target-local parent policy mismatch")
        if "preserve_existing_target_mode" in transaction:
            errors.append("build/manifest.json: must not preserve arbitrary target mode")
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
        if safety.get("lock_path") != ".nddev-cursor-cli/lock":
            errors.append("config/nddev-contract.json: lock path mismatch")
        if safety.get("lock_type") != "persistent flock file":
            errors.append("config/nddev-contract.json: lock type mismatch")
        if safety.get("lock_file_mode") != "0600":
            errors.append("config/nddev-contract.json: lock file mode mismatch")
        if safety.get("lock_parent_mode_while_launching") != "0500":
            errors.append("config/nddev-contract.json: lock parent launch mode mismatch")
        if safety.get("backup_path") != ".nddev-cursor-cli/backups":
            errors.append("config/nddev-contract.json: backup path mismatch")
        if (
            safety.get("target_local_directory_parents")
            != "existing builder and runtime parents must be real current-user-owned 0700; symlinks are drift/fail-closed"
        ):
            errors.append("config/nddev-contract.json: target-local parent policy mismatch")
        if "preserve_existing_target_mode" in safety:
            errors.append("config/nddev-contract.json: must not preserve arbitrary target mode")
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
    validate_release_roots(errors)
    validate_public_manager_smokes(errors)
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
