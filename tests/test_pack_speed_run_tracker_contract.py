from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
COACH_CSS = (ROOT / "rareiq/web/static/pack_run_coach.css").read_text(encoding="utf-8")


def test_pack_speed_header_exposes_live_run_metrics_and_reset():
    for element_id in ("packSpeedRun", "packRunCards", "packRunAverage", "packRunSubsecond", "packRunOpen", "packRunReset", "packRunDetail", "packRunRows", "packRunCoach", "packRunCoachApply", "packSessionScoreboard", "packSessionElapsed", "packSessionFastest", "packSessionSlowest", "packSessionCompleted"):
        assert f'id="{element_id}"' in HTML


def test_only_successful_pack_speed_adds_record_latency():
    auto_add = JS.split("async function maybeAutoAddVerified", 1)[1].split("async function runRecognitionDecision", 1)[0]
    assert "if(result){const expectedCards=" in auto_add
    assert "recordPackSpeedSuccess({...context,expectedCards,packReveal});" in auto_add
    assert "timings.total_ms" in JS
    assert "value<1000" in JS
    assert "localStorage.setItem(PACK_SPEED_RUN_KEY" in JS
    assert "sessionStorage.getItem(PACK_SPEED_RUN_KEY)" in JS


def test_pack_history_records_identity_latency_and_bottleneck():
    assert "function packRunStage" in JS
    assert "bottleneck:packRunStage(timings)" in JS
    assert 'data-health="${Number(row.total)<1000?"fast":"slow"}"' in JS
    assert "records.slice(-12).reverse()" in JS


def test_pack_history_correlates_each_card_with_cache_performance():
    assert "function packRunCacheSample(context={})" in JS
    assert "reference_cache_timing" in JS
    assert "cacheState:state" in JS
    assert 'class="pack-cache-result"' in JS
    assert 'data-cache="${escapeHtml(row.cacheState||"unknown")}"' in JS
    assert '.pack-run-detail article[data-cache="warm"]' in COACH_CSS


def test_pack_speed_tracker_is_responsive_and_theme_aware():
    assert ".pack-speed-run[data-health=fast]" in CSS
    assert "html[data-theme=light] .pack-speed-run" in CSS
    assert "@media(max-width:1250px)" in CSS
    assert ".pack-session-scoreboard" in COACH_CSS
    assert 'html[data-theme="light"] .pack-session-scoreboard' in COACH_CSS


def test_pack_session_persists_timing_extremes_and_explicit_reset():
    assert "packSpeedRun.startedAt=at" in JS
    assert "Math.min(...values)" in JS
    assert "Math.max(...values)" in JS
    assert 'packSpeedRun={records:[],startedAt:null}' in JS
    assert 'notify("New Pack Started"' in JS


def test_pack_finish_archives_compares_and_exports_session():
    for token in ("PACK_SPEED_HISTORY_KEY", "archivePackSpeedRun", "exportPackSpeedRun", "packRunSummaryData", "packSessionComparison", "packRunFinish", "packRunExport"):
        assert token in JS
    assert 'schema:"rareiq-pack-speed-v1"' in JS
    assert "previousPack:loadPackSpeedHistory()" in JS
    assert ".pack-session-actions" in COACH_CSS


def test_recent_pack_trend_chart_includes_active_run():
    for token in ("ensurePackHistoryChart", "renderPackHistoryChart", "packHistoryTrend", "packHistoryRange", "packHistoryBars"):
        assert token in JS
    assert 'label:"LIVE"' in JS
    assert 'trend=points.length<2?"baseline"' in JS
    assert '.pack-history-chart[data-trend="improving"]' in COACH_CSS
    assert '#packHistoryBars article[data-active="true"]' in COACH_CSS


def test_pack_auto_finish_uses_product_count_and_keeps_manual_control():
    for token in ("PACK_AUTO_FINISH_KEY", "packAutoFinishPrefs", "packAutoFinishEnabled", "packSpeedExpectedCards", "maybeCompletePackSpeedRun"):
        assert token in JS
    assert "result.reveal_sequence?.expected_cards" in JS
    assert "packSpeedRun.records.length<expected" in JS
    assert 'id="packRunFinish"' in JS
    assert 'notify("Pack Auto-finished"' in JS
    assert ".pack-session-actions label" in COACH_CSS


