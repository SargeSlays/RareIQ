from pathlib import Path

from rareiq.services.recognition_service import RecognitionService


def test_ocr_warmup_runs_once_and_is_visible_in_status(tmp_path: Path):
    service = RecognitionService(lambda event: None, database_path=tmp_path / "missing.json")
    calls = []
    service._engine = lambda image: calls.append(image.shape) or []

    first = service.warm_ocr()
    second = service.warm_ocr()

    assert first["warmed"] is True
    assert first["warmup_ms"] is not None
    assert second["warmed"] is True
    assert len(calls) == 1
    assert service.status()["ocr_runtime"]["warmed"] is True


def test_all_recognition_ocr_calls_use_the_serialized_inference_gate():
    source = Path("rareiq/services/recognition_service.py").read_text(encoding="utf-8")
    assert "def _infer_ocr" in source
    assert "with self._ocr_inference_lock" in source
    assert "self._engine_instance()(prepared)" not in source
    assert "self._engine_instance()(canvas)" not in source
