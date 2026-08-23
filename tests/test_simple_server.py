"""simple_server 安全加固回归测试：黑名单后缀与回环绑定。"""
import os
import tempfile
import unittest

from backend.simple_server import _is_blacklisted


class SimpleServerBlacklistTestCase(unittest.TestCase):
    def test_blacklists_database_and_backup_files(self):
        for name in ("image_classifier.db", "image_classifier.sqlite", "backup.sqlite3",
                     "image_classifier.db-wal", "image_classifier.db-shm", "archive.bak",
                     "DATA/IMAGES.DB"):
            self.assertTrue(_is_blacklisted(name), f"{name} 应被黑名单拦截")

    def test_allows_media_files(self):
        for name in ("sample.jpg", "video.mp4", "audio.mp3", "sub/dir/photo.PNG", "x.webm"):
            self.assertFalse(_is_blacklisted(name), f"{name} 不应被拦截")

    def test_blacklist_is_case_insensitive(self):
        self.assertTrue(_is_blacklisted("IMAGE_CLASSIFIER.DB"))
        self.assertFalse(_is_blacklisted("photo.DB.JPG"))  # 仅后缀结尾，非子串


if __name__ == "__main__":
    unittest.main()
