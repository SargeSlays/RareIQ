from pathlib import Path

STUDIO=Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS=Path("rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")

def test_recent_scans_explicitly_hides_current_and_multicard_content():
    assert 'setAttribute("data-primary-view",ui4InspectorView)' in STUDIO
    assert '.inspector[data-primary-view="recent"] .ui4-current-card-view' in CSS
    assert '[aria-hidden="true"]{display:none!important' in CSS

def test_recent_scan_detail_has_compact_two_column_layout():
    assert 'className="ui4-history-detail-heading"' in STUDIO
    assert "grid-template-columns:110px minmax(0,1fr)" in CSS
    assert '.ui4-recent-scans-view:has(.ui4-history-detail)' in CSS
