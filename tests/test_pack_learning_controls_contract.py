from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / "rareiq/web/server.py").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_active_product_learning_api_supports_inspect_toggle_and_reset():
    assert '@app.get("/api/recognition/pack-learning")' in SERVER
    assert '@app.post("/api/recognition/pack-learning/enabled")' in SERVER
    assert '@app.post("/api/recognition/pack-learning/rename")' in SERVER
    assert '@app.post("/api/recognition/pack-learning/activate")' in SERVER
    assert '@app.post("/api/recognition/pack-learning/reset")' in SERVER
    assert '@app.post("/api/recognition/pack-learning/remove-transition")' in SERVER
    assert '@app.post("/api/recognition/pack-learning/undo-transition")' in SERVER
    assert '@app.get("/api/recognition/pack-learning/export")' in SERVER
    assert '@app.post("/api/recognition/pack-learning/import-preview")' in SERVER
    assert '@app.get("/api/recognition/pack-learning/backups")' in SERVER
    assert '@app.post("/api/recognition/pack-learning/restore")' in SERVER
    assert '@app.post("/api/recognition/pack-learning/import")' in SERVER


def test_pack_run_exposes_scoped_learning_controls():
    for name in ("ensurePackLearningControls", "loadPackLearningStatus", "setPackLearningEnabled", "resetPackLearningContext"):
        assert f"function {name}" in JS or f"async function {name}" in JS
    for element_id in ("packLearningEnabled", "packLearningInspect", "packLearningUndo", "packLearningRecover", "packLearningExport", "packLearningImport", "packLearningImportFile", "packLearningReset", "packLearningEvidence", "packLearningBackups"):
        assert element_id in JS
    assert "active product only" in JS
    assert "function renderPackLearningEvidence" in JS
    assert "async function removePackLearningTransition" in JS
    assert "data-remove-transition" in JS
    assert "async function undoPackLearningTransition" in JS
    assert "async function exportPackLearningModel" in JS
    assert "async function importPackLearningModel" in JS
    assert "Compatibility: Exact match" in JS
    assert "SHA-256 verified" in JS
    assert "Recovery backup saved" in JS
    assert "Previous model backed up locally" in JS
    assert "async function loadPackLearningBackups" in JS
    assert "async function restorePackLearningBackup" in JS
    assert "context_label" in JS
    assert "product_label" in JS
    assert "renamePackLearningContext" in JS
    assert "packLearningThumb" in JS
    assert "packLearningSelector" in JS
    assert "activatePackLearningContext" in JS
    assert "pack_reference" in SERVER
    assert "/api/recognition/pack-learning/import-preview" in JS
