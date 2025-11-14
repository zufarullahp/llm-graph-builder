# src/proactive_entity_inspector.py
import logging
from typing import Dict, Any, List

from src.history_graph import _run_query


def _build_display_name(labels: List[str], props: Dict[str, Any]) -> str:
    """
    Build human-friendly display name similar to your retrieval Cypher:
      LabelWithout__Entity__:value
    where value is taken from id | name | title | description (first non-empty).
    """
    domain_labels = [l for l in labels if l != "__Entity__"]
    primary_label = domain_labels[0] if domain_labels else "__Entity__"

    value = (
        props.get("id")
        or props.get("name")
        or props.get("title")
        or props.get("description")
    )

    if not value:
        # reasonable fallbacks, in case schema varies
        for k in ["identifier", "code", "url"]:
            if k in props and props[k]:
                value = props[k]
                break

    if not value:
        value = "<unnamed>"

    return f"{primary_label}:{value}"


def _resolve_entity_nodes(graph, entity_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Resolve elementId-based entity_ids into full node structures.
    """
    if not entity_ids:
        return []

    rows = _run_query(
        graph,
        """
        UNWIND $ids AS id
        MATCH (e)
        WHERE elementId(e) = id
        RETURN
          elementId(e) AS id,
          labels(e) AS labels,
          properties(e) AS props
        """,
        {"ids": entity_ids},
        access="READ",
    )

    resolved = []
    for r in rows:
        labels = r["labels"] or []
        props = r["props"] or {}
        display = _build_display_name(labels, props)
        resolved.append(
            {
                "id": r["id"],
                "labels": labels,
                "props": props,
                "display": display,
            }
        )
    return resolved


def _resolve_relationships(graph, rel_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Resolve elementId-based relationship_ids into triples.
    """
    if not rel_ids:
        return []

    rows = _run_query(
        graph,
        """
        UNWIND $ids AS id
        MATCH (s)-[r]->(t)
        WHERE elementId(r) = id
        RETURN
          elementId(r) AS id,
          type(r) AS rel_type,
          elementId(s) AS start_id,
          elementId(t) AS end_id,
          labels(s) AS start_labels,
          properties(s) AS start_props,
          labels(t) AS end_labels,
          properties(t) AS end_props
        """,
        {"ids": rel_ids},
        access="READ",
    )

    rels = []
    for r in rows:
        s_display = _build_display_name(r["start_labels"], r["start_props"])
        t_display = _build_display_name(r["end_labels"], r["end_props"])
        rels.append(
            {
                "id": r["id"],
                "type": r["rel_type"],
                "start_id": r["start_id"],
                "end_id": r["end_id"],
                "start_labels": r["start_labels"],
                "end_labels": r["end_labels"],
                "start_display": s_display,
                "end_display": t_display,
            }
        )
    return rels


def inspect_entities_in_graph(
    graph,
    entities_dict: Dict[str, Any],
    nodedetails: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """
    Central Graph Entity Inspector.

    Input:
      entities_dict: result["entities"] from retrieval, e.g.
        {
          "entityids": [...],
          "relationshipids": [...]
        }

      nodedetails: result["nodedetails"] (optional, for chunk cooccurrence if needed)

    Output shape (fed to DPE & Composer):
      {
        "nodes": [ {id, labels, props, display}, ... ],
        "relationships": [
          {id, type, start_id, end_id, start_display, end_display}, ...
        ],
        "candidates": [
          {id, display, primary_label, salience},
          ...
        ],
      }
    """
    entity_ids: List[str] = (entities_dict or {}).get("entityids") or []
    rel_ids: List[str] = (entities_dict or {}).get("relationshipids") or []
    logging.debug(
        f"[Proactive][Inspector] start "
        f"entityids={len(entity_ids)} relationshipids={len(rel_ids)}"
    )

    try:
        nodes = _resolve_entity_nodes(graph, entity_ids)
        logging.debug(
            f"[Proactive][Inspector] resolved_nodes count={len(nodes)} "
            f"sample={[n['display'] for n in nodes[:3]]}"
        )
    except Exception as e:
        logging.error(f"[Inspector] Error resolving entity nodes: {e}")
        nodes = []

    try:
        rels = _resolve_relationships(graph, rel_ids)
        logging.debug(
            f"[Proactive][Inspector] resolved_relationships count={len(rels)} "
            f"sample={[r['type'] for r in rels[:3]]}"
        )
    except Exception as e:
        logging.error(f"[Inspector] Error resolving relationships: {e}")
        rels = []

    # Build candidate list for DPE/Composer: top few node entities.
    # We don't have per-entity salience, so we keep a flat salience = 1.0 for now.
    candidates = []
    for n in nodes:
        labels = n["labels"] or []
        domain_labels = [l for l in labels if l != "__Entity__"]
        primary_label = domain_labels[0] if domain_labels else "__Entity__"

        candidates.append(
            {
                "id": n["id"],
                "display": n["display"],
                "primary_label": primary_label,
                "salience": 1.0,  # equal for now; future: derive from usage frequency if needed
            }
        )

    return {
        "nodes": nodes,
        "relationships": rels,
        "candidates": candidates,
    }
