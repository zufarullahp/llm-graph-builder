# Migration Plan — Transition from Local Storage to Uploadcare

### 1. Overview

Goal

- Replace local filesystem storage of uploaded files (chunk_dir / merged_dir) with Uploadcare-hosted files, keeping the system stable and reversible.
- Use the `UPLOADCARE_ENABLED` feature flag to toggle behavior: when false, system uses existing local storage; when true, the system uses Uploadcare UUIDs and APIs.
- Ensure uploads, downloads, and deletions remain verifiable and recoverable during and after migration.

References

- This plan complements the design and REST contract captured in `SYSTEM_NOTE.md`.
- The canonical Uploadcare integration reference is the Next.js repository NOTE: `../ai-chatbot-diditz/NOTE.md` (see "Related Repository Notes" in `SYSTEM_NOTE.md`).

---

### 2. Safety and Rollback Strategy

- Dual compatibility: Maintain both local and Uploadcare code-paths until migration validation completes.
- Feature flag / rollout:
  - Default: `UPLOADCARE_ENABLED=false` in all environments until testing is finished.
  - Rollout order: local dev → CI/integration → staging → canary/production.
- Automatic fallback:
  - Implement safe fallbacks when Uploadcare requests fail (429 / 5xx). On transient failure, retry with backoff; after a configurable threshold, fall back to writing locally and log an alert.
- Preserve existing behavior: If `UPLOADCARE_ENABLED=false`, preserve all current local upload, merge, extract and delete semantics exactly as today.
- Backups & archive: Do not delete or irrevocably modify local merged files until the migration is validated and a separate archival policy is applied.

---

### 3. Data Integrity and Compatibility

- Node schema changes (Neo4j):
  - Add new fields to Source/Document nodes: `file_storage_type` (enum/string) and `file_storage_id` (string).
    - Example values: `file_storage_type: "local"`, `file_storage_id: "/data/merged/foo.pdf"` (legacy) or `file_storage_type: "uploadcare"`, `file_storage_id: "2c9bd4ab-..."`.
  - Optionally add `file_size` and `file_checksum` (MD5/SHA256) to help verify parity.
- Handling existing nodes:
  - Preserve current `local` paths in `file_storage_id` for all existing Source/Document nodes.
  - Do not overwrite existing nodes during the initial migration phases.
- Runtime loader behavior:
  - If `file_storage_type == "local"` → read from local disk as today.
  - If `file_storage_type == "uploadcare"` → use the Uploadcare helper to `download_file()` (stream or temp file) for ingestion.
- Optional: bulk migration script (one-time)
  - Purpose: re-upload legacy local files to Uploadcare and patch Neo4j nodes to set `file_storage_type: "uploadcare"` and `file_storage_id: <UUID>`.
  - Requirements: run in a controlled environment, verify checksums after upload, log successes/failures, and rate-limit requests.
  - This script is optional and should be run only after Phase 3 verification completes.

---

### 4. Implementation Phases

Phase 1 — Add Uploadcare helper (no production change)

- Create `backend/src/storage/uploadcare.py` with stable, testable function signatures and clear docstrings:
  - `upload_chunk(session_id, part_bytes, part_number) -> {ok, part_number}` (stub)
  - `finalize_upload(session_id) -> {file_id: UUID, cdn_url}`
  - `download_file(file_id) -> BytesIO / stream` (or save to temp file path)
  - `delete_file(file_id) -> bool`
- Add configuration variables (no-op when `UPLOADCARE_ENABLED=false`):
  - `UPLOADCARE_ENABLED`, `UPLOAD_CARE_SECRET_KEY`, `UPLOAD_CARE_PUBLIC_KEY`, `UPLOADCARE_API_BASE_URL`.
- Write unit tests for the helper (mocking Uploadcare responses). Keep `UPLOADCARE_ENABLED=false` in deployments.

Phase 2 — Dual-write (verification stage)

- Enable dual-write in non-production (dev/staging) or opt-in environments:
  - When an upload occurs, persist locally as today and also create/upload in Uploadcare.
  - Record both identifiers in Neo4j: keep `file_storage_type: "local"` as primary initially and store Uploadcare UUID in a provisional field like `file_storage_candidate_id` or log entry for verification.
- Verification:
  - Compare file sizes and checksums (MD5/SHA256) between local and Uploadcare copies.
  - Collect and review parity metrics. Resolve any mismatch patterns.
- Logging & metric collection:
  - Log Uploadcare upload latency, success/failure, and the returned UUID.
  - Emit a metric for parity verification (pass/fail).

Phase 3 — UUID-first operation

