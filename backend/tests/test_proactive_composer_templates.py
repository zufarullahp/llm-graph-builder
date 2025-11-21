from src.proactive_composer import compose_followup_template


def test_composer_tip_every_3_turns_template():
    rule = {
        "id": "generic_every_3_turns",
        "template_key": "tip_every_3_turns_v1",
    }

    msg = compose_followup_template(rule, {}, {})
    assert msg is not None
    assert isinstance(msg, str)
    assert msg.strip() != ""
    assert "tip" in msg.lower() or "example" in msg.lower()
