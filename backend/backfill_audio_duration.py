import os
import sys
from datetime import datetime
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from data.database import Database

def _length_ms(p: str):
    try:
        ext = os.path.splitext(p)[1].lower()
    except Exception:
        ext = ""
    try:
        if ext == ".mp3":
            from mutagen.mp3 import MP3
            a = MP3(p)
            info = getattr(a, "info", None)
            length = getattr(info, "length", None)
            if length:
                return int(float(length) * 1000)
        elif ext == ".m4a":
            from mutagen.mp4 import MP4
            a = MP4(p)
            info = getattr(a, "info", None)
            length = getattr(info, "length", None)
            if length:
                return int(float(length) * 1000)
    except Exception:
        return None
    return None

def run(limit: int | None = None):
    db = Database()
    conn = db.get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, file_path, file_type, duration_ms
        FROM files
        WHERE (
            LOWER(COALESCE(file_type,'')) IN ('mp3','m4a')
            OR LOWER(COALESCE(file_path,'')) LIKE '%.mp3'
            OR LOWER(COALESCE(file_path,'')) LIKE '%.m4a'
        )
        AND (duration_ms IS NULL OR duration_ms <= 0)
        ORDER BY created_at DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    if limit is not None:
        rows = rows[:int(limit)]
    updated = 0
    skipped = 0
    now = datetime.now().isoformat()
    for r in rows:
        p = r.get("file_path") or ""
        if not p or not os.path.isfile(p):
            skipped += 1
            continue
        dur = _length_ms(p)
        if not dur or dur <= 0:
            skipped += 1
            continue
        cur.execute("""
            UPDATE files SET duration_ms = ?, updated_at = ? WHERE id = ?
        """, (int(dur), now, r["id"]))
        updated += 1
    conn.commit()
    conn.close()
    print(f"updated={updated} skipped={skipped} total={len(rows)}")

if __name__ == "__main__":
    n = None
    if len(sys.argv) >= 2:
        try:
            n = int(sys.argv[1])
        except Exception:
            n = None
    run(n)
