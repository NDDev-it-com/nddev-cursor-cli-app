# nddev-cursor-cli-app

Portable setup manager for Cursor CLI configuration. It manages one explicit
absolute Cursor config target, never the caller's live `~/.cursor` by default.

## Usage

```bash
python3 cli-tools/nddev_cursor_cli.py list
python3 cli-tools/nddev_cursor_cli.py plan --setup safe --target /absolute/cursor-config
python3 cli-tools/nddev_cursor_cli.py install --setup safe --target /absolute/cursor-config
python3 cli-tools/nddev_cursor_cli.py switch --setup review --target /absolute/cursor-config
python3 cli-tools/nddev_cursor_cli.py restore --backup 0 --target /absolute/cursor-config
python3 cli-tools/nddev_cursor_cli.py remove --target /absolute/cursor-config
```

`launch` runs `agent` with `CURSOR_CONFIG_DIR` scoped only to the child process:

```bash
python3 cli-tools/nddev_cursor_cli.py launch --target /absolute/cursor-config -- -p "summarize"
```

The setup variants also project `nddev-builder` as a local native Cursor plugin
under the selected target. The projection uses Cursor's plugin, rules, skills,
and custom agents surfaces. This module does not provision Cursor team
marketplaces.
