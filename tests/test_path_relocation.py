"""路径相对化（方案 B）测试：to_rel / resolve_abs / add_file 自动相对化 / 查询出口绝对化。"""
import os
import tempfile
import unittest

from backend.data.database import Database, resolve_abs, to_rel


class PathRelocationTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = self.temp_dir.name
        self.old_env = os.environ.get('CW_DATA_ROOT')
        os.environ['CW_DATA_ROOT'] = self.root
        self.db_path = os.path.join(self.temp_dir.name, "test_rel.db")
        self.db = Database(db_path=self.db_path, background_count_repair=False)

    def tearDown(self):
        if self.old_env is None:
            os.environ.pop('CW_DATA_ROOT', None)
        else:
            os.environ['CW_DATA_ROOT'] = self.old_env
        self.temp_dir.cleanup()

    def _make_file(self, rel_sub):
        real = os.path.join(self.root, rel_sub)
        os.makedirs(os.path.dirname(real), exist_ok=True)
        with open(real, 'wb') as f:
            f.write(b'x')
        return real

    # ---------- to_rel ----------

    def test_to_rel_converts_abs_under_root(self):
        abs_path = os.path.join(self.root, 'good', 'x.jpg')
        self.assertEqual(to_rel(abs_path), os.path.join('data', 'good', 'x.jpg'))

    def test_to_rel_keeps_outside_abs(self):
        outside = os.path.abspath(os.path.join(self.temp_dir.name, '..', 'y.jpg'))
        self.assertEqual(to_rel(outside), outside)

    def test_to_rel_keeps_already_rel(self):
        self.assertEqual(to_rel('data/good/x.jpg'), 'data/good/x.jpg')

    # ---------- resolve_abs ----------

    def test_resolve_abs_converts_rel(self):
        self.assertEqual(resolve_abs('data/good/x.jpg'), os.path.join(self.root, 'good', 'x.jpg'))

    def test_resolve_abs_keeps_abs(self):
        abs_path = os.path.join(self.root, 'good', 'x.jpg')
        self.assertEqual(resolve_abs(abs_path), abs_path)

    def test_resolve_abs_rejects_traversal(self):
        self.assertIsNone(resolve_abs('data/../../outside.jpg'))

    def test_resolve_abs_accepts_explicit_data_root(self):
        """显式传 data_root 优先（server.py 的 DATA_ROOT 可被 monkey-patch）"""
        other = tempfile.mkdtemp(prefix='cw_root2_')
        try:
            self.assertEqual(resolve_abs('data/good/x.jpg', other), os.path.join(other, 'good', 'x.jpg'))
        finally:
            os.rmdir(other)

    # ---------- 读写边界 ----------

    def test_add_file_stores_rel_path(self):
        real = self._make_file('good/f.jpg')
        fid = self.db.add_file(real)
        row = self.db.get_file_by_id(fid)
        self.assertEqual(row['file_path'], os.path.join('data', 'good', 'f.jpg'))

    def test_get_file_accepts_abs_query(self):
        real = self._make_file('good/f.jpg')
        fid = self.db.add_file(real)
        self.assertEqual(self.db.get_file(real)['id'], fid)

    def test_get_files_page_returns_abs(self):
        real = self._make_file(os.path.join('good', 'g.jpg'))
        self.db.add_file(real)
        rows = self.db.get_files_page(limit=10)
        self.assertTrue(rows)
        self.assertEqual(rows[0]['file_path'], real)

    def test_update_file_thumbnail_stores_rel(self):
        real = self._make_file('good/h.jpg')
        fid = self.db.add_file(real)
        thumb = os.path.join(self.root, 'good', 'h_thumb.jpg')
        self.db.update_file_thumbnail(fid, thumb)
        row = self.db.get_file_by_id(fid)
        self.assertEqual(row['thumbnail_path'], os.path.join('data', 'good', 'h_thumb.jpg'))


if __name__ == '__main__':
    unittest.main()
