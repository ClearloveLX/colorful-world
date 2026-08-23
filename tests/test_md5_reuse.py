import hashlib
import os
import tempfile
import unittest

from backend.data.database import Database, compute_md5


class ComputeMd5TestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_md5.db")
        self.db = Database(db_path=self.db_path, background_count_repair=False)
        # 构造一个真实存在的测试文件
        self.file_path = os.path.join(self.temp_dir.name, "sample.png")
        with open(self.file_path, 'wb') as f:
            f.write(os.urandom(64 * 1024))  # 64KB 随机内容

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_compute_md5_matches_manual_hashlib(self):
        expected = hashlib.md5()
        with open(self.file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                expected.update(chunk)
        self.assertEqual(compute_md5(self.file_path), expected.hexdigest())

    def test_add_file_with_precomputed_md5_skips_file_read(self):
        """传入 md5_value 时即使文件不存在也能插入成功,证明跳过了文件读取"""
        fake_path = os.path.join(self.temp_dir.name, "not_exists.jpg")
        self.assertFalse(os.path.exists(fake_path))
        file_id = self.db.add_file(fake_path, file_name="not_exists.jpg", md5_value="deadbeef")
        self.assertIsNotNone(file_id)
        row = self.db.get_file_by_id(file_id)
        self.assertEqual(row['md5'], "deadbeef")

    def test_add_file_without_md5_computes_normally(self):
        """不传 md5_value 时行为不变:自动计算真实文件的 MD5"""
        file_id = self.db.add_file(self.file_path)
        row = self.db.get_file_by_id(file_id)
        self.assertEqual(row['md5'], compute_md5(self.file_path))

    def test_save_image_data_with_precomputed_md5(self):
        """传入 md5_value 时更新为传入值,文件不存在也不抛错"""
        file_id = self.db.add_file(self.file_path)
        self.db.save_image_data(file_id, os.path.join(self.temp_dir.name, "gone.png"), md5_value="cafebabe")
        row = self.db.get_file_by_id(file_id)
        self.assertEqual(row['md5'], "cafebabe")

    def test_save_image_data_without_md5_computes_normally(self):
        """不传 md5_value 时行为不变:自动计算并更新"""
        file_id = self.db.add_file(self.file_path)
        self.db.save_image_data(file_id, self.file_path)
        row = self.db.get_file_by_id(file_id)
        self.assertEqual(row['md5'], compute_md5(self.file_path))


if __name__ == '__main__':
    unittest.main()
