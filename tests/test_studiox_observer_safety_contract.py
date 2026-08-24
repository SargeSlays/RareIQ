from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1] / "rareiq/web/static/studiox.js"
).read_text(encoding="utf-8")


def test_mutation_observers_only_use_guarded_node_targets():
    assert 'target instanceof Node' in SCRIPT
    assert 'try{observer.observe(target,options);return true}catch(error)' in SCRIPT
    assert SCRIPT.count(".observe(") == 1
    assert "observeStudioXTarget(decisionObserver" in SCRIPT
    assert "observeStudioXTarget(inspectorNavigationObserver" in SCRIPT
