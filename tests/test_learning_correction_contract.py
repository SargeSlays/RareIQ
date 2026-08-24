import asyncio
from types import SimpleNamespace

from rareiq.core.orchestrator import RareIQOrchestrator
from rareiq.services.learning_queue_service import LearningQueueService


CARD={"english_name":"Goldeen","collector_number":"013/084","set_id":"me05","set_name":"Pitch Black","language":"English"}


def test_learned_correction_supports_guarded_near_fingerprint_matches(tmp_path):
    service=LearningQueueService(tmp_path/"learning")
    saved=service.add_correction(fingerprint="0000000000000000",candidate=CARD,state_id="state-1")
    assert saved["ok"]
    exact=service.correction_match("0000000000000000",{})
    assert exact["match_type"]=="exact" and exact["distance"]==0
    near=service.correction_match("0000000000000003",{"collector_number":"013/084","set_id":"me05"})
    assert near["match_type"]=="approximate" and near["distance"]==2 and near["evidence_agreement"]>=2
    assert service.correction_match("0000000000000003",{"english_name":"Wrong"}) is None
    assert service.correction_match("ffffffffffffffff",CARD) is None
    recorded=service.record_correction_use(saved["correction"]["id"],"approximate",2)
    assert recorded["recorded"] and recorded["correction"]["times_applied"]==1
    status=service.corrections()
    assert status["applications"]==1 and status["approximate_applications"]==1
    assert service.revoke_correction(saved["correction"]["id"])["revoked"]
    assert service.correction_match("0000000000000000",CARD) is None


def test_exact_learned_fingerprint_never_overrides_conflicting_fresh_identity(tmp_path):
    service=LearningQueueService(tmp_path/"learning")
    service.add_correction(fingerprint="0000000000000000",candidate=CARD,state_id="state-1")
    assert service.correction_match("0000000000000000",{
        "collector_number":"099/084",
        "language":"Japanese",
    }) is None


def test_learned_evidence_normalizes_collector_and_chinese_aliases(tmp_path):
    service=LearningQueueService(tmp_path/"learning")
    chinese={**CARD,"collector_number":"029/084","language":"Simplified Chinese"}
    service.add_correction(fingerprint="0000000000000000",candidate=chinese,state_id="state-1")
    match=service.correction_match("0000000000000003",{
        "collector_number":"29/84",
        "language":"zh_cn",
    })
    assert match is not None
    assert match["match_type"]=="approximate"
    assert match["evidence_agreement"]==2
    assert match["evidence_conflicts"]==0
    assert match["evidence_compared"]==2


class _Status:
    def status(self):
        return {}


class _RecognitionState:
    def __init__(self,payload):
        self.payload=payload

    def refresh(self,**_kwargs):
        return self.payload


class _LearningQueue:
    def __init__(self,match):
        self.match=match
        self.observed=None

    def correction_match(self,_fingerprint,observed):
        self.observed=observed
        return self.match


def test_orchestrator_routes_observed_ocr_to_learning_and_preserves_guard_metadata():
    orchestrator=RareIQOrchestrator.__new__(RareIQOrchestrator)
    orchestrator.vision=orchestrator.recognition=orchestrator.catalog=_Status()
    orchestrator._current_artwork_fingerprint=None
    orchestrator.recognition_state=_RecognitionState({
        "primary_candidate":{**CARD,"fused_score":0.6},
        "artwork_fingerprint":"0000000000000000",
        "identity_evidence":{"observed":{"collector_number":"029/084","language":"Chinese"}},
        "revision":3,
    })
    orchestrator.learning_queue=_LearningQueue({
        "candidate":{**CARD,"collector_number":"029/084","language":"Simplified Chinese"},
        "correction_id":"correction-1",
        "distance":2,
        "match_type":"approximate",
        "evidence_agreement":2,
        "evidence_conflicts":0,
        "evidence_compared":2,
    })

    card=orchestrator._current_recognition_card()

    assert orchestrator.learning_queue.observed=={
        "collector_number":"029/084","language":"Chinese"
    }
    assert card["operator_learned"] is True
    assert card["learned_match_type"]=="approximate"
    assert card["learned_evidence_agreement"]==2
    assert card["correction_id"]=="correction-1"


def test_automatic_confirmation_blocks_approximate_learned_identity():
    fake=SimpleNamespace(
        _decision_recognition_card=lambda:{
            "card_name":"Goldeen",
            "operator_learned":True,
            "learned_match_type":"approximate",
        }
    )
    result=asyncio.run(
        RareIQOrchestrator.confirm_recognition(fake,automatic=True)
    )
    assert result["ok"] is False
    assert result["reason"]=="learned_approximate_requires_review"
