from pathlib import Path


SERVER = Path("rareiq/web/server.py").read_text(encoding="utf-8")
CONTROL = Path("rareiq/web/static/control.html").read_text(encoding="utf-8")
STUDIO = Path("rareiq/web/static/studiox.js").read_text(encoding="utf-8")


def test_collection_api_exposes_coverage_aware_valuation():
    assert "orchestrator.collection.dashboard(references)" in SERVER
    service = Path("rareiq/services/collection_service.py").read_text(encoding="utf-8")
    assert "valuation = self.valuation()" in service
    assert '"valuation": valuation' in service


def test_collection_ui_labels_verified_value_and_unpriced_coverage():
    assert "Verified Market Value" in CONTROL
    assert 'id="collectionPricingCoverage"' in CONTROL
    assert 'id="collectionPricingCounts"' in CONTROL
    assert 'id="collectionBiggestHits"' in CONTROL
    assert "function renderCollectionValuation(valuation)" in STUDIO
    assert "pricing_coverage_percent" in STUDIO
    assert "unpriced_copies" in STUDIO
