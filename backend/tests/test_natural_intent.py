import pytest

from src.natural_intent import detect_natural_intent


cases = [
    # 1. Contact Sharing (EN)
    ("This is my email: alice@example.com", "contact_sharing"),
    ("You can email me at bob@corp.id", "contact_sharing"),
    # 1. Contact Sharing (ID)
    ("Email saya: joko@dom.com", "contact_sharing"),

    # 2. Small Talk (EN/ID)
    ("Thanks!", "small_talk"),
    ("terima kasih", "small_talk"),

    # 3. Clarification
    ("What do you mean?", "clarification"),
    ("Jelaskan lagi", "clarification"),

    # 4. Task Meta
    ("Clear history", "task_meta"),
    ("hapus sesi", "task_meta"),

    # 5. Feedback
    ("That's wrong", "feedback"),
    ("jawabannya salah", "feedback"),

    # 6. Personal Context
    ("I'm working on an office assignment for a client called Pelni and we use Joget", "personal_context"),
    ("saya sedang mengerjakan proyek klien dan memakai versi lama joget", "personal_context"),

    # 7. Greeting / Closing
    ("Hi", "greeting_closing"),
    ("Sampai jumpa", "greeting_closing"),

    # 8. Non-Retrieval Information Inquiry
    ("How do I use this bot?", "non_retrieval_inquiry"),
    ("Bagaimana cara pakai bot ini?", "non_retrieval_inquiry"),

    # 9. Upload / Attachment
    ("Here's the file", "upload_attachment"),
    ("tolong analisa file ini", "upload_attachment"),

    # 10. Explicit Proactive Intent
    ("What's next?", "explicit_proactive_intent"),
    ("lanjut gimana", "explicit_proactive_intent"),

    # 11. No-Content / Empty
    ("   ", "no_content"),
]


@pytest.mark.parametrize("text,expected", cases)
def test_detect_intent_basic(text, expected):
    r = detect_natural_intent(text)
    assert r["intent"] == expected, f"text={text} got={r}"


def test_detect_email_slot():
    r = detect_natural_intent("Contact: anna+1@example.co.uk please")
    assert r["intent"] == "contact_sharing"
    assert "email" in r["slots"] and r["slots"]["email"].endswith("example.co.uk")
