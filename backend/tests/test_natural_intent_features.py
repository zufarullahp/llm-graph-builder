from src.natural_intent import detect_natural_intent, compute_nid_features


def test_yes_please_simpler_explanation_not_affirmative_or_contact():
    text = "yes please simpler explanation"
    features = compute_nid_features(text)

    # Sanity on features
    assert "is_short" in features
    assert "is_question" in features
    assert isinstance(features["token_count"], int)

    res = detect_natural_intent(text)

    # Should not be interpreted as affirmative or contact_sharing
    assert res.get("intent") not in ("affirmative", "contact_sharing")
    # Features should be attached
    assert "features" in res


def test_short_yes_is_affirmative():
    res = detect_natural_intent("yes")
    assert res.get("intent") == "affirmative"
    assert res.get("features", {}).get("token_count", 0) <= 2


def test_email_triggers_contact_sharing():
    text = "here is my email a@b.com"
    res = detect_natural_intent(text)
    assert res.get("intent") == "contact_sharing"
    assert res.get("features", {}).get("has_email") is True
