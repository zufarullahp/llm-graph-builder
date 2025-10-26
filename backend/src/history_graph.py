# src/history_graph.py
import logging
from typing import List, Optional

def _run_query(graph, cypher: str, params: dict, access: str = "READ"):
    # Works with LangChain Neo4jGraph (has .query) or neo4j.Driver
    if hasattr(graph, "query"):
        return graph.query(cypher, params, access)
    from neo4j import Driver
    if isinstance(graph, Driver):
        with graph.session() as s:
            res = s.run(cypher, **params)
            return [r.data() for r in res]
    raise RuntimeError("Unsupported graph connection type")

def ensure_constraints(graph):
    cyphers = [
        "CREATE CONSTRAINT session_id IF NOT EXISTS FOR (s:Session) REQUIRE s.id IS UNIQUE",
        "CREATE CONSTRAINT response_id IF NOT EXISTS FOR (r:Response) REQUIRE r.id IS UNIQUE",
        "CREATE INDEX response_createdAt IF NOT EXISTS FOR (r:Response) ON (r.createdAt)"
    ]
    for c in cyphers:
        graph.query(c)

def clear_history_graph(graph, session_id: str) -> None:
    _run_query(graph, """
    MATCH (s:Session {id:$sessionId})-[:HAS_RESPONSE]->(r)
    DETACH DELETE r
    """, {"sessionId": session_id}, "WRITE")

def get_history_graph(graph, session_id: str, limit: int = 5):
    cypher = f"""
    MATCH (:Session {{id:$sessionId}})-[:LAST_RESPONSE]->(last)
    MATCH p=(start)-[:NEXT*0..{limit}]->(last)
    WHERE length(p)={limit} OR NOT exists {{ ()-[:NEXT]->(start) }}
    UNWIND nodes(p) AS r
    RETURN r.id AS id, r.input AS input, r.rephrasedQuestion AS rephrasedQuestion,
           r.output AS output, r.cypher AS cypher, r.createdAt AS createdAt,
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
) -> str:
    params = {
        "session_id": session_id,
        "source": source,
        "input": input_text,
        "rephrased": rephrased,
        "output": output_text,
        "ids": ids or [],
        "cypher": cypher,
    }

    res = graph.query(
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
          ids: $ids
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
        params,   # ← params dict, tidak ada argumen ketiga
    )
    return res[0]["id"] if res else ""