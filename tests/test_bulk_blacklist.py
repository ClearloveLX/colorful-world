"""批量加入黑名单端点测试：移动文件到 bad + 删除记录。"""
import os
import shutil
import tempfile
import unittest

from fastapi.testclient import TestClient

import backend.server as server
from backend.data.database import Database


class BulkBlacklistTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(db_path=os.path.join(self.temp_dir.name, "test_bb.db"), background_count_repair=False)
        self.original_db = server.db
        self.original_data_root = server.DATA_ROOT
        server.db = self.db
        server.DATA_ROOT = self.temp_dir.name
        self.client = TestClient(server.app)
        code = self.db.get_current_access_password()
        self.client.get(f"/api/password/validate?code={code}")

        # 两个真实媒体文件入库
        self.media_a = os.path.join(self.temp_dir.name, "a.jpg")
        self.media_b = os.path.join(self.temp_dir.name, "b.jpg")
        with open(self.media_a, "wb") as f:
            f.write(b"fake-a")
        with open(self.media_b, "wb") as f:
            f.write(b"fake-b")
        self.id_a = self.db.add_file(self.media_a)
        self.id_b = self.db.add_file(self.media_b)

    def tearDown(self):
        server.db = self.original_db
        server.DATA_ROOT = self.original_data_root
        self.temp_dir.cleanup()

    def _post(self, file_ids, headers=None):
        return self.client.post("/api/files/bulk/blacklist", json={"file_ids": file_ids}, headers=headers)

    def test_requires_auth(self):
        # setUp 里已登录并持有 cookie，这里用无 cookie 的新 client 验证鉴权
        client = TestClient(server.app)
        resp = client.post("/api/files/bulk/blacklist", json={"file_ids": [self.id_a]})
        self.assertEqual(resp.status_code, 401)

    def test_moves_file_to_bad_and_deletes_record(self):
        resp = self._post([self.id_a])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["updated"], 1)
        self.assertIsNone(self.db.get_file_by_id(self.id_a))  # 记录已删
        self.assertTrue(os.path.exists(os.path.join(self.temp_dir.name, "bad", "a.jpg")))  # 文件已移动

    def test_duplicate_name_gets_timestamp(self):
        bad_folder = os.path.join(self.temp_dir.name, "bad")
        os.makedirs(bad_folder, exist_ok=True)
        with open(os.path.join(bad_folder, "b.jpg"), "wb") as f:
            f.write(b"existing")
        resp = self._post([self.id_b])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["updated"], 1)
        # bad 里有原文件 + 时间戳副本
        files = os.listdir(bad_folder)
        self.assertEqual(len([n for n in files if n.startswith("b_") and n.endswith(".jpg")]), 1)

    def test_missing_file_still_deletes_record(self):
        os.remove(self.media_b)
        resp = self._post([self.id_b])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["updated"], 1)
        self.assertIsNone(self.db.get_file_by_id(self.id_b))

    def test_outside_data_root_is_error(self):
        outside = os.path.join(self.temp_dir.name, "..", "outside.jpg")
        outside = os.path.abspath(outside)
        with open(outside, "wb") as f:
            f.write(b"x")
        try:
            fid = self.db.add_file(outside)
            resp = self._post([fid])
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json()["errors"], 1)
            self.assertIsNotNone(self.db.get_file_by_id(fid))  # 记录保留
        finally:
            os.remove(outside)

    def test_unknown_file_id_is_skipped(self):
        resp = self._post(["does-not-exist"])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
