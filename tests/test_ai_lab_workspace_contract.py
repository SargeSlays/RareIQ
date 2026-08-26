from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROL = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
SCRIPT = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
LEGACY_STYLES = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
STYLES = (ROOT / "rareiq/web/static/studiox_command_deck.css").read_text(encoding="utf-8")


def test_ai_lab_has_six_real_accessible_views():
    assert 'id="aiLabTabs" role="tablist" aria-label="AI Lab views"' in CONTROL
    for view, panel in (
        ("recognition", "aiLabRecognition"),
        ("ocr", "aiLabOcr"),
        ("embeddings", "aiLabEmbeddings"),
        ("learning", "aiLabLearning"),
        ("benchmarks", "aiLabBenchmarks"),
        ("advisor", "aiLabAdvisor"),
    ):
        assert f'data-ai-lab-view="{view}"' in CONTROL
        assert f'aria-controls="{panel}"' in CONTROL
        assert f'id="{panel}" role="tabpanel"' in CONTROL


def test_ai_lab_uses_only_existing_read_only_diagnostic_endpoints():
    assert 'api("/api/recognition-state")' in SCRIPT
    assert 'api("/api/intelligence/status")' in SCRIPT
    assert 'api("/api/benchmarks/latest")' in SCRIPT
    assert 'api("/api/ai/advisor/status")' in SCRIPT
    ai_lab = SCRIPT[SCRIPT.index("async function loadAiLab"):SCRIPT.index("function initializeAiLab")]
    assert 'method:"POST"' not in ai_lab
    assert "setInterval" not in ai_lab


def test_ai_lab_reports_recognition_ocr_index_learning_and_benchmark_state():
    for function in (
        "renderAiLabRecognition",
        "renderAiLabIntelligence",
        "renderAiLabBenchmark",
        "loadAiLab",
    ):
        assert f"function {function}" in SCRIPT
    for element_id in (
        "aiLabRecognitionPhase",
        "aiLabOcrCode",
        "aiLabIndexRecords",
        "aiLabLearningQueued",
        "aiLabBenchmarkP95",
        "sargeAdvisorProvider",
    ):
        assert f'id="{element_id}"' in CONTROL


def test_visual_index_build_duration_is_not_mislabeled_as_query_latency():
    assert '<span>Last Build</span><strong id="aiLabIndexLatency">' in CONTROL
    assert "function aiLabDuration" in SCRIPT
    assert 'setCardText("aiLabIndexLatency",aiLabDuration(index.latency_ms))' in SCRIPT
    assert 'setCardText("aiLabIndexLatency",aiLabMilliseconds(index.latency_ms))' not in SCRIPT


def test_ai_lab_navigation_is_persistent_and_keyboard_accessible():
    assert 'const AI_LAB_VIEW_KEY="rareiq.ai-lab.view.v1"' in SCRIPT
    assert "function setAiLabView" in SCRIPT
    assert "function initializeAiLab" in SCRIPT
    assert "initializeAiLab();" in SCRIPT
    assert "localStorage.setItem(AI_LAB_VIEW_KEY,view)" in SCRIPT
    for key in ("ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Home", "End"):
        assert f'"{key}"' in SCRIPT


def test_ai_lab_is_responsive_and_keeps_focus_visible():
    assert '.workspace[data-workspace="ai"] .ai-lab-metrics {' in STYLES
    assert 'grid-template-columns: repeat(4, minmax(0, 1fr)) !important;' in STYLES
    assert '@media (max-width: 1200px)' in STYLES
    assert 'grid-template-columns: repeat(2, minmax(0, 1fr)) !important;' in STYLES
    assert '@media (max-width: 540px)' in STYLES
    assert 'grid-template-columns: minmax(0, 1fr) !important;' in STYLES
    assert '[role="tabpanel"]:focus-visible' in STYLES


def test_ai_lab_uses_a_compact_numbered_diagnostic_grid():
    assert '.workspace[data-workspace="ai"] .ai-lab-stage-list {' in STYLES
    assert 'grid-template-columns: repeat(3, minmax(0, 1fr)) !important;' in STYLES
    assert 'counter-reset: ai-lab-step !important;' in STYLES
    assert 'counter(ai-lab-step, decimal-leading-zero)' in STYLES
    assert 'grid-template-columns: 24px minmax(0, 1fr) auto !important;' in STYLES
    assert 'min-height: 84px !important;' in STYLES


def test_command_deck_owns_ai_lab_visuals_without_legacy_theme_fragments():
    assert '/* AI Lab */' in STYLES
    assert '.workspace[data-workspace="ai"] .ai-lab-heading {' in STYLES
    assert '.workspace[data-workspace="ai"] .sarge-advisor-card {' in STYLES
    assert 'background: var(--sx-surface-raised) !important;' in STYLES
    assert 'outline: 2px solid var(--sx-accent) !important;' in STYLES
    assert '.workspace[data-workspace="ai"] .ai-lab-panel[hidden]' not in LEGACY_STYLES
    assert '.workspace[data-workspace="ai"] .side-nav [data-ai-lab-view][aria-selected="true"]' not in LEGACY_STYLES


def test_ai_lab_readiness_uses_the_actual_workspace_key():
    assert 'ai:{path:"/api/system/health",label:"AI Lab"' in SCRIPT
    assert 'if(name==="ai") loadAiLab()' in SCRIPT
