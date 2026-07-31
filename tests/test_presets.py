import os
import tempfile
import threading
import unittest

from backend.data.database import Database


class PresetDatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_presets.db")
        # 禁用启动后台计数重算,避免线程持有临时 DB 句柄导致清理失败
        self.db = Database(db_path=self.db_path, background_count_repair=False)
        self.tag_a = self.db.add_tag("标签A")
        self.tag_b = self.db.add_tag("标签B")
        self.tag_c = self.db.add_tag("标签C")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_create_preset_returns_id_and_keeps_sort_contiguous(self):
        preset_id = self.db.create_preset("image", "默认图像预制", 0, [self.tag_a, self.tag_b])

        preset = self.db.get_preset("image", preset_id)
        presets = self.db.list_presets("image")

        self.assertIsNotNone(preset)
        self.assertEqual(preset["name"], "默认图像预制")
        self.assertEqual(preset["tags"], [self.tag_a, self.tag_b])
        self.assertEqual([item["sort_order"] for item in presets], [0])

    def test_update_preset_can_rename_retag_and_reorder(self):
        first_id = self.db.create_preset("image", "预制1", 0, [self.tag_a])
        second_id = self.db.create_preset("image", "预制2", 1, [self.tag_b])
        self.db.update_preset("image", second_id, name="预制2-改", sort_order=0, tags=[self.tag_b, self.tag_c])

        presets = self.db.list_presets("image")
        self.assertEqual([item["name"] for item in presets], ["预制2-改", "预制1"])
        self.assertEqual([item["sort_order"] for item in presets], [0, 1])
        updated = self.db.get_preset("image", second_id)
        self.assertEqual(updated["tags"], [self.tag_b, self.tag_c])
        self.assertEqual(self.db.get_preset("image", first_id)["sort_order"], 1)

    def test_delete_preset_soft_deletes_and_reorders(self):
        first_id = self.db.create_preset("image", "预制1", 0, [self.tag_a])
        second_id = self.db.create_preset("image", "预制2", 1, [self.tag_b])
        third_id = self.db.create_preset("image", "预制3", 2, [self.tag_c])

        self.db.delete_preset("image", second_id)

        active = self.db.list_presets("image")
        deleted = self.db.get_preset("image", second_id, include_deleted=True)

        self.assertEqual([item["preset_id"] for item in active], [first_id, third_id])
        self.assertEqual([item["sort_order"] for item in active], [0, 1])
        self.assertEqual(deleted["is_deleted"], 1)

    def test_duplicate_name_conflict_is_scoped_by_media_type(self):
        self.db.create_preset("image", "同名预制", 0, [self.tag_a])

        with self.assertRaisesRegex(ValueError, "已存在"):
            self.db.create_preset("image", "同名预制", 1, [self.tag_b])

        video_id = self.db.create_preset("video", "同名预制", 0, [self.tag_b])
        self.assertIsNotNone(video_id)

    def test_invalid_tag_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "非法标签"):
            self.db.create_preset("image", "非法标签预制", 0, [self.tag_a, "missing-tag"])

    def test_concurrent_create_keeps_sort_unique_and_contiguous(self):
        created_ids = []
        errors = []
        lock = threading.Lock()

        def worker(index):
            try:
                preset_id = self.db.create_preset("image", f"并发创建{index}", index, [self.tag_a])
                with lock:
                    created_ids.append(preset_id)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(index,)) for index in range(10)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        presets = self.db.list_presets("image")
        self.assertEqual(len(created_ids), 10)
        self.assertEqual(len(presets), 10)
        self.assertEqual([item["sort_order"] for item in presets], list(range(10)))

    def test_concurrent_reorder_keeps_sort_unique_and_contiguous(self):
        preset_ids = [
            self.db.create_preset("image", f"重排{i}", i, [self.tag_a])
            for i in range(5)
        ]
        targets = [4, 0, 3, 1, 2]
        errors = []
        lock = threading.Lock()

        def worker(preset_id, target_order):
            try:
                self.db.update_preset("image", preset_id, sort_order=target_order)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(preset_id, targets[idx]))
            for idx, preset_id in enumerate(preset_ids)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(errors, [])
        presets = self.db.list_presets("image")
        self.assertEqual(sorted(item["sort_order"] for item in presets), list(range(5)))
        self.assertEqual(len({item["sort_order"] for item in presets}), 5)


if __name__ == "__main__":
    unittest.main()
