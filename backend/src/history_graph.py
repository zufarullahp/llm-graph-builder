# src/history_graph.py
import logging
import json
from typing import List, Optional


def _run_query(graph, cypher: str, params: dict, access: str = "READ"):
    """
    Run a Cypher query against either:
    - LangChain-style Neo4jGraph (has .query(cypher, params))
    - neo4j.Driver from official driver

    `access` is only used to choose READ/WRITE mode for the low-level driver.
    """
    # Case 1: LangChain / Neo4jGraph style wrapper
    if hasattr(graph, "query"):
        # Most wrappers expect (cypher, params) and handle routing internally
        return graph.query(cypher, params)

    # Case 2: Native neo4j.Driver
    try:
        from neo4j import Driver
    except ImportError:
        Driver = None

    if Driver is not None and isinstance(graph, Driver):
        mode = "WRITE" if access == "WRITE" else "READ"
        with graph.session(default_access_mode=mode) as session:
            result = session.run(cypher, **params)
            return [record.data() for record in result]

    raise RuntimeError("Unsupported graph connection type for _run_query")


def ensure_constraints(graph):
    cyphers = [
        "CREATE CONSTRAINT session_id IF NOT EXISTS FOR (s:Session) REQUIRE s.id IS UNIQUE",
        "CREATE CONSTRAINT response_id IF NOT EXISTS FOR (r:Response) REQUIRE r.id IS UNIQUE",
        "CREATE INDEX response_createdAt IF NOT EXISTS FOR (r:Response) ON (r.createdAt)"
    ]
    for c in cyphers:
        _run_query(graph, c, {}, access="WRITE")


def clear_history_graph(graph, session_id: str) -> None:
    _run_query(
        graph,
        """
        MATCH (s:Session {id:$sessionId})-[:HAS_RESPONSE]->(r)
        DETACH DELETE r
        """,
        {"sessionId": session_id},
        "WRITE",
    )


def get_history_graph(graph, session_id: str, limit: int = 5):
    """
    Return last `limit` Response nodes (following NEXT chain to LAST_RESPONSE),
    including any CONTEXT elementIds.
    """
    cypher = f"""
    MATCH (:Session {{id:$sessionId}})-[:LAST_RESPONSE]->(last)
    MATCH p=(start)-[:NEXT*0..{limit}]->(last)
    WHERE length(p) = {limit} OR NOT EXISTS {{ ()-[:NEXT]->(start) }}
    WITH nodes(p) AS ns
    UNWIND ns AS r
    RETURN
        r.id AS id,
        r.input AS input,
        r.rephrasedQuestion AS rephrasedQuestion,
        r.output AS output,
        r.cypher AS cypher,
        r.createdAt AS createdAt,
        r.type AS type,
        r.proactiveReason AS proactiveReason,
        [ (r)-[:CONTEXT]->(n) | elementId(n) ] AS context
    """
    return _run_query(graph, cypher, {"sessionId": session_id}, "READ")


def save_history_graph(
    graph,
    session_id: str,
    source: str,
    input_text: str,
    rephrased: str | None,
    output_text: str,
    ids: list[str] | None,
    cypher: str | None = None,
    response_type: str = "answer",
    proactive_reason: str | None = None,
    trigger_meta: dict | None = None,
) -> str:
    """
    Persist one turn in the history graph as a Response node.

    response_type: "answer" | "followup" | etc
    proactive_reason: short string, e.g. "first_message_welcome", "clarify_entity"
    trigger_meta: arbitrary JSON-ish dict (for telemetry) -> stored as JSON string
    """
    # 🔑 Penting: serialize trigger_meta ke JSON string supaya tidak Map{} di Neo4j
    trigger_meta_str = json.dumps(trigger_meta or {})

    params = {
        "session_id": session_id,
        "source": source,
        "input": input_text,
        "rephrased": rephrased,
        "output": output_text,
        "ids": ids or [],
        "cypher": cypher,
        "response_type": response_type,
        "proactive_reason": proactive_reason,
        "trigger_meta": trigger_meta_str,
    }

    res = _run_query(
        graph,
        """
        MERGE (s:Session { id: $session_id })

        CREATE (r:Response {
          id: randomUuid(),
          createdAt: datetime(),
          source: $source,
          input: $input,
          output: $output,
          rephrasedQuestion: $rephrased,
          cypher: $cypher,
          ids: $ids,
          type: $response_type,
          proactiveReason: $proactive_reason,
          triggerMeta: $trigger_meta
        })
        MERGE (s)-[:HAS_RESPONSE]->(r)

        WITH s, r
        OPTIONAL MATCH (s)-[lr:LAST_RESPONSE]->(last)
        DELETE lr

        FOREACH (_ IN CASE WHEN last IS NULL THEN [] ELSE [1] END |
          MERGE (last)-[:NEXT]->(r)
        )

        MERGE (s)-[:LAST_RESPONSE]->(r)

        WITH r, $ids AS ids
        UNWIND ids AS id
        MATCH (ctx) WHERE elementId(ctx) = id
        MERGE (r)-[:CONTEXT]->(ctx)

        RETURN r.id AS id
        """,
        params,
        access="WRITE",
    )
    return res[0]["id"] if res else ""
