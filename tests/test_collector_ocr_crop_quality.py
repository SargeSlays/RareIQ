from __future__ import annotations

import cv2
import numpy as np

from rareiq.services.candidate_ranker_service import CandidateRankerService
from rareiq.services.recognition_fusion_service import RecognitionFusionService
from rareiq.services.recognition_service import RecognitionService
from rareiq.services.vision_service import VisionService


class FakeOcrResult:
    def __init__(self, texts: list[str], scores: list[float]) -> None:
        self.txts = texts
        self.scores = scores
        self.boxes = [None] * len(texts)


class SequencedOcr:
    def __init__(self, results: list[FakeOcrResult]) -> None:
        self.results = results
        self.calls = 0

    def __call__(self, _image: np.ndarray, **_kwargs: object) -> FakeOcrResult:
        result = self.results[min(self.calls, len(self.results) - 1)]
        self.calls += 1
        return result


class BoxedOcr:
    def __init__(self) -> None:
        self.calls = 0
        self.last_shape: tuple[int, ...] | None = None
        self.last_kwargs: dict[str, object] = {}

    def __call__(self, image: np.ndarray, **kwargs: object) -> FakeOcrResult:
        self.calls += 1
        self.last_shape = image.shape
        self.last_kwargs = kwargs
        result = FakeOcrResult(["2302/07"], [0.94])
        height = image.shape[0]
        result.boxes = [np.array([[5, height * .45], [80, height * .45], [80, height * .49], [5, height * .49]])]
        return result


def _service() -> RecognitionService:
    return RecognitionService(lambda _event: None)


def test_collector_roi_contains_normalized_footer_text_area() -> None:
    card = np.zeros((1400, 1000, 3), dtype=np.uint8)
    card[1260:1360, 80:300] = (120, 200, 255)

    region = RecognitionService._collector_region(card)

    assert region.shape == (245, 785, 3)
    assert int(region[:, :, 2].max()) == 255


def test_printed_code_crop_is_tight_lower_left_strip() -> None:
    card = np.zeros((1400, 1000, 3), dtype=np.uint8)
    card[1148:1393, 15:550] = (15, 25, 240)

    region = RecognitionService._printed_code_region(card)

    assert region.shape == (147, 405, 3)
    assert int(region[:, :, 2].max()) == 240


def test_collector_retry_canvas_covers_two_offset_footer_bands() -> None:
    card = np.zeros((1400, 1000, 3), dtype=np.uint8)
    card[1040:1120, :920] = (10, 20, 30)
    card[1260:1370, :920] = (80, 90, 100)

    canvas = RecognitionService._collector_retry_canvas(card)

    assert canvas.shape[1] == 920
    assert canvas.shape[0] > 500
    assert np.any(np.all(canvas == (10, 20, 30), axis=2))
    assert np.any(np.all(canvas == (80, 90, 100), axis=2))


def test_native_detail_crop_is_preserved_without_changing_canonical_crop() -> None:
    frame = np.full((2160, 3840, 3), 28, dtype=np.uint8)
    cv2.rectangle(frame, (1250, 180), (2500, 1930), (232, 232, 232), -1)
    cv2.rectangle(frame, (1250, 180), (2500, 1930), (8, 8, 8), 18)

    result = VisionService.detect(frame)

    assert result.crop is not None
    assert result.crop.shape == (1400, 1000, 3)
    assert result.ocr_crop is not None
    assert result.ocr_crop.shape[1] >= 1200
    assert result.ocr_crop.shape[0] >= 1680


def test_preprocessing_stops_on_truthful_full_width_slash_code() -> None:
    service = _service()
    engine = SequencedOcr([
        FakeOcrResult([], []),
        FakeOcrResult(["2302\uff0f07"], [0.93]),
    ])
    service._engine = engine  # type: ignore[assignment]
    card = np.full((1400, 1000, 3), 160, dtype=np.uint8)

    items, diagnostics = service._run_collector_ocr(card, "collector_frame_0")

    assert service._best_printed_code(items) == "2302/07"
    assert engine.calls == 2
    assert [item["variant"] for item in diagnostics] == [
        "bottom30_original",
        "bottom30_grayscale",
    ]


def test_expected_reference_code_keeps_preprocessing_past_confident_neighbor() -> None:
    service = _service()
    engine = SequencedOcr([
        FakeOcrResult(["2303/07"], [0.96]),
        FakeOcrResult(["2301/07"], [0.88]),
    ])
    service._engine = engine  # type: ignore[assignment]
    card = np.full((1400, 1000, 3), 160, dtype=np.uint8)

    items, diagnostics = service._run_collector_ocr(
        card,
        "collector_frame_0",
        expected_codes={"2301/07"},
    )

    assert service._printed_code_candidates(items) == {"2301/07", "2303/07"}
    assert engine.calls == 2
    assert len(diagnostics) == 2


