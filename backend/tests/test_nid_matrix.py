import pytest

from src.natural_intent import detect_natural_intent, compute_nid_features


@pytest.mark.parametrize(
    "text,expected",
    [
        ("how are you?", "small_talk"),
        ("lagi ngapain?", "small_talk"),
        ("that's cool", "small_talk"),
        ("this is interesting", "small_talk"),
        ("you are very helpful", {"small_talk", "feedback"}),
        ("you are stupid", {"small_talk", "feedback"}),
        ("can you explain more?", "clarification"),
        ("are you human?", "small_talk"),
    ],
)
def test_small_talk_matrix(text, expected):
    res = detect_natural_intent(text)
    intent = res.get("intent")
    if isinstance(expected, set):
        assert intent in expected, f"{text} -> {intent} not in {expected}"
    else:
        assert intent == expected, f"{text} -> {intent} != {expected}"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("hi", "greeting_closing"),
        ("hello", "greeting_closing"),
        ("halo", "greeting_closing"),
        ("good morning", "greeting_closing"),
        ("see you later", "greeting_closing"),
        ("thank you", {"greeting_closing", "feedback"}),
        ("thanks, bye", "greeting_closing"),
        ("good night, talk to you tomorrow", "greeting_closing"),
        ("hello, I need help with Joget", "not_only_greeting"),
    ],
)
def test_greeting_closing_matrix(text, expected):
    res = detect_natural_intent(text)
    intent = res.get("intent")
    if expected == "not_only_greeting":
        assert intent != "greeting_closing", f"{text} should not be only greeting (got {intent})"
    elif isinstance(expected, set):
        assert intent in expected
    else:
        assert intent == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("what should I do next?", "explicit_proactive_intent"),
        ("lanjut dong", "explicit_proactive_intent"),
        ("next step please", "explicit_proactive_intent"),
        ("bantu saya bikin checklist langkah-langkahnya", "explicit_proactive_intent"),
        ("can you give me more ideas?", "explicit_proactive_intent"),
        ("help me navigate this feature", "explicit_proactive_intent"),
        ("can you repeat the last answer?", "clarification"),
        ("what else can I ask you?", "explicit_proactive_intent"),
    ],
)
def test_explicit_proactive_matrix(text, expected):
    res = detect_natural_intent(text)
    assert res.get("intent") == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("hi, can you help me with my Joget process?", "not_only_greeting"),
        ("ok lanjut", {"affirmative", "explicit_proactive_intent"}),
        ("ok, that makes sense", "affirmative"),
        ("can you explain it in simpler words?", "clarification"),
        ("this answer is not helpful", "feedback"),
        ("thanks, that was very clear", {"feedback", "greeting_closing"}),
        ("yo", "greeting_closing"),
        ("bro", {"small_talk", "greeting_closing"}),
    ],
)
def test_cross_intent_matrix(text, expected):
    res = detect_natural_intent(text)
    intent = res.get("intent")
    if expected == "not_only_greeting":
        assert intent != "greeting_closing"
    elif isinstance(expected, set):
        assert intent in expected
    else:
        assert intent == expected
