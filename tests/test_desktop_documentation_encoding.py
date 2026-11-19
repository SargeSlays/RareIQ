"""Guard operator instructions against accidental Windows text transcoding."""
from pathlib import Path


def test_desktop_setup_documentation_preserves_utf8_punctuation():
    content = (Path(__file__).resolve().parents[1] / 'docs/DESKTOP_APP.md').read_text(encoding='utf-8')
    assert '\ufffd' not in content
    assert '\u00e2\u20ac' not in content
    assert '\u00c3\u00a2\u00e2' not in content
