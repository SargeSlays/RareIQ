from pathlib import Path

SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
SERVICE = Path("rareiq/services/overlay_state_service.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = Path("rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
OVERLAY = Path("rareiq/web/static/overlay_graphics.html").read_text(encoding="utf-8")
OVERLAY_JS = Path("rareiq/web/static/overlay_graphics.js").read_text(encoding="utf-8")


def test_graphics_state_persists_and_has_preview_take_hide_api():
    assert '"broadcast_graphic"' in SERVICE
    assert '@app.get("/api/production/graphics")' in SERVER
    assert '@app.post("/api/production/graphics/preview")' in SERVER
    assert '@app.post("/api/production/graphics/take")' in SERVER
    assert '@app.post("/api/production/graphics/hide")' in SERVER
    assert '@app.get("/overlay/graphics")' in SERVER


def test_broadcast_workspace_controls_lower_thirds_and_card_graphics():
    assert 'id="productionGraphicsForm"' in CONTROL
    assert 'id="productionGraphicKind"' in CONTROL
    assert 'id="productionGraphicTitle"' in CONTROL
    assert 'id="productionGraphicCardFill"' in CONTROL
    assert 'id="productionGraphicPreview"' in CONTROL
    assert 'id="productionGraphicHide"' in CONTROL
    assert 'function productionGraphicPayload()' in STUDIO
    assert 'function sendProductionGraphic' in STUDIO
    assert 'function fillProductionGraphicFromCard' in STUDIO
    fill = STUDIO.split('function fillProductionGraphicFromCard', 1)[1].split(
        'let spotifyState', 1
    )[0]
    assert 'isAuthoritativelyVerified' in fill
    assert 'window.__rareiqCardContext' in fill
    assert 'latestState' not in fill
    assert 'primary_candidate' not in fill
    assert 'Verified Card Required' in fill
    assert '.production-graphics-layout' in CSS
    assert 'previewLayout.dataset.graphicState=action' in STUDIO
    assert '.production-graphics-layout::after' in CSS
    assert '[data-graphic-state="preview"]::after' in CSS
    assert '@media(max-width:1000px){.production-graphics-layout::after{display:none}}' in CSS


def test_transparent_browser_source_animates_and_auto_hides():
    assert 'background:transparent' in OVERLAY
    assert '/static/overlay_runtime.js' in OVERLAY
    assert '/static/overlay_graphics.js' in OVERLAY
    assert '/api/production/graphics' in OVERLAY_JS
    assert 'classList.toggle("visible"' in OVERLAY_JS
    assert 'duration_ms' in OVERLAY_JS
    assert 'shown_at' in OVERLAY_JS
    assert 'RareIQOverlay.start' in OVERLAY_JS
    assert 'data-style' in OVERLAY
    assert 'data-kind' in OVERLAY


def test_card_graphics_are_bound_to_verified_backend_identity():
    assert 'def _bind_card_graphic_identity(' in SERVER
    assert 'def _sanitize_card_graphic(' in SERVER
    assert 'identity_state_id' in SERVER
    assert 'verified_current_card_required' in SERVER
    status = SERVER.split(
        'async def production_graphics_status', 1
    )[1].split('@app.post("/api/production/graphics/preview")', 1)[0]
    assert '_sanitize_card_graphic' in status
