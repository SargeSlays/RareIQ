from rareiq.services.experience_service import ExperienceService


def test_hit_tiers_are_conservative_and_support_operator_override():
    service = ExperienceService()

    assert service.for_card({"rarity": "Common"})["hit_tier"] == "standard"
    assert service.for_card({"rarity": "Rare"})["hit_tier"] == "low"
    assert service.for_card({"rarity": "Illustration Rare"})["hit_tier"] == "medium"
    assert service.for_card({"rarity": "Special Art Rare"})["hit_tier"] == "medium"
    assert service.for_card({"rarity": "Rare", "hit_tier": "grail"})["hit_tier"] == "grail"


def test_reveal_audio_is_off_until_user_supplies_and_enables_it():
    experience = ExperienceService().for_card({"rarity": "GRAIL"})

    assert experience["reaction_copy"] == "GRAIL HIT"
    assert experience["intensity"] == 4
    assert experience["audio_enabled"] is False
    assert experience["audio_source"] == "user-supplied"
