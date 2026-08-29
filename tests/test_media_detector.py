import os
import sqlite3
import tempfile
import unittest

from backend.data.database import Database
from backend.services.media_detector import (
    MEDIA_KIND_AUDIO,
    MEDIA_KIND_IMAGE,
    MEDIA_KIND_UNKNOWN,
    MEDIA_KIND_VIDEO,
    detect_media_file,
)


class MediaDetectorUnitTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = self.temp_dir.name

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write(self, name, data):
        path = os.path.join(self.root, name)
        with open(path, 'wb') as fh:
            fh.write(data)
        return path

    def test_content_signature_detection(self):
        cases = [
            ('a.png', b'\x89PNG\r\n\x1a\n' + b'0' * 16, MEDIA_KIND_IMAGE, 'png'),
            ('b.bin', b'\xff\xd8\xff\xe0' + b'0' * 16, MEDIA_KIND_IMAGE, 'jpg'),
            ('c.mp3', b'ID3' + b'0' * 32, MEDIA_KIND_AUDIO, 'mp3'),
            ('d.mp4', b'\x00\x00\x00\x18ftypmp42' + b'0' * 16, MEDIA_KIND_VIDEO, 'mp4'),
            ('e.m4a', b'\x00\x00\x00\x18ftypM4A ' + b'0' * 16, MEDIA_KIND_AUDIO, 'm4a'),
        ]
        for name, data, expected_kind, expected_fmt in cases:
            path = self._write(name, data)
            info = detect_media_file(path)
            self.assertEqual(info['kind'], expected_kind, name)
            self.assertEqual(info['format'], expected_fmt, name)
            self.assertEqual(info['detected_by'], 'content', name)

    def test_extension_fallback(self):
        path = self._write('cover.jpg', b'not really a jpeg')
        info = detect_media_file(path)
        self.assertEqual(info['kind'], MEDIA_KIND_IMAGE)
        self.assertEqual(info['detected_by'], 'extension')

    def test_unknown_file_is_unknown(self):
        path = self._write('random.txt', b'plain text')
        info = detect_media_file(path)
        self.assertEqual(info['kind'], MEDIA_KIND_UNKNOWN)


class DatabaseMediaKindTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_add_file_detects_and_filters(self):
        db_path = os.path.join(self.temp_dir.name, 'detect.db')
        db = Database(db_path=db_path, background_count_repair=False)

        png = os.path.join(self.temp_dir.name, 'a.png')
        with open(png, 'wb') as fh:
            fh.write(b'\x89PNG\r\n\x1a\n' + b'0' * 16)
        mp3 = os.path.join(self.temp_dir.name, 'b.mp3')
        with open(mp3, 'wb') as fh:
            fh.write(b'ID3' + b'0' * 16)

        png_id = db.add_file(png)
        mp3_id = db.add_file(mp3)
        self.assertEqual(db.get_file_by_id(png_id)['media_kind'], MEDIA_KIND_IMAGE)
        self.assertEqual(db.get_file_by_id(mp3_id)['media_kind'], MEDIA_KIND_AUDIO)

        audio_rows = db.query_files_with_filters(media_kind=MEDIA_KIND_AUDIO, order='recent')
        self.assertEqual([r['id'] for r in audio_rows], [mp3_id])
        image_rows = db.query_files_with_filters(media_kind=MEDIA_KIND_IMAGE, order='recent')
        self.assertEqual([r['id'] for r in image_rows], [png_id])

    def test_batch_update_media_kind(self):
        db_path = os.path.join(self.temp_dir.name, 'batch.db')
        db = Database(db_path=db_path, background_count_repair=False)

        png = os.path.join(self.temp_dir.name, 'a.png')
        with open(png, 'wb') as fh:
            fh.write(b'\x89PNG\r\n\x1a\n' + b'0' * 16)
        mp3 = os.path.join(self.temp_dir.name, 'b.mp3')
        with open(mp3, 'wb') as fh:
            fh.write(b'ID3' + b'0' * 16)
        vid = os.path.join(self.temp_dir.name, 'c.mp4')
        with open(vid, 'wb') as fh:
            fh.write(b'\x00\x00\x00\x18ftypmp42' + b'0' * 16)

        ids = [db.add_file(png), db.add_file(mp3), db.add_file(vid)]
        updated = db.update_files_media_kind(ids, MEDIA_KIND_UNKNOWN)
        self.assertEqual(updated, 3)
        for file_id in ids:
            self.assertEqual(db.get_file_by_id(file_id)['media_kind'], MEDIA_KIND_UNKNOWN)

        updated = db.update_files_media_kind(ids[:2], MEDIA_KIND_IMAGE)
        self.assertEqual(updated, 2)
        self.assertEqual(db.get_file_by_id(ids[0])['media_kind'], MEDIA_KIND_IMAGE)
        self.assertEqual(db.get_file_by_id(ids[1])['media_kind'], MEDIA_KIND_IMAGE)
        self.assertEqual(db.get_file_by_id(ids[2])['media_kind'], MEDIA_KIND_UNKNOWN)

    def test_existing_table_backfill(self):
        db_path = os.path.join(self.temp_dir.name, 'backfill.db')
        conn = sqlite3.connect(db_path)
        conn.executescript('''
            CREATE TABLE files (
                id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL UNIQUE,
                file_name TEXT NOT NULL,
                original_file_name TEXT,
                file_size INTEGER,
                md5 TEXT,
                file_type TEXT,
                thumbnail_path TEXT,
                image_width INTEGER,
                image_height INTEGER,
                video_width INTEGER,
                video_height INTEGER,
                duration_ms INTEGER,
                heat_value INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            INSERT INTO files (id, file_path, file_name, file_type, created_at, updated_at)
            VALUES ('1', 'data/a.jpg', 'a.jpg', 'jpg', '2026-01-01', '2026-01-01');
            INSERT INTO files (id, file_path, file_name, file_type, created_at, updated_at)
            VALUES ('2', 'data/b.mp3', 'b.mp3', 'mp3', '2026-01-01', '2026-01-01');
        ''')
        conn.commit()
        conn.close()

        db = Database(db_path=db_path, background_count_repair=False)
        rows = {r['id']: r['media_kind'] for r in db.get_all_files(10)}
        self.assertEqual(rows, {'1': MEDIA_KIND_IMAGE, '2': MEDIA_KIND_AUDIO})


if __name__ == '__main__':
    unittest.main()
