from pathlib import Path


SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_collection_full_backup_and_two_phase_import_routes_exist():
    assert "orchestrator.collection.backup()" in SERVER
    assert '@app.post("/api/collection/import/preview")' in SERVER
    assert '@app.post("/api/collection/import/merge")' in SERVER
    assert "orchestrator.collection.preview_import" in SERVER
    assert "orchestrator.collection.merge_backup" in SERVER


def test_collection_recovery_ui_requires_preview_before_merge():
    assert 'id="collectionBackupFile"' in CONTROL
    assert 'id="previewCollectionBackup"' in CONTROL
    assert 'id="mergeCollectionBackup" type="button" disabled' in CONTROL
    assert 'id="collectionImportPreview"' in CONTROL
    assert "function readCollectionBackup()" in STUDIO
    assert "function mergeCollectionBackup()" in STUDIO
    assert "keep the higher owned quantity" in STUDIO


def test_collection_recovery_actions_are_one_shot_and_retryable():
    preview = STUDIO[STUDIO.index("async function readCollectionBackup()"):STUDIO.index("async function mergeCollectionBackup()")]
    merge = STUDIO[STUDIO.index("async function mergeCollectionBackup()"):STUDIO.index("function renderCollectionGoals")]
    assert 'if(button?.disabled)return null' in preview
    assert 'button.textContent="Previewing…"' in preview
    assert "collectionImportBackup=null" in preview
    assert "merge.disabled=true" in preview
    assert "finally{if(button){button.disabled=false" in preview
    assert 'if(button?.disabled)return null' in merge
    assert 'button.textContent="Merging…"' in merge
    assert "let merged=false" in merge
    assert "button.disabled=merged||!collectionImportBackup" in merge


def test_generated_production_session_state_is_ignored():
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "production_session.json" in ignore
    assert "production_history.json" in ignore
