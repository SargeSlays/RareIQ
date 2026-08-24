import numpy as np

from rareiq.services.vision_service import VisionService


def test_printed_card_content_outranks_smooth_background_rectangle():
    smooth = np.full((300, 220, 3), 96, dtype=np.uint8)
    printed = smooth.copy()
    for y in range(12, 290, 18):
        printed[y:y + 3, 12:208] = (220, 220, 220)
    for x in range(15, 210, 24):
        printed[15:285, x:x + 2] = (20, 20, 20)
    points = np.asarray(
        [[0, 0], [219, 0], [219, 299], [0, 299]],
        dtype=np.float32,
    )

    assert VisionService._candidate_content_score(
        printed, points
    ) > VisionService._candidate_content_score(smooth, points)
