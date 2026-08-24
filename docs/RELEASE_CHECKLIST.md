# RareIQ Release Checklist

Run the release gate from the repository root with the Python 3.13 environment active:

```powershell
.venv\Scripts\python.exe -B tools\release_check.py --require-node
```

If Node.js is not on `PATH`, provide its executable explicitly with `--node`.

The gate verifies:

- installed dependency integrity
- Python syntax without writing bytecode
- JavaScript syntax
- working-tree and staged whitespace
- the complete canonical `tests/` suite

The gate does not require cameras, API credentials, an artwork index, captures, catalog caches, or other runtime data. GitHub Actions runs the same command on Windows for pull requests and protected development/release branches.

Before creating a release tag:

1. Confirm the branch and worktree are clean.
2. Confirm `rareiq/version.py` contains the intended release version and no development suffix.
3. Run the release gate successfully.
4. Review the exact commit and tag targets.
5. Push without force and verify the remote workflow passes.
