# RareIQ Studio X 6.4.18-dev — WAR Build Foundation

Repository agents must follow the project-management and quality baseline in
[`AGENTS.md`](AGENTS.md) before changing RareIQ.

RareIQ is a live trading-card recognition and production workspace. The current development foundation combines:

- High-resolution camera capture, normalized ROI detection, and rectified card crops
- Continuous recognition with generation-safe card replacement and removal handling
- OCR, artwork verification, variant-family matching, and candidate ranking
- Multi-camera preview sessions with one explicit active recognition source
- Studio X camera, intelligence, session, and provenance workflows
- Deterministic automated coverage for recognition, catalog, inventory, creator, and frontend contracts

Runtime catalogs, artwork indexes, captures, provenance events, diagnostics, and secrets are local data and are intentionally excluded from source control.

Development status and upcoming work are tracked in `docs/ROADMAP.md`.

## Quick start

RareIQ targets Python 3.13. From a Windows command prompt in the project directory:

```bat
start.bat
```

The launcher creates `.venv` when needed, installs the pinned runtime dependencies, and opens RareIQ at `http://127.0.0.1:8765/control`.

On first launch, `storage_config.json` is created from `storage_config.example.json`. Relative paths are resolved beside the local configuration file; edit the local file to place large runtime data on another drive. Credentials belong only in the ignored `rareiq_secrets.json` file or supported environment variables—never in the example file.

For development and tests:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -B -m pytest tests
```

Run the complete release-quality gate with the command documented in [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md).

For opt-in, authenticated access from a phone on the same trusted private
network, follow [`docs/MOBILE_ACCESS.md`](docs/MOBILE_ACCESS.md). RareIQ remains
loopback-only unless LAN mode is explicitly enabled.
