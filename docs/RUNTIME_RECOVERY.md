# Runtime recovery

RareIQ runtime recovery snapshots are atomic, manifest-backed, and SHA-256
verified. They never include `rareiq_secrets.json`; keep provider credentials
in a password manager or another encrypted secret store.

## Critical checkpoint

Stop RareIQ before applying a snapshot so mutable state remains consistent.

```powershell
.\.venv\Scripts\python.exe -B tools\runtime_recovery.py create
.\.venv\Scripts\python.exe -B tools\runtime_recovery.py create --apply
```

The default dry-run reports the file count, size, scopes, and whether the
destination shares a physical volume with the source. The critical profile
contains collection/inventory state, configuration databases, JSON cache
state, session history, project runtime JSON, and provenance manifests. It
does not duplicate screenshot, replay, or recording media.

## Media checkpoint

Media checkpoints are opt-in because they can be very large:

```powershell
.\.venv\Scripts\python.exe -B tools\runtime_recovery.py create --profile media
.\.venv\Scripts\python.exe -B tools\runtime_recovery.py create --profile media --destination G:\RareIQ-Backup --apply
```

For protection from physical drive failure, place a snapshot on a different
physical disk or encrypted cloud volume. A snapshot under `F:\RareIQ\backups`
protects against application corruption but is not a disaster-grade copy of
the F: drive.

## Verify and restore

```powershell
.\.venv\Scripts\python.exe -B tools\runtime_recovery.py verify F:\RareIQ\backups\runtime-snapshots\SNAPSHOT-ID
.\.venv\Scripts\python.exe -B tools\runtime_recovery.py restore F:\RareIQ\backups\runtime-snapshots\SNAPSHOT-ID
.\.venv\Scripts\python.exe -B tools\runtime_recovery.py restore F:\RareIQ\backups\runtime-snapshots\SNAPSHOT-ID --apply
```

Restore defaults to dry-run. Applied restores verify the complete snapshot
first, write files atomically, retain overwritten files in a timestamped
rollback directory, and automatically restore originals if any write fails.
Extra live files are never deleted merely because they are absent from a
snapshot.

## Daily checkpoints and retention

The scheduled runner creates a verified critical snapshot and then retains
the newest 14 fully verified snapshots. Unknown directories, partial output,
linked paths, and snapshots that fail verification are never pruned.

```powershell
.\.venv\Scripts\python.exe -B tools\runtime_recovery.py scheduled-run --keep 14
.\.venv\Scripts\python.exe -B tools\runtime_recovery.py prune --keep 14
.\.venv\Scripts\python.exe -B tools\runtime_recovery.py prune --keep 14 --apply
```

Install the user-level Windows daily task at 03:00 after reviewing its dry
run. The task uses the repository virtual environment and does not invoke a
shell.

```powershell
.\.venv\Scripts\python.exe -B tools\runtime_recovery.py schedule --time 03:00 --keep 14
.\.venv\Scripts\python.exe -B tools\runtime_recovery.py schedule --time 03:00 --keep 14 --apply
```

`/api/storage/status` reports manifest-level checkpoint health and age. Run
the explicit `verify` command for full payload verification. The default
same-F-drive schedule protects against application corruption; it does not
protect against physical loss of the F: drive.
