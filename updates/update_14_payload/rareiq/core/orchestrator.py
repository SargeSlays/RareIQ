from __future__ import annotations
import asyncio
import time
import cv2
import numpy as np
import uuid
from collections import deque
from pathlib import Path
from typing import Any

from rareiq.core.events import EventBus
from rareiq.core.recognition_state import RecognitionStateStore
from rareiq.core.storage import storage
from rareiq.services.session_service import SessionService
from rareiq.services.experience_service import ExperienceService
from rareiq.services.vision_service import VisionService
from rareiq.services.camera_manager_service import CameraManagerService
from rareiq.services.boot_manager_service import BootManagerService
from rareiq.services.backend_test_service import BackendTestService
from rareiq.services.pipeline_state_service import PipelineStateService
from rareiq.services.trigger_manager_service import TriggerManagerService
from rareiq.services.recognition_service import RecognitionService
from rareiq.services.catalog_service import CatalogService
from rareiq.services.cardgrader_service import CardGraderService
from rareiq.services.catalog_intelligence_service import CatalogIntelligenceService
from rareiq.services.pokemon_master_database_service import PokemonMasterDatabaseService
from rareiq.services.global_visual_index_service import GlobalVisualIndexService
from rareiq.services.pokemon_auto_sync_service import PokemonAutoSyncService
from rareiq.services.master_database_builder_service import MasterDatabaseBuilderService
from rareiq.services.provider_diagnostics_service import ProviderDiagnosticsService
from rareiq.services.fast_pipeline_service import FastPipelineService
from rareiq.services.universal_asset_manager_service import UniversalAssetManagerService
from rareiq.services.recognition_fusion_service import RecognitionFusionService
from rareiq.services.benchmark_service import BenchmarkService
from rareiq.services.war_room_service import WarRoomService
from rareiq.services.index_activation_service import IndexActivationService
from rareiq.services.job_queue_service import JobQueueService
from rareiq.services.system_health_service import SystemHealthService
from rareiq.services.library_optimizer_service import LibraryOptimizerService
from rareiq.services.vision_optimizer_service import VisionOptimizerService
from rareiq.services.candidate_ranker_service import CandidateRankerService
from rareiq.services.recognition_diagnostics_service import RecognitionDiagnosticsService
from rareiq.services.learning_queue_service import LearningQueueService
from rareiq.services.x7_benchmark_service import X7BenchmarkService
from rareiq.services.brand_settings_service import BrandSettingsService
from rareiq.services.overlay_state_service import OverlayStateService


