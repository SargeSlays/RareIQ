from __future__ import annotations

import json
import queue
import threading
from types import SimpleNamespace
from pathlib import Path

from rareiq.services.master_database_builder_service import (
    BuildTask,
    MasterDatabaseBuilderService,
)


def test_resume_reimports_legacy_metadata_only_manifests(tmp_path):
    sets_dir = tmp_path / "sets"
    sets_dir.mkdir()

    legacy = sets_dir / "legacy" / "manifest.json"
    legacy.parent.mkdir()
    legacy.write_text(json.dumps({
        "provider": "tcgdex",
        "language": "English",
        "set_id": "base1",
        "cards": 102,
        "images": 0,
    }), encoding="utf-8")

    complete = sets_dir / "complete" / "manifest.json"
    complete.parent.mkdir()
    complete.write_text(json.dumps({
        "provider": "tcgdex",
        "language": "English",
        "set_id": "base2",
        "cards": 64,
        "images": 64,
        "download_complete": True,
    }), encoding="utf-8")

    builder = MasterDatabaseBuilderService.__new__(
        MasterDatabaseBuilderService
    )
    builder.catalog_engine = SimpleNamespace(sets_dir=sets_dir)

    assert builder._completed_keys() == {"tcgdex|english|base2"}


def test_resume_reimports_empty_completed_manifest(tmp_path):
    sets_dir = tmp_path / "sets"
    manifest = sets_dir / "empty" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({
        "provider": "tcgdex",
        "language": "Traditional Chinese",
        "set_id": "empty",
        "cards": 0,
        "images": 0,
        "download_complete": True,
    }), encoding="utf-8")

    builder = MasterDatabaseBuilderService.__new__(
        MasterDatabaseBuilderService
    )
    builder.catalog_engine = SimpleNamespace(sets_dir=sets_dir)

    assert builder._completed_keys() == set()


def test_collection_exposes_live_world_sync_controls():
    root = Path(__file__).resolve().parents[1] / "rareiq" / "web" / "static"
    html = (root / "control.html").read_text(encoding="utf-8")
    script = (root / "studiox.js").read_text(encoding="utf-8")

    for element_id in (
        "librarySyncPanel",
        "librarySyncStart",
        "librarySyncPause",
        "librarySyncCurrentBar",
        "librarySyncOverallBar",
        "librarySyncCoverage",
        "librarySyncFailures",
    ):
        assert f'id="{element_id}"' in html

    assert 'api("/api/master-builder/status")' in script
    assert 'api("/api/master-builder/start"' in script
    assert 'api("/api/master-builder/stop"' in script
    assert "loadLibrarySyncStatus()" in script


def test_freshness_scan_appends_only_new_provider_language_sets(tmp_path):
    sets_dir = tmp_path / "sets"
    complete = sets_dir / "english_old" / "manifest.json"
    complete.parent.mkdir(parents=True)
    complete.write_text(json.dumps({
        "provider": "tcgdex",
        "language": "English",
        "set_id": "me04",
        "cards": 100,
        "images": 100,
        "download_complete": True,
    }), encoding="utf-8")

    discovered = [
        {"provider": "tcgdex", "language": "English", "set_id": "me04", "set_name": "Older", "card_count": 100},
        {"provider": "tcgdex", "language": "English", "set_id": "me05", "set_name": "Pitch Black", "card_count": 120},
        {"provider": "tcgdex", "language": "French", "set_id": "me05", "set_name": "Nuit Noire", "card_count": 120},
    ]
    builder = MasterDatabaseBuilderService.__new__(MasterDatabaseBuilderService)
    builder.master_database = SimpleNamespace(
        discover_all=lambda: {"ok": True, "sets": discovered, "errors": []}
    )
    builder.catalog_engine = SimpleNamespace(sets_dir=sets_dir)
    builder._tasks = queue.Queue()
    builder._tasks.put(BuildTask("tcgdex", "English", "queued", "Already queued", 1))
    builder._lock = threading.RLock()
    builder._refresh_lock = threading.Lock()
    builder._worker = None
    builder._state = {
        "busy": True,
        "sets_queued": 1,
        "new_releases_added": 0,
        "current_provider": None,
        "current_language": None,
        "current_set_id": None,
    }
    builder.queue_path = tmp_path / "queue.json"
    builder._activity = lambda _message: None

    result = builder.refresh_new_releases(start_if_idle=False)

    assert result["ok"] is True
    assert result["added"] == 2
    assert builder._state["sets_queued"] == len(discovered)
    assert builder._state["sets_completed"] == 1
    assert {(item["language"], item["set_id"]) for item in result["sets"]} == {
        ("English", "me05"),
        ("French", "me05"),
    }
    persisted = json.loads(builder.queue_path.read_text(encoding="utf-8"))
    assert [item["set_id"] for item in persisted] == ["queued", "me05", "me05"]


