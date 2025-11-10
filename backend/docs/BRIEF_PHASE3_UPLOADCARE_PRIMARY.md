# BRIEF_PHASE3_UPLOADCARE_PRIMARY.md
**Phase 3 — Uploadcare-Primary Migration Brief**

---

## 🎯 Goal
Make **Uploadcare the authoritative storage backend** when  
`UPLOADCARE_ENABLED=true` and `UPLOADCARE_MODE="uploadcare"`.

- New uploads write **only** to Uploadcare (UUID + CDN).
- Neo4j records use:
  - `file_storage_type="uploadcare"`
  - `file_storage_id=<Uploadcare UUID>`
  - `file_checksum=<sha256>`
- Legacy local data remains readable and deletable.
- The entire change is gated by feature flags and is fully reversible.

---

## 🧭 Context
Phase 1–2.5 are complete:  
- Uploadcare helper, dual-write, and checksum parity verified.  
- Local storage is still canonical.  
Phase 3 enables **UUID-first** behavior for new writes.

Reference docs:  
- `backend/docs/MIGRATION_UPLOADCARE_PLAN.md`  
- `backend/docs/BRIEF_PHASE2_5_UUID_CHECKSUM.md`  
- `SYSTEM_NOTE.md → Related Repository Notes`  

---

## ⚙️ Implementation Tasks

### 1️⃣ Upload Path (main.upload_file)
When `UPLOADCARE_MODE="uploadcare"`:
- Accept chunks as usual.  
- On final merge:
  ```python
  meta = uploadcare.upload_file_direct(merged_bytes, originalname)
On success:

python
Copy code
file_storage_type = "uploadcare"
file_storage_id   = meta.file_id
file_checksum     = meta.file_checksum or calculate_checksum(temp_path)
Save node to Neo4j and remove local temp file.

On failure:

Log a warning.

Fallback to local write (file_storage_type="local") without aborting request.

### 2️⃣ Read Path
If file_storage_type=="uploadcare":

python
Copy code
tmp_path = uploadcare.download_file(file_storage_id, dest_path)
Then feed tmp_path to existing loader (PyMuPDFLoader / UnstructuredFileLoader).
Legacy local files remain unchanged.

### 3️⃣ Delete Path
If file_storage_type=="uploadcare", call:

python
Copy code
uploadcare.delete_file(file_storage_id)
Otherwise keep existing local delete logic.
Failures log warnings, never raise.

### 4️⃣ Config / Modes
MODE	Behavior
local	Legacy disk-only
dual	Local + Uploadcare (non-authoritative)
uploadcare	Uploadcare-first; local used only for temp

Rollback is one-line: set UPLOADCARE_MODE=local.

## 🧪 Tests (backend/tests/test_uploadcare.py)
Add / update:

test_uploadcare_mode_writes_uuid_primary
Verify Uploadcare called, UUID stored, local temp cleaned.

test_uploadcare_mode_fallback_to_local_on_failure
Simulate Uploadcare 5xx, ensure local fallback.

test_read_uses_download_for_uploadcare_type
Ensure download_file() invoked for Uploadcare nodes.

test_delete_uses_uploadcare_for_uploadcare_type
Ensure delete_file() called appropriately.

All network & DB calls mocked; local default remains intact.

## 🪵 Logging
info: "Uploadcare-mode: stored uuid=<id> as primary for <file>"

warning: "Uploadcare-mode: upload failed, falling back to local for <file>"

## 📄 Deliverables
Updated main.py (uploadcare-first branch).

Extended test_uploadcare.py with Uploadcare-mode tests.

.env.example documenting UPLOADCARE_MODE.

No regression for local or dual.

## ✅ Expected Outcome
Uploadcare UUIDs become the canonical source for new files.

Legacy data fully accessible.

Single env flag controls rollout and rollback.

All tests green with mocked HTTP.

## ⚠️ Constraints
Do not delete or rewrite legacy local files.

Do not remove local/dual modes.

Do not make irreversible schema changes yet.

Keep Uploadcare integration aligned with Next.js repo NOTE.md.