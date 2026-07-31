import os
import tempfile
import unittest

from backend.data.database import Database


class TagFileCountsTestCase(unittest.TestCase):
    """验证 tags.file_count 持久化计数：写路径增量维护 == 全量重算"""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_tag_counts.db")
        # 禁用启动后台重算,避免与断言并发
        self.db = Database(db_path=self.db_path, background_count_repair=False)
        # 1 个模特（带标签 B）和 3 个标签
        self.model_id = self.db.add_model("model1")
        self.tag_a = self.db.add_tag("tagA")
        self.tag_b = self.db.add_tag("tagB")
        self.tag_c = self.db.add_tag("tagC")
        self.file_ids = []
        for index in range(3):
            file_id = self.db.add_file(
                file_path=os.path.join(self.temp_dir.name, f"sample_{index}.jpg"),
                file_name=f"sample_{index}.jpg",
                file_size=1000 + index,
            )
            self.file_ids.append(file_id)

    def tearDown(self):
        self.temp_dir.cleanup()

    def get_counts(self):
        return {r['id']: r['file_count'] for r in self.db._query('SELECT id, file_count FROM tags')}

    def assert_incremental_matches_recalc(self):
        """当前增量维护的计数必须与全量重算一致"""
        inc = self.get_counts()
        self.db.recalc_tag_file_counts()
        rec = self.get_counts()
        self.assertEqual(inc, rec, "增量维护与全量重算结果不一致")

    def test_recalc_dedup_semantics(self):
        """全量重算：直接 ∪ 继承去重计数"""
        # file1: 直接 A；file2: 直接 B；file3: 直接 B + 模特继承 B（去重）
        self.db.add_file_tag(self.file_ids[0], self.tag_a)
        self.db.add_file_tag(self.file_ids[1], self.tag_b)
        self.db.add_file_model(self.file_ids[1], self.model_id)
        self.db.add_model_tag(self.model_id, self.tag_b)
        self.db.add_file_tag(self.file_ids[2], self.tag_b)
        self.db.add_file_model(self.file_ids[2], self.model_id)
        self.db.recalc_tag_file_counts()
        counts = self.get_counts()
        self.assertEqual(counts[self.tag_a], 1)
        self.assertEqual(counts[self.tag_b], 2)  # file2 + file3（file3 直接与继承只计一次）
        self.assertEqual(counts[self.tag_c], 0)

    def test_set_file_tags_incremental(self):
        self.db.set_file_tags(self.file_ids[0], [self.tag_a, self.tag_b])
        self.assert_incremental_matches_recalc()
        self.db.set_file_tags(self.file_ids[0], [self.tag_a])
        self.assert_incremental_matches_recalc()
        self.db.set_file_tags(self.file_ids[0], [])
        self.assert_incremental_matches_recalc()

    def test_set_file_models_incremental(self):
        self.db.add_model_tag(self.model_id, self.tag_b)
        self.db.set_file_models(self.file_ids[0], [self.model_id])
        self.assert_incremental_matches_recalc()
        # 换模特到无标签的模特
        other = self.db.add_model("model2")
        self.db.set_file_models(self.file_ids[0], [other])
        self.assert_incremental_matches_recalc()

    def test_order_independence(self):
        """先 models 后 tags 与先 tags 后 models，结果一致"""
        self.db.add_model_tag(self.model_id, self.tag_b)
        # 顺序 1：先设模特再设标签
        self.db.set_file_models(self.file_ids[0], [self.model_id])
        self.db.set_file_tags(self.file_ids[0], [self.tag_b])
        forward = self.get_counts()
        # 清空该文件状态
        self.db.set_file_models(self.file_ids[0], [])
        self.db.set_file_tags(self.file_ids[0], [])
        self.db.recalc_tag_file_counts()
        # 顺序 2：先设标签再设模特
        self.db.set_file_tags(self.file_ids[0], [self.tag_b])
        self.db.set_file_models(self.file_ids[0], [self.model_id])
        backward = self.get_counts()

        self.assertEqual(forward, backward)

    def test_add_remove_file_tag(self):
        self.db.add_file_tag(self.file_ids[0], self.tag_a)
        self.assert_incremental_matches_recalc()
        self.db.remove_file_tag(self.file_ids[0], self.tag_a)
        self.assert_incremental_matches_recalc()
        # 已存在时重复添加不重复计数
        self.db.add_file_tag(self.file_ids[0], self.tag_a)
        self.db.add_file_tag(self.file_ids[0], self.tag_a)
        self.assert_incremental_matches_recalc()

    def test_add_remove_model_tag(self):
        # 给所有文件挂上模特,再给模特加标签:全部文件继承计数
        for fid in self.file_ids:
            self.db.add_file_model(fid, self.model_id)
        self.db.add_model_tag(self.model_id, self.tag_b)
        self.assert_incremental_matches_recalc()
        self.assertEqual(self.get_counts()[self.tag_b], 3)
        # 部分文件已有直接标签,继承新增时不重复计数
        self.db.add_file_tag(self.file_ids[0], self.tag_c)
        self.db.add_model_tag(self.model_id, self.tag_c)
        self.assert_incremental_matches_recalc()
        self.assertEqual(self.get_counts()[self.tag_c], 3)
        # 移除模特标签:直接带标签的文件仍计数
        self.db.remove_model_tag(self.model_id, self.tag_b)
        self.assert_incremental_matches_recalc()
        self.assertEqual(self.get_counts()[self.tag_b], 0)

    def test_set_model_tags_incremental(self):
        # 给所有文件挂上模特,批量设置模特标签
        for fid in self.file_ids:
            self.db.add_file_model(fid, self.model_id)
        self.db.set_model_tags(self.model_id, [self.tag_b])
        self.assert_incremental_matches_recalc()
        self.assertEqual(self.get_counts()[self.tag_b], 3)
        # 部分文件已有直接标签,新增继承不重复计数
        self.db.add_file_tag(self.file_ids[0], self.tag_c)
        self.db.set_model_tags(self.model_id, [self.tag_b, self.tag_c])
        self.assert_incremental_matches_recalc()
        self.assertEqual(self.get_counts()[self.tag_c], 3)
        # 移除一个标签:直接带标签的文件仍计数
        self.db.set_model_tags(self.model_id, [self.tag_c])
        self.assert_incremental_matches_recalc()
        self.assertEqual(self.get_counts()[self.tag_b], 0)
        self.assertEqual(self.get_counts()[self.tag_c], 3)
        # 清空所有模特标签
        self.db.set_model_tags(self.model_id, [])
        self.assert_incremental_matches_recalc()
        self.assertEqual(self.get_counts()[self.tag_c], 1)

    def test_delete_file(self):
        self.db.add_file_model(self.file_ids[0], self.model_id)
        self.db.add_model_tag(self.model_id, self.tag_b)
        self.db.set_file_tags(self.file_ids[0], [self.tag_a])
        self.db.delete_file(self.file_ids[0])
        self.assert_incremental_matches_recalc()

    def test_delete_model_recalc_fallback(self):
        self.db.add_file_model(self.file_ids[0], self.model_id)
        self.db.add_model_tag(self.model_id, self.tag_b)
        self.db.delete_model(self.model_id)
        counts = self.get_counts()
        self.assertEqual(counts[self.tag_b], 0)

    def test_get_tags_with_category_name(self):
        self.db.add_file_tag(self.file_ids[0], self.tag_a)
        rows = self.db.get_tags_with_category_name(only_active=False)
        by_id = {r['id']: r for r in rows}
        self.assertEqual(by_id[self.tag_a]['file_count'], 1)
        self.assertEqual(by_id[self.tag_b]['file_count'], 0)
        # with_file_count=False 时不返回 file_count 字段
        rows_no_count = self.db.get_tags_with_category_name(only_active=False, with_file_count=False)
        self.assertNotIn('file_count', rows_no_count[0])


if __name__ == '__main__':
    unittest.main()