def test_batched_collector_ocr_reads_three_treatments_with_one_inference() -> None:
    service = _service()
    engine = BoxedOcr()
    service._engine = engine  # type: ignore[assignment]
    card = np.full((1400, 1000, 3), 160, dtype=np.uint8)

    items, diagnostics = service._run_collector_ocr_batched(card, "collector_frame_0")

    assert engine.calls == 1
    assert service._best_printed_code(items) == "2302/07"
    assert len(diagnostics) == 3
    assert all(item["batched"] is True for item in diagnostics)


def test_single_footer_fast_pass_uses_recognition_only_line() -> None:
    service = _service()
    engine = BoxedOcr()
    service._engine = engine  # type: ignore[assignment]
    card = np.full((1400, 1000, 3), 160, dtype=np.uint8)

    service._run_collector_ocr_batched(
        card,
        "collector_frame_0",
        max_variants=1,
    )

    assert engine.last_shape is not None
    assert engine.last_kwargs == {
        "use_det": False,
        "use_cls": False,
        "use_rec": True,
    }
    runtime = service.status()["ocr_runtime"]
    assert runtime["footer_recognition_only_hits"] == 1
    assert runtime["footer_detector_fallbacks"] == 0
    assert runtime["footer_recognition_only_hit_rate"] == 1.0
    assert runtime["last_footer_mode"] == "recognition_only"


def test_single_footer_fast_pass_falls_back_to_720_pixel_detector() -> None:
    service = _service()
    engine = BoxedOcr()
    service._engine = engine  # type: ignore[assignment]
    service._infer_ocr_recognition_only = (  # type: ignore[method-assign]
        lambda _image: FakeOcrResult(["not an identifier"], [0.99])
    )
    card = np.full((1400, 1000, 3), 160, dtype=np.uint8)

    service._run_collector_ocr_batched(
        card,
        "collector_frame_0",
        max_variants=1,
    )

    assert engine.last_shape is not None
    assert engine.last_shape[1] <= 720
    assert engine.last_kwargs == {"use_det": True, "use_cls": True, "use_rec": True}
    runtime = service.status()["ocr_runtime"]
    assert runtime["footer_recognition_only_hits"] == 0
    assert runtime["footer_detector_fallbacks"] == 1
    assert runtime["footer_recognition_only_hit_rate"] == 0.0
    assert runtime["last_footer_mode"] == "detector_fallback"


def test_general_ocr_restores_detector_after_stateful_fast_line_pass() -> None:
    service = _service()
    modes = []

    class StatefulOcr:
        # RapidOCR keeps non-None call options on the reused engine instance.
        flags = {"use_det": True, "use_cls": True, "use_rec": True}

        def __call__(self, _image, **kwargs):
            self.flags.update(kwargs)
            modes.append(dict(self.flags))
            return FakeOcrResult(["029/084"] if self.flags["use_det"] else [], [0.94])

    service._engine = StatefulOcr()
    card = np.zeros((1400, 1000, 3), dtype=np.uint8)
    for _ in range(2):
        items, _diagnostics = service._run_collector_ocr_batched(card, "collector_frame_0", max_variants=1)
        assert service._best_collector_number(items) == "029/084"
        service._run_ocr(card[:180], "top")
    assert modes == [
        {"use_det": False, "use_cls": False, "use_rec": True},
        {"use_det": True, "use_cls": True, "use_rec": True},
        {"use_det": True, "use_cls": True, "use_rec": True},
    ] * 2


def test_low_latency_batched_collector_ocr_uses_two_complementary_treatments() -> None:
    service = _service()
    engine = BoxedOcr()
    service._engine = engine  # type: ignore[assignment]
    card = np.full((1400, 1000, 3), 160, dtype=np.uint8)

    _items, diagnostics = service._run_collector_ocr_batched(
        card,
        "collector_frame_0",
        max_variants=2,
    )

    assert engine.calls == 1
    assert [item["variant"] for item in diagnostics] == [
        "printed_code_2x",
        "bottom30_original",
    ]


