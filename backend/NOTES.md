# Project Notes — llm-graph-builder (FastAPI backend)
<!-- cd C:\RnDGenAI\llm-graph-builder\backend\ -->
Purpose
-------
Lightweight reference for an agent (Copilot) to understand the project structure, major packages, core models, service boundaries, and external dependencies.

High-level architecture
-----------------------
- API layer: `score.py` (FastAPI) exposes endpoints for extracting graphs, uploading files, chat (RAG), post-processing and administrative actions.
- Orchestration / Processing: `src/main.py` contains orchestration helpers for creating source nodes, extracting chunks, creating embeddings, invoking LLM extraction, and coordinating DB saves.
- Graph Data Access: `src/graphDB_dataAccess.py` wraps Neo4j operations (node/relationship CRUD and admin tasks). `src/graph_query.py` provides custom queries used by the API.
- LLM & Embeddings: `src/llm.py` and related modules handle interactions with LLMs and embedding models (via LangChain, OpenAI, VertexAI, etc.).
- Chunking & Indexing: `src/create_chunks.py`, vector index creation and embedding logic manage chunks and vector indexes saved to Neo4j.
- Post-processing & Analytics: `src/post_processing.py`, `src/communities.py`, `src/neighbours.py` provide graph enrichment, community detection and neighbour queries.
- Document sources: `src/document_sources/*` contains loaders for local files, GCS, S3, web pages, YouTube, and Wikipedia.
- Agents & orchestration: `src/agent/*` contains code for agent routing, evaluation, and orchestration.
- DB (SQL) & background: `src/db_psql/postgres.py` manages Postgres checks; background processing hooks and provisioning live in services and gea.

Core data models (logical)
--------------------------
- SourceNode (`src/entities/source_node.py`): metadata for a source (file/url), ingestion status, counters for chunks/entities/communities.
- Chunk node (managed in `create_chunks.py`): tokenized pieces of source content, embeddings and references to source.
- Entity node (created by LLM extraction): named entities or typed nodes with relationships to chunk nodes and other entities.
- Community node: grouping of related entities or chunks detected in post-processing.

Service boundaries
------------------
- FastAPI HTTP API (`score.py`) — handles request/response, validation, and delegates to sync/async workers.
- Graph DB (Neo4j) — persistent store for graph, vector storage (via Neo4j vector plugin) and search.
- LLM/Embedding services — external AI providers (OpenAI, Vertex AI, Gemini, etc.) invoked via `src/llm.py` and LangChain wrappers.
- Object storage & loaders — GCS/S3/local/YouTube/Wikipedia loaders for input content.
- Postgres — optional relational store used for other features or metadata checks.

External dependencies / integrations (observed)
--------------------------------------------
- Neo4j (bolt URI usage; `langchain_neo4j` integration)
- OpenAI (LLM + embeddings) — keys in `.env`
- LangChain and LangChain community loaders (Wikipedia, WebBaseLoader, etc.)
- Google Cloud Storage (GCS) — optional via `document_sources/gcs_bucket.py`
- AWS S3 — optional via `document_sources/s3_bucket.py`
- YouTube transcripts
- Postgres (psycopg or SQLAlchemy – check `requirements.txt`)
- FastAPI, Starlette middlewares and SSE (`sse_starlette`)

Key files and responsibilities (concise)
--------------------------------------
- `score.py` — FastAPI app, routes, request handling, endpoint wiring, middleware and logging; primary entrypoint for HTTP API.
- `src/main.py` — Core orchestration for ingestion pipelines: create source nodes, read files, chunking, calling LLM extraction, saving nodes/relationships.
- `src/graphDB_dataAccess.py` — Low-level Neo4j access layer: CRUD for source/chunk/entity nodes and admin/utility queries.
- `src/graph_query.py` — Higher-level Neo4j queries used by API endpoints (query execution, results shaping, fetch chunk text, visualization helper).
- `src/llm.py` — LLM and embedding client wrappers and model orchestration logic (LangChain + provider glue).
- `src/create_chunks.py` — Chunk creation, merging chunk uploads, and pre-processing content into chunk documents with tokenization and overlap.
- `src/chunkid_entities.py` — Helpers to get entities for given chunk ids and map chunk<->entity relationships for API consumers.
- `src/post_processing.py` — Post-processing tasks such as creating vector/text indexes, entity embeddings and schema consolidation.
- `src/communities.py` — Community detection / grouping logic on the graph.
- `src/neighbours.py` — Neighbor node search and related utilities.
- `src/make_relationships.py` — Utilities to merge relationships between chunks and entities or entity-entity links.
- `src/document_sources/*` — Various loaders: `local_file.py`, `gcs_bucket.py`, `s3_bucket.py`, `web_pages.py`, `youtube.py`, `wikipedia.py` each return content/pages used for chunking.
- `src/entities/source_node.py` — Source node model/DTO used to carry metadata into graph data access layer.
- `src/shared/*` — Utilities shared across the app (logging, constants, error types, schema extraction helpers and common functions).
- `src/agent/*` — Agent router and agent orchestration modules enabling agent-driven workflows and routing.
- `src/db_psql/postgres.py` — Postgres connectivity / health-checks used by the API.
- `Dockerfile`, `requirements.txt`, `.env` — Deployment and environment configuration. `.env` lists many LLM, Neo4j, GCS and AWS keys.

