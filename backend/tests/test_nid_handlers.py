import json

from src.natural_intent import detect_natural_intent
from src.nid_handlers import store_pending_contact, get_and_clear_pending_contact, persist_contact


def test_contact_consent_flow_and_persist(fake_graph):
    graph = fake_graph
    session_id = "s1"

    # 1) User provides contact
    text = "Contact: anna+1@example.co.uk please"
    nid = detect_natural_intent(text)
    print(f"Detected NID: {nid}")
    assert nid["intent"] == "contact_sharing"
    slots = nid["slots"]
    assert "email" in slots

    # 2) Store pending contact
    store_pending_contact(graph, session_id, slots)
    pending = graph.sessions.get(session_id, {}).get("pending_contact")
    print(f"Pending stored (raw): {pending}")
    assert pending is not None

    # 3) User affirms
    nid_yes = detect_natural_intent("Yes")
    print(f"Detected NID for 'Yes': {nid_yes}")
    assert nid_yes["intent"] == "affirmative"

    # 4) Handler reads and clears pending
    p = get_and_clear_pending_contact(graph, session_id)
    print(f"Retrieved pending (parsed): {p}")
    assert p is not None and p.get("email") == slots.get("email")

    # 5) Persist contact
    resp_id = persist_contact(graph, session_id, p)
    print(f"Persisted response id: {resp_id}")
    # Accept any non-empty id from the fake graph
    assert resp_id

    # 6) Check saved response trigger_meta contains our slots
    last = graph.saved_responses[-1]
    tm = last.get("trigger_meta")
    print(f"Saved response trigger_meta param: {tm}")
    assert tm is not None
    # trigger_meta is a JSON string
    parsed = json.loads(tm)
    assert parsed.get("slots", {}).get("email") == slots.get("email")
