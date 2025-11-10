import os
import sys
import tempfile
import unittest
from unittest import mock

# Ensure backend/src is importable when running tests from backend/
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.storage import uploadcare
from src.main import upload_file
import src.main as main_mod


class TestUploadcareHelper(unittest.TestCase):
    def setUp(self):
        # Ensure UPLOADCARE_ENABLED is enabled for helper invocation in tests
        self.env_patcher = mock.patch.dict(os.environ, {"UPLOADCARE_ENABLED": "true", "UPLOAD_CARE_PUBLIC_KEY": "pk", "UPLOAD_CARE_SECRET_KEY": "sk", "UPLOADCARE_API_BASE_URL": "https://api.uploadcare.test"})
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()

    @mock.patch("src.storage.uploadcare.requests.post")
    def test_upload_success(self, mock_post):
        mock_resp = mock.Mock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {"file_id": "uuid-123", "cdn_url": "https://ucarecdn.com/uuid-123/", "size": 123}
        mock_post.return_value = mock_resp

        meta = uploadcare.upload_file_direct(b"abc", "test.txt")
        self.assertEqual(meta.file_id, "uuid-123")
        self.assertEqual(meta.cdn_url, "https://ucarecdn.com/uuid-123/")
        self.assertEqual(meta.file_size, 123)

    @mock.patch("src.storage.uploadcare.requests.post")
    def test_upload_failure_raises(self, mock_post):
        mock_resp = mock.Mock()
        mock_resp.status_code = 500
        mock_resp.text = "server error"
        mock_post.return_value = mock_resp

        with self.assertRaises(ValueError):
            uploadcare.upload_file_direct(b"x", "f.txt")

    @mock.patch("src.storage.uploadcare.requests.get")
    def test_download_file_streams(self, mock_get):
        mock_resp = mock.Mock()
        mock_resp.status_code = 200
        mock_resp.iter_content = mock.Mock(return_value=[b"ab", b"cd"])
        mock_get.return_value = mock_resp

        fd, path = tempfile.mkstemp()
        os.close(fd)
        try:
            out = uploadcare.download_file("uuid-123", path)
            self.assertEqual(out, path)
            with open(path, "rb") as fh:
                data = fh.read()
            self.assertEqual(data, b"abcd")
        finally:
            try:
                os.remove(path)
            except Exception:
                pass

    @mock.patch("src.storage.uploadcare.requests.delete")
    def test_delete_file(self, mock_delete):
        mock_resp_ok = mock.Mock()
        mock_resp_ok.status_code = 204
        mock_delete.return_value = mock_resp_ok
        self.assertTrue(uploadcare.delete_file("uuid-1"))

        mock_resp_bad = mock.Mock()
        mock_resp_bad.status_code = 404
        mock_delete.return_value = mock_resp_bad
        self.assertFalse(uploadcare.delete_file("uuid-2"))

    def test_dual_write_triggers_uploadcare_and_preserves_local(self):
        # Prepare environment for dual mode
        with mock.patch.dict(os.environ, {"UPLOADCARE_ENABLED": "true", "UPLOADCARE_MODE": "dual"}):
            # Create temp dirs for chunks and merged
            with tempfile.TemporaryDirectory() as chunk_dir, tempfile.TemporaryDirectory() as merged_dir:
                originalname = "file.pdf"

                # Create a dummy chunk object with file.read()
                class DummyFile:
                    def read(self):
                        return b"part"

                chunk = mock.Mock()
                chunk.file = DummyFile()

                # Patch merge_chunks_local to create the merged file and return its size
                def fake_merge(fname, total_chunks, cdir, mdir):
                    os.makedirs(mdir, exist_ok=True)
                    path = os.path.join(mdir, fname)
                    with open(path, "wb") as fh:
                        fh.write(b"mergedcontent")
                    return os.path.getsize(path)

                # Patch graphDBdataAccess to avoid DB calls
                fake_graph_db = mock.Mock()
                fake_graph_db.create_source_node = mock.Mock()

                with mock.patch("src.main.merge_chunks_local", side_effect=fake_merge) as m_merge, \
                     mock.patch("src.main.graphDBdataAccess", return_value=fake_graph_db) as m_graph_access, \
                     mock.patch("src.storage.uploadcare.upload_file_direct") as m_upload_direct:

                    # Configure Uploadcare upload to return meta
                    m_upload_direct.return_value = uploadcare.UploadcareFileMeta(file_id="uuid-xyz", cdn_url="https://cdn/uuid-xyz", file_size=13)

                    # Ensure fake_graph_db supports candidate persistence
                    fake_graph_db.set_candidate_file_metadata = mock.Mock(return_value=True)

                    # Patch checksum computation to a known value
                    with mock.patch("src.storage.uploadcare.calculate_checksum", return_value="deadbeef") as m_calc:
                        # Call upload_file simulating last chunk
                        result = upload_file(None, "model", chunk, 1, 1, originalname, "uri", chunk_dir, merged_dir)

                    # Ensure merge and db create called
                    m_merge.assert_called_once()
                    m_graph_access.assert_called()
                    # Uploadcare upload called once
                    m_upload_direct.assert_called_once()
                    # Candidate metadata persisted
                    fake_graph_db.set_candidate_file_metadata.assert_called_once_with(originalname, "uuid-xyz", "deadbeef")
                    # Local behavior preserved: return includes file_size and file_name
                    self.assertIsInstance(result, dict)
                    resd = dict(result)
                    self.assertEqual(resd["file_name"], originalname)

    def test_dual_write_uploadcare_failure_is_logged_but_local_continues(self):
        # Simulate uploadcare raising an exception; local should continue
        with mock.patch.dict(os.environ, {"UPLOADCARE_ENABLED": "true", "UPLOADCARE_MODE": "dual"}):
            with tempfile.TemporaryDirectory() as chunk_dir, tempfile.TemporaryDirectory() as merged_dir:
                originalname = "file2.pdf"

                class DummyFile:
                    def read(self):
                        return b"part"

                chunk = mock.Mock()
                chunk.file = DummyFile()

                def fake_merge(fname, total_chunks, cdir, mdir):
                    os.makedirs(mdir, exist_ok=True)
                    path = os.path.join(mdir, fname)
                    with open(path, "wb") as fh:
                        fh.write(b"mergedcontent")
                    return os.path.getsize(path)

                fake_graph_db = mock.Mock()
                fake_graph_db.create_source_node = mock.Mock()

                with mock.patch("src.main.merge_chunks_local", side_effect=fake_merge), \
                     mock.patch("src.main.graphDBdataAccess", return_value=fake_graph_db), \
                     mock.patch("src.storage.uploadcare.upload_file_direct", side_effect=Exception("up fail")) as m_upload, \
                     mock.patch("src.main.logging.warning") as mock_warn:

                    result = upload_file(None, "model", chunk, 1, 1, originalname, "uri", chunk_dir, merged_dir)

                    # Even though upload failed, local flow returns normally
                    self.assertIsInstance(result, dict)
                    # Warning logged for upload failure
                    self.assertTrue(mock_warn.called)

    def test_dual_write_persist_failure_logged_but_local_continues(self):
        # Uploadcare succeeds but persistence to graph fails; should warn and continue
        with mock.patch.dict(os.environ, {"UPLOADCARE_ENABLED": "true", "UPLOADCARE_MODE": "dual"}):
            with tempfile.TemporaryDirectory() as chunk_dir, tempfile.TemporaryDirectory() as merged_dir:
                originalname = "file3.pdf"

                class DummyFile:
                    def read(self):
                        return b"part"

                chunk = mock.Mock()
                chunk.file = DummyFile()

                def fake_merge(fname, total_chunks, cdir, mdir):
                    os.makedirs(mdir, exist_ok=True)
                    path = os.path.join(mdir, fname)
                    with open(path, "wb") as fh:
                        fh.write(b"mergedcontent")
                    return os.path.getsize(path)

                fake_graph_db = mock.Mock()
                fake_graph_db.create_source_node = mock.Mock()
                # simulate persistence failure
                fake_graph_db.set_candidate_file_metadata = mock.Mock(side_effect=Exception("db fail"))

                with mock.patch("src.main.merge_chunks_local", side_effect=fake_merge), \
                     mock.patch("src.main.graphDBdataAccess", return_value=fake_graph_db), \
                     mock.patch("src.storage.uploadcare.upload_file_direct") as m_upload_direct, \
                     mock.patch("src.storage.uploadcare.calculate_checksum", return_value="deadbeef"), \
                     mock.patch("src.main.logging.warning") as mock_warn:

                    m_upload_direct.return_value = uploadcare.UploadcareFileMeta(file_id="uuid-abc", cdn_url="https://cdn/uuid-abc", file_size=13)
                    result = upload_file(None, "model", chunk, 1, 1, originalname, "uri", chunk_dir, merged_dir)

                    # Local flow returns normally
                    self.assertIsInstance(result, dict)
                    # Warning logged for persistence failure
                    self.assertTrue(mock_warn.called)

    def test_dual_write_disabled_no_uploadcare_calls(self):
        # Ensure when disabled or mode=local, no Uploadcare calls occur
        with mock.patch.dict(os.environ, {"UPLOADCARE_ENABLED": "false", "UPLOADCARE_MODE": "local"}):
            with tempfile.TemporaryDirectory() as chunk_dir, tempfile.TemporaryDirectory() as merged_dir:
                originalname = "file4.pdf"

                class DummyFile:
                    def read(self):
                        return b"part"

                chunk = mock.Mock()
                chunk.file = DummyFile()

                def fake_merge(fname, total_chunks, cdir, mdir):
                    os.makedirs(mdir, exist_ok=True)
                    path = os.path.join(mdir, fname)
                    with open(path, "wb") as fh:
                        fh.write(b"mergedcontent")
                    return os.path.getsize(path)

                fake_graph_db = mock.Mock()
                fake_graph_db.create_source_node = mock.Mock()

                with mock.patch("src.main.merge_chunks_local", side_effect=fake_merge), \
                     mock.patch("src.main.graphDBdataAccess", return_value=fake_graph_db), \
                     mock.patch("src.storage.uploadcare.upload_file_direct") as m_upload_direct:

                    result = upload_file(None, "model", chunk, 1, 1, originalname, "uri", chunk_dir, merged_dir)

                    # Uploadcare should not be called
                    self.assertFalse(m_upload_direct.called)
                    self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