Quick run / developer notes
---------------------------
- The main HTTP entrypoint is `score.py` (FastAPI). Look for `uvicorn` run or Dockerfile to run the service.
- Neo4j must be available and configured in `.env` (NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD, NEO4J_DATABASE).
- Embedding/LLM calls rely on keys in `.env` (OPENAI_API_KEY, LLM_MODEL_CONFIG_*, EMBEDDING_MODEL, etc.).

Where to look first when changing behavior
-----------------------------------------
- For API changes: `score.py` and `src/api/*` routers.
- For extraction pipeline changes: `src/main.py`, `src/create_chunks.py`, and `src/llm.py`.
- For graph schema/Neo4j specifics: `src/graphDB_dataAccess.py` and `src/graph_query.py`.

Contact points for further automation
-----------------------------------
- Add tests for critical pipeline pieces: chunking, LLM mapping, and graph saving.
- Consider adding small unit tests for `src/shared` and `src/document_sources` loaders.

Last-updated: automated NOTES.md created by Copilot agent.

## In-depth analysis (requested)

1) Entry points and call paths (file:line anchors)

- HTTP API endpoints (FastAPI — `score.py`)
	- POST /url/scan -> `create_source_knowledge_graph_url` (score.py:157)
		- call path: score.py:157 create_source_knowledge_graph_url -> create_graph_database_connection(...) (score.py) -> depending on `source_type` calls into `src/main.py`:
			- S3: `create_source_node_graph_url_s3` (src/main.py:40) -> uses `graphDBdataAccess.create_source_node` (src/graphDB_dataAccess.py:41) to persist Document nodes.
			- GCS: `create_source_node_graph_url_gcs` (src/main.py:78) -> persists via graphDBdataAccess.create_source_node (src/graphDB_dataAccess.py:41).
			- Web URL: `create_source_node_graph_web_url` (src/main.py:117) -> persists via graphDBdataAccess.create_source_node (src/graphDB_dataAccess.py:41).
			- YouTube: `create_source_node_graph_url_youtube` (src/main.py:161) -> persists via graphDBdataAccess.create_source_node (src/graphDB_dataAccess.py:41).
			- Wikipedia: `create_source_node_graph_url_wikipedia` (src/main.py:210) -> persists via graphDBdataAccess.create_source_node (src/graphDB_dataAccess.py:41).

	- POST /extract -> `extract_knowledge_graph_from_file` (score.py:229)
		- call path: score.py:229 extract_knowledge_graph_from_file -> create_graph_database_connection(...) -> selects per-source async helper in `src/main.py`:
			- local file -> `extract_graph_from_file_local_file` (src/main.py:230) -> processing pipeline calls `processing_source` (src/main.py:297) ->
				- chunking: `create_chunk_vector_index` / `get_chunkId_chunkDoc_list` (src/main.py:513)
				- embeddings: `create_chunk_embeddings` (src/make_relationships.py:41)
				- LLM extraction: `get_graph_from_llm` (src/llm.py) — returns graph documents
				- save: `save_graphDocuments_in_neo4j` (src/main.py / src/graphDB_dataAccess.py)

			- s3/gcs/web/youtube/wikipedia -> `extract_graph_from_file_s3` (src/main.py:246) / `extract_graph_from_file_gcs` (src/main.py:288) / `extract_graph_from_web_page` (src/main.py:260) / `extract_graph_from_file_youtube` (src/main.py:269) / `extract_graph_from_file_Wikipedia` (src/main.py:279) -> all eventually call into the same processing pipeline functions: chunk creation, embedding, LLM extraction and graph writes (processing_source at src/main.py:297).

- Other important API entry points (score.py anchors)
	- /chat_bot -> `chat_bot` (score.py:451) -> builds Neo4jGraph or uses create_graph_database_connection -> calls `QA_RAG` (src/QA_integration.py) for RAG-style QA flows.
	- /upload -> `upload_large_file_into_chunks` (score.py:597) -> calls `upload_file` (src/main.py:623-ish) to save chunk parts and eventually merge via `merge_chunks_local` (src/main.py:604).
	- /post_processing -> `post_processing` (score.py:394) -> delegates to `update_graph`, `create_vector_fulltext_indexes`, `create_entity_embedding`, `graph_schema_consolidation` (various src/* modules).
	- SSE status feed /update_extract_status -> `update_extract_status` (score.py:657) -> polls `graphDb_data_Access.get_current_status_document_node` (src/graphDB_dataAccess.py).

Notes: the majority of business logic for ingestion/extraction lives in `src/main.py` (helpers & orchestration) and the graph writes/queries live in `src/graphDB_dataAccess.py` (see create_source_node at src/graphDB_dataAccess.py:41).

2) Settings: where loaded, precedence, and critical env vars

- How settings are loaded
	- `.env` is loaded explicitly in many modules via `from dotenv import load_dotenv` then `load_dotenv()` or `load_dotenv(override=True)` (examples: `src/main.py` at src/main.py:37 loads `load_dotenv()`; `score.py` calls `load_dotenv(override=True)` at score.py:51). Many other modules call `load_dotenv()` too (graphDB_dataAccess.py, QA_integration.py, ragas_eval.py, tests).
	- A central Pydantic-based settings object exists in `src/core/config.py` (class `Settings` at src/core/config.py:6). `get_settings()` returns a cached Settings instance and the SettingsConfigDict includes env_file=".env" which means Pydantic will also read `.env` in addition to environment variables.

- Config precedence summary (effective)
	1. Explicit environment variables set in the process environment (highest precedence).
	2. Values loaded into the environment by `load_dotenv()` (when called) from the repository `.env` file — note that `load_dotenv(override=True)` will overwrite existing env vars if present.
	3. Pydantic `BaseSettings` default values and the `.env` referenced by SettingsConfigDict (used by `src/core/config.py`).

	Practical effect: modules that call `os.getenv()` or `os.environ.get()` will read the current process environment (possibly populated by `load_dotenv()` earlier). Code that uses `get_settings()` will instantiate the Pydantic Settings object which also reads `.env` (but respects env vars already present). Because `score.py` invokes `load_dotenv(override=True)` at process start, `.env` will often be loaded early and available to other modules.

- Critical env vars (observed in `.env`) and their effects
	- NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD / NEO4J_DATABASE — Neo4j connection & target database. Changing these re-points the graph DB used by all graph operations.
	- OPENAI_API_KEY / LLM_MODEL_CONFIG_* / EMBEDDING_MODEL / OPENAI_EMBEDDING_MODEL — control which LLM and embedding backends are used (OpenAI, VertexAI, local). Missing keys will break LLM/embedding calls.
	- DATABASE_URL — Postgres registry used by `src/db_psql/postgres.py` and related services.
	- GCS_FILE_CACHE — toggles whether uploaded files are cached in GCS (affects upload/merge logic).
	- ENTITY_EMBEDDING / IS_EMBEDDING — toggles whether entity and chunk embeddings are created/used.
	- JOB_BACKEND / PROVISION_ASYNC — affect how provisioning/background jobs are scheduled (sync vs queue).
	- DEFAULT_DIFFBOT_CHAT_MODEL / GRAPH_CLEANUP_MODEL — defaults used by LLM orchestration flows.

3) Polished anchors (validated)

The following anchors were collected by scanning the repository and are useful when tracing the ingestion pipeline. They are intended to help you jump directly to key orchestration points.

- FastAPI / main HTTP entry (`score.py`):
	- POST /url/scan -> create_source_knowledge_graph_url (score.py: ~157)
	- POST /extract -> extract_knowledge_graph_from_file (score.py: ~229)
	- POST /upload -> upload_large_file_into_chunks (score.py: ~597)
	- POST /chat_bot -> chat_bot (score.py: ~451)
	- SSE / status -> update_extract_status (score.py: ~657)

- Orchestration (`src/main.py`):
	- create_source_node_graph_url_s3 (src/main.py: ~40)
	- create_source_node_graph_url_gcs (src/main.py: ~78)
	- create_source_node_graph_web_url (src/main.py: ~117)
	- create_source_node_graph_url_youtube (src/main.py: ~161)
	- create_source_node_graph_url_wikipedia (src/main.py: ~210)
	- extract_graph_from_file_local_file (src/main.py: ~230)
	- processing_source (src/main.py: ~297)
	- processing_chunks (async function referenced around src/main.py: ~470)
	- get_chunkId_chunkDoc_list (src/main.py: ~513)
	- upload_file / merge_chunks_local (src/main.py: ~604-627)

- Embedding & relationship helpers:
	- create_chunk_embeddings (src/make_relationships.py: ~41)
	- create_chunk_vector_index (src/make_relationships.py: ~158)

- Graph DB data access:
	- create_source_node (src/graphDB_dataAccess.py: ~41)
	- update_exception_db / update_source_node / get_current_status_document_node (src/graphDB_dataAccess.py)

Notes on accuracy: these anchors were collected by reading the repository files in this workspace; line offsets are approximate (shown with ~) but should be sufficiently precise to quickly locate the functions. If you want, I can update these to exact line numbers (I can re-scan and write precise file:line entries).

## Appendix — polish: extra analysis, call-paths, edge cases & quick remediations

Below are additional, non-destructive lines that expand the previous analysis with concrete call-path bullets, edge cases, and recommended quick fixes. These are appended only and do not modify earlier sections.

- Detailed domain provisioning call-path (compact)
	1. UI / Admin -> API (FastAPI) -> domain create endpoint -> service layer -> `create_domain_async` in `src/services/domain_service.py`.
	2. `create_domain_async` -> `tenant_service.find_or_create_tenant_for` (ensures tenant exists) -> `domain_repo.create` (insert Domain row) -> `domain_graph_repo.create_initial` (insert DomainGraph placeholder with idempotency key) -> `db.commit()`.
	3. After commit, if `cfg.PROVISION_ASYNC` true -> `_EXECUTOR.submit(_provision_job_wrapper, domain_id)` else call `_provision_job_wrapper(domain_id)` inline.
	4. `_provision_job_wrapper` creates a fresh `SessionLocal()` session, marks provisioning via `domain_graph_repo.mark_provisioning` and commits, then calls `provision_domain_graph(db, domain_id=domain_id)`.
	5. `provision_domain_graph` uses `_admin_driver()` to connect to Neo4j admin API, calls `_supports_multi_db()` to detect Enterprise support, constructs db name via `_make_db_name()`, issues `CREATE DATABASE` if supported, waits for online with `_wait_until_online()`, encrypts credentials and writes them into Postgres via `domain_graph_repo.save_credentials`, then `domain_graph_repo.mark_online`.

- Edge cases observed and how the code handles them
	- Race: worker starts before the registry commit is visible -> mitigated by a short retry in `provision_domain_graph` (loop retrying `domain_repo.get_by_id`). Still, increasing retries or using database advisory locks can make this more robust.
	- CREATE DATABASE latency/timeouts -> `provision_domain_graph` raises `GraphTimeout` after a 120s deadline and marks the DomainGraph as failed; consider configurable timeout and exponential backoff for very large clusters.
	- Shared admin credentials vs per-domain accounts -> current code reuses a shared user (safer in small deployments) but elevates blast radius; production recommendation: use scoped credentials or short-lived tokens.
	- Thread-safety: `_provision_job_wrapper` creates its own `SessionLocal()` to avoid sharing connections/transactions — correct pattern. Avoid passing SQLAlchemy sessions across threads.

- Quick remediations & checks to add (low-effort wins)
	- Add metrics/logging around provisioning duration and CREATE DATABASE attempts (count, duration, fail reason) in `graph_provisioner.provision_domain_graph`.
	- Make the CREATE DATABASE wait timeout configurable via settings (e.g., `cfg.NEO4J_DB_CREATE_TIMEOUT_SEC`) and document the default.
	- Surface `failReason` and last provisioning logs in the domain status API so operators can triage quickly.
	- Add a unit/integration test that mocks `_admin_driver` to simulate slow CREATE DATABASE responses and confirm `mark_failed` behavior.

- Tests & validation suggestions
	- Integration test: create a test Postgres DB, call `create_domain_async` with `cfg.PROVISION_ASYNC=False` and a mocked `provision_domain_graph` to assert that `domain_repo` and `domain_graph_repo` rows exist and committed before the provision call.
	- End-to-end test: with a test Neo4j instance (or dockerized Neo4j), run `provision_domain_graph` to validate multi-db creation, `_wait_until_online` behavior and `save_credentials` persistence.
	- Security test: verify `secret_enc` stored by `domain_graph_repo.save_credentials` decrypts correctly with `src.shared.crypto` and does not store plaintext.

- Small housekeeping observations
	- `src/db_psql/postgres.py` uses `expire_on_commit=False` on the session factory which helps keep objects usable after commit; that is helpful for background workflows but be mindful when re-loading state in new sessions.
	- Consider adding explicit docstrings to `domain_service.create_domain_async` summarizing the transaction/commit-before-enqueue requirement — it is a behaviour that future contributors must preserve.

---
Appendix added: non-destructive polish and recommended next steps. If you'd like, I can now replace approximate anchors with exact file:line numbers (finishing the anchor polish task) or add the provisioning flow Mermaid diagram.


