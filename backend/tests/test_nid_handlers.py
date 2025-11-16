import json

from src.natural_intent import detect_natural_intent
from src.nid_handlers import store_pending_contact, get_and_clear_pending_contact, persist_contact


class FakeGraph:
    def __init__(self):
        self.sessions = {}
        self.saved_responses = []

    def query(self, cypher: str, params: dict):
        sid = params.get("sessionId")
        # Store pending
        if "SET s.pending_contact" in cypher:
            pending = params.get("pending")
            self.sessions.setdefault(sid, {})["pending_contact"] = pending
            return [{"pending": pending}]

        # Read pending
        if "RETURN s.pending_contact AS pending" in cypher and "MERGE (s:Session" not in cypher:
            pending = self.sessions.get(sid, {}).get("pending_contact")
            return [{"pending": pending}]

        # Clear pending
        if "REMOVE s.pending_contact" in cypher:
            if sid in self.sessions and "pending_contact" in self.sessions[sid]:
                del self.sessions[sid]["pending_contact"]
            return [{"cleared": True}]

        # Save Response (save_history_graph)
        if "CREATE (r:Response" in cypher:
            # record params for inspection
            self.saved_responses.append(params)
            return [{"id": "fake-response-id"}]

        return []


def test_contact_consent_flow_and_persist():
    graph = FakeGraph()
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
    assert resp_id == "fake-response-id"

    # 6) Check saved response trigger_meta contains our slots
    last = graph.saved_responses[-1]
    tm = last.get("trigger_meta")
    print(f"Saved response trigger_meta param: {tm}")
    assert tm is not None
    # trigger_meta is a JSON string
    parsed = json.loads(tm)
    assert parsed.get("slots", {}).get("email") == slots.get("email")
