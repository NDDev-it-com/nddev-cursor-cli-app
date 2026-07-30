# Changelog

All notable changes to `nddev-cursor-cli-app` are documented here.

## [0.2.1] - 2026-07-30

- Capture and strictly resolve the caller workspace once at launch entry, then
  pass it explicitly as Cursor Agent's child working directory.
- Declare the managed target and project workspace roles in public status and
  contracts without inventing a native Cursor workspace flag.

## [0.2.0] - 2026-07-27

- Breaking pre-1.0 contract change: the setup model is now one content setup
  plus orthogonal permission profiles.
- Replaced setup variants with `nddev-builder` content setup plus orthogonal
  `full-auto` and `safe` permission profiles.
- Moved the managed local Cursor plugin projection into the launch-isolated
  home at `.nddev-cursor-home/.cursor/plugins/local/nddev-builder`.
- Added legacy managed-target migration and explicit launch/switch denial for
  legacy setup stamps.
- Expanded the public `nddev-builder` plugin into a routed builder toolkit with
  rules, Agent Skills, references, commands, a custom agent, and public
  validation workflow guidance.

## [0.1.0] - 2026-07-26

- Initial target-explicit Cursor CLI setup manager.
- `safe`, `review`, and `full-auto` setup variants for `cli-config.json`.
- Default-on native `nddev-builder` Cursor plugin projection with rules,
  skills, and agents components.
- Target-owned Cursor Agent software status/install/update lifecycle using
  pinned official Cursor artifacts.
