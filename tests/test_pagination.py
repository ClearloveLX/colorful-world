import os
import tempfile
import unittest

from backend.data.database import Database


class PaginationKeysetTestCase(unittest.TestCase):
    """游标（keyset）分页一致性：滚动期间数据集变化（新增/删除）不跳页、不重复"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_pagination.db")
        self.db = Database(db_path=self.db_path, background_count_repair=False)
        self.file_ids = []
        for i in range(10):
            fid = self.db.add_file(
                file_path=os.path.join(self.temp_dir.name, f"f_{i:02d}.jpg"),
                file_name=f"f_{i:02d}.jpg",
                file_size=1000 + i,
            )
            self.file_ids.append(fid)
        # 控制 created_at：f00 最新 ... f09 最旧
        for i, fid in enumerate(self.file_ids):
            ts = f"2026-01-01T10:00:{59 - i:02d}.000000"
            self.db._execute('UPDATE files SET created_at = ? WHERE id = ?', (ts, fid))
        self.order_desc = [self.file_ids[i] for i in range(10)]          # 最新在前
        self.order_asc = [self.file_ids[9 - i] for i in range(10)]       # 最旧在前

    def tearDown(self):
        self.temp_dir.cleanup()

    def fetch_all_by_cursor(self, order='recent', limit=3, mutate=None):
        """用游标翻完整页；mutate 在每两页之间调用（模拟滚动期间的数据变更）"""
        collected = []
        cursor = None
        page = 0
        while True:
            page += 1
            rows = self.db.query_files_with_filters(offset=(page - 1) * limit, limit=limit, order=order, cursor=cursor)
            if not rows:
                break
            collected.extend([r['id'] for r in rows])
            if len(rows) < limit:
                break
            last = rows[-1]
            if order in ('duration', 'duration_asc'):
                cursor = f"{last.get('duration_ms') or 0}|{last.get('created_at')}|{last['id']}"
            elif order in ('heat', 'heat_asc'):
                cursor = f"{last.get('heat_value') or 0}|{last.get('created_at')}|{last['id']}"
            else:
                cursor = f"{last.get('created_at')}|{last['id']}"
            if mutate:
                mutate(page)
        return collected

    def test_static_matches_offset(self):
        """静态数据下，游标翻页结果与 OFFSET 翻页一致"""
        by_cursor = self.fetch_all_by_cursor(order='recent', limit=3)
        self.assertEqual(by_cursor, self.order_desc)
        by_cursor_asc = self.fetch_all_by_cursor(order='recent_asc', limit=4)
        self.assertEqual(by_cursor_asc, self.order_asc)

    def test_insert_mid_scroll_no_skip(self):
        """滚动到一半时顶部插入新文件：游标翻页不漏掉任何原有文件、不重复"""
        def insert_new(page):
            if page == 1:
                fid = self.db.add_file(
                    file_path=os.path.join(self.temp_dir.name, "new_top.jpg"),
                    file_name="new_top.jpg",
                    file_size=999,
                )
                # 比所有文件更新
                self.db._execute('UPDATE files SET created_at = ? WHERE id = ?', ("2026-01-02T00:00:00.000000", fid))
        collected = self.fetch_all_by_cursor(order='recent', limit=3, mutate=insert_new)
        # 原有 10 个文件必须全部出现且各一次（新文件在游标之上，本次滚动不出现，刷新后才会看到）
        seen = [fid for fid in collected if fid in self.file_ids]
        self.assertEqual(seen, self.order_desc)
        self.assertEqual(len(seen), len(set(seen)), "存在重复项")

    def test_delete_mid_scroll_no_skip(self):
        """滚动到一半时删除一个文件：游标翻页不漏掉其余文件、不重复"""
        deleted_id = self.file_ids[5]
        def delete_mid(page):
            if page == 1:
                self.db.delete_file(deleted_id)
        collected = self.fetch_all_by_cursor(order='recent', limit=3, mutate=delete_mid)
        remaining = [fid for fid in self.order_desc if fid != deleted_id]
        self.assertEqual(collected, remaining)

    def test_recent_asc_insert_mid_scroll(self):
        """recent_asc（最旧在前）在底部插入新文件：游标方向正确，不漏不重"""
        def insert_bottom(page):
            if page == 1:
                fid = self.db.add_file(
                    file_path=os.path.join(self.temp_dir.name, "new_bottom.jpg"),
                    file_name="new_bottom.jpg",
                    file_size=998,
                )
                self.db._execute('UPDATE files SET created_at = ? WHERE id = ?', ("2026-01-03T00:00:00.000000", fid))
        collected = self.fetch_all_by_cursor(order='recent_asc', limit=3, mutate=insert_bottom)
        seen = [fid for fid in collected if fid in self.file_ids]
        self.assertEqual(seen, self.order_asc)
        self.assertEqual(len(seen), len(set(seen)), "存在重复项")

    def test_heat_keyset(self):
        """heat 排序游标（含 NULL 热度）"""
        for i, fid in enumerate(self.file_ids):
            self.db._execute('UPDATE files SET heat_value = ? WHERE id = ?', (i % 3, fid))
        # 期望：heat 3(无) → 2 → 1 → 0，同值按 created_at DESC
        heat_order = [fid for fid in self.order_desc]
        heat_order.sort(key=lambda fid: -(self._heat(fid)))
        collected = self.fetch_all_by_cursor(order='heat', limit=3)
        self.assertEqual(collected, heat_order)

    def _heat(self, fid):
        row = self.db._query('SELECT heat_value FROM files WHERE id = ?', (fid,), fetch='one')
        return int(row.get('heat_value') or 0)

    def test_invalid_cursor_falls_back_to_offset(self):
        """畸形游标退回 OFFSET 分页"""
        rows = self.db.query_files_with_filters(offset=0, limit=3, order='recent', cursor='garbage')
        self.assertEqual([r['id'] for r in rows], self.order_desc[:3])
        rows2 = self.db.query_files_with_filters(offset=3, limit=3, order='recent', cursor='a|')
        self.assertEqual([r['id'] for r in rows2], self.order_desc[3:6])

    def test_cursor_with_filters(self):
        """游标与筛选条件组合：只翻出匹配项"""
        # 给偶数位文件打标签
        tag_id = self.db.add_tag('even')
        for i, fid in enumerate(self.file_ids):
            if i % 2 == 0:
                self.db.add_file_tag(fid, tag_id)
        expected = [self.file_ids[i] for i in range(10) if i % 2 == 0]
        collected = []
        cursor = None
        while True:
            rows = self.db.query_files_with_filters(tag_ids=[tag_id], limit=2, order='recent', cursor=cursor)
            if not rows:
                break
            collected.extend([r['id'] for r in rows])
            if len(rows) < 2:
                break
            last = rows[-1]
            cursor = f"{last.get('created_at')}|{last['id']}"
        self.assertEqual(collected, expected)

    def test_recent_cursor_with_created_at_ties(self):
        """created_at 相同时按 id ASC 决出顺序,游标不能漏项/重复"""
        same_ts = "2026-01-01T00:00:00.000000"
        self.db._execute('UPDATE files SET created_at = ?', (same_ts,))
        expected = sorted(self.file_ids)
        for order in ('recent', 'recent_asc'):
            collected = []
            cursor = None
            while True:
                rows = self.db.query_files_with_filters(limit=3, order=order, cursor=cursor)
                if not rows:
                    break
                collected.extend([r['id'] for r in rows])
                if len(rows) < 3:
                    break
                last = rows[-1]
                cursor = f"{last.get('created_at')}|{last['id']}"
            self.assertEqual(collected, expected, order)

    def test_duration_cursor_with_null_ties(self):
        """duration_ms 全部为 NULL 时 COALESCE 后同值,游标按 created_at DESC 继续翻页"""
        self.db._execute('UPDATE files SET duration_ms = NULL')
        for order in ('duration', 'duration_asc'):
            collected = []
            cursor = None
            while True:
                rows = self.db.query_files_with_filters(limit=3, order=order, cursor=cursor)
                if not rows:
                    break
                collected.extend([r['id'] for r in rows])
                if len(rows) < 3:
                    break
                last = rows[-1]
                cursor = f"{last.get('duration_ms') or 0}|{last.get('created_at')}|{last['id']}"
            self.assertEqual(collected, self.order_desc, order)

    def test_strict_model_filter_uses_count_distinct_semantics(self):
        """strict 多模特:必须同时关联全部模特;只关联其中一个的文件不应返回"""
        model_a = self.db.add_model('cursor-a')
        model_b = self.db.add_model('cursor-b')
        self.db.add_file_model(self.file_ids[0], model_a)
        self.db.add_file_model(self.file_ids[1], model_b)
        self.db.add_file_model(self.file_ids[2], model_a)
        self.db.add_file_model(self.file_ids[2], model_b)
        only_a = {r['id'] for r in self.db.query_files_with_filters(model_ids=[model_a], strict=True, limit=100)}
        self.assertEqual(only_a, {self.file_ids[0], self.file_ids[2]})
        both = {r['id'] for r in self.db.query_files_with_filters(model_ids=[model_a, model_b], strict=True, limit=100)}
        self.assertEqual(both, {self.file_ids[2]})
        loose = {r['id'] for r in self.db.query_files_with_filters(model_ids=[model_a, model_b], strict=False, limit=100)}
        self.assertEqual(loose, {self.file_ids[0], self.file_ids[1], self.file_ids[2]})


if __name__ == '__main__':
    unittest.main()