- Flip behavior to UUID-first when confident (start in staging, then production):
  - Set `UPLOADCARE_ENABLED=true` in target environment(s).
  - On new uploads, write only to Uploadcare. Persist `file_storage_type: "uploadcare"` and `file_storage_id: <UUID>` to Neo4j. Optionally store `file_size`/`checksum`.
  - Update downstream loaders to prefer Uploadcare downloads for `file_storage_type == "uploadcare"`.
  - Keep read-only compatibility for legacy `file_storage_type == "local"` nodes.

Phase 4 — Deprecate local storage

- After a stabilization period and validation:
  - Stop writing to local `chunk_dir`/`merged_dir` entirely.
  - Optionally run the one-time migration script to re-upload legacy local files to Uploadcare (see Section 3) or archive local files to cold storage for retention.
  - Implement scheduled cleanup jobs to remove archived local files only after backups and migration verification are complete.
- Maintain compatibility code to read legacy `local` nodes until a final migration/cleanup completes.

---

### 5. Testing and Monitoring

Unit Tests

- Mock Uploadcare API responses and test Uploadcare helper methods for success and failure (including 429 handling and retry/backoff).
- Test metadata writing: validate Neo4j node fields updated correctly for both modes.

Integration Tests

- Simulate multi-chunk upload→finalize flow to ensure the backend persists Uploadcare UUID and that `download_file()` returns identical bytes.
- Test delete operations: ensure `delete_file()` removes Uploadcare CDN copy and that Neo4j metadata is updated/cleared as expected.

Staging Tests

- Run dual-write parity checks on representative files.
- Validate end-to-end flows (upload → extract → graph persistence) using Uploadcare downloads in staging.

Monitoring & Metrics

- Track Uploadcare-specific metrics:
  - Upload success rate
  - Upload latency distribution
  - API error rates (4xx/5xx)
  - Parity check pass rate (Uploadcare vs local checksum)
- Dashboard ideas:
  - Total `file_storage_type=="uploadcare"` vs `local`
  - Number of files successfully migrated
- Alerts:
  - High error-rate alert on Uploadcare uploads or high fallback-to-local events.

---

### 6. Security and Configuration

Environment variables (required):

- `UPLOADCARE_ENABLED` — boolean toggle.
- `UPLOAD_CARE_SECRET_KEY` — server-side secret key (do not commit to repo).
- `UPLOAD_CARE_PUBLIC_KEY` — client-side public key (if integrating client uploads directly in a UI repo).
- `UPLOADCARE_API_BASE_URL` — base endpoint (default Uploadcare API endpoint).

Security best practices

- Never commit API secrets to source control; use secret stores or CI/CD secret injection.
- Do not log raw Uploadcare secret keys or private URLs.
- Use minimal privileges for any service account; rotate keys periodically.
- Implement exponential backoff and circuit-breaker style controls when calling Uploadcare.

---

### 7. Rollback Procedure

- Quick rollback:
  - Set `UPLOADCARE_ENABLED=false` in the environment and restart the backend services (or roll deployment).
  - The system will resume local upload/read/delete behavior immediately.
- Data recovery:
  - Files already uploaded to Uploadcare remain accessible via CDN using their UUIDs.
  - If needed, download from Uploadcare and re-ingest or re-persist locally using the optional migration script.
- Handling long outages:
  - If Uploadcare experiences prolonged downtime, temporarily route uploads to local storage and mark uploads as pending for later reconciliation.

---

### 8. Acceptance Criteria

To move between phases and ultimately finalize the migration the following must be true:

- No loss of existing local data (local files are preserved until explicitly archived or deleted under an approved process).
- Uploadcare UUIDs are stored consistently in Neo4j (`file_storage_type="uploadcare"` and `file_storage_id=<UUID>` for new uploads).
- End-to-end tests (upload → extract → delete) pass in both modes (`UPLOADCARE_ENABLED=true` and `false`).
- Parity verification has been performed for a representative sample of files (checksums match or discrepancies are understood and resolved).
- Monitoring in production shows acceptable Uploadcare upload success rate and latency; no elevated fallback-to-local rate persists after rollout.

---

### Next steps / Runbook

- Create the `backend/src/storage/uploadcare.py` helper and unit tests (Phase 1).
- Run dual-write verification in staging (Phase 2).
- Flip `UPLOADCARE_ENABLED=true` in a controlled production rollout once staging acceptance is achieved (Phase 3).
- Optionally run the one-time migration script and archive local files (Phase 4).

For implementation details and the exact Uploadcare REST contract, see `SYSTEM_NOTE.md` and the Uploadcare canonical NOTE at `../ai-chatbot-diditz/NOTE.md`.

---

Document created for backend maintainers and migration implementers. Do not modify application logic until the helper and tests are in place.
