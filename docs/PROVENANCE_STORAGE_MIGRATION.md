# Provenance storage migration

RareIQ writes new provenance screenshots, replay highlights, and recordings to
the paths configured in `storage_config.json`. Existing provenance evidence in
`rareiq/data/provenance` remains readable until it is migrated.

The migration is intentionally explicit. Stop RareIQ before applying it so the
source cannot change while files are copied.

## 1. Dry-run

```powershell
.\.venv\Scripts\python.exe -B tools\migrate_provenance_storage.py
```

The report shows the source, configured destination, event count, copy size,
and available destination space. A dry-run writes and deletes nothing.

## 2. Copy and verify

```powershell
.\.venv\Scripts\python.exe -B tools\migrate_provenance_storage.py --apply
```

Files are copied atomically and verified with SHA-256. Existing identical files
are reused, event indexes are merged by stable event ID, and conflicting files
or events stop the migration. The original source remains intact, making an
interrupted copy safe to resume with the same command.

## 3. Release C-drive space

After reviewing the successful verification report, run:

```powershell
.\.venv\Scripts\python.exe -B tools\migrate_provenance_storage.py --apply --remove-source
```

Source removal is permitted only for RareIQ's exact legacy provenance folder
and only after every source file and event has been verified at the configured
destination. The tool refuses nested paths, symbolic links, insufficient disk
space, content conflicts, malformed indexes, and sources that change during
the operation.
