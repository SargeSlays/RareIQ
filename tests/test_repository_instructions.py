from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTRUCTIONS = ROOT / "AGENTS.md"


def test_root_repository_instructions_define_the_product_and_authority_baseline():
    text = INSTRUCTIONS.read_text(encoding="utf-8")

    assert "technical project manager" in text
    assert "Studio core is the primary product" in text
    assert "Card Studio is a secondary optional premium add-on" in text
    assert "OBS is the current external encoder" in text
    assert "Never initiate a real stream" in text
    assert "Never force-push" in text


def test_repository_instructions_bind_quality_memory_and_backup_controls():
    text = INSTRUCTIONS.read_text(encoding="utf-8")

    for path in (
        "docs/PRODUCT_DIRECTION.md",
        "docs/ROADMAP.md",
        "docs/ENGINEERING_MEMORY.md",
        "docs/RELEASE_CHECKLIST.md",
    ):
        assert path in text
        assert (ROOT / path).is_file()

    assert "tools\\release_check.py --require-node" in text
    assert "1920x1080" in text
    assert "3840x2160" in text
    assert "complete-history Git bundle" in text
    assert "local and remote commit IDs match" in text
