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