def test_standard_collector_and_printed_code_are_not_conflated() -> None:
    items = [
        {"text": "239\uff0f204", "score": 0.9, "source": "collector_frame_0"},
        {"text": "2302/07", "score": 0.95, "source": "collector_frame_0"},
    ]

    assert RecognitionService._best_collector_number(items) == "239/204"
    assert RecognitionService._best_printed_code(items) == "2302/07"
    assert RecognitionService._valid_collector_number("239/204")
    assert not RecognitionService._valid_collector_number("2302/07")


def test_identifier_normalization_recovers_common_tiny_footer_ocr_errors() -> None:
    items = [
        {"text": "I57 ／ 2O4", "score": 0.82, "source": "collector_frame_0"},
        {"text": "23O2∕O7", "score": 0.79, "source": "collector_frame_0"},
    ]

    assert RecognitionService._best_collector_number(items) == "157/204"
    assert RecognitionService._best_printed_code(items) == "2302/07"


def test_collector_number_is_recovered_when_ocr_joins_it_to_set_mark() -> None:
    items = [{
        "text": "PBLIM 001/084",
        "score": 0.96,
        "source": "collector_frame_0",
    }]

    assert RecognitionService._best_collector_number(items) == "001/084"


def test_embedded_collector_recovery_still_requires_numeric_slash_form() -> None:
    items = [{
        "text": "PBLIM OOI/O84",
        "score": 0.96,
        "source": "collector_frame_0",
    }]

    assert RecognitionService._best_collector_number(items) is None


def test_split_ocr_boxes_are_rejoined_only_within_the_same_variant() -> None:
    items = [
        {"text": "157", "score": 0.88, "source": "collector_frame_0", "variant": "otsu"},
        {"text": "/", "score": 0.91, "source": "collector_frame_0", "variant": "otsu"},
        {"text": "198", "score": 0.86, "source": "collector_frame_0", "variant": "otsu"},
    ]

    assert RecognitionService._best_collector_number(items) == "157/198"

    items[2]["variant"] = "clahe_sharp_2x"
    assert RecognitionService._best_collector_number(items) is None


def test_identifier_normalization_does_not_invent_a_missing_slash() -> None:
    items = [{
        "text": "Crocalor I57 2O4",
        "score": 0.96,
        "source": "collector_frame_0",
    }]

    assert RecognitionService._best_collector_number(items) is None
    assert RecognitionService._best_printed_code(items) is None


def test_collector_frame_selection_prefers_detail_without_glare_or_blur() -> None:
    blurred = np.full((1400, 1000, 3), 150, dtype=np.uint8)
    glared = np.full((1400, 1000, 3), 255, dtype=np.uint8)
    sharp = np.full((1400, 1000, 3), 150, dtype=np.uint8)
    for x in range(20, 790, 16):
        cv2.line(sharp, (x, 1160), (x, 1380), (20, 20, 20), 2)

    selected = RecognitionService._select_collector_frames(
        [blurred, glared, sharp],
        limit=3,
    )

    assert selected[0][0] is sharp
    sharp_metrics = RecognitionService._collector_frame_metrics(sharp)
    glare_metrics = RecognitionService._collector_frame_metrics(glared)
    assert sharp_metrics["glare_ratio"] < glare_metrics["glare_ratio"]


def test_collector_frame_selection_preserves_primary_and_remains_bounded() -> None:
    primary = np.full((1400, 1000, 3), 110, dtype=np.uint8)
    alternates = []
    for index in range(6):
        frame = np.full((1400, 1000, 3), 125 + index * 10, dtype=np.uint8)
        cv2.line(
            frame,
            (30 + index * 7, 1160),
            (760 - index * 5, 1370),
            (10, 10, 10),
            2 + index,
        )
        alternates.append(frame)

    selected = RecognitionService._select_collector_frames(
        [primary, *alternates],
        limit=4,
        preserve_first=True,
    )

    assert len(selected) == 4
    assert selected[0][0] is primary
    assert len({id(frame) for frame, _metrics in selected}) == 4


def test_collector_frame_selection_deduplicates_equivalent_samples() -> None:
    frame = np.full((1400, 1000, 3), 150, dtype=np.uint8)
    cv2.putText(
        frame,
        "2302/07",
        (40, 1340),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        (20, 20, 20),
        2,
    )

    selected = RecognitionService._select_collector_frames(
        [frame, frame.copy(), frame.copy()],
        limit=4,
    )

    assert len(selected) == 1