def test_server_exposes_manual_release_refresh_endpoint():
    server = (Path(__file__).resolve().parents[1] / "rareiq" / "web" / "server.py").read_text(encoding="utf-8")
    assert '@app.post("/api/master-builder/refresh")' in server
    assert "refresh_new_releases" in server


def test_server_checks_for_new_tcg_releases_hourly_by_default():
    server = (Path(__file__).resolve().parents[1] / "rareiq" / "web" / "server.py").read_text(encoding="utf-8")
    assert 'os.getenv("RAREIQ_CATALOG_REFRESH_SECONDS", str(60 * 60))' in server
    assert "max(\n    15 * 60," in server
    assert "await asyncio.sleep(CATALOG_REFRESH_INTERVAL_SECONDS)" in server
    assert 'LOGGER.exception("TCG catalog freshness scan failed")' in server


def test_resume_progress_uses_worldwide_denominator():
    source = (Path(__file__).resolve().parents[1] / "rareiq" / "services" / "master_database_builder_service.py").read_text(encoding="utf-8")
    assert '"sets_queued": len(discovered)' in source
    assert '"sets_completed": len(completed_keys & discovered_keys)' in source
    assert 'completed & discovered_keys' in source


def test_transient_provider_failure_is_requeued(tmp_path):
    builder = MasterDatabaseBuilderService.__new__(MasterDatabaseBuilderService)
    builder._tasks = queue.Queue()
    builder._lock = threading.RLock()
    builder._state = {"activity": [], "last_error": None}
    builder.queue_path = tmp_path / "queue.json"
    builder.log_path = tmp_path / "builder.log"
    builder.state_path = tmp_path / "state.json"

    task = BuildTask("pokemontcg", "English", "dp4", "Great Encounters")
    assert builder._requeue_transient_failure(task, "502 Bad Gateway") is True
    retry = builder._tasks.get_nowait()
    assert retry.set_id == "dp4"
    assert retry.attempts == 1
    assert builder._state["last_error"] == "502 Bad Gateway"


def test_permanent_provider_failure_is_not_requeued(tmp_path):
    builder = MasterDatabaseBuilderService.__new__(MasterDatabaseBuilderService)
    builder._tasks = queue.Queue()
    task = BuildTask("tcgdex", "English", "missing", "Missing")

    assert builder._requeue_transient_failure(task, "404 Not Found") is False
    assert builder._tasks.empty()


def test_terminal_failures_are_persisted_by_provider_record() -> None:
    builder = MasterDatabaseBuilderService.__new__(MasterDatabaseBuilderService)
    builder._lock = threading.RLock()
    builder._state = {"sets_failed": 0, "failed_tasks": [], "last_error": None}
    task = BuildTask("pokemontcg", "English", "neo2", "Neo Discovery", attempts=3)

    builder._record_task_failure(task, "500 Internal Server Error")
    builder._record_task_failure(task, "502 Bad Gateway")

    assert builder._state["sets_failed"] == 1
    assert builder._state["failed_tasks"] == [{
        "provider": "pokemontcg",
        "language": "English",
        "set_id": "neo2",
        "set_name": "Neo Discovery",
        "estimated_cards": 0,
        "attempts": 3,
        "task_key": "pokemontcg|english|neo2",
        "error": "502 Bad Gateway",
        "failed_at": builder._state["failed_tasks"][0]["failed_at"],
    }]
    assert builder._state["last_error"] == "502 Bad Gateway"
