# Release artifacts

RareIQ source releases are built directly from the committed Git tree, not
from arbitrary working-tree files. Builds require a clean worktree and are
dry-run by default.

```powershell
.\.venv\Scripts\python.exe -B tools\build_release.py build
.\.venv\Scripts\python.exe -B tools\build_release.py build --apply
.\.venv\Scripts\python.exe -B tools\build_release.py verify F:\RareIQ\exports\releases\RareIQ-VERSION-COMMIT.zip
```

Every archive has one top-level versioned directory and a SHA-256 manifest
covering every committed file. ZIP timestamps and permissions are normalized,
so the same commit produces identical bytes. The builder fails closed if Git
tracks a local configuration, secret, bytecode, log, capture, backup, runtime,
artifact, or environment path. Ignored runtime data is never considered.

The default destination is `<export_path>\releases`. A successful archive
verification proves file integrity and source identity; it does not replace
the canonical release-quality gate or a clean-checkout installation test.
