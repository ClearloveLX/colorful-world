"""安全修复回归测试：/api/static 白名单、API 鉴权、Range 流式化、open_helper 校验。"""
import base64
import os
import tempfile
import unittest

from fastapi.testclient import TestClient

import backend.server as server
from backend.data.database import Database
from backend.open_helper import _is_local_origin, _get_data_root


class StaticWhitelistTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        # 禁用启动后台计数重算,避免线程持有临时 DB 句柄导致清理失败
        self.db = Database(db_path=os.path.join(self.temp_dir.name, "test_security.db"), background_count_repair=False)
        self.original_db = server.db
        self.original_data_root = server.DATA_ROOT
        server.db = self.db
        server.DATA_ROOT = self.temp_dir.name
        self.client = TestClient(server.app)
        # 登录拿 cookie
        code = self.db.get_current_access_password()
        self.client.get(f"/api/password/validate?code={code}")

        # 在临时 DATA_ROOT 里放一个媒体文件
        self.media_path = os.path.join(self.temp_dir.name, "sample.jpg")
        with open(self.media_path, "wb") as f:
            f.write(b"fake-jpeg-data")

    def tearDown(self):
        server.db = self.original_db
        server.DATA_ROOT = self.original_data_root
        self.temp_dir.cleanup()

    def _b64(self, p: str) -> str:
        return base64.urlsafe_b64encode(p.encode("utf-8")).decode("ascii").rstrip("=")

    # ---------- /api/static 白名单 ----------

    def test_static_blocks_source_and_db_files(self):
        for rel in ("backend/server.py", "data/image_classifier.db", "main.py", ".git/config", "requirements.txt"):
            resp = self.client.get(f"/api/static/{rel}")
            self.assertEqual(resp.status_code, 403, f"/api/static/{rel} 应被拒绝")

    def test_static_allows_whitelisted_prefixes(self):
        # 白名单内资源（data/output/frontend/dist）仍可访问
        data_dir = os.path.join(self.temp_dir.name, "data")
        os.makedirs(data_dir, exist_ok=True)
        os.makedirs(os.path.join(server.STATIC_BASE, "output"), exist_ok=True)
        resp = self.client.get("/api/static/data/")
        self.assertIn(resp.status_code, (200, 404))
        resp = self.client.get("/api/static/output/")
        self.assertIn(resp.status_code, (200, 404))

    def test_static_traversal_blocked(self):
        # 客户端可能先行规范化 ../ 路径（404）或由白名单中间件拦截（403），均视为拦截成功
        resp = self.client.get("/api/static/data/../../backend/server.py")
        self.assertIn(resp.status_code, (403, 404))
        resp = self.client.get("/api/static/..%2f..%2fbackend%2fserver.py")
        self.assertIn(resp.status_code, (403, 404))

    # ---------- API 鉴权 ----------

    def test_api_without_access_returns_401(self):
        client = TestClient(server.app)  # 无 cookie
        resp = client.get("/api/media")
        self.assertEqual(resp.status_code, 401)

    def test_api_with_cookie_works(self):
        resp = self.client.get("/api/media")
        self.assertEqual(resp.status_code, 200)

    def test_api_with_header_code_works(self):
        client = TestClient(server.app)
        code = self.db.get_current_access_password()
        resp = client.get("/api/media", headers={"X-Access-Code": code})
        self.assertEqual(resp.status_code, 200)

    def test_api_with_query_code_works(self):
        client = TestClient(server.app)
        code = self.db.get_current_access_password()
        resp = client.get(f"/api/media?code={code}")
        self.assertEqual(resp.status_code, 200)

    def test_password_endpoints_exempt(self):
        # 锁屏页需预取访问码写入 localStorage 自动填入，两个密码端点均豁免鉴权
        client = TestClient(server.app)  # 无 cookie
        resp = client.get("/api/password/current")
        self.assertEqual(resp.status_code, 200)
        resp = client.get("/api/password/validate", params={"code": "whatever"})
        self.assertEqual(resp.status_code, 200)

    def test_invalid_code_rejected(self):
        client = TestClient(server.app)
        resp = client.get("/api/media", headers={"X-Access-Code": "wrong-code"})
        self.assertEqual(resp.status_code, 401)

    # ---------- Range 流式 ----------

    def test_range_request_streams_206(self):
        big = os.path.join(self.temp_dir.name, "big.bin")
        with open(big, "wb") as f:
            f.write(b"x" * (5 * 1024 * 1024))  # 5MB
        resp = self.client.get(
            f"/api/file?path={self._b64(big)}",
            headers={"Range": "bytes=0-"},
        )
        self.assertEqual(resp.status_code, 206)
        self.assertIn("Content-Range", resp.headers)
        self.assertEqual(resp.headers["Content-Range"], f"bytes 0-{5*1024*1024-1}/{5*1024*1024}")
        self.assertEqual(resp.headers.get("Accept-Ranges"), "bytes")
        body = resp.content
        self.assertEqual(len(body), 5 * 1024 * 1024)
        self.assertEqual(body[:4], b"xxxx")

    def test_partial_range(self):
        small = os.path.join(self.temp_dir.name, "small.bin")
        with open(small, "wb") as f:
            f.write(b"0123456789")
        resp = self.client.get(
            f"/api/file?path={self._b64(small)}",
            headers={"Range": "bytes=2-5"},
        )
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(resp.content, b"2345")


class OpenHelperValidationTestCase(unittest.TestCase):
    def test_local_origin_accepted(self):
        import email.message
        headers = email.message.Message()
        headers["Origin"] = "http://127.0.0.1:4396"
        self.assertTrue(_is_local_origin(headers))
        headers = email.message.Message()
        headers["Origin"] = "http://localhost:4398"
        self.assertTrue(_is_local_origin(headers))

    def test_foreign_origin_rejected(self):
        import email.message
        headers = email.message.Message()
        headers["Origin"] = "http://evil.example.com"
        self.assertFalse(_is_local_origin(headers))
        headers = email.message.Message()
        headers["Referer"] = "http://192.168.1.99/"
        self.assertFalse(_is_local_origin(headers))

    def test_missing_origin_rejected(self):
        import email.message
        headers = email.message.Message()
        # 缺失 Origin/Referer 一律拒绝：浏览器跨站请求必然携带，缺失说明非浏览器来源
        self.assertFalse(_is_local_origin(headers))

    def test_data_root_resolution(self):
        root = _get_data_root()
        self.assertTrue(os.path.isabs(root))


if __name__ == "__main__":
    unittest.main()
