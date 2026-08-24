from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from rareiq.core.storage import storage


class LearningQueueService:
    MAX_CORRECTION_DISTANCE = 6

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or (storage.get_path("grading_path") / "learning_queue")
        self.root.mkdir(parents=True, exist_ok=True)

    def add(
        self,
        *,
        scan_payload: dict[str, Any],
        reason: str,
        correct_card_id: str | None = None,
    ) -> dict[str, Any]:
        item_id = uuid.uuid4().hex
        payload = {
            "id": item_id,
            "created_at": time.time(),
            "reason": reason,
            "correct_card_id": correct_card_id,
            "scan": scan_payload,
        }
        path = self.root / f"{item_id}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"ok": True, "id": item_id, "path": str(path)}

    def status(self) -> dict[str, Any]:
        return {
            "queued": len(list(self.root.glob("*.json"))),
            "root": str(self.root),
        }

    def add_correction(self, *, fingerprint: str, candidate: dict[str, Any], state_id: str = "", resolution: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized=str(fingerprint or "").strip()
        if not normalized: return {"ok":False,"reason":"artwork_fingerprint_required"}
        item_id=uuid.uuid4().hex
        payload={"id":item_id,"kind":"identity_correction","created_at":time.time(),"fingerprint":normalized,"state_id":str(state_id or "")[:80],"candidate":dict(candidate),"active":True,"times_applied":0,"exact_applies":0,"approximate_applies":0}
        if isinstance(resolution,dict): payload["resolution"]=dict(resolution)
        path=self.root/f"correction-{item_id}.json"; path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        return {"ok":True,"correction":payload}

    def corrections(self, limit: int = 100) -> dict[str, Any]:
        rows=[]
        for path in self.root.glob("correction-*.json"):
            try:
                row=json.loads(path.read_text(encoding="utf-8"))
                if isinstance(row,dict): rows.append(row)
            except (OSError,ValueError): continue
        rows.sort(key=lambda row:float(row.get("created_at") or 0),reverse=True)
        active=sum(1 for row in rows if row.get("active") is not False)
        return {
            "corrections":rows[:max(1,min(500,int(limit)))],
            "total":len(rows),
            "active":active,
            "revoked":len(rows)-active,
            "applications":sum(int(row.get("times_applied") or 0) for row in rows),
            "exact_applications":sum(int(row.get("exact_applies") or 0) for row in rows),
            "approximate_applications":sum(int(row.get("approximate_applies") or 0) for row in rows),
        }

    @staticmethod
    def _hamming(left: str, right: str) -> int | None:
        try:
            if len(left)!=16 or len(right)!=16: return None
            return (int(left,16)^int(right,16)).bit_count()
        except ValueError: return None

    @staticmethod
    def _evidence_agreement(observed: dict[str, Any], learned: dict[str, Any]) -> int:
        pairs=(("collector_number","collector_number"),("set_id","set_id"),("set_name","set_name"),("english_name","english_name"),("language","language"))
        return sum(1 for left,right in pairs if str(observed.get(left) or "").strip().lower() and str(observed.get(left) or "").strip().lower()==str(learned.get(right) or "").strip().lower())

    def correction_match(self, fingerprint: str, observed: dict[str, Any] | None = None) -> dict[str, Any] | None:
        key=str(fingerprint or "").strip().lower(); observed=observed or {}; best=None
        for row in self.corrections(500)["corrections"]:
            candidate=row.get("candidate"); stored=str(row.get("fingerprint") or "").strip().lower()
            if row.get("active") is False or not isinstance(candidate,dict): continue
            distance=self._hamming(key,stored)
            if distance is None: continue
            agreement=self._evidence_agreement(observed,candidate)
            if distance==0 or (distance<=self.MAX_CORRECTION_DISTANCE and agreement>=2):
                match={"candidate":dict(candidate),"correction_id":row.get("id"),"distance":distance,"match_type":"exact" if distance==0 else "approximate","evidence_agreement":agreement}
                if best is None or (distance,-agreement)<(best["distance"],-best["evidence_agreement"]): best=match
        return best

    def correction_for(self, fingerprint: str, observed: dict[str, Any] | None = None) -> dict[str, Any] | None:
        match=self.correction_match(fingerprint,observed)
        return dict(match["candidate"]) if match else None

    def record_correction_use(self, correction_id: str, match_type: str, distance: int | None = None) -> dict[str, Any]:
        key=str(correction_id or "").strip(); path=self.root/f"correction-{key}.json"
        try: payload=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,ValueError): return {"recorded":False,"reason":"correction_not_found"}
        if payload.get("active") is False: return {"recorded":False,"reason":"correction_revoked"}
        kind="approximate" if match_type=="approximate" else "exact"
        payload["times_applied"]=int(payload.get("times_applied") or 0)+1
        payload[f"{kind}_applies"]=int(payload.get(f"{kind}_applies") or 0)+1
        payload["last_applied_at"]=time.time(); payload["last_match_type"]=kind
        payload["last_fingerprint_distance"]=int(distance or 0)
        path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        return {"recorded":True,"correction":payload}

    def revoke_correction(self, correction_id: str) -> dict[str, Any]:
        key=str(correction_id or "").strip()
        path=self.root/f"correction-{key}.json"
        try: payload=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,ValueError): return {"revoked":False,"reason":"correction_not_found"}
        payload["active"]=False; payload["revoked_at"]=time.time(); path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
        return {"revoked":True,"correction":payload}