class RareIQOrchestrator:
    def __init__(self, event_bus: EventBus, capture_dir: Path) -> None:

        self.event_bus = event_bus
        self._shutting_down = False

        data_root = storage.get_path("database_root")
        capture_dir = storage.get_path("capture_path")
        log_dir = storage.get_path("log_path")
        cache_dir = storage.get_path("cache_path")

        self.sessions = SessionService(log_dir / "sessions")

        self._last_auto_crop_hash: int | None = None
        self._last_auto_card_signature: str | None = None
        self._last_auto_added_at: float = 0.0

        # Automatic recognition-trigger telemetry.
        self._last_submitted_crop_hash: int | None = None
        self._last_recognition_submit_at: float = 0.0
        self._recognition_submit_count: int = 0
        self._recognition_duplicate_count: int = 0
        self._last_trigger_result: str = "waiting"
        self._continuous_state = "EMPTY"
        self._recognition_generation = 0
        self._active_job_generation: int | None = None
        self._pending_recognition: dict[str, Any] | None = None
        self._deferred_change_evidence: dict[str, Any] | None = None
        self._current_acquisition_epoch = 0
        self._minimum_capture_frame_id = 0
        self._current_full_fingerprint: str | None = None
        self._current_artwork_fingerprint: str | None = None
        self._continuous_state_at = time.time()
        self._auto_capture_generation: int | None = None
        self._diagnostic_journal: deque[dict[str, Any]] = deque(maxlen=64)
        self._current_stream_session_id: int | None = None
        self._active_capture_attribution: dict[str, Any] | None = None

        self.experiences = ExperienceService()
        self.loop: asyncio.AbstractEventLoop | None = None

        raw_vision = VisionService(self._emit_from_thread, capture_dir)
        self.camera_manager = CameraManagerService(
            raw_vision,
            cache_dir / "camera_manager.json",
        )
        # Compatibility alias: legacy recognition code continues using .vision.
        self.vision = self.camera_manager
        self.boot_manager = BootManagerService(self)
        self.pipeline_state = PipelineStateService()
        self.backend_test = BackendTestService(
            self,
            cache_dir / "diagnostics",
        )
        self.recognition = RecognitionService(self._emit_from_thread)
        self.trigger_manager = TriggerManagerService(
            self.vision,
            self.recognition,
            self.pipeline_state,
        )
        self.trigger_manager.start()
        self.catalog = CatalogService(self._emit_from_thread, cache_dir / "catalog")
        self.cardgrader = CardGraderService(storage.get_path("grading_path"))

        self.catalog_intelligence = CatalogIntelligenceService(
            data_root,
            self.recognition.artwork_index,
            shared_dropbox_link="https://www.dropbox.com/scl/fo/i8fwz3ktmh53ved36hdht/AHvdG4tiZ8w_PV-XfBFAAoM?rlkey=fxq3gpdgn8tui4nooqqr8cbbs&st=retasmap&dl=0",
        )
        self.pokemon_master_database = PokemonMasterDatabaseService(
            data_root,
            self.catalog_intelligence,
        )
        self.global_visual_index = GlobalVisualIndexService(
            data_root,
            self.catalog_intelligence,
        )
        self.pokemon_auto_sync = PokemonAutoSyncService(
            data_root,
            self.pokemon_master_database,
            self.global_visual_index,
        )
        self.master_database_builder = MasterDatabaseBuilderService(
            self.pokemon_master_database,
            self.catalog_intelligence,
            self.global_visual_index,
        )
        self.provider_diagnostics = ProviderDiagnosticsService(
            self.pokemon_master_database.providers,
        )
        self.fast_pipeline = FastPipelineService(
            self.pokemon_master_database,
            self.catalog_intelligence,
            self.global_visual_index,
        )
        self.asset_manager = UniversalAssetManagerService()
        self.recognition_fusion = RecognitionFusionService()
        self.benchmarks = BenchmarkService(self.recognition_fusion)
        self.war_room = WarRoomService(
            self.asset_manager,
            self.benchmarks,
            self.fast_pipeline,
            self.global_visual_index,
        )
        self.recognition.set_global_visual_index(
            self.global_visual_index
        )
        self.index_activation = IndexActivationService(
            self.catalog_intelligence,
            self.global_visual_index,
            self.recognition,
        )
        self.job_queue = JobQueueService()
        self.library_optimizer = LibraryOptimizerService(
            self.asset_manager,
            self.global_visual_index,
            self.recognition,
        )
        self.system_health = SystemHealthService(
            self.vision,
            self.recognition,
            self.global_visual_index,
            self.asset_manager,
            self.fast_pipeline,
            self.provider_diagnostics,
            self.job_queue,
        )
        self.vision_optimizer = VisionOptimizerService()
        self.candidate_ranker = CandidateRankerService(
            self.recognition_fusion
        )
        self.recognition_diagnostics = RecognitionDiagnosticsService()
        self.learning_queue = LearningQueueService()
        self.x7_benchmarks = X7BenchmarkService(
            self.vision_optimizer,
            self.candidate_ranker,
        )
        self.brand_settings = BrandSettingsService()
        self.overlay_state = OverlayStateService()
        self.recognition.set_intelligence_services(
            self.vision_optimizer,
            self.candidate_ranker,
            self.recognition_diagnostics,
        )

        self.recognition_state = RecognitionStateStore()
        self.recognition_state.refresh(
            vision=self.vision.status(),
            recognition=self.recognition.status(),
            catalog=self.catalog.status(),
        )

    async def shutdown(self) -> None:
        """Stop background work before the event loop closes."""
        self._shutting_down = True

        services = (
            getattr(self, "trigger_manager", None),
            getattr(self, "system_health", None),
            getattr(self, "job_queue", None),
            getattr(self, "index_activation", None),
            getattr(self, "fast_pipeline", None),
            getattr(self, "master_database_builder", None),
            getattr(self, "pokemon_auto_sync", None),
            getattr(self, "recognition", None),
            getattr(self, "vision", None),
            getattr(self, "sessions", None),
        )

        for service in services:
            if service is None:
                continue

            for method_name in ("shutdown", "stop", "close"):
                method = getattr(service, method_name, None)
                if not callable(method):
                    continue

                try:
                    result = method()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    pass
                break

        self.loop = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Publish a normalized RareIQ event."""

        event = {
            "type": str(event_type),
            "payload": payload or {},
        }

        self._handle_internal_event(
            event
        )

        await self.event_bus.publish(
            event
        )
    def _emit_from_thread(self, event: dict[str, Any]) -> None:
        if self._shutting_down:
            return

        # Internal processing must not depend on the websocket event loop.
        self._handle_internal_event(event)

        loop = self.loop
        if loop is None or loop.is_closed() or not loop.is_running():
            return

        try:
            future = asyncio.run_coroutine_threadsafe(
                self.event_bus.publish(event),
                loop,
            )
            future.add_done_callback(self._consume_publish_result)
        except RuntimeError:
            return


    def _handle_internal_event(self, event: dict[str, Any]) -> None:
        """Connect Vision card captures to Recognition automatically."""
        event_type = str(event.get("type") or "")
        payload = event.get("payload") or {}

        if event_type == "card_captured":
            self._submit_captured_card(payload)
            return

        if event_type == "card_changed":
            self._begin_card_change(payload)
            return

        if event_type == "card_removed":
            self._confirm_card_removed(payload)
            return

        if event_type == "card_tracking":
            self._observe_card_tracking(payload)
            return

        if event_type == "recognition_update":
            self._apply_recognition_pipeline_update(payload)
            return

        if event_type == "recognition_discarded":
            self._submit_pending_if_current()

    def _set_continuous_state(
        self,
        state: str,
        *,
        frame_id: int | None = None,
        present: bool = False,
        clear: bool = False,
    ) -> None:
        previous = self._continuous_state
        self._continuous_state = state
        self._continuous_state_at = time.time()
        self.recognition_state.set_continuous_state(
            state,
            generation=self._recognition_generation,
            frame_id=frame_id,
            card_present=present,
            clear_result=clear,
        )
        self._append_diagnostic(
            event="state_transition",
            reason="clear_result" if clear else "tracking_state",
            frame_id=frame_id,
            previous_state=previous,
            next_state=state,
        )

    def _append_diagnostic(
        self,
        *,
        event: str,
        reason: str,
        frame_id: int | None = None,
        previous_state: str | None = None,
        next_state: str | None = None,
        **metrics: Any,
    ) -> None:
        journal = getattr(self, "_diagnostic_journal", None)
        if journal is None:
            journal = deque(maxlen=64)
            self._diagnostic_journal = journal
        journal.append({
            "timestamp": time.time(),
            "frame_id": frame_id,
            "generation": self._recognition_generation,
            "previous_state": previous_state or self._continuous_state,
            "next_state": next_state or self._continuous_state,
            "event": event,
            "reason": reason,
            **metrics,
        })

    def _observe_card_tracking(self, payload: dict[str, Any]) -> None:
        provenance = dict(payload.get("camera_provenance") or {})
        if provenance.get("stream_session_id") is not None:
            self._current_stream_session_id = int(
                provenance["stream_session_id"]
            )
        visible = bool(payload.get("visible"))
        stable = bool(payload.get("stable"))
        frame_id = payload.get("frame_id")
        if visible and self._continuous_state in {"EMPTY", "LOST"}:
            self._set_continuous_state(
                "ACQUIRING", frame_id=frame_id, present=True
            )
        elif stable and self._continuous_state == "ACQUIRING":
            self._set_continuous_state(
                "STABLE", frame_id=frame_id, present=True
            )
        elif not visible and self._continuous_state not in {"EMPTY", "LOST"}:
            self._set_continuous_state(
                "LOST", frame_id=frame_id, present=False
            )

    def _begin_card_change(self, payload: dict[str, Any]) -> None:
        full_distance = int(payload.get("full_card_hash_distance") or 0)
        artwork_distance = int(payload.get("artwork_hash_distance") or 0)
        structural_similarity = float(
            payload.get("structural_similarity") or 1.0
        )
        primary_identity_change = bool(
            full_distance >= 16
            and artwork_distance >= 14
            and structural_similarity < 0.72
        )
        artwork_identity_change = bool(
            artwork_distance >= 14
            and structural_similarity < 0.60
        )
        decisive = bool(
            payload.get("decisive")
            and payload.get("replacement_confirmed")
            and payload.get("geometry_valid")
            and int(payload.get("changed_frames") or 0) >= 6
            and (primary_identity_change or artwork_identity_change)
        )
        if self._continuous_state == "RECOGNIZING" and not decisive:
            self._deferred_change_evidence = {
                **payload,
                "deferred_at": time.time(),
                "generation": self._recognition_generation,
            }
            self._append_diagnostic(
                event="replacement_deferred",
                reason="ambiguous_during_recognition",
                frame_id=payload.get("frame_id"),
                **self._replacement_metrics(payload),
            )
            return

        incoming_epoch = payload.get("acquisition_epoch")
        incoming_frame = int(payload.get("frame_id") or 0)
        if (
            incoming_epoch is not None
            and int(incoming_epoch) == self._current_acquisition_epoch
        ):
            self._append_diagnostic(
                event="replacement_ignored",
                reason="duplicate_card_changed_event",
                frame_id=incoming_frame,
                **self._replacement_metrics(payload),
            )
            return

        self._deferred_change_evidence = None
        self._current_acquisition_epoch = int(
            payload.get("acquisition_epoch")
            if payload.get("acquisition_epoch") is not None
            else self._current_acquisition_epoch + 1
        )
        self._minimum_capture_frame_id = int(payload.get("frame_id") or 0)
        previous_generation = self._recognition_generation
        self._recognition_generation += 1
        self.recognition.invalidate_before(self._recognition_generation)
        self._pending_recognition = None
        self._auto_capture_generation = None
        self._current_full_fingerprint = payload.get("full_card_fingerprint")
        self._current_artwork_fingerprint = payload.get("artwork_fingerprint")
        self._set_continuous_state(
            "CHANGING",
            frame_id=payload.get("frame_id"),
            present=True,
            clear=True,
        )
        self._append_diagnostic(
            event="generation_increment",
            reason="replacement_confirmed",
            frame_id=payload.get("frame_id"),
            old_generation=previous_generation,
            new_generation=self._recognition_generation,
            **self._replacement_metrics(payload),
        )

    @staticmethod
    def _replacement_metrics(payload: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "full_card_hash_distance", "artwork_hash_distance",
            "structural_similarity", "polygon_iou", "corner_movement",
            "changed_frames", "window_size", "geometry_valid",
            "stable_crop_quality", "acquisition_epoch",
        )
        return {key: payload.get(key) for key in keys if key in payload}

    def _confirm_card_removed(self, payload: dict[str, Any]) -> None:
        previous_generation = self._recognition_generation
        self._recognition_generation += 1
        self.recognition.invalidate_before(self._recognition_generation)
        self._pending_recognition = None
        self._deferred_change_evidence = None
        self._current_acquisition_epoch += 1
        self._minimum_capture_frame_id = int(payload.get("frame_id") or 0)
        self._current_full_fingerprint = None
        self._current_artwork_fingerprint = None
        self._last_submitted_crop_hash = None
        self._auto_capture_generation = None
        self._set_continuous_state(
            "EMPTY",
            frame_id=payload.get("frame_id"),
            clear=True,
        )
        self._append_diagnostic(
            event="generation_increment",
            reason="removal_confirmed",
            frame_id=payload.get("frame_id"),
            old_generation=previous_generation,
            new_generation=self._recognition_generation,
        )

    def _submit_captured_card(self, payload: dict[str, Any]) -> None:
        crop = payload.get("crop")
        frame_id = payload.get("frame_id")
        event_epoch = int(payload.get("acquisition_epoch") or 0)
        provenance = dict(payload.get("provenance") or {})
        event_stream = provenance.get("stream_session_id")

        if (
            event_stream is not None
            and self._current_stream_session_id is not None
            and int(event_stream) != self._current_stream_session_id
        ):
            self._last_trigger_result = "stale_capture_stream_session"
            self._append_diagnostic(
                event="capture_rejected",
                reason=self._last_trigger_result,
                frame_id=frame_id,
                **self._provenance_metrics(payload),
            )
            return
        if event_epoch != self._current_acquisition_epoch:
            self._last_trigger_result = "stale_capture_epoch"
            self._append_diagnostic(event="capture_rejected", reason=self._last_trigger_result, frame_id=frame_id)
            return
        if int(frame_id or 0) < self._minimum_capture_frame_id:
            self._last_trigger_result = "stale_capture_frame"
            self._append_diagnostic(event="capture_rejected", reason=self._last_trigger_result, frame_id=frame_id)
            return
        validation = payload.get("validation") or {}
        if validation.get("accepted") is not True:
            self._last_trigger_result = "capture_quality_rejected"
            self._append_diagnostic(event="capture_rejected", reason=self._last_trigger_result, frame_id=frame_id)
            return

        if crop is None or getattr(crop, "size", 0) == 0:
            self._last_trigger_result = "no_crop"
            self.pipeline_state.fail(
                "crop",
                "Card capture event did not contain a corrected crop.",
                "Corrected crop unavailable",
                frame_id=frame_id,
            )
            return
        crop = np.asarray(crop).copy()

        current_hash = self._crop_dhash(crop)
        source = str(payload.get("source") or "auto")
        if (
            source == "auto"
            and getattr(self, "_auto_capture_generation", None)
            == self._recognition_generation
        ):
            self._last_trigger_result = "duplicate_generation_capture"
            self._recognition_duplicate_count += 1
            self._append_diagnostic(
                event="capture_rejected",
                reason=self._last_trigger_result,
                frame_id=frame_id,
            )
            return
        if source == "manual":
            self._recognition_generation += 1
            self.recognition.invalidate_before(self._recognition_generation)
        elif self._continuous_state != "CHANGING":
            self._recognition_generation += 1
            self.recognition.invalidate_before(self._recognition_generation)

        self.pipeline_state.complete(
            "camera",
            "Live frame received",
            frame_id=frame_id,
        )
        self.pipeline_state.complete(
            "detect",
            "Stable card captured",
            frame_id=frame_id,
        )
        self.pipeline_state.complete(
            "crop",
            "Corrected crop submitted",
            frame_id=frame_id,
        )
        self.pipeline_state.start(
            "ocr",
            "Recognition engine reading card details",
            frame_id=frame_id,
        )
        self.pipeline_state.waiting(
            "artwork",
            "Waiting for OCR evidence",
        )
        self.pipeline_state.waiting(
            "verify",
            "Waiting for candidates",
        )
        self.pipeline_state.waiting(
            "current_card",
            "Waiting for verified result",
        )

        generation = self._recognition_generation
        result = self.recognition.submit_frame(
            crop,
            generation=generation,
            frame_id=frame_id,
            source=source,
        )
        if result == "busy_queued":
            self._pending_recognition = {
                "crop": crop.copy(),
                "generation": generation,
                "frame_id": frame_id,
                "source": source,
                "crop_path": payload.get("crop_path") or payload.get("path"),
                "provenance": provenance,
                "acquisition_epoch": event_epoch,
            }
            self._last_trigger_result = "busy_queued"
        elif result not in {None, "accepted"}:
            self._last_trigger_result = str(result)
            return
        else:
            self._active_job_generation = generation
            self._last_trigger_result = "submitted"
        if source == "auto":
            self._auto_capture_generation = generation
        self._active_capture_attribution = {
            "generation": generation,
            "frame_id": frame_id,
            "crop_path": payload.get("crop_path") or payload.get("path"),
            "source": source,
            "acquisition_epoch": event_epoch,
            "provenance": provenance,
        }
        self._append_diagnostic(
            event="recognition_submission",
            reason=self._last_trigger_result,
            frame_id=frame_id,
            source=source,
            validation=dict(validation),
            **self._provenance_metrics(payload),
        )
        self._set_continuous_state(
            "RECOGNIZING", frame_id=frame_id, present=True
        )
        self._last_submitted_crop_hash = current_hash
        self._last_recognition_submit_at = time.time()
        self._recognition_submit_count += 1

    def force_manual_capture(self) -> dict[str, Any]:
        result = self.vision.capture_fresh(source="manual")
        if not result.get("ok"):
            return {
                "ok": False,
                "job_accepted": False,
                "reason": result.get("reason") or "capture_failed",
            }
        return {
            "ok": True,
            "job_accepted": self._last_trigger_result == "submitted",
            "queued": self._last_trigger_result == "busy_queued",
            "generation": self._recognition_generation,
            "frame_id": result.get("frame_id"),
            "crop_path": result.get("path"),
            "reason": self._last_trigger_result,
        }

    def _submit_pending_if_current(self) -> bool:
        pending = self._pending_recognition
        if not pending or pending["generation"] != self._recognition_generation:
            return False
        result = self.recognition.submit_frame(
            pending["crop"],
            generation=pending["generation"],
            frame_id=pending["frame_id"],
            source=pending["source"],
        )
        if result != "accepted":
            return False
        self._pending_recognition = None
        self._active_job_generation = pending["generation"]
        self._set_continuous_state(
            "RECOGNIZING",
            frame_id=pending["frame_id"],
            present=True,
        )
        return True

    def _apply_recognition_pipeline_update(
        self,
        payload: dict[str, Any],
    ) -> None:
        generation = int(payload.get("generation") or 0)
        if generation != self._recognition_generation:
            self._append_diagnostic(
                event="recognition_discarded",
                reason="obsolete_generation",
                frame_id=payload.get("frame_id"),
                result_generation=generation,
            )
            return
        error = payload.get("error")
        candidates = payload.get("candidates") or []
        name = payload.get("name_candidate")
        number = (
            payload.get("collector_number")
            or payload.get("ocr_collector_number")
        )
        verification_state = str(
            payload.get("verification_state") or ""
        ).upper()

        if error:
            self.pipeline_state.fail(
                "ocr",
                str(error),
                "Recognition failed",
            )
            self._last_trigger_result = "recognition_failed"
            return

        if name or number:
            evidence = " / ".join(
                str(value)
                for value in (name, number)
                if value
            )
            self.pipeline_state.complete(
                "ocr",
                f"OCR evidence: {evidence}",
            )
        else:
            self.pipeline_state.complete(
                "ocr",
                "OCR pass completed",
            )

        if candidates:
            self.pipeline_state.complete(
                "artwork",
                f"{len(candidates)} candidate(s) ranked",
            )
        else:
            self.pipeline_state.waiting(
                "artwork",
                "No artwork candidates returned",
            )

        if verification_state == "VERIFIED":
            self.pipeline_state.complete(
                "verify",
                "Recognition verified",
            )
        elif candidates:
            self.pipeline_state.start(
                "verify",
                "Evaluating candidate confidence",
            )
        else:
            self.pipeline_state.waiting(
                "verify",
                "Waiting for candidates",
            )

        card = self._current_recognition_card()
        if card:
            self.pipeline_state.complete(
                "current_card",
                f"Current Card: {card.get('card_name')}",
            )
            self._last_trigger_result = "card_ready"
        else:
            self.pipeline_state.waiting(
                "current_card",
                "Recognition completed without a usable card",
            )
            self._last_trigger_result = "no_card"
        self._active_job_generation = None
        self._set_continuous_state(
            "IDENTIFIED",
            frame_id=payload.get("frame_id"),
            present=True,
        )
        self._append_diagnostic(
            event="recognition_completion",
            reason=self._last_trigger_result,
            frame_id=payload.get("frame_id"),
            candidate_count=len(candidates),
            candidate_id=(candidates[0].get("id") if candidates else None),
            candidate_name=(
                (
                    candidates[0].get("printed_name")
                    or candidates[0].get("name")
                )
                if candidates else name
            ),
            capture_attribution=dict(
                getattr(self, "_active_capture_attribution", None) or {}
            ),
        )
        # Ambiguous change evidence must never erase a result that just
        # completed. It is only retained while the same generation is active;
        # Vision will emit a fresh decisive event if a replacement persists.
        deferred = getattr(self, "_deferred_change_evidence", None)
        self._deferred_change_evidence = None
        if deferred and deferred.get("generation") != generation:
            deferred = None
        self._submit_pending_if_current()

    @staticmethod
    def _provenance_metrics(payload: dict[str, Any]) -> dict[str, Any]:
        provenance = dict(payload.get("provenance") or {})
        return {
            "crop_path": payload.get("crop_path") or payload.get("path"),
            "capture_source": payload.get("source"),
            "acquisition_epoch": payload.get("acquisition_epoch"),
            "stream_session_id": provenance.get("stream_session_id"),
            "device_sequence_id": provenance.get("device_sequence_id"),
            "device_timestamp": provenance.get("device_timestamp"),
            "content_fingerprint": provenance.get("content_fingerprint"),
        }

    def recognition_trigger_status(self) -> dict[str, Any]:
        recognition = self.recognition.status()
        return {
            "enabled": bool(recognition.get("enabled")),
            "busy": bool(recognition.get("busy")),
            "submit_count": self._recognition_submit_count,
            "duplicates_suppressed": self._recognition_duplicate_count,
            "last_submit_at": self._last_recognition_submit_at or None,
            "last_result": self._last_trigger_result,
            "last_crop_hash": self._last_submitted_crop_hash,
            "candidate_count": int(
                recognition.get("candidate_count")
                or len(recognition.get("candidates") or [])
            ),
            "verification_state": recognition.get(
                "verification_state"
            ),
            "continuous_state": self._continuous_state,
            "generation": self._recognition_generation,
            "pending_generation": (
                self._pending_recognition.get("generation")
                if self._pending_recognition else None
            ),
            "diagnostic_journal": list(
                getattr(self, "_diagnostic_journal", ())
            ),
        }

    @staticmethod
    def _consume_publish_result(future: Any) -> None:
        try:
            future.result()
        except Exception:
            pass


    @staticmethod
    def _crop_dhash(image: np.ndarray | None) -> int | None:
        if image is None or image.size == 0:
            return None
        try:
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            resized = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
            diff = resized[:, 1:] > resized[:, :-1]
            value = 0
            for bit in diff.flatten():
                value = (value << 1) | int(bool(bit))
            return value
        except Exception:
            return None

    @staticmethod
    def _hash_distance(left: int | None, right: int | None) -> int | None:
        if left is None or right is None:
            return None
        return (left ^ right).bit_count()

    def _current_recognition_card(self) -> dict[str, Any] | None:
        unified = self.recognition_state.refresh(
            vision=self.vision.status(),
            recognition=self.recognition.status(),
            catalog=self.catalog.status(),
        )
        candidate = unified.get("primary_candidate")
        if not candidate:
            return None

        printed = (
            candidate.get("printed_name")
            or candidate.get("name")
            or unified.get("name_candidate")
            or "Unknown Card"
        )
        english = candidate.get("english_name") or unified.get("english_name")
        card_name = english or printed
        number = candidate.get("collector_number") or unified.get("collector_number")
        language = candidate.get("language") or unified.get("language")
        set_name = candidate.get("set_name")
        confidence = float(
            candidate.get("fused_score")
            if candidate.get("fused_score") is not None
            else candidate.get("score")
            if candidate.get("score") is not None
            else unified.get("overall_confidence")
            or 0.0
        )
        signature = "|".join(
            str(value or "").strip().lower()
            for value in (
                card_name, number, language, set_name,
                unified.get("artwork_fingerprint"),
            )
        )
        return {
            "card_name": card_name,
            "printed_name": printed,
            "english_name": english,
            "collector_number": number,
            "language": language,
            "set_name": set_name,
            "rarity": candidate.get("rarity") or "UNKNOWN",
            "source": candidate.get("source") or "unified_recognition",
            "reference_image_url": (
                candidate.get("reference_image_url")
                or candidate.get("image_url")
                or candidate.get("image")
                or "/api/camera/crop.jpg"
            ),
            "raw_value": float(candidate.get("market_price") or 0.0),
            "confidence": confidence,
            "recognition_signature": signature,
            "recognition_revision": unified.get("revision"),
            "provisional": bool(candidate.get("provisional")),
        }

    async def confirm_recognition(
        self,
        automatic: bool = False,
        allow_unverified_test: bool = False,
    ):
        card = self._current_recognition_card()
        if not card:
            return {"ok": False, "error": "No recognition candidate is available."}

        recognition = self.recognition_state.refresh(
            vision=self.vision.status(),
            recognition=self.recognition.status(),
            catalog=self.catalog.status(),
        )
        overall = float(recognition.get("overall_confidence") or 0.0)

        if (
            automatic
            and not recognition.get("has_reference_evidence")
            and not allow_unverified_test
        ):
            return {
                "ok": False,
                "error": (
                    "Auto-add blocked: this card is not in the loaded database "
                    "or artwork reference index."
                ),
                "reason": "reference_required",
                "confidence": overall,
            }

        if automatic and allow_unverified_test:
            card["source"] = "test_auto_add"
            card["unverified_test_add"] = True
        pipeline = recognition.get("pipeline_stages") or []
        verify_done = any(
            stage.get("key") == "verify" and stage.get("state") == "done"
            for stage in pipeline
        )
        minimum_auto_confidence = 0.45 if allow_unverified_test else 0.55
        if automatic and overall < minimum_auto_confidence and not verify_done:
            return {
                "ok": False,
                "error": "Recognition confidence is not high enough for auto-add.",
                "confidence": overall,
            }

        if automatic:
            now = time.time()
            current_crop = self.vision.latest_crop()
            current_hash = self._crop_dhash(current_crop)
            distance = self._hash_distance(current_hash, self._last_auto_crop_hash)
            signature = card.get("recognition_signature")

            # Hard safety rule: never auto-add the same physical card image twice.
            # OCR and candidate text may fluctuate, but the crop remains visually similar.
            if self._last_auto_crop_hash is not None and distance is not None and distance <= 14:
                return {
                    "ok": True,
                    "duplicate_suppressed": True,
                    "reason": "same_physical_card",
                    "hash_distance": distance,
                    "session": self.sessions.snapshot(),
                    "card": card,
                }

            # Secondary signature/cooldown guard for cases where no crop is available.
            if (
                signature
                and signature == self._last_auto_card_signature
                and now - self._last_auto_added_at < 120.0
            ):
                return {
                    "ok": True,
                    "duplicate_suppressed": True,
                    "reason": "same_recognition_signature",
                    "session": self.sessions.snapshot(),
                    "card": card,
                }

        session = self.sessions.add_card(card)

        if automatic and not session.get("duplicate_suppressed"):
            self._last_auto_crop_hash = self._crop_dhash(self.vision.latest_crop())
            self._last_auto_card_signature = card.get("recognition_signature")
            self._last_auto_added_at = time.time()

        await self.publish(
            "card_confirmed",
            {
                "session": session,
                "card": card,
                "automatic": automatic,
                "experience": self.experiences.for_card(card),
            },
        )
        return {
            "ok": True,
            "session": session,
            "card": card,
            "duplicate_suppressed": bool(session.get("duplicate_suppressed")),
        }

    async def reject_recognition(self):
        card = self._current_recognition_card()
        if not card:
            return {"ok": False, "error": "No recognition candidate is available."}
        result = self.sessions.reject_card(card)
        await self.publish("card_rejected", result)
        return {"ok": True, **result}

    async def session_snapshot(self):
        recognition = self.recognition.status()
        index_status = self.recognition.artwork_index.status()
        active_set = self.recognition.set_catalog.status()
        return {
            "session": self.sessions.snapshot(),
            "recent_cards": self.sessions.recent_cards(),
            "rejected_count": len(self.sessions.rejected),
            "recognition_readiness": {
                "indexed_cards": self.global_visual_index.status().get(
                    "records", 0
                ),
                "active_set": active_set,
                "has_reference_evidence": bool(
                    recognition.get("has_reference_evidence")
                ),
                "verification_state": recognition.get("verification_state"),
            },
            "recognition_state": self.recognition_state.refresh(
                vision=self.vision.status(),
                recognition=self.recognition.status(),
                catalog=self.catalog.status(),
            ),
        }

    async def undo(self):
        s, removed = self.sessions.undo(); await self.publish("session_updated", {"session": s, "removed": removed}); return s
    async def close_session(self):
        s = self.sessions.close(); await self.publish("session_closed", {"session": s}); return s


