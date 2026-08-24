from __future__ import annotations
import asyncio
import threading
import time
import cv2
import numpy as np
from collections import deque
from pathlib import Path
from typing import Any

from rareiq.core.events import EventBus
from rareiq.core.recognition_state import RecognitionStateStore
from rareiq.core.storage import storage
from rareiq.services.session_service import SessionService
from rareiq.services.collection_service import CollectionService
from rareiq.services.inventory_service import InventoryService
from rareiq.services.experience_service import ExperienceService
from rareiq.services.multi_card_recognition_service import MultiCardRecognitionService
from rareiq.services.artwork_index_service import ArtworkIndexService
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
from rareiq.services.pokedex_service import PokedexService
from rareiq.services.reveal_sequence_service import RevealSequenceService
from rareiq.services.reaction_asset_service import ReactionAssetService
from rareiq.services.pack_artwork_recognition_service import PackArtworkRecognitionService
from rareiq.services.tcg_registry_service import TCGDefinition, TCGRegistryService


class RareIQOrchestrator:
    COLLECTOR_OCR_RETRY_TIMEOUT_SECONDS = 2.0

    def __init__(self, event_bus: EventBus, capture_dir: Path) -> None:

        self.event_bus = event_bus
        self._shutting_down = False

        data_root = storage.get_path("database_root")
        capture_dir = storage.get_path("capture_path")
        log_dir = storage.get_path("log_path")
        cache_dir = storage.get_path("cache_path")

        self.sessions = SessionService(log_dir / "sessions")
        self.collection = CollectionService(data_root / "collection.json")
        self.inventory = InventoryService(data_root / "inventory.json")

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
        self._pack_cycle: dict[str, Any] | None = None
        self._pack_cycle_samples: deque[dict[str, Any]] = deque(maxlen=50)
        self._current_stream_session_id: int | None = None
        self._active_capture_attribution: dict[str, Any] | None = None
        self._removal_finalize_card: dict[str, Any] | None = None
        self._removal_finalize_generation: int | None = None
        self._recognition_decision_generation: int | None = None
        self._picked_region_context: dict[str, Any] | None = None
        self._collector_retry_attempted_epoch: int | None = None

        self.experiences = ExperienceService()
        self.reveal_sequence = RevealSequenceService(cache_dir / "reveal_sequence.json")
        self.reaction_assets = ReactionAssetService(
            data_root / "creator_assets", cache_dir / "reaction_assets.json"
        )
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
        self.recognition = RecognitionService(
            self._emit_from_thread,
            temporal_path=cache_dir / "single_card_temporal.json",
        )
        self.trigger_manager = TriggerManagerService(
            self.vision,
            self.recognition,
            self.pipeline_state,
        )
        self.trigger_manager.start()
        self.catalog = CatalogService(self._emit_from_thread, cache_dir / "catalog")
        self.recognition.set_prediction_prefetcher(self.catalog.prefetch_predictions)
        self.cardgrader = CardGraderService(storage.get_path("grading_path"))

        self.tcg_registry = TCGRegistryService((
            TCGDefinition(
                game_id="pokemon",
                name="Pokémon Trading Card Game",
                aliases=("pokemon", "pokémon", "ptcg"),
                providers=("tcgdex", "pokemontcg", "simplifiedtcg"),
                capabilities=(
                    "catalog",
                    "visual_recognition",
                    "pack_recognition",
                    "inventory",
                    "localized_sets",
                ),
            ),
        ), config_path=storage.get_path("config_path") / "tcg_selection.json")

        self.catalog_intelligence = CatalogIntelligenceService(
            data_root,
            self.recognition.artwork_index,
            shared_dropbox_link="https://www.dropbox.com/scl/fo/i8fwz3ktmh53ved36hdht/AHvdG4tiZ8w_PV-XfBFAAoM?rlkey=fxq3gpdgn8tui4nooqqr8cbbs&st=retasmap&dl=0",
        )
        self.recognition.set_catalog_resolver(
            self.catalog_intelligence.resolve
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
            storage,
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
        self.pokedex = PokedexService(cache_dir / "pokedex")
        self.recognition.set_intelligence_services(
            self.vision_optimizer,
            self.candidate_ranker,
            self.recognition_diagnostics,
        )
        self.pack_artwork_recognition = PackArtworkRecognitionService(
            cache_dir / "pack_artwork"
        )
        self.multi_card_recognition = MultiCardRecognitionService(self.recognition)
        self.recognition.set_exact_reference_resolver(
            self.multi_card_recognition.resolve_exact_reference
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
            getattr(self, "catalog", None),
            getattr(self, "system_health", None),
            getattr(self, "job_queue", None),
            getattr(self, "index_activation", None),
            getattr(self, "fast_pipeline", None),
            getattr(self, "master_database_builder", None),
            getattr(self, "pokemon_auto_sync", None),
            getattr(self, "recognition", None),
            getattr(self, "multi_card_recognition", None),
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
        present: bool | None = None,
        clear: bool = False,
    ) -> None:
        previous = self._continuous_state
        self._continuous_state = state
        self._continuous_state_at = time.time()

        effective_present = (
            bool(present)
            if present is not None
            else state not in {"EMPTY", "LOST"}
        )

        self.recognition_state.set_continuous_state(
            state,
            generation=self._recognition_generation,
            frame_id=frame_id,
            card_present=effective_present,
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
        self._finalize_verified_card_on_removal()
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
        self._removal_finalize_card = None
        self._removal_finalize_generation = None
        self._set_continuous_state(
            "EMPTY",
            frame_id=payload.get("frame_id"),
            clear=True,
        )
        removed_at = float(payload.get("timestamp") or time.time())
        self._pack_cycle = {
            "cycle_id": f"{self._recognition_generation}:{int(removed_at * 1000)}",
            "removed_at": removed_at,
            "removal_frame_id": payload.get("frame_id"),
            "operator_clear": bool(payload.get("operator_clear")),
        }
        self._append_diagnostic(
            event="generation_increment",
            reason="removal_confirmed",
            frame_id=payload.get("frame_id"),
            old_generation=previous_generation,
            new_generation=self._recognition_generation,
        )

    def _finalize_verified_card_on_removal(self) -> dict[str, Any] | None:
        card = getattr(self, "_removal_finalize_card", None)
        generation = getattr(self, "_removal_finalize_generation", None)
        decision_generation = getattr(
            self, "_recognition_decision_generation", None
        )
        if (
            not card
            or generation != self._recognition_generation
            or decision_generation == self._recognition_generation
        ):
            return None

        session = self.sessions.add_card(dict(card))
        self._record_collection_pull(card, session)
        reveal = self._advance_reveal_sequence(card, bool(session.get("duplicate_suppressed")))
        self._recognition_decision_generation = self._recognition_generation
        self._removal_finalize_card = None
        self._removal_finalize_generation = None
        self._emit_from_thread({
            "type": "card_confirmed",
            "payload": {
                "session": session,
                "card": card,
                "automatic": True,
                "reason": "verified_card_removed",
                "reveal_sequence": reveal,
            },
        })
        self._append_diagnostic(
            event="card_auto_finalized",
            reason="verified_card_removed",
        )
        return session

    def _record_collection_pull(
        self,
        card: dict[str, Any],
        session: dict[str, Any],
    ) -> dict[str, Any] | None:
        collection = getattr(self, "collection", None)
        pull = session.get("last_added_card") or {}
        if collection is None or session.get("duplicate_suppressed") or not pull.get("id"):
            return None
        return collection.record(card, str(pull["id"]))

    def _advance_reveal_sequence(self, card: dict[str, Any], duplicate: bool) -> dict[str, Any] | None:
        reveal_service = getattr(self, "reveal_sequence", None)
        if reveal_service is None:
            return None
        return reveal_service.snapshot() if duplicate else reveal_service.advance(card)

    def _submit_captured_card(self, payload: dict[str, Any]) -> None:
        crop = payload.get("crop")
        ocr_crop = payload.get("ocr_crop")
        ocr_frames = tuple(payload.get("ocr_frames") or ())
        frame_id = payload.get("frame_id")
        captured_at = float(
            payload.get("capture_timestamp")
            or payload.get("timestamp")
            or time.time()
        )
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
        # RecognitionService takes the single ownership snapshot immediately
        # before launching its worker. Copying the same 4K arrays here as well
        # doubled capture handoff cost without adding isolation.
        crop = np.asarray(crop)
        if ocr_crop is not None and getattr(ocr_crop, "size", 0):
            ocr_crop = np.asarray(ocr_crop)
        else:
            ocr_crop = crop
        collector_frames = tuple(
            np.asarray(item)
            for item in ocr_frames[:3]
            if item is not None and getattr(item, "size", 0)
        )

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
        elif source == "collector-ocr-retry":
            # This is another sample of the current physical card, not a new
            # identity generation. Keeping the generation stable preserves the
            # existing candidate until the stronger result replaces it.
            pass
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
        cycle = getattr(self, "_pack_cycle", None)
        if cycle is not None and cycle.get("capture_submitted_at") is None:
            submitted_at = time.time()
            cycle.update({
                "generation": generation,
                "capture_submitted_at": submitted_at,
                "capture_frame_id": frame_id,
                "removal_to_capture_ms": round(
                    max(0.0, submitted_at - float(cycle["removed_at"])) * 1000,
                    1,
                ),
            })
        result = self.recognition.submit_frame(
            crop,
            generation=generation,
            frame_id=frame_id,
            source=source,
            captured_at=captured_at,
            ocr_frame=ocr_crop,
            collector_frames=collector_frames,
        )
        if result == "busy_queued":
            self._pending_recognition = {
                "crop": crop.copy(),
                "ocr_crop": ocr_crop.copy(),
                "collector_frames": tuple(
                    item.copy() for item in collector_frames
                ),
                "generation": generation,
                "frame_id": frame_id,
                "source": source,
                "captured_at": captured_at,
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

    def recognize_picked_region(
        self,
        crop: np.ndarray,
        slot: int,
        *,
        automatic_follow_up: bool = False,
        polygon: list[list[float]] | None = None,
    ) -> dict[str, Any]:
        self._recognition_generation += 1
        generation = self._recognition_generation
        self.recognition.invalidate_before(generation)
        result = self.recognition.submit_frame(
            crop,
            generation=generation,
            frame_id=self.vision.status().get("frame_id"),
            source=f"manual-picked-slot-{int(slot)}",
            captured_at=time.time(),
            ocr_frame=crop,
            collector_frames=(crop,),
        )
        if result == "accepted":
            self._active_job_generation = generation
            self._picked_region_context = {
                "slot": int(slot),
                "generation": generation,
                "fingerprint": ArtworkIndexService.variant_marker_fingerprint(crop),
                "treatment_response": self.multi_card_recognition.treatment_response(crop),
                "frame_id": self.vision.status().get("frame_id"),
                "polygon": polygon,
                "automatic_follow_up": bool(automatic_follow_up),
            }
            self._set_continuous_state("RECOGNIZING", present=True)
        return {
            "ok": result == "accepted",
            "job_accepted": result == "accepted",
            "reason": result,
            "generation": generation,
            "slot": int(slot),
        }

    def _schedule_picked_region_follow_up(self, payload: dict[str, Any]) -> None:
        diagnostics = payload.get("exact_reference_diagnostics") or {}
        context = getattr(self, "_picked_region_context", None) or {}
        if (
            payload.get("background_enrichment")
            or
            diagnostics.get("status") != "ambiguous"
            or int(diagnostics.get("confirmation_progress") or 0) != 1
            or context.get("automatic_follow_up")
            or int(context.get("generation") or 0) != self._recognition_generation
        ):
            return
        expected_generation = self._recognition_generation
        slot = int(context.get("slot") or 0)
        fingerprint = str(context.get("fingerprint") or "")
        treatment_response = context.get("treatment_response") or (0.0, 0.0, 0.0)
        original_frame_id = context.get("frame_id")
        polygon = context.get("polygon")
        self.recognition.update_exact_reference_follow_up("waiting-for-fresh-foil-sample")

        def follow_up() -> None:
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline and not self._shutting_down:
                time.sleep(0.25)
                if expected_generation != self._recognition_generation:
                    return
                frame = self.vision.latest_frame()
                region = (
                    self.multi_card_recognition.track_region(frame, polygon, 12)
                    if polygon
                    else None
                )
                if not region:
                    self.recognition.update_exact_reference_follow_up("selected-card-lost")
                    return
                crop = region.get("crop")
                if self.vision.status().get("frame_id") == original_frame_id:
                    continue
                current = ArtworkIndexService.variant_marker_fingerprint(crop)
                distance = ArtworkIndexService.hamming(fingerprint, current)
                response_distance = self.multi_card_recognition.treatment_response_distance(
                    treatment_response,
                    self.multi_card_recognition.treatment_response(crop),
                )
                if distance > 10 or (distance == 0 and response_distance < 1.25):
                    continue
                self.recognize_picked_region(
                    crop,
                    slot,
                    automatic_follow_up=True,
                    polygon=region.get("polygon"),
                )
                return
            if expected_generation == self._recognition_generation:
                self.recognition.update_exact_reference_follow_up("timed-out-safely")

        threading.Thread(
            target=follow_up,
            name="rareiq-picked-card-follow-up",
            daemon=True,
        ).start()

    def _schedule_collector_ocr_retry(self, payload: dict[str, Any]) -> bool:
        """Capture one newer frame when footer OCR explicitly requests it."""
        if (
            payload.get("background_enrichment")
            or not payload.get("collector_retry_recommended")
            or self._pending_recognition is not None
            or self._continuous_state in {"EMPTY", "LOST", "CHANGING"}
        ):
            return False
        expected_generation = self._recognition_generation
        expected_epoch = self._current_acquisition_epoch
        if self._collector_retry_attempted_epoch == expected_epoch:
            return False
        self._collector_retry_attempted_epoch = expected_epoch
        original_frame_id = int(payload.get("frame_id") or 0)
        attribution = dict(
            getattr(self, "_active_capture_attribution", None) or {}
        )
        original_provenance = dict(attribution.get("provenance") or {})
        original_content_fingerprint = str(
            original_provenance.get("content_fingerprint") or ""
        )
        self._append_diagnostic(
            event="collector_ocr_retry_scheduled",
            reason="newer_frame_requested",
            frame_id=original_frame_id,
            acquisition_epoch=expected_epoch,
        )

        def retry() -> None:
            deadline = (
                time.monotonic() + self.COLLECTOR_OCR_RETRY_TIMEOUT_SECONDS
            )
            while time.monotonic() < deadline and not self._shutting_down:
                time.sleep(0.10)
                if (
                    expected_generation != self._recognition_generation
                    or expected_epoch != self._current_acquisition_epoch
                    or self._continuous_state in {"EMPTY", "LOST", "CHANGING"}
                ):
                    self._append_diagnostic(
                        event="collector_ocr_retry_cancelled",
                        reason="card_changed_or_removed",
                        frame_id=original_frame_id,
                    )
                    return
                camera_status = self.vision.status()
                fresh_frame_id = int(camera_status.get("frame_id") or 0)
                if fresh_frame_id <= original_frame_id:
                    continue
                fresh_provenance = dict(
                    camera_status.get("camera_provenance") or {}
                )
                fresh_content_fingerprint = str(
                    fresh_provenance.get("content_fingerprint")
                    or camera_status.get("manager", {}).get("content_fingerprint")
                    or ""
                )
                if (
                    original_content_fingerprint
                    and fresh_content_fingerprint == original_content_fingerprint
                ):
                    continue
                result = self.vision.capture_fresh(source="collector-ocr-retry")
                self._append_diagnostic(
                    event="collector_ocr_retry_capture",
                    reason=("captured" if result.get("ok") else result.get("reason") or "capture_failed"),
                    frame_id=result.get("frame_id") or fresh_frame_id,
                    acquisition_epoch=expected_epoch,
                )
                return
            self._append_diagnostic(
                event="collector_ocr_retry_timeout",
                reason=(
                    "no_changed_content"
                    if original_content_fingerprint
                    else "no_newer_frame"
                ),
                frame_id=original_frame_id,
                acquisition_epoch=expected_epoch,
            )

        threading.Thread(
            target=retry,
            name="rareiq-collector-ocr-retry",
            daemon=True,
        ).start()
        return True

    def _submit_pending_if_current(self) -> bool:
        pending = self._pending_recognition
        if not pending or pending["generation"] != self._recognition_generation:
            return False
        result = self.recognition.submit_frame(
            pending["crop"],
            generation=pending["generation"],
            frame_id=pending["frame_id"],
            source=pending["source"],
            captured_at=pending.get("captured_at"),
            ocr_frame=pending.get("ocr_crop"),
            collector_frames=pending.get("collector_frames"),
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
        self._schedule_picked_region_follow_up(payload)
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
        cycle = getattr(self, "_pack_cycle", None)
        if cycle and int(cycle.get("generation") or -1) == generation:
            now = time.time()
            if candidates and cycle.get("first_candidate_at") is None:
                cycle["first_candidate_at"] = now
                cycle["removal_to_candidate_ms"] = round(
                    max(0.0, now - float(cycle["removed_at"])) * 1000, 1
                )
                cycle["capture_to_candidate_ms"] = round(
                    max(0.0, now - float(cycle["capture_submitted_at"])) * 1000,
                    1,
                )
            if verification_state == "VERIFIED" and cycle.get("verified_at") is None:
                cycle["verified_at"] = now
                cycle["removal_to_verified_ms"] = round(
                    max(0.0, now - float(cycle["removed_at"])) * 1000, 1
                )
                cycle["capture_to_verified_ms"] = round(
                    max(0.0, now - float(cycle["capture_submitted_at"])) * 1000,
                    1,
                )
                samples = getattr(self, "_pack_cycle_samples", None)
                if samples is None:
                    samples = deque(maxlen=50)
                    self._pack_cycle_samples = samples
                samples.append(dict(cycle))
            payload["pack_cycle_timings"] = self._pack_cycle_snapshot()

        if error:
            self.pipeline_state.fail(
                "ocr",
                str(error),
                "Recognition failed",
            )
            self._last_trigger_result = "recognition_failed"
            return

        # Start catalog enrichment after every usable recognition result.
        # Prefer OCR identity, but borrow missing metadata from the strongest
        # non-provisional visual candidate.
        catalog_request = dict(payload)

        visual_candidate = next(
            (
                candidate
                for candidate in candidates
                if isinstance(candidate, dict)
                and candidate.get("source") != "ocr_provisional"
            ),
            None,
        )

        if visual_candidate:
            for key in (
                "collector_number",
                "language",
                "language_code",
                "printed_name",
                "name",
                "english_name",
                "canonical_name",
                "pokemon_name",
                "pricing_lookup_name",
                "identity_override_key",
                "set_id",
                "set_name",
            ):
                if not catalog_request.get(key):
                    value = visual_candidate.get(key)
                    if value not in (None, ""):
                        catalog_request[key] = value

        if not catalog_request.get("name_candidate"):
            catalog_request["name_candidate"] = (
                catalog_request.get("printed_name")
                or catalog_request.get("name")
                or name
            )

        self.catalog.submit(catalog_request)

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
            if verification_state == "VERIFIED" and not card.get("provisional"):
                self._removal_finalize_card = dict(card)
                self._removal_finalize_generation = generation
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
        self._schedule_collector_ocr_retry(payload)

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
            "pack_cycle": self._pack_cycle_snapshot(),
        }

    def _pack_cycle_snapshot(self) -> dict[str, Any] | None:
        cycle = getattr(self, "_pack_cycle", None)
        if not cycle:
            return None
        public_keys = (
            "cycle_id", "generation", "removal_frame_id", "capture_frame_id",
            "operator_clear", "removal_to_capture_ms",
            "capture_to_candidate_ms", "removal_to_candidate_ms",
            "capture_to_verified_ms", "removal_to_verified_ms",
        )
        snapshot = {
            key: cycle.get(key) for key in public_keys if cycle.get(key) is not None
        }
        samples = list(getattr(self, "_pack_cycle_samples", ()))
        completed = [
            float(item["removal_to_verified_ms"])
            for item in samples if item.get("removal_to_verified_ms") is not None
        ]
        if completed:
            ordered = sorted(completed)
            snapshot["sample_count"] = len(ordered)
            snapshot["p50_removal_to_verified_ms"] = round(
                ordered[int((len(ordered) - 1) * 0.50)], 1
            )
            snapshot["p95_removal_to_verified_ms"] = round(
                ordered[int((len(ordered) - 1) * 0.95)], 1
            )
        return snapshot

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
        learned=self.learning_queue.correction_match(unified.get("artwork_fingerprint") or self._current_artwork_fingerprint or "",candidate)
        if learned:
            corrected=learned["candidate"]
            candidate={**corrected,"source":"learned_operator_correction","operator_learned":True,"learned_match_type":learned["match_type"],"learned_fingerprint_distance":learned["distance"],"learned_evidence_agreement":learned["evidence_agreement"],"correction_id":learned["correction_id"],"fused_score":max(.99,float(corrected.get("fused_score") or corrected.get("score") or 0))}

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
        pricing = dict(candidate.get("pricing") or {})

        market_value = candidate.get("market_price")
        if market_value is None:
            market_value = candidate.get("raw_market")
        if market_value is None:
            market_value = candidate.get("raw_value")
        if market_value is None:
            market_value = pricing.get("market")

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
            "set_id": candidate.get("set_id"),
            "rarity": candidate.get("rarity") or "UNKNOWN",
            "category": candidate.get("category"),
            "hp": candidate.get("hp"),
            "types": candidate.get("types"),
            "energy_type": candidate.get("energy_type"),
            "source": candidate.get("source") or "unified_recognition",
            "pricing": pricing,
            "market_price": float(market_value or 0.0),
            "raw_market": float(market_value or 0.0),
            "raw_low": pricing.get("low"),
            "raw_high": pricing.get("high"),
            "price_source": (
                candidate.get("price_source")
                or pricing.get("source")
            ),
            "pricing_source": (
                candidate.get("pricing_source")
                or pricing.get("source")
            ),
            "currency": (
                candidate.get("currency")
                or pricing.get("currency")
                or pricing.get("unit")
                or "USD"
            ),
            "price_updated_at": (
                candidate.get("price_updated_at")
                or pricing.get("updated_at")
            ),
            "reference_image_url": (
                candidate.get("reference_image_url")
                or candidate.get("image_url")
                or candidate.get("image")
                or "/api/camera/crop.jpg"
            ),
            "raw_value": float(market_value or 0.0),
            "confidence": confidence,
            "recognition_signature": signature,
            "recognition_revision": unified.get("revision"),
            "provisional": bool(
                candidate.get("provisional")
                and not (
                    unified.get("recognition_locked") is True
                    and str(unified.get("verification_state") or "").upper()
                    == "VERIFIED"
                )
            ),
        }

    def _decision_recognition_card(self) -> dict[str, Any] | None:
        """Return the current card or the backend's retained verified card.

        Recognition enrichment may briefly publish a weaker follow-up result
        after the UI has already rendered a verified card. The decision path
        must use the backend-owned verified snapshot retained for automatic
        removal, never fail merely because that transient refresh has no
        primary candidate.
        """
        current = self._current_recognition_card()
        if current:
            return current
        retained = getattr(self, "_removal_finalize_card", None)
        retained_generation = getattr(
            self, "_removal_finalize_generation", None
        )
        if (
            retained
            and retained_generation == self._recognition_generation
        ):
            return dict(retained)
        return None

    async def confirm_recognition(
        self,
        automatic: bool = False,
        allow_unverified_test: bool = False,
        card_override: dict[str, Any] | None = None,
    ):
        card = dict(card_override) if isinstance(card_override, dict) else self._decision_recognition_card()
        if not card:
            return {"ok": False, "error": "No recognition candidate is available."}

        if automatic and card.get("operator_learned") and card.get("learned_match_type") == "approximate":
            return {
                "ok": False,
                "error": "A learned near-match needs operator approval before it can be added.",
                "reason": "learned_approximate_requires_review",
                "card": card,
            }

        recognition = self.recognition_state.refresh(
            vision=self.vision.status(),
            recognition=self.recognition.status(),
            catalog=self.catalog.status(),
        )
        overall = float(recognition.get("overall_confidence") or 0.0)

        if (
            card_override is None
            and recognition.get("identity_consistent") is False
        ):
            return {
                "ok": False,
                "error": (
                    "Observed OCR evidence conflicts with the selected catalog "
                    "identity. Review and select the correct candidate."
                ),
                "reason": "identity_evidence_conflict",
                "identity_conflicts": list(
                    recognition.get("identity_conflicts") or []
                ),
                "confidence": overall,
            }

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
        if card.get("operator_learned") and card.get("correction_id"):
            self.learning_queue.record_correction_use(
                card["correction_id"],
                str(card.get("learned_match_type") or "exact"),
                card.get("learned_fingerprint_distance"),
            )
        self._record_collection_pull(card, session)
        reveal = self._advance_reveal_sequence(card, bool(session.get("duplicate_suppressed")))
        self._recognition_decision_generation = self._recognition_generation
        self._removal_finalize_card = None
        self._removal_finalize_generation = None

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
                "reveal_sequence": reveal,
            },
        )
        return {
            "ok": True,
            "session": session,
            "card": card,
            "duplicate_suppressed": bool(session.get("duplicate_suppressed")),
            "reveal_sequence": reveal,
        }

    async def reject_recognition(self):
        card = self._decision_recognition_card()
        if not card:
            return {"ok": False, "error": "No recognition candidate is available."}
        result = self.sessions.reject_card(card)
        self._recognition_decision_generation = self._recognition_generation
        self._removal_finalize_card = None
        self._removal_finalize_generation = None
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

    async def start_session(self, **payload):
        session = self.sessions.start(**payload)
        self.reveal_sequence.next_pack()
        await self.publish("session_started", {"session": session})
        return session

    async def next_pack(self):
        session = self.sessions.next_pack()
        reveal = self.reveal_sequence.next_pack()
        await self.publish("session_updated", {"session": session, "reveal_sequence": reveal})
        return session

    async def previous_pack(self):
        session = self.sessions.previous_pack()
        await self.publish("session_updated", {"session": session})
        return session

    async def next_box(self):
        session = self.sessions.next_box()
        self.reveal_sequence.next_pack()
        await self.publish("session_updated", {"session": session})
        return session

    async def previous_box(self):
        session = self.sessions.previous_box()
        await self.publish("session_updated", {"session": session})
        return session

    async def undo(self):
        s, removed = self.sessions.undo()
        collection = getattr(self, "collection", None)
        if collection is not None and removed and removed.get("id"):
            collection.remove_event(str(removed["id"]))
        await self.publish("session_updated", {"session": s, "removed": removed})
        return s
    async def close_session(self):
        s = self.sessions.close(); await self.publish("session_closed", {"session": s}); return s




