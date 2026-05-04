import argparse
import os
import sqlite3
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.data.database import Database


def main():
    parser = argparse.ArgumentParser(description="初始化图片/视频预制表")
    parser.add_argument("--db-path", default=None, help="SQLite 数据库文件路径")
    args = parser.parse_args()

    db = Database(db_path=args.db_path)
    conn = sqlite3.connect(db.db_path)
    try:
        cursor = conn.cursor()
        for table in ("image_presets", "video_presets"):
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"{table}: ok, rows={count}")
    finally:
        conn.close()

    print(f"preset migration finished: {os.path.abspath(db.db_path)}")


if __name__ == "__main__":
    main()