def test_pack_speed_and_pack_profile_controls_have_unique_ids():
    assert 'id="packSpeedExpectedCards"' in JS
    assert 'Number($("packSpeedExpectedCards")?.value)' in JS
    assert 'select instanceof HTMLSelectElement' in JS
    assert 'id="packExpectedCards" type="number"' not in JS


def test_between_pack_rearm_requires_empty_zone_and_fresh_state():
    for token in ("PACK_REARM_KEY", "packRearmGate", "armNextPackGate", "clearNextPackGate", "packRearmState"):
        assert token in JS
    assert 'packRearmGate.active&&!present&&phase==="EMPTY"' in JS
    assert 'if(packRearmGate.active){renderCardRemovalProgress' in JS
    assert 'finishedStateId:String(lastAutoAddStateId||"")' in JS
    assert '.pack-session-actions > b[data-state="waiting"]' in COACH_CSS


def test_pack_archives_pull_intelligence_without_guessing_prices():
    for token in ("rarity_counts", "tier_counts", "strongest_pull", "verified_value_total", "valued_cards", "unvalued_cards", "packPullSummary"):
        assert token in JS
    assert 'reveal.market_value!==null' in JS
    assert 'hasPrice=row=>row.marketValue!==null' in JS
    assert "result.reveal_sequence?.current" in JS
    assert 'data-tier="grail"' in COACH_CSS


def test_pack_recap_sends_verified_pull_summary_to_graphic_output():
    for token in ("packPullSendRecap", "sendPackSpeedRecapOverlay", "productionGraphicTitle", "productionGraphicSubtitle", "productionGraphicPreviewFrame"):
        assert token in JS
    assert 'await sendProductionGraphic("take")' in JS
    assert 'summary.valued_cards?`Verified value $' in JS
    assert 'pull?.reference_image_url||""' in JS
    assert ".pack-pull-summary > header button" in COACH_CSS


def test_pack_recap_supports_persisted_styles_and_safe_preview():
    for token in ("PACK_RECAP_STYLE_KEY", "packRecapStyle", "packRecapStyle\"", "packPullPreviewRecap", "buildPackRecapGraphic"):
        assert token in JS
    for style in ("clean", "hype", "grail", "stats"):
        assert f'<option value="{style}">' in JS
    assert 'sendPackSpeedRecapOverlay("preview")' in JS
    assert 'sendPackSpeedRecapOverlay("take")' in JS
    assert ".pack-pull-summary > header select" in COACH_CSS


def test_auto_recap_is_opt_in_delayed_and_cancellable():
    for token in ("PACK_AUTO_RECAP_KEY", "packAutoRecapPrefs", "schedulePackRecap", "cancelPendingPackRecap", "packAutoRecapEnabled", "packAutoRecapDelay", "packAutoRecapCancel"):
        assert token in JS
    assert "enabled:false,delaySeconds:5" in JS
    assert 'sendPackSpeedRecapOverlay("take")' in JS
    assert 'if(archived)schedulePackRecap()' in JS
    assert '#packAutoRecapStatus[data-state="armed"]' in COACH_CSS


def test_live_recap_has_countdown_emergency_hide_and_auto_return():
    for token in ("packRecapLiveTimer", "packRecapLiveDueAt", "hidePackSpeedRecap", "packRecapHide", "Hide Now"):
        assert token in JS
    assert 'sendProductionGraphic("hide")' in JS
    assert 'Math.max(3000,Number(graphic.duration_ms)||12000)' in JS
    assert '#packAutoRecapStatus[data-state="live"]' in COACH_CSS


def test_pack_coach_only_applies_reversible_set_lock_tuning():
    assert "function packRunRecommendation" in JS
    assert 'action:"lock-set"' in JS
    assert 'recommendation.action!=="lock-set"' in JS
    assert '$("setContextMode").value="manual"' in JS
    assert "await updateRecognitionSetContext()" in JS
    assert "RareIQ will not change camera controls automatically" in JS
    assert '.pack-run-coach[data-stage="candidate"]' in COACH_CSS
    assert '@media (max-width: 520px)' in COACH_CSS
