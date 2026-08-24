from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "rareiq" / "web" / "static" / "studiox.js").read_text(encoding="utf-8-sig")


def test_background_tabs_skip_existing_network_pollers() -> None:
    assert 'setInterval(()=>{if(document.hidden!==true)loadRecognition()},600)' in SCRIPT
    assert 'setInterval(()=>{if(document.hidden!==true)loadCameraStatus({forceStream:false})},1800)' in SCRIPT
    assert 'setInterval(()=>{if(document.hidden!==true)loadSystemHealth()},5000)' in SCRIPT
    assert 'setInterval(()=>{if(document.hidden!==true)loadCameraManagerState()},1800)' in SCRIPT
    assert 'document.hidden!==true&&document.body.dataset.ui4Workspace==="broadcast"' in SCRIPT


def test_foreground_transition_runs_one_bounded_catch_up_refresh() -> None:
    section = SCRIPT[SCRIPT.index("async function refreshStudioXAfterForeground") : SCRIPT.index("let mobileAccessUrl")]
    assert "foregroundRefreshInFlight" in section
    assert "Promise.allSettled" in section
    for operation in (
        "loadRecognition()",
        "loadCameraStatus({forceStream:false})",
        "loadCameraManagerState()",
        "loadSystemHealth()",
    ):
        assert operation in section


def test_visibility_handling_adds_no_new_polling_loop() -> None:
    section = SCRIPT[SCRIPT.index("function initializeVisibilityAwareRefresh") : SCRIPT.index("let mobileAccessUrl")]
    assert 'document.addEventListener("visibilitychange"' in section
    assert "setInterval" not in section
    assert "setTimeout" not in section
    assert "initializeVisibilityAwareRefresh()" in SCRIPT
