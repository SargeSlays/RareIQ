# Diagnostic bundles

RareIQ can create a small, privacy-bounded support bundle without copying
card images or runtime databases. Creation is dry-run by default.

```powershell
.\.venv\Scripts\python.exe -B tools\diagnostic_bundle.py create
.\.venv\Scripts\python.exe -B tools\diagnostic_bundle.py create --apply
.\.venv\Scripts\python.exe -B tools\diagnostic_bundle.py verify F:\RareIQ\exports\diagnostics\BUNDLE.zip
```

Bundles contain release identity, the current Git branch/commit and filename-
only status, operating-system and Python versions, storage/recovery health,
managed server identity, live system health when reachable, and bounded tails
from at most six recent RareIQ server logs. Each entry is SHA-256 protected by
the bundle manifest.

Bundles never read or include `rareiq_secrets.json`, environment variables,
captures, provenance images, databases, catalogs, artwork, indexes, receipts,
recordings, or replays. Recognizable secret assignments and bearer tokens in
server-log tails are redacted. Review a bundle before sending it outside your
organization because diagnostic paths and operational metadata may still be
personally identifying.
