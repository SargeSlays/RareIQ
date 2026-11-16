from pathlib import Path


def test_studio_output_composes_program_graphics_and_routed_audio() -> None:
    source = Path("rareiq/web/static/studio_output.html").read_text(encoding="utf-8")
    assert 'src="/program?embedded=1"' in source
    assert 'src="/overlay/graphics?embedded=1"' in source
    assert 'src="/output/soundboard"' in source
    assert 'src="/overlay/audience?embedded=1"' in source
    assert source.count("<iframe") == 4
    assert 'allow="autoplay"' in source
