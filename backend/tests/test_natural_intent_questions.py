import pytest
from src.natural_intent import detect_natural_intent


def test_question_with_question_mark_not_personal_context():
    text = "do I need to contact sales representative to get access support site?"
    nid = detect_natural_intent(text)
    assert nid["requires_retrieval"] is True
    assert nid["intent"] != "personal_context"


def test_long_first_person_without_question_is_personal_context():
    text = "I have been using your product for several months and my team experienced repeated failures during deployment which affected our SLA"
    nid = detect_natural_intent(text)
    assert nid["intent"] == "personal_context"
    assert nid["requires_retrieval"] is False


def test_contact_email_still_detected():
    text = "here is my email: alice@example.com"
    nid = detect_natural_intent(text)
    assert nid["intent"] == "contact_sharing"
    assert "email" in nid["slots"]