def test_collector_preprocessing_is_bounded_when_no_identifier_exists() -> None:
    service = _service()
    engine = SequencedOcr([FakeOcrResult([], [])])
    service._engine = engine  # type: ignore[assignment]
    card = np.full((1400, 1000, 3), 160, dtype=np.uint8)

    items, diagnostics = service._run_collector_ocr(
        card,
        "collector_frame_0",
    )

    assert items == []
    assert engine.calls == len(RecognitionService._collector_variants(card))
    assert engine.calls == 7
    assert len(diagnostics) == 7


def test_missing_ocr_does_not_fabricate_identifier() -> None:
    items = [
        {"text": "unreadable footer", "score": 0.99, "source": "collector_frame_0"}
    ]

    assert RecognitionService._best_collector_number(items) is None
    assert RecognitionService._best_printed_code(items) is None


def test_reference_printed_code_is_identity_evidence_only_when_verified() -> None:
    service = _service()
    service._reference_printed_code = lambda _path: "2302/07"  # type: ignore[method-assign]
    candidates = service._annotate_reference_identifiers(
        [
            {
                "id": "verified",
                "image_path": "verified.png",
                "verification_strong": True,
            },
            {
                "id": "hash-only",
                "image_path": "hash-only.png",
                "verification_strong": False,
            },
        ],
        "2302/07",
    )

    assert candidates[0]["printed_code_match"] is True
    assert "printed_code_match" not in candidates[1]


def test_neighboring_printed_code_is_not_treated_as_an_exact_match() -> None:
    service = _service()
    service._reference_printed_code = lambda _path: "2302/07"  # type: ignore[method-assign]

    candidates = service._annotate_reference_identifiers(
        [{
            "id": "neighboring-variant",
            "image_path": "neighboring.png",
            "verification_strong": True,
        }],
        {"2301/07"},
    )

    assert candidates[0]["printed_code"] == "2302/07"
    assert candidates[0]["printed_code_match"] is False
    assert candidates[0]["printed_code_match_mode"] is None
    assert candidates[0]["printed_code_matching_frames"] == 0
    assert candidates[0]["printed_code_distance"] is None


def test_ambiguous_one_digit_catalog_neighbors_cannot_correct_identity() -> None:
    service = _service()
    service.artwork_index._records = [
        {
            "id": "variant-a",
            "set_id": "TEST",
            "collector_number": "1",
            "printed_code": "2301/07",
        },
        {
            "id": "variant-b",
            "set_id": "TEST",
            "collector_number": "2",
            "printed_code": "2302/07",
        },
    ]
    visual = [{
        "id": "variant-a",
        "set_id": "TEST",
        "collector_number": "1",
        "printed_code": "2301/07",
        "verification_strong": True,
        "artwork_verification_strong": True,
    }]

    corrected, evidence = service._catalog_visual_printed_code_correction(
        "2303/07",
        visual,
    )

    assert corrected == "2303/07"
    assert evidence is None


def test_printed_code_is_compared_across_verified_sibling_versions() -> None:
    service = _service()
    reference_codes = {
        "crocalor-156.png": "2301/07",
        "crocalor-157.png": "2302/07",
        "crocalor-158.png": "2303/07",
    }
    service._reference_printed_code = (  # type: ignore[method-assign]
        lambda path: reference_codes[str(path)]
    )
    candidates = [
        {
            "id": f"crocalor-{number}",
            "image_path": f"crocalor-{number}.png",
            "verification_strong": True,
        }
        for number in (156, 157, 158)
    ]

    annotated = service._annotate_reference_identifiers(
        candidates,
        {"2303/07"},
        limit=8,
    )

    assert [item.get("printed_code_match") for item in annotated] == [
        False,
        False,
        True,
    ]
    assert annotated[2]["printed_code"] == "2303/07"


def test_printed_code_match_boosts_verified_named_candidate() -> None:
    ranker = CandidateRankerService(RecognitionFusionService())
    ranked = ranker.rank(
        visual_candidates=[{
            "id": "crocalor-157",
            "name": "Crocalor",
            "printed_name": "\u7099\u70eb\u9cc4",
            "collector_number": "157",
            "printed_code": "2302/07",
            "printed_code_match": True,
            "language": "zh-cn",
            "visual_score": 0.77,
            "score": 0.77,
            "source": "pokipair",
            "verification_strong": True,
        }],
        ocr_payload={
            "text": "\u7099\u70eb\u9cc4 HP 110 2302/07",
            "collector_number": None,
            "printed_code": "2302/07",
            "language": "Chinese",
        },
        quality={"score": 0.41},
    )

    assert ranked[0]["signals"]["collector_number"] == 1.0
    assert ranked[0]["signals"]["ocr_name"] == 1.0
    assert ranked[0]["fused_score"] >= 0.82
