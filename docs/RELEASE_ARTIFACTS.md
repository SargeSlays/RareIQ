# Release artifacts

RareIQ source releases are built directly from the committed Git tree, not
from arbitrary working-tree files. Builds require a clean worktree and are
dry-run by default.

```powershell
.\.venv\Scripts\python.exe -B tools\build_release.py build
.\.venv\Scripts\python.exe -B tools\build_release.py build --apply
.\.venv\Scripts\python.exe -B tools\build_release.py verify F:\RareIQ\exports\releases\RareIQ-VERSION-COMMIT.zip
.\.venv\Scripts\python.exe -B tools\build_release.py smoke F:\RareIQ\exports\releases\RareIQ-VERSION-COMMIT.zip --node C:\path\to\node.exe
```

Every archive has one top-level versioned directory and a SHA-256 manifest
covering every committed file. ZIP timestamps and permissions are normalized,
so the same commit produces identical bytes. The builder fails closed if Git
tracks a local configuration, secret, bytecode, log, capture, backup, runtime,
artifact, or environment path. Ignored runtime data is never considered.

The default destination is `<export_path>\releases`. A successful archive
verification proves file integrity and source identity; it does not replace
the canonical release-quality gate.

The `smoke` command verifies and safely extracts the archive into a disposable
directory beside the release, seeds only `storage_config.example.json`, checks
all Python and JavaScript syntax, imports the complete web application, and
runs the canonical suite without any local catalogs, captures, artwork index,
database, or secrets. The disposable installation is removed automatically;
use `--keep` only when an operator needs to inspect it.
