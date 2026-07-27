# Creator, Checker, And Release Validation

Use this reference before handing off public module work.

## Public validation workflow

Run from the module root:

```bash
python3 plugins/nddev-builder/skills/nddev-builder/scripts/validate-toolkit.py --module-root .
python3 cli-tools/validate_public_contracts.py
python3 cli-tools/nddev_cursor_cli.py list --json
```

For a non-live target lifecycle smoke test, use a temporary directory outside
the repository:

```bash
tmpdir="$(mktemp -d)"
target="$tmpdir/cursor-target"
python3 cli-tools/nddev_cursor_cli.py plan --target "$target" --json
python3 cli-tools/nddev_cursor_cli.py install --target "$target" --json
python3 cli-tools/nddev_cursor_cli.py status --target "$target" --json
python3 cli-tools/nddev_cursor_cli.py switch --target "$target" --profile safe --json
python3 cli-tools/nddev_cursor_cli.py remove --target "$target" --json
```

Finish with:

```bash
git diff --check
```

Do not run root harness lanes, private validation, CI, pushes, or tags from this
public toolkit unless the owning phase explicitly authorizes them.

## Creator/checker checklist

- Creator work adds only supported public surfaces.
- Checker work verifies schema, paths, safety invariants, and docs claims.
- Release work updates public version files, changelog, manifest, contract,
  README, and validators in the same module.
- Private root memory and operational skills remain outside this repository.
