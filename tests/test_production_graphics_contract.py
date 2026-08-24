from pathlib import Path

SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
SERVICE = Path("rareiq/services/overlay_state_service.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = Path("rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
OVERLAY = Path("rareiq/web/static/overlay_graphics.html").read_text(encoding="utf-8")


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
    assert '.production-graphics-layout' in CSS
    assert 'previewLayout.dataset.graphicState=action' in STUDIO
    assert '.production-graphics-layout::after' in CSS
    assert '[data-graphic-state="preview"]::after' in CSS
    assert '@media(max-width:1000px){.production-graphics-layout::after{display:none}}' in CSS


def test_transparent_browser_source_animates_and_auto_hides():
    assert 'background:transparent' in OVERLAY
    assert '/api/production/graphics' in OVERLAY
    assert 'classList.toggle("visible"' in OVERLAY
    assert 'duration_ms' in OVERLAY
    assert 'data-style' in OVERLAY
    assert 'data-kind' in OVERLAY
