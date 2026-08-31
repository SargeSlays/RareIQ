from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1] / "rareiq/web/static/studiox.js"
).read_text(encoding="utf-8")


def test_mutation_observers_only_use_guarded_node_targets():
    assert 'target instanceof Node' in SCRIPT
    assert 'try{observer.observe(target,options);return true}catch(error)' in SCRIPT
    # ResizeObserver has its own checked element targets; do not mistake those
    # calls for unguarded MutationObserver registrations.
    mutation_script = SCRIPT
    for target in ("stage", "image"):
        mutation_script = mutation_script.replace(f"binding.observer?.observe({target});", "")
    assert mutation_script.count(".observe(") == 1
    assert "observeStudioXTarget(decisionObserver" in SCRIPT
    assert "observeStudioXTarget(inspectorNavigationObserver" in SCRIPT


def test_camera_resize_observer_checks_both_elements_before_registration():
    renderer = SCRIPT.split("function renderMultiCardCameraOverlay(", 1)[1].split(
        "let singleCardPickerActive=", 1
    )[0]
    guard = renderer.index("if(!overlay||!stage||!image) return;")
    assert 'typeof ResizeObserver==="function"' in renderer
    assert "new ResizeObserver(binding.schedule)" in renderer
    for target in ("stage", "image"):
        assert guard < renderer.index(f"binding.observer?.observe({target});")
    assert renderer.count(".observe(") == 2
