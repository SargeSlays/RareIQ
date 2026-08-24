from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import cv2
import numpy as np


@dataclass(frozen=True)
class VisionQuality:
    sharpness: float
    brightness: float
    contrast: float
    glare: float
    score: float
    status: str
    recommendation: str | None


class VisionOptimizerService:
    def optimize(self, image: np.ndarray) -> dict[str, Any]:
        if image is None or image.size == 0:
            raise ValueError("Vision optimizer received an empty image.")

        corrected = self._perspective_correct(image)
        normalized = self._normalize(corrected)
        quality = self.quality(normalized)

        return {
            "image": normalized,
            "quality": asdict(quality),
            "width": int(normalized.shape[1]),
            "height": int(normalized.shape[0]),
        }

    def quality(self, image: np.ndarray) -> VisionQuality:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        sharpness = min(
            1.0,
            float(cv2.Laplacian(gray, cv2.CV_64F).var()) / 650.0,
        )
        mean = float(gray.mean())
        brightness = max(0.0, 1.0 - abs(mean - 132.0) / 132.0)
        contrast = min(1.0, float(gray.std()) / 72.0)

        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        glare_mask = cv2.inRange(
            hsv,
            np.array([0, 0, 235], dtype=np.uint8),
            np.array([180, 48, 255], dtype=np.uint8),
        )
        glare_ratio = float(np.count_nonzero(glare_mask)) / float(glare_mask.size)
        glare = max(0.0, 1.0 - min(1.0, glare_ratio / 0.18))

        score = (
            sharpness * 0.35
            + brightness * 0.20
            + contrast * 0.20
            + glare * 0.25
        )

        recommendation = None
        if sharpness < 0.42:
            recommendation = "Hold the card still or improve focus."
        elif brightness < 0.48:
            recommendation = "Increase or rebalance lighting."
        elif glare < 0.45:
            recommendation = "Tilt the card slightly to reduce glare."

        status = (
            "excellent"
            if score >= 0.82
            else "good"
            if score >= 0.66
            else "usable"
            if score >= 0.48
            else "poor"
        )

        return VisionQuality(
            sharpness=round(sharpness, 4),
            brightness=round(brightness, 4),
            contrast=round(contrast, 4),
            glare=round(glare, 4),
            score=round(score, 4),
            status=status,
            recommendation=recommendation,
        )

    def _perspective_correct(self, image: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 55, 150)
        contours, _ = cv2.findContours(
            edges,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )

        image_area = image.shape[0] * image.shape[1]
        for contour in sorted(
            contours,
            key=cv2.contourArea,
            reverse=True,
        )[:12]:
            if cv2.contourArea(contour) < image_area * 0.18:
                continue

            perimeter = cv2.arcLength(contour, True)
            polygon = cv2.approxPolyDP(contour, 0.022 * perimeter, True)
            if len(polygon) != 4:
                continue

            points = polygon.reshape(4, 2).astype(np.float32)
            ordered = self._order_points(points)
            width = int(max(
                np.linalg.norm(ordered[1] - ordered[0]),
                np.linalg.norm(ordered[2] - ordered[3]),
            ))
            height = int(max(
                np.linalg.norm(ordered[3] - ordered[0]),
                np.linalg.norm(ordered[2] - ordered[1]),
            ))
            if width < 120 or height < 160:
                continue

            destination = np.array(
                [
                    [0, 0],
                    [width - 1, 0],
                    [width - 1, height - 1],
                    [0, height - 1],
                ],
                dtype=np.float32,
            )
            transform = cv2.getPerspectiveTransform(ordered, destination)
            return cv2.warpPerspective(image, transform, (width, height))

        return image.copy()

    @staticmethod
    def _order_points(points: np.ndarray) -> np.ndarray:
        ordered = np.zeros((4, 2), dtype=np.float32)
        sums = points.sum(axis=1)
        differences = np.diff(points, axis=1).reshape(-1)
        ordered[0] = points[np.argmin(sums)]
        ordered[2] = points[np.argmax(sums)]
        ordered[1] = points[np.argmin(differences)]
        ordered[3] = points[np.argmax(differences)]
        return ordered

    @staticmethod
    def _normalize(image: np.ndarray) -> np.ndarray:
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = cv2.merge((
            clahe.apply(l_channel),
            a_channel,
            b_channel,
        ))
        normalized = cv2.cvtColor(enhanced, cv2.COLOR_LAB2BGR)
        blurred = cv2.GaussianBlur(normalized, (0, 0), 1.1)
        return cv2.addWeighted(normalized, 1.35, blurred, -0.35, 0)
