from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "app.py").read_text(encoding="utf-8")


def test_card_workers_own_parallelism_instead_of_nested_opencv_pools():
    assert "cv2.setNumThreads(1)" in APP
    assert "cv2.setUseOptimized(True)" in APP
