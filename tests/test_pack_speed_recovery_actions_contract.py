from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")


def test_failed_recovery_rows_expose_operator_actions():
    render = JS.split("function renderPackRecoveryHistory", 1)[1].split("function loadPackSpeedRun", 1)[0]
    for action in ("retry", "correct", "dismiss"):
        assert f'data-recovery-action="{action}"' in render
    assert "data-recovery-index" in render


def test_retry_is_generation_scoped_and_never_approves():
    retry = JS.split("async function retryPackRecovery", 1)[1].split("function dismissPackRecovery", 1)[0]
    assert "generation!==Number(row.generation)" in retry
    assert "!present" in retry
    assert 'api("/api/camera/capture"' in retry
    assert "/api/session/auto-confirm-recognition" not in retry
    assert "attemptedAt:Date.now()" in retry


def test_stale_correction_is_inspection_only():
    correct = JS.split("function correctPackRecovery", 1)[1].split("function renderPackRecoveryHistory", 1)[0]
    assert "current===Number(row.generation)" in correct
    assert "openMatchCorrectionWorkflow()" in correct
    assert "openReferenceLightbox" in correct
    assert "cannot replace the current live recognition" in correct


def test_recovery_actions_are_responsive():
    assert ".pack-recovery-history article nav" in CSS
    assert "button:disabled" in CSS
    assert "@media(max-width:760px)" in CSS
