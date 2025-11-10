# Phase 2.5 Migration Brief — Candidate UUID Persistence & Checksum Parity

**Role:** Backend engineer continuing the Uploadcare migration (Phase 2.5 from `MIGRATION_UPLOADCARE_PLAN.md`)

---

## 🌟 Goal

Extend the existing dual-write implementation to **persist Uploadcare candidate UUIDs** and **add checksum-based parity verification**.
This phase provides measurable data integrity assurance before switching to full Uploadcare operation in Phase 3.

All modifications must remain **backward-compatible** and **non-disruptive** when `UPLOADCARE_MODE="local"`.

---

## 🗭️ Context

* Phase 2 (Dual-Write + Parity stub) is complete and passing tests.
* Uploadcare helper, environment flags, and unit tests are stable.
* Local storage remains canonical.
* `SourceNode` already includes optional `file_storage_type`, `file_storage_id`, and `file_checksum` fields.
* Neo4j writes are functional through `graphDBdataAccess`.

---

## ⚙️ Tasks

### **1️⃣ Persist Candidate UUID to Neo4j**

* In `upload_file()` (inside the guarded dual-write block):

  * After successful Uploadcare upload, attach the returned UUID to the in-memory `source_node`.

    ```python
    source_node.file_storage_candidate_id = meta.file_id
    ```
  * Extend the call to `graphDBdataAccess.create_source_node(...)` (or update logic) to include that field.
  * This field is **non-authoritative**; the backend still treats local storage as the primary source.

* **Failure behavior:**

  * If Uploadcare upload fails, log a warning and skip persistence (do not write partial data).
  * Do not delete local files or modify existing node schema.

* Add explicit comment:

  > “Phase 2.5 — Candidate UUIDs are for parity analysis only; local file remains canonical.”

---

### **2️⃣ Add Checksum Support**

* Implement a helper in `uploadcare.py`:

  ```python
  import hashlib

  def calculate_checksum(path: str) -> str:
      with open(path, "rb") as f:
          return hashlib.sha256(f.read()).hexdigest()
  ```
* Extend `UploadcareFileMeta` dataclass with an optional `file_checksum` field.
* When performing the local merge, compute the local checksum and assign:

  ```python
  local_checksum = uploadcare.calculate_checksum(local_path)
  source_node.file_checksum = local_checksum
  ```
* Extend `compare_file_integrity(local_path, uploadcare_meta)` to verify both size and checksum when available.

---

### **3️⃣ Enhance Logging and Metrics**

* **On success:**

  ```text
  Dual-write: UUID persisted (uuid-123) and checksums match
  ```
* **On mismatch:**

  ```text
  Dual-write: checksum mismatch (local=abc123 vs remote=def456)
  ```
* Keep failures non-blocking but emit `logger.warning` and increment an optional metric counter (placeholder for later Prometheus integration).

---

### **4️⃣ Extend Tests (backend/tests/test_uploadcare.py)**

Add new unit tests:

| Scenario                      | Expected                                                                     |
| ----------------------------- | ---------------------------------------------------------------------------- |
| **UUID persisted on success** | `graphDBdataAccess.create_source_node` receives `file_storage_candidate_id`. |
| **Checksum parity match**     | Returns True, logs info.                                                     |
| **Checksum mismatch**         | Logs warning, continues.                                                     |
| **Uploadcare 5xx**            | UUID field not written, local flow proceeds.                                 |

Use `unittest.mock.patch` for both Uploadcare and Neo4j calls.
No real network or DB calls.

---

### **5️⃣ Environment Variables & Flags**

No new required flags.
Existing vars:

* `UPLOADCARE_ENABLED`
* `UPLOADCARE_MODE` (`local | dual | uploadcare`)

---

### **6️⃣ Documentation Updates**

* Update docstrings in `upload_file()` and `uploadcare.py` to mention:
  “Phase 2.5 adds candidate UUID persistence and checksum parity verification before UUID-first transition.”
* Reference:

  * `/backend/docs/MIGRATION_UPLOADCARE_PLAN.md`
  * `SYSTEM_NOTE.md` → “Related Repository Notes”
  * Next.js `NOTE.md` for UUID/CDN contract reference.
* Append `UPLOADCARE_MODE` and checksum notes to `.env.example` if not yet present.

---

### **7️⃣ Deliverables**

🔁 Updated:

* `main.py` — UUID persistence + checksum verification.
* `uploadcare.py` — checksum helper + updated meta class + extended compare logic.
* `test_uploadcare.py` — new tests for UUID and checksum flows.
* Optional: updated `example.env` and docstrings.

🧩 Optional:

* Introduce metric counters (stub only).
* Generate parity report log summary during tests.

---

## ✅ Expected Outcome

* Uploadcare candidate UUIDs persisted safely in Neo4j for parity tracking.
* Size + checksum parity verified and logged in dual-write mode.
* Local storage remains authoritative and rollback trivial.
* All unit tests pass without network or DB dependencies.
* Backend fully ready for Phase 3 (UUID-first operation mode).

---

## ⚠️ Constraints

* ❌ Do not replace existing local storage paths.
* ❌ Do not remove dual-write logging or parity fallbacks.
* ❌ No schema migrations that break older nodes.
* ❌ Do not enable UUID-only mode yet —that’s Phase 3.

---

## 📘 References

* [`/backend/docs/MIGRATION_UPLOADCARE_PLAN.md`](./MIGRATION_UPLOADCARE_PLAN.md)
* [`SYSTEM_NOTE.md`](../../SYSTEM_NOTE.md)
* [`../ai-chatbot-diditz/NOTE.md`](../ai-chatbot-diditz/NOTE.md)
