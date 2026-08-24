from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any
from urllib.parse import urlparse

import httpx


class SargeAdvisorService:
    """Read-only operator advice with an optional Sarge AI handoff."""

    VERSION = 1
    MAX_QUESTION_LENGTH = 800
    MAX_ANSWER_LENGTH = 8000

    def __init__(
        self,
        endpoint: str | None = None,
        *,
        token: str | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.endpoint = str(endpoint or "").strip()
        self.token = str(token or "").strip()
        self.timeout_seconds = max(2.0, min(60.0, float(timeout_seconds)))
        self._lock = threading.RLock()
        self._last_request_at: float | None = None
        self._last_success_at: float | None = None
        self._last_error: str | None = None

    @classmethod
    def from_environment(cls) -> "SargeAdvisorService":
        try:
            timeout_seconds = float(os.getenv("RAREIQ_SARGE_AI_TIMEOUT", "15"))
        except (TypeError, ValueError):
            timeout_seconds = 15.0
        return cls(
            os.getenv("RAREIQ_SARGE_AI_URL"),
            token=os.getenv("RAREIQ_SARGE_AI_TOKEN"),
            timeout_seconds=timeout_seconds,
        )

    def _endpoint_valid(self) -> bool:
        if not self.endpoint:
            return False
        parsed = urlparse(self.endpoint)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname)

    def status(self) -> dict[str, Any]:
        parsed = urlparse(self.endpoint) if self.endpoint else None
        with self._lock:
            return {
                "available": True,
                "configured": self._endpoint_valid(),
                "mode": "sarge_ai" if self._endpoint_valid() else "local_rareiq",
                "provider": "Sarge AI" if self._endpoint_valid() else "RareIQ Local Advisor",
                "endpoint_host": (
                    f"{parsed.hostname}:{parsed.port}"
                    if parsed and parsed.hostname and parsed.port
                    else parsed.hostname if parsed else None
                ),
                "advisory_only": True,
                "mutations_allowed": False,
                "images_shared": False,
                "last_request_at": self._last_request_at,
                "last_success_at": self._last_success_at,
                "last_error": self._last_error,
            }

    @staticmethod
    def _candidate(candidate: Any) -> dict[str, Any]:
        value = candidate if isinstance(candidate, dict) else {}
        return {
            "id": value.get("id"),
            "name": value.get("english_name") or value.get("name"),
            "set_id": value.get("set_id"),
            "set_name": value.get("set_name"),
            "collector_number": value.get("collector_number"),
            "language": value.get("language"),
            "score": value.get("score"),
            "visual_similarity": value.get("visual_similarity"),
            "verification_strong": value.get("verification_strong") is True,
        }

    @classmethod
    def sanitize_context(cls, context: dict[str, Any] | None) -> dict[str, Any]:
        raw = context if isinstance(context, dict) else {}
        recognition = raw.get("recognition") if isinstance(raw.get("recognition"), dict) else {}
        card = raw.get("card") if isinstance(raw.get("card"), dict) else {}
        camera = raw.get("camera") if isinstance(raw.get("camera"), dict) else {}
        session = raw.get("session") if isinstance(raw.get("session"), dict) else {}
        broadcast = raw.get("broadcast") if isinstance(raw.get("broadcast"), dict) else {}
        candidates = recognition.get("candidates") if isinstance(recognition.get("candidates"), list) else []
        timings = recognition.get("stage_timings") if isinstance(recognition.get("stage_timings"), dict) else {}
        return {
            "recognition": {
                "state_id": recognition.get("state_id"),
                "generation": recognition.get("generation"),
                "phase": recognition.get("phase"),
                "verification_state": recognition.get("verification_state"),
                "overall_confidence": recognition.get("overall_confidence"),
                "has_reference_evidence": recognition.get("has_reference_evidence") is True,
                "card_present": recognition.get("card_present") is True,
                "result_current": recognition.get("result_current") is True,
                "collector_number": recognition.get("ocr_collector_number") or recognition.get("collector_number"),
                "language": recognition.get("language"),
                "candidate_count": recognition.get("candidate_count"),
                "primary_candidate": cls._candidate(recognition.get("primary_candidate")),
                "candidates": [cls._candidate(item) for item in candidates[:3]],
                "stage_timings": {
                    "total_ms": timings.get("total_ms"),
                    "ocr_ms": timings.get("ocr_ms"),
                    "artwork_search_ms": timings.get("artwork_search_ms"),
                    "path": timings.get("path"),
                },
            },
            "card": {
                "card_id": card.get("card_id"),
                "card_name": card.get("card_name"),
                "printed_name": card.get("printed_name"),
                "english_name": card.get("english_name"),
                "set_id": card.get("set_id"),
                "set_name": card.get("set_name"),
                "collector_number": card.get("collector_number"),
                "language": card.get("language"),
                "rarity": card.get("rarity"),
                "confidence": card.get("confidence"),
                "verification_state": card.get("verification_state"),
                "raw_value": card.get("raw_value"),
            },
            "camera": {
                "state": camera.get("state"),
                "health_reason": camera.get("health_reason"),
                "frame_fresh": camera.get("frame_fresh") is True,
                "resolution": camera.get("resolution"),
                "fps": camera.get("fps"),
                "visible": camera.get("visible") is True,
                "stable": camera.get("stable") is True,
                "detection_confidence": camera.get("detection_confidence"),
                "lock_confidence": camera.get("lock_confidence"),
            },
            "session": {
                "active": session.get("active") is True,
                "card_count": session.get("card_count"),
                "hit_count": session.get("hit_count"),
                "active_pack_number": session.get("active_pack_number"),
                "active_box_number": session.get("active_box_number"),
                "total_value": session.get("total_value"),
            },
            "broadcast": {
                "active": broadcast.get("active") is True,
                "recording_active": broadcast.get("recording_active") is True,
                "event_count": broadcast.get("event_count"),
            },
        }

    @staticmethod
    def _local_advice(question: str, context: dict[str, Any], scope: str) -> dict[str, Any]:
        recognition = context["recognition"]
        card = context["card"]
        camera = context["camera"]
        session = context["session"]
        primary = recognition.get("primary_candidate") or {}
        candidates = recognition.get("candidates") or []
        evidence: list[str] = []
        suggestions: list[str] = []

        if camera.get("state") not in {"running", "healthy"} or not camera.get("frame_fresh"):
            answer = "The active camera is not delivering a confirmed fresh frame. Recover the selected source before trusting recognition or capture results."
            evidence.append(f"Camera state: {camera.get('state') or 'unknown'}")
            suggestions.extend(["Reconnect the selected camera", "Confirm frame IDs are advancing"])
        elif not recognition.get("card_present"):
            answer = "RareIQ is ready for a card. Place one complete card inside the scan zone and keep normal handheld movement small until the boundary locks."
            evidence.extend(["Camera frame is fresh", "No card is currently present"])
            suggestions.extend(["Present a full card inside the scan zone", "Avoid glare across the footer"])
        elif primary.get("id") and recognition.get("has_reference_evidence"):
            name = primary.get("name") or card.get("card_name") or "the card"
            answer = f"{name} has reference-backed identity evidence. Review the collector number, language, and set shown in Studio X before approving it."
            evidence.extend([
                f"Verification: {recognition.get('verification_state') or 'complete'}",
                f"Overall confidence: {round(float(recognition.get('overall_confidence') or 0) * 100)}%",
            ])
            suggestions.extend(["Review the exact identity evidence", "Approve only if the printed identifiers agree"])
        elif candidates:
            lead = candidates[0]
            live_number = recognition.get("collector_number")
            lead_number = lead.get("collector_number")
            live_language = recognition.get("language")
            lead_language = lead.get("language")
            conflicts = []
            if live_number and lead_number and str(live_number) != str(lead_number):
                conflicts.append(f"collector {live_number} vs {lead_number}")
            if live_language and lead_language and str(live_language).lower() != str(lead_language).lower():
                conflicts.append(f"language {live_language} vs {lead_language}")
            lead_name = lead.get("name") or "the leading artwork candidate"
            answer = f"RareIQ has an artwork lead for {lead_name}, but it does not have enough exact identity evidence to approve this card."
            if conflicts:
                answer += f" The current conflict is {', '.join(conflicts)}."
            evidence.extend([
                f"Candidates considered: {recognition.get('candidate_count') or len(candidates)}",
                f"Primary candidate: withheld",
                *conflicts,
            ])
            suggestions.extend(["Keep approval blocked", "Search the catalog using the printed collector number", "Capture again only if the footer is blurred or obscured"])
        else:
            answer = "Recognition has not produced enough trustworthy identity evidence yet. Keep the card inside the scan zone and review the live diagnostics before acting."
            evidence.extend([
                f"Phase: {recognition.get('phase') or 'waiting'}",
                f"Verification: {recognition.get('verification_state') or 'unknown'}",
            ])
            suggestions.extend(["Check card focus and footer visibility", "Wait for a reference-backed candidate"])

        lowered = question.lower()
        if any(term in lowered for term in ("sell", "price", "value", "market")):
            value = card.get("raw_value")
            verification = str(card.get("verification_state") or recognition.get("verification_state") or "").upper()
            value_is_truthful = (
                recognition.get("has_reference_evidence")
                and verification in {"EXACT_MATCH", "MATCHED", "VERIFIED", "LOCKED"}
                and isinstance(value, (int, float))
                and value > 0
            )
            if value_is_truthful:
                evidence.append(f"Verified card value available: {value:.2f}")
                suggestions.append("Review fees, shipping, and cost basis before listing")
            else:
                evidence.append("No truthful market value is available")
                suggestions.append("Do not estimate a sale price until a verified market quote exists")
        if scope in {"session", "broadcast"} or any(term in lowered for term in ("session", "stream", "show", "broadcast")):
            evidence.append(f"Session cards: {session.get('card_count') or 0}")
            suggestions.append("Keep the current card decision resolved before advancing the show")

        return {
            "answer": answer,
            "suggestions": list(dict.fromkeys(suggestions))[:6],
            "evidence": list(dict.fromkeys(evidence))[:8],
        }

    async def _ask_sarge(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_seconds, connect=min(5.0, self.timeout_seconds)),
            follow_redirects=False,
        ) as client:
            response = await client.post(self.endpoint, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Sarge AI returned an invalid response.")
        answer = str(result.get("answer") or result.get("message") or "").strip()
        if not answer:
            raise ValueError("Sarge AI returned no answer.")
        return {
            "answer": answer[: self.MAX_ANSWER_LENGTH],
            "suggestions": [str(item)[:300] for item in (result.get("suggestions") or [])[:6]],
            "evidence": [str(item)[:300] for item in (result.get("evidence") or [])[:8]],
        }

    async def ask(self, question: str, context: dict[str, Any] | None, *, scope: str = "general") -> dict[str, Any]:
        normalized_question = " ".join(str(question or "").split())
        if not normalized_question:
            raise ValueError("Ask Sarge AI a question first.")
        if len(normalized_question) > self.MAX_QUESTION_LENGTH:
            raise ValueError(f"Questions are limited to {self.MAX_QUESTION_LENGTH} characters.")
        safe_context = self.sanitize_context(context)
        request_id = uuid.uuid4().hex
        now = time.time()
        with self._lock:
            self._last_request_at = now
        local = self._local_advice(normalized_question, safe_context, scope)
        source = "local_rareiq"
        fallback_reason = None
        result = local
        if self._endpoint_valid():
            payload = {
                "version": self.VERSION,
                "requestId": request_id,
                "question": normalized_question,
                "scope": scope,
                "context": safe_context,
                "safety": {"mode": "advisory", "mutationsAllowed": False},
            }
            try:
                result = await self._ask_sarge(payload)
                source = "sarge_ai"
                with self._lock:
                    self._last_success_at = time.time()
                    self._last_error = None
            except (httpx.HTTPError, ValueError, TypeError) as exc:
                fallback_reason = type(exc).__name__
                with self._lock:
                    self._last_error = "Sarge AI was unavailable; local advice was used."
        return {
            "ok": True,
            "version": self.VERSION,
            "request_id": request_id,
            "source": source,
            "provider": "Sarge AI" if source == "sarge_ai" else "RareIQ Local Advisor",
            "advisory_only": True,
            "mutations_performed": False,
            "question": normalized_question,
            "scope": scope,
            "answer": result["answer"],
            "suggestions": result["suggestions"],
            "evidence": result["evidence"],
            "fallback_reason": fallback_reason,
            "answered_at": time.time(),
        }
