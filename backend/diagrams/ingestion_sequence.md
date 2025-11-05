```markdown
# Ingestion sequence — upload → chunking → embedding → LLM → Neo4j

This sequence diagram shows the high-level call flow for ingesting a document (via upload or URL scan) through chunking, embedding, LLM extraction, and saving to Neo4j.

```mermaid
sequenceDiagram
    participant Client
    participant API as score.py
    participant Orch as src/main.py
    participant Chunk as src/create_chunks.py
    participant MR as src/make_relationships.py
    participant LLM as src/llm.py
    participant Graph as src/graphDB_dataAccess.py

    Client->>API: POST /upload or POST /url/scan
    API->>Orch: create_source_node_graph_* / extract_knowledge_graph_from_file
    Orch->>Chunk: call chunk creation (create_chunks.py)
    Chunk-->>Orch: return chunk list (chunkId_chunkDoc_list)
    Orch->>MR: create_chunk_embeddings(chunk list)
    MR->>LLM: (optional) call get_graph_from_llm or embeddings API
    LLM-->>MR: graph documents / extracted entities
    MR->>Graph: save chunks, embeddings, relationships (create_chunk_vector_index, relationship merges)
    Graph-->>API: ack / status (node created / ingestion queued / ingestion complete)

    Note over API,Graph: status updates are available via SSE / polling endpoints (update_extract_status)

```

Mapping to files (quick):
- API endpoints: `score.py` (see create_source_knowledge_graph_url, extract_knowledge_graph_from_file, upload_large_file_into_chunks)
- Orchestration: `src/main.py` (processing_source, processing_chunks, upload_file/merge_chunks_local)
- Chunk creation: `src/create_chunks.py`
- Embeddings & relationships: `src/make_relationships.py` (create_chunk_embeddings, create_chunk_vector_index)
- LLM / extraction: `src/llm.py` (get_graph_from_llm and related helpers)
- Graph writes: `src/graphDB_dataAccess.py` (create_source_node and other persistence functions)

```
