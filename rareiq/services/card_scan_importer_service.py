from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import cv2
import numpy as np


@dataclass(slots=True)
class CardImageValidation:
    accepted: bool
    score: float
    reasons: list[str]
    width: int
    height: int
    aspect_ratio: float
    file_size_bytes: int
    sharpness: float
    brightness: float
    contrast: float
    checksum: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CardScanImporterService:
    SUPPORTED_EXTENSIONS = {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
    }

    TARGET_CARD_RATIO = 2.5 / 3.5

    MIN_ASPECT_RATIO = 0.58
    MAX_ASPECT_RATIO = 0.86

    MIN_WIDTH = 260
    MIN_HEIGHT = 360
    MIN_FILE_SIZE = 8_000

    MIN_SHARPNESS = 18.0
    MIN_CONTRAST = 12.0

    ACCEPT_SCORE = 0.64

    def __init__(
        self,
        project_root: Path,
        emit: Callable[
            [dict[str, Any]],
            None,
        ] | None = None,
    ) -> None:
        self.project_root = Path(
            project_root
        )

        self.emit = emit or (
            lambda payload: None
        )

        self.root = (
            self.project_root
            / "catalog_master"
            / "card_scan_imports"
        )

        self.incoming_root = (
            self.root
            / "incoming"
        )

        self.accepted_root = (
            self.root
            / "accepted"
        )

        self.rejected_root = (
            self.root
            / "rejected"
        )

        self.normalized_root = (
            self.root
            / "normalized"
        )

        self.report_root = (
            self.root
            / "reports"
        )

        self.catalog_path = (
            self.root
            / "cards.json"
        )

        self.rejection_path = (
            self.root
            / "rejections.json"
        )

        self.manifest_path = (
            self.root
            / "manifest.json"
        )

        for directory in (
            self.root,
            self.incoming_root,
            self.accepted_root,
            self.rejected_root,
            self.normalized_root,
            self.report_root,
        ):
            directory.mkdir(
                parents=True,
                exist_ok=True,
            )

        self._lock = threading.RLock()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None

        self._status: dict[str, Any] = {
            "busy": False,
            "phase": "IDLE",
            "files_discovered": 0,
            "files_processed": 0,
            "files_accepted": 0,
            "files_rejected": 0,
            "files_duplicate": 0,
            "files_failed": 0,
            "current_file": None,
            "started_at": None,
            "updated_at": time.time(),
            "error": None,
            "errors": [],
        }

        self._load_manifest()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(
                self._status
            )

    def _set_status(
        self,
        **values: Any,
    ) -> None:
        with self._lock:
            self._status.update(
                values
            )

            self._status[
                "updated_at"
            ] = time.time()

            payload = dict(
                self._status
            )

        self.emit({
            "type": "card_scan_import_status",
            "payload": payload,
        })

    def _load_manifest(self) -> None:
        if not self.manifest_path.exists():
            return

        try:
            payload = json.loads(
                self.manifest_path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            return

        with self._lock:
            self._status.update({
                "phase": "READY",
                "files_discovered": int(
                    payload.get(
                        "files_discovered"
                    )
                    or 0
                ),
                "files_processed": int(
                    payload.get(
                        "files_processed"
                    )
                    or 0
                ),
                "files_accepted": int(
                    payload.get(
                        "files_accepted"
                    )
                    or 0
                ),
                "files_rejected": int(
                    payload.get(
                        "files_rejected"
                    )
                    or 0
                ),
                "files_duplicate": int(
                    payload.get(
                        "files_duplicate"
                    )
                    or 0
                ),
                "files_failed": int(
                    payload.get(
                        "files_failed"
                    )
                    or 0
                ),
            })

    @staticmethod
    def _read_json(
        path: Path,
        default: Any,
    ) -> Any:
        if not path.exists():
            return default

        try:
            return json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            return default

    @staticmethod
    def _write_json(
        path: Path,
        payload: Any,
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _safe_filename(
        value: Any,
    ) -> str:
        cleaned = "".join(
            character
            if character.isalnum()
            or character in "-_."
            else "_"
            for character in str(
                value or ""
            )
        )

        return (
            cleaned.strip("._")
            or "card"
        )

    @staticmethod
    def _sha256_file(
        path: Path,
    ) -> str | None:
        try:
            digest = hashlib.sha256()

            with path.open(
                "rb"
            ) as handle:
                while True:
                    chunk = handle.read(
                        1024 * 1024
                    )

                    if not chunk:
                        break

                    digest.update(
                        chunk
                    )

            return digest.hexdigest()

        except Exception:
            return None

    @classmethod
    def _is_supported(
        cls,
        path: Path,
    ) -> bool:
        return (
            path.is_file()
            and path.suffix.lower()
            in cls.SUPPORTED_EXTENSIONS
        )

    @staticmethod
    def _load_image(
        path: Path,
    ) -> np.ndarray | None:
        try:
            payload = np.fromfile(
                str(path),
                dtype=np.uint8,
            )

            if payload.size == 0:
                return None

            return cv2.imdecode(
                payload,
                cv2.IMREAD_COLOR,
            )

        except Exception:
            return None

    @staticmethod
    def _write_image(
        path: Path,
        image: np.ndarray,
        quality: int = 95,
    ) -> bool:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        extension = path.suffix.lower()

        if extension in {
            ".jpg",
            ".jpeg",
        }:
            parameters = [
                cv2.IMWRITE_JPEG_QUALITY,
                quality,
            ]

        elif extension == ".webp":
            parameters = [
                cv2.IMWRITE_WEBP_QUALITY,
                quality,
            ]

        else:
            parameters = []

        success, encoded = cv2.imencode(
            extension,
            image,
            parameters,
        )

        if not success:
            return False

        encoded.tofile(
            str(path)
        )

        return True

    @classmethod
    def _ratio_score(
        cls,
        aspect_ratio: float,
    ) -> float:
        difference = abs(
            aspect_ratio
            - cls.TARGET_CARD_RATIO
        )

        return max(
            0.0,
            1.0
            - difference
            / 0.18,
        )

    @staticmethod
    def _quality_metrics(
        image: np.ndarray,
    ) -> tuple[
        float,
        float,
        float,
    ]:
        gray = cv2.cvtColor(
            image,
            cv2.COLOR_BGR2GRAY,
        )

        sharpness = float(
            cv2.Laplacian(
                gray,
                cv2.CV_64F,
            ).var()
        )

        brightness = float(
            np.mean(
                gray
            )
        )

        contrast = float(
            np.std(
                gray
            )
        )

        return (
            sharpness,
            brightness,
            contrast,
        )

    def validate_image(
        self,
        path: Path,
    ) -> CardImageValidation:
        path = Path(
            path
        )

        if not path.exists():
            return CardImageValidation(
                accepted=False,
                score=0.0,
                reasons=[
                    "file_missing"
                ],
                width=0,
                height=0,
                aspect_ratio=0.0,
                file_size_bytes=0,
                sharpness=0.0,
                brightness=0.0,
                contrast=0.0,
                checksum=None,
            )

        reasons: list[str] = []

        file_size = path.stat().st_size
        checksum = self._sha256_file(
            path
        )

        if not self._is_supported(
            path
        ):
            reasons.append(
                "unsupported_extension"
            )

        if file_size < self.MIN_FILE_SIZE:
            reasons.append(
                "file_too_small"
            )

        image = self._load_image(
            path
        )

        if image is None:
            reasons.append(
                "decode_failed"
            )

            return CardImageValidation(
                accepted=False,
                score=0.0,
                reasons=reasons,
                width=0,
                height=0,
                aspect_ratio=0.0,
                file_size_bytes=file_size,
                sharpness=0.0,
                brightness=0.0,
                contrast=0.0,
                checksum=checksum,
            )

        height, width = image.shape[:2]

        aspect_ratio = (
            width
            / max(
                1,
                height,
            )
        )

        if width < self.MIN_WIDTH:
            reasons.append(
                "width_too_small"
            )

        if height < self.MIN_HEIGHT:
            reasons.append(
                "height_too_small"
            )

        if width >= height:
            reasons.append(
                "landscape_or_square"
            )

        if not (
            self.MIN_ASPECT_RATIO
            <= aspect_ratio
            <= self.MAX_ASPECT_RATIO
        ):
            reasons.append(
                "invalid_card_aspect_ratio"
            )

        (
            sharpness,
            brightness,
            contrast,
        ) = self._quality_metrics(
            image
        )

        if sharpness < self.MIN_SHARPNESS:
            reasons.append(
                "image_too_blurry"
            )

        if contrast < self.MIN_CONTRAST:
            reasons.append(
                "image_too_flat"
            )

        if brightness < 18:
            reasons.append(
                "image_too_dark"
            )

        if brightness > 242:
            reasons.append(
                "image_too_bright"
            )

        ratio_score = self._ratio_score(
            aspect_ratio
        )

        resolution_score = min(
            1.0,
            (
                width
                * height
            )
            / (
                1000
                * 1400
            ),
        )

        sharpness_score = min(
            1.0,
            max(
                0.0,
                sharpness
                / 180.0,
            ),
        )

        contrast_score = min(
            1.0,
            max(
                0.0,
                contrast
                / 65.0,
            ),
        )

        portrait_score = (
            1.0
            if width < height
            else 0.0
        )

        score = (
            ratio_score
            * 0.45
            + portrait_score
            * 0.20
            + resolution_score
            * 0.15
            + sharpness_score
            * 0.10
            + contrast_score
            * 0.10
        )

        hard_rejections = {
            "decode_failed",
            "unsupported_extension",
            "landscape_or_square",
            "invalid_card_aspect_ratio",
            "width_too_small",
            "height_too_small",
        }

        accepted = (
            score
            >= self.ACCEPT_SCORE
            and not any(
                reason
                in hard_rejections
                for reason in reasons
            )
        )

        return CardImageValidation(
            accepted=accepted,
            score=round(
                float(score),
                4,
            ),
            reasons=reasons,
            width=int(width),
            height=int(height),
            aspect_ratio=round(
                float(aspect_ratio),
                4,
            ),
            file_size_bytes=int(
                file_size
            ),
            sharpness=round(
                float(sharpness),
                3,
            ),
            brightness=round(
                float(brightness),
                3,
            ),
            contrast=round(
                float(contrast),
                3,
            ),
            checksum=checksum,
        )

    def normalize_card_image(
        self,
        source_path: Path,
        output_path: Path,
        output_width: int = 500,
        output_height: int = 700,
    ) -> bool:
        image = self._load_image(
            source_path
        )

        if image is None:
            return False

        normalized = cv2.resize(
            image,
            (
                output_width,
                output_height,
            ),
            interpolation=cv2.INTER_AREA,
        )

        return self._write_image(
            output_path,
            normalized,
            quality=95,
        )

    def discover_files(
        self,
        source_directory: Path,
    ) -> list[Path]:
        source_directory = Path(
            source_directory
        )

        if not source_directory.exists():
            return []

        files = [
            path
            for path
            in source_directory.rglob("*")
            if self._is_supported(
                path
            )
        ]

        files.sort(
            key=lambda path: str(
                path
            ).lower()
        )

        return files

    @staticmethod
    def _destination_path(
        source_path: Path,
        source_root: Path,
        destination_root: Path,
    ) -> Path:
        try:
            relative = (
                source_path.relative_to(
                    source_root
                )
            )

        except ValueError:
            relative = Path(
                source_path.name
            )

        return (
            destination_root
            / relative
        )

    def import_directory(
        self,
        source_directory: Path,
        *,
        language: str = "Simplified Chinese",
        language_code: str = "zh-cn",
        set_id: str | None = None,
        set_name: str | None = None,
        move_files: bool = False,
        normalize: bool = True,
    ) -> dict[str, Any]:
        self._cancel.clear()

        source_directory = Path(
            source_directory
        ).resolve()

        started_at = time.time()

        self._set_status(
            busy=True,
            phase="DISCOVERING",
            files_discovered=0,
            files_processed=0,
            files_accepted=0,
            files_rejected=0,
            files_duplicate=0,
            files_failed=0,
            current_file=None,
            started_at=started_at,
            error=None,
            errors=[],
        )

        if not source_directory.exists():
            error = (
                "Source directory does not exist: "
                f"{source_directory}"
            )

            self._set_status(
                busy=False,
                phase="FAILED",
                error=error,
            )

            return {
                "ok": False,
                "error": error,
            }

        files = self.discover_files(
            source_directory
        )

        self._set_status(
            phase="VALIDATING",
            files_discovered=len(
                files
            ),
        )

        catalog = self._read_json(
            self.catalog_path,
            [],
        )

        rejections = self._read_json(
            self.rejection_path,
            [],
        )

        if not isinstance(
            catalog,
            list,
        ):
            catalog = []

        if not isinstance(
            rejections,
            list,
        ):
            rejections = []

        known_hashes = {
            str(
                record.get(
                    "checksum"
                )
            )
            for record in catalog
            if record.get(
                "checksum"
            )
        }

        processed = 0
        accepted = 0
        rejected = 0
        duplicates = 0
        failed = 0

        errors: list[str] = []

        for source_path in files:
            if self._cancel.is_set():
                break

            processed += 1

            self._set_status(
                phase="VALIDATING",
                current_file=str(
                    source_path
                ),
                files_processed=processed,
            )

            try:
                validation = (
                    self.validate_image(
                        source_path
                    )
                )

                if (
                    validation.checksum
                    and validation.checksum
                    in known_hashes
                ):
                    duplicates += 1

                    self._set_status(
                        files_duplicate=duplicates,
                    )

                    continue

                destination_root = (
                    self.accepted_root
                    if validation.accepted
                    else self.rejected_root
                )

                destination_path = (
                    self._destination_path(
                        source_path,
                        source_directory,
                        destination_root,
                    )
                )

                destination_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                if move_files:
                    shutil.move(
                        str(
                            source_path
                        ),
                        str(
                            destination_path
                        ),
                    )

                else:
                    shutil.copy2(
                        source_path,
                        destination_path,
                    )

                if validation.accepted:
                    accepted += 1

                    normalized_path: Path | None = None

                    if normalize:
                        normalized_relative = (
                            destination_path
                            .relative_to(
                                self.accepted_root
                            )
                            .with_suffix(
                                ".webp"
                            )
                        )

                        normalized_path = (
                            self.normalized_root
                            / normalized_relative
                        )

                        normalized_ok = (
                            self.normalize_card_image(
                                destination_path,
                                normalized_path,
                            )
                        )

                        if not normalized_ok:
                            normalized_path = None

                    record = {
                        "id": (
                            validation.checksum
                            or self._safe_filename(
                                source_path.stem
                            )
                        ),
                        "name": source_path.stem,
                        "printed_name": None,
                        "english_name": None,
                        "collector_number": None,
                        "rarity": None,
                        "variant": None,
                        "language": language,
                        "language_code": (
                            language_code
                        ),
                        "set_id": set_id,
                        "set_name": set_name,
                        "local_image": str(
                            destination_path
                        ),
                        "normalized_image": (
                            str(
                                normalized_path
                            )
                            if normalized_path
                            else None
                        ),
                        "checksum": (
                            validation.checksum
                        ),
                        "validation_score": (
                            validation.score
                        ),
                        "validation": (
                            validation.to_dict()
                        ),
                        "source": (
                            "RareIQ Card Scan Import"
                        ),
                        "imported_at": time.time(),
                    }

                    catalog.append(
                        record
                    )

                    if validation.checksum:
                        known_hashes.add(
                            validation.checksum
                        )

                else:
                    rejected += 1

                    rejections.append({
                        "source_path": str(
                            source_path
                        ),
                        "rejected_path": str(
                            destination_path
                        ),
                        "language": language,
                        "language_code": (
                            language_code
                        ),
                        "set_id": set_id,
                        "set_name": set_name,
                        "validation": (
                            validation.to_dict()
                        ),
                        "rejected_at": time.time(),
                    })

                self._set_status(
                    files_accepted=accepted,
                    files_rejected=rejected,
                    files_duplicate=duplicates,
                    files_failed=failed,
                )

            except Exception as exc:
                failed += 1

                errors.append(
                    f"{source_path}: {exc}"
                )

                self._set_status(
                    files_failed=failed,
                    errors=errors[-200:],
                )

        self._write_json(
            self.catalog_path,
            catalog,
        )

        self._write_json(
            self.rejection_path,
            rejections,
        )

        manifest = {
            "catalog_format": (
                "RareIQ Card Scan Import v1"
            ),
            "source_directory": str(
                source_directory
            ),
            "language": language,
            "language_code": language_code,
            "set_id": set_id,
            "set_name": set_name,
            "move_files": move_files,
            "normalize": normalize,
            "files_discovered": len(
                files
            ),
            "files_processed": processed,
            "files_accepted": accepted,
            "files_rejected": rejected,
            "files_duplicate": duplicates,
            "files_failed": failed,
            "catalog_records_total": len(
                catalog
            ),
            "rejection_records_total": len(
                rejections
            ),
            "canceled": (
                self._cancel.is_set()
            ),
            "duration_seconds": round(
                time.time()
                - started_at,
                2,
            ),
            "built_at": time.time(),
            "errors": errors[-500:],
        }

        self._write_json(
            self.manifest_path,
            manifest,
        )

        self._write_missing_metadata_report(
            catalog
        )

        phase = (
            "CANCELED"
            if self._cancel.is_set()
            else "READY"
        )

        self._set_status(
            busy=False,
            phase=phase,
            files_discovered=len(
                files
            ),
            files_processed=processed,
            files_accepted=accepted,
            files_rejected=rejected,
            files_duplicate=duplicates,
            files_failed=failed,
            current_file=None,
            error=None,
            errors=errors[-200:],
        )

        return {
            "ok": True,
            "manifest": manifest,
            "catalog_path": str(
                self.catalog_path
            ),
            "rejection_path": str(
                self.rejection_path
            ),
            "accepted_root": str(
                self.accepted_root
            ),
            "rejected_root": str(
                self.rejected_root
            ),
            "normalized_root": str(
                self.normalized_root
            ),
        }

    def _write_missing_metadata_report(
        self,
        catalog: list[
            dict[str, Any]
        ],
    ) -> None:
        required_fields = (
            "printed_name",
            "english_name",
            "collector_number",
            "rarity",
            "variant",
            "set_id",
        )

        missing = []

        for record in catalog:
            missing_fields = [
                field
                for field in required_fields
                if not record.get(
                    field
                )
            ]

            if missing_fields:
                missing.append({
                    "id": record.get(
                        "id"
                    ),
                    "local_image": record.get(
                        "local_image"
                    ),
                    "normalized_image": record.get(
                        "normalized_image"
                    ),
                    "missing_fields": (
                        missing_fields
                    ),
                })

        self._write_json(
            (
                self.report_root
                / "missing_metadata.json"
            ),
            {
                "catalog_records": len(
                    catalog
                ),
                "records_missing_metadata": len(
                    missing
                ),
                "metadata_complete": (
                    len(
                        catalog
                    )
                    - len(
                        missing
                    )
                ),
                "generated_at": time.time(),
                "records": missing,
            },
        )

    def start_import(
        self,
        source_directory: Path,
        **kwargs: Any,
    ) -> dict[str, Any]:
        with self._lock:
            if self._status.get(
                "busy"
            ):
                return {
                    "ok": False,
                    "error": (
                        "Card scan import "
                        "is already running."
                    ),
                }

        self._worker = threading.Thread(
            target=self.import_directory,
            args=(
                source_directory,
            ),
            kwargs=kwargs,
            daemon=True,
            name=(
                "RareIQCardScanImporter"
            ),
        )

        self._worker.start()

        return {
            "ok": True,
            "status": self.status(),
        }

    def cancel(
        self,
    ) -> dict[str, Any]:
        self._cancel.set()

        self._set_status(
            phase="CANCELING"
        )

        return {
            "ok": True
        }
