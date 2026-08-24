from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "rareiq/web/static/studiox.js").read_text(encoding="utf-8")
CSS = (ROOT / "rareiq/web/static/studiox_update15.css").read_text(encoding="utf-8")
HTML = (ROOT / "rareiq/web/static/control.html").read_text(encoding="utf-8")


def test_provider_comparison_is_collapsed_and_complete():
    assert 'id="marketProviderComparison"' in HTML
    assert 'id="marketProviderComparisonRows"' in HTML
    assert 'id="marketProviderComparisonSummary"' in HTML
    render = JS.split("function renderMarketProviderComparison", 1)[1].split("function renderPriceHistory", 1)[0]
    assert "pricing.quotes" in render
    assert "quote.source" in render
    assert "quote.variant" in render
    assert "quote.unit||quote.currency" in render
    assert "quote.updated_at" in render
    assert 'selected?"SELECTED"' in render
    assert '"OTHER CURRENCY"' in render


def test_selected_and_comparable_quotes_have_distinct_states():
    assert 'data-selected="${selected?"true":"false"}"' in JS
    assert 'data-comparable="${currency===selectedCurrency?"true":"false"}"' in JS
    assert '#marketProviderComparisonRows article[data-selected="true"]' in CSS
    assert '#marketProviderComparisonRows article[data-comparable="false"]' in CSS
    assert "renderMarketProviderComparison(pricing)" in JS
    assert "6.8.8-provisional-identity" in HTML
