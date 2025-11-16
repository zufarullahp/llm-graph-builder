import json


import json


class FakeGraph:
    """A minimal fake graph usable by tests.

    Supports a subset of query patterns used by the test-suite:
      - pending contact set/read/clear
      - save_history_graph Response creation
      - RuleInstance create / list / update
      - set Session.email
      - create Job stub
      - lookup last Response by input/output/source
    """

    def __init__(self):
        self.sessions = {}
        self.saved_responses = []
        self.rule_instances = []
        self.jobs = []
        self._ri_seq = 0
        self._resp_seq = 0

    def query(self, cypher: str, params: dict):
        sid = params.get("sessionId") or params.get("session_id")

        # Pending contact operations
        if "SET s.pending_contact" in cypher:
            pending = params.get("pending")
            self.sessions.setdefault(sid, {})["pending_contact"] = pending
            return [{"pending": pending}]

        if "RETURN s.pending_contact AS pending" in cypher and "MERGE (s:Session" not in cypher:
            pending = self.sessions.get(sid, {}).get("pending_contact")
            return [{"pending": pending}]

        if "REMOVE s.pending_contact" in cypher:
            if sid in self.sessions and "pending_contact" in self.sessions[sid]:
                del self.sessions[sid]["pending_contact"]
            return [{"cleared": True}]

        # Save Response (save_history_graph)
        if "CREATE (r:Response" in cypher:
            self._resp_seq += 1
            rid = f"resp-{self._resp_seq}"
            self.saved_responses.append({
                "id": rid,
                "sessionId": params.get("session_id"),
                "input": params.get("input"),
                "output": params.get("output"),
                "source": params.get("source"),
                "trigger_meta": params.get("trigger_meta"),
            })
            return [{"id": rid}]

        # RuleInstance creation
        if "CREATE (ri:RuleInstance" in cypher:
            self._ri_seq += 1
            ri_id = f"ri-{self._ri_seq}"
            meta = params.get("meta") or "{}"
            try:
                meta_parsed = json.loads(meta) if isinstance(meta, str) else meta
            except Exception:
                meta_parsed = {"raw": meta}
            ri = {
                "id": ri_id,
                "rule_id": params.get("ruleId"),
                "status": params.get("status"),
                "asked_at_turn": params.get("askedAtTurn"),
                "metadata": meta_parsed,
            }
            self.rule_instances.append(ri)
            return [{"id": ri_id}]

        # Expire sibling rule instances (used by proactive_actions cleanup)
        if "SET ri.status = 'EXPIRED'" in cypher and "ri.id <> $currentId" in cypher:
            expired = 0
            meta = params.get("meta")
            try:
                meta_parsed = json.loads(meta) if isinstance(meta, str) else meta
            except Exception:
                meta_parsed = {"raw": meta}
            # debug
            print(f"FakeGraph: expire siblings called with params={params}")
            for ri in self.rule_instances:
                if ri.get("rule_id") == params.get("ruleId") and ri.get("status") == "WAITING" and ri.get("id") != params.get("currentId"):
                    ri["status"] = "EXPIRED"
                    ri["completed_at_turn"] = params.get("currentTurn")
                    ri["metadata"] = meta_parsed
                    expired += 1
            return [{"expired_count": expired}]

        # Query active rule instances (optionally filtered by ruleId)
        # Match queries that list RuleInstances. Accept variations like (ri) or (ri:RuleInstance)
        if "MATCH (s:Session" in cypher and "HAS_RULE_INSTANCE" in cypher:
            # debug hook: indicate we received a match/list query
            # print statement helps during test debugging
            # print(f"FakeGraph: MATCH query received params={params}")
            rows = []
            requested_rule = params.get("ruleId")
            for ri in self.rule_instances:
                if ri.get("status") in ("WAITING", "PENDING"):
                    if requested_rule and ri.get("rule_id") != requested_rule:
                        continue
                    rows.append({
                        "id": ri["id"],
                        "rule_id": ri["rule_id"],
                        "status": ri["status"],
                        "asked_at_turn": ri.get("asked_at_turn"),
                        "metadata": json.dumps(ri.get("metadata") or {}),
                        "asked_at_ts": None,
                    })
            return rows

        # Update rule instance status
        if "MATCH (ri:RuleInstance {id:$id}) SET ri.status=$status" in cypher:
            rid = params.get("id")
            for ri in self.rule_instances:
                if ri["id"] == rid:
                    ri["status"] = params.get("status")
                    meta = params.get("meta")
                    try:
                        ri["metadata"] = json.loads(meta) if isinstance(meta, str) else meta
                    except Exception:
                        ri["metadata"] = {"raw": meta}
                    return [{"id": rid}]
            return []

        # Expire sibling rule instances (used by proactive_actions cleanup)
        if "SET ri.status = 'EXPIRED'" in cypher and "ri.id <> $currentId" in cypher:
            expired = 0
            meta = params.get("meta")
            try:
                meta_parsed = json.loads(meta) if isinstance(meta, str) else meta
            except Exception:
                meta_parsed = {"raw": meta}
            # debug
            print(f"FakeGraph: expire siblings called with params={params}")
            for ri in self.rule_instances:
                if ri.get("rule_id") == params.get("ruleId") and ri.get("status") == "WAITING" and ri.get("id") != params.get("currentId"):
                    ri["status"] = "EXPIRED"
                    ri["completed_at_turn"] = params.get("currentTurn")
                    ri["metadata"] = meta_parsed
                    expired += 1
            return [{"expired_count": expired}]

        # Set session email
        if "SET s.email" in cypher:
            email = params.get("email")
            self.sessions.setdefault(sid, {})["email"] = email
            return [{"sid": "session-el"}]

        # Create Job stub
        if "CREATE (j:Job" in cypher:
            job_id = f"job-{len(self.jobs)+1}"
            self.jobs.append({"id": job_id, "payload": params.get("payload")})
            return [{"id": job_id}]

        # Lookup last response by input/output/source (fallback in nid_handlers.persist_contact)
        if "WHERE r.input=$input AND r.output=$output AND r.source=$source" in cypher:
            input_v = params.get("input")
            output_v = params.get("output")
            source_v = params.get("source")
            for r in reversed(self.saved_responses):
                if r.get("input") == input_v and r.get("output") == output_v and r.get("source") == source_v:
                    return [{"id": r.get("id")}]
            return []

        return []
