import os
import tempfile
import unittest

from fastapi.testclient import TestClient

import backend.server as server
from backend.data.database import Database


class TrueRandomCacheTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_true_random_cache.db")
        self.db = Database(db_path=self.db_path)
        self.original_db = server.db
        server.db = self.db
        self.client = TestClient(server.app)
        self.file_ids = []
        for index in range(4):
            file_id = self.db.add_file(
                file_path=os.path.join(self.temp_dir.name, f"sample_{index}.jpg"),
                file_name=f"sample_{index}.jpg",
                file_size=1024 + index,
            )
            self.file_ids.append(file_id)

    def tearDown(self):
        server.db = self.original_db
        self.temp_dir.cleanup()

    def test_settings_endpoints_round_trip(self):
        response = self.client.get("/api/settings/true-random-cache")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["enabled"])

        response = self.client.put("/api/settings/true-random-cache", json={"enabled": False})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["enabled"])
        self.assertFalse(self.db.get_true_random_cache_enabled())

    def test_true_random_edit_mode_writes_cache_and_filters_by_not_exists(self):
        first = self.client.get(
            "/api/media",
            params={
                "order": "random",
                "seed": 42,
                "page": 1,
                "page_size": 2,
                "edit_mode": "true",
                "true_random": "true",
            },
        )
        self.assertEqual(first.status_code, 200)
        first_ids = [item["id"] for item in first.json()["items"]]
        self.assertEqual(len(first_ids), 2)
        self.assertEqual(self.db.count_true_random_cache(), 2)

        second = self.client.get(
            "/api/media",
            params={
                "order": "random",
                "seed": 42,
                "page": 2,
                "page_size": 2,
                "edit_mode": "true",
                "true_random": "true",
            },
        )
        self.assertEqual(second.status_code, 200)
        second_ids = [item["id"] for item in second.json()["items"]]
        self.assertEqual(len(second_ids), 2)
        self.assertTrue(set(first_ids).isdisjoint(set(second_ids)))
        self.assertEqual(self.db.count_true_random_cache(), 4)

    def test_disabled_cache_stops_writes_and_filtering(self):
        self.db.set_true_random_cache_enabled(False)

        first = self.client.get(
            "/api/media",
            params={
                "order": "random",
                "seed": 7,
                "page": 1,
                "page_size": 2,
                "edit_mode": "true",
                "true_random": "true",
            },
        )
        second = self.client.get(
            "/api/media",
            params={
                "order": "random",
                "seed": 7,
                "page": 1,
                "page_size": 2,
                "edit_mode": "true",
                "true_random": "true",
            },
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual([item["id"] for item in first.json()["items"]], [item["id"] for item in second.json()["items"]])
        self.assertEqual(self.db.count_true_random_cache(), 0)

    def test_clear_endpoint_removes_all_cache_rows(self):
        self.db.cache_true_random_results("demo", self.file_ids[:3])
        response = self.client.post("/api/true-random-cache/clear")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted"], 3)
        self.assertEqual(self.db.count_true_random_cache(), 0)


if __name__ == "__main__":
    unittest.main()
