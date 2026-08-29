import sqlite3
import os
import uuid
import hashlib
import random
import base64
import json
import secrets
import threading
import time as _time
from datetime import datetime
from pathlib import Path
from PIL import Image

# 与 simple_server 的 dual import 路径保持一致：
# 直接以 data.database 运行时用 services.media_detector，作为 backend.data.database 导入时用 backend.services.media_detector。
try:
    from backend.services.media_detector import (  # type: ignore
        MEDIA_KIND_AUDIO,
        MEDIA_KIND_IMAGE,
        MEDIA_KIND_UNKNOWN,
        MEDIA_KIND_VIDEO,
        AUDIO_EXTENSIONS,
        IMAGE_EXTENSIONS,
        VIDEO_EXTENSIONS,
        detect_media_file,
        media_kind_from_extension,
    )
except Exception:  # pragma: no cover - 仅在旧式 data.* 导入路径下触发
    from services.media_detector import (  # type: ignore
        MEDIA_KIND_AUDIO,
        MEDIA_KIND_IMAGE,
        MEDIA_KIND_UNKNOWN,
        MEDIA_KIND_VIDEO,
        AUDIO_EXTENSIONS,
        IMAGE_EXTENSIONS,
        VIDEO_EXTENSIONS,
        detect_media_file,
        media_kind_from_extension,
    )


def compute_md5(file_path):
    """分块计算文件 MD5(4096 字节),返回 hexdigest。

    不做 try/except 兜底,由调用方决定异常策略(与两处原调用点行为一致)。
    """
    md5_hash = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            md5_hash.update(chunk)
    return md5_hash.hexdigest()


def get_data_root():
    """统一数据根解析：CW_DATA_ROOT → L:\\data（存在时）→ 项目 data。

    与 server.py 的 DATA_ROOT / open_helper 的 _get_data_root 保持一致，
    避免多处实现分叉导致相对路径解析不一致。
    """
    env = os.environ.get('CW_DATA_ROOT')
    if env and env.strip():
        return os.path.abspath(env.strip())
    candidate = r"L:\data"
    if os.path.isdir(candidate):
        return os.path.abspath(candidate)
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data"))


def resolve_abs(file_path, data_root=None):
    """DB 中存储的相对路径（data/...，相对数据根）解析为绝对路径；绝对路径原样返回。

    相对路径做 normpath + realpath 逃逸检查（防 data/../../ 或 symlink 指向数据根外），
    逃逸时返回 None（由调用方决定计数策略）。
    data_root 显式传入时优先（如 server.py 的 DATA_ROOT，可被测试 monkey-patch）。
    """
    if not file_path:
        return file_path
    root = os.path.abspath(data_root) if data_root else get_data_root()
    s = str(file_path).replace('\\', '/')
    if s.lower().startswith('data/'):
        joined = os.path.normpath(os.path.join(root, s[5:]))
        try:
            real_root = os.path.realpath(root)
            if os.path.commonpath([real_root, os.path.realpath(joined)]) != real_root:
                return None
        except ValueError:
            return None
        return joined
    return file_path


def to_rel(file_path, data_root=None):
    """数据根内的绝对路径 → data/ 相对路径（换盘符零迁移）；其余路径原样返回。"""
    if not file_path:
        return file_path
    s = str(file_path).replace('\\', '/')
    if s.lower().startswith('data/'):
        return file_path  # 已是相对
    ap = os.path.abspath(str(file_path))
    root = os.path.abspath(data_root) if data_root else get_data_root()
    try:
        if os.path.commonpath([root, ap]) == root:
            rel = os.path.relpath(ap, root)
            return os.path.join('data', rel)
    except ValueError:
        pass
    return file_path


try:
    import cv2  # 可选：仅用于视频元数据提取
except Exception:
    cv2 = None


class Database:
    """SQLite数据库管理类"""
    
    def __init__(self, db_path=None, background_count_repair=True):
        if db_path is None:
            env_db = os.environ.get('CW_DB_PATH')
            if env_db:
                db_path = env_db
            else:
                db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'image_classifier.db'))
        self.db_path = db_path
        # 确保数据库目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._needs_tag_count_recalc = False
        self._access_password_cache = (None, 0.0)
        self._true_random_count_cache = (None, 0.0)
        self._true_random_enabled_cache = (None, 0.0)
        self.init_database()
        # 迁移新增 file_count 列后,需要全量重算一次标签计数
        if self._needs_tag_count_recalc:
            self.recalc_tag_file_counts()
        # 启动兜底:后台全量重算一次,纠正任何历史漂移(幂等,不阻塞 UI)
        if background_count_repair:
            self._schedule_tag_count_repair()

    def _schedule_tag_count_repair(self):
        """后台线程全量重算标签计数,纠正增量遗漏/外部修改导致的漂移。

        每次启动都全量重算会无谓争抢磁盘 IO;记录上次修复时间,
        24 小时内只做一次(手动 /api/tags/recalc 不受影响)。
        """
        def _repair():
            try:
                last_raw = str(self.get_app_setting('last_tag_count_repair', '') or '').strip()
                if last_raw:
                    try:
                        last_at = datetime.fromisoformat(last_raw)
                        age_seconds = (datetime.now() - last_at).total_seconds()
                        if 0 <= age_seconds < 24 * 3600:
                            return
                    except ValueError:
                        pass
                self.recalc_tag_file_counts()
                self.set_app_setting('last_tag_count_repair', datetime.now().isoformat())
            except Exception as e:
                print(f"[database] 标签计数后台重算失败: {e}")
        threading.Thread(target=_repair, daemon=True).start()
    
    def get_connection(self):
        """获取数据库连接

        WAL 下 synchronous=NORMAL 可少刷盘且不会破坏一致性;
        temp_store=MEMORY 让排序临时 B 树优先用内存,避免查询排序反复写临时文件磨损磁盘。
        """
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        conn.execute('PRAGMA busy_timeout = 30000')
        conn.execute('PRAGMA synchronous = NORMAL')
        conn.execute('PRAGMA temp_store = MEMORY')
        return conn

    def transaction(self):
        """Context manager: yields a connection, commits on success,
        rolls back on exception, always closes."""
        from contextlib import contextmanager

        @contextmanager
        def _tx():
            conn = self.get_connection()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return _tx()

    def _query(self, sql, params=(), fetch='all'):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            if fetch == 'all':
                return [dict(r) for r in cursor.fetchall()]
            elif fetch == 'one':
                row = cursor.fetchone()
                return dict(row) if row else None
            return None
        finally:
            conn.close()

    def _execute(self, sql, params=()):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def _generate_guid(self):
        """生成不带横杠的GUID"""
        return uuid.uuid4().hex
    
    def init_database(self):
        """初始化数据库表结构（两段连接均 try/finally 保证异常时关闭）"""
        conn = self.get_connection()
        try:
            self._init_schema(conn)
        finally:
            conn.close()
        conn = self.get_connection()
        try:
            self._init_access_password(conn)
        finally:
            conn.close()

    def _init_schema(self, conn):
        """建表 + 迁移（连接由调用方关闭）"""
        cursor = conn.cursor()
        # WAL 模式：读写不互锁，避免多连接写锁竞争（设置持久化到数据库文件，后续连接自动生效）
        cursor.execute('PRAGMA journal_mode = WAL')
        
        # 检查是否需要迁移数据库
        self._migrate_database_if_needed(cursor)
        
        # 创建模特表（preview_image_path 实际存储 base64 编码的图片数据，非文件路径）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS models (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                preview_image_path TEXT,
                model_type TEXT,
                model_type_id TEXT,
                is_active INTEGER DEFAULT 1,
                description TEXT,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        
        # 创建标签表（preview_image_path 实际存储 base64 编码的图片数据，非文件路径）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tags (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                preview_image_path TEXT,
                is_active INTEGER DEFAULT 1,
                description TEXT,
                sort_order INTEGER DEFAULT 0,
                category_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                file_count INTEGER DEFAULT 0
            )
        ''')
        
        # 检查并添加preview_image_path字段（如果不存在）
        try:
            cursor.execute("PRAGMA table_info(models)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'preview_image_path' not in columns:
                cursor.execute('ALTER TABLE models ADD COLUMN preview_image_path TEXT')
            if 'model_type' not in columns:
                cursor.execute('ALTER TABLE models ADD COLUMN model_type TEXT')
            if 'model_type_id' not in columns:
                cursor.execute('ALTER TABLE models ADD COLUMN model_type_id TEXT')
            if 'is_active' not in columns:
                cursor.execute('ALTER TABLE models ADD COLUMN is_active INTEGER DEFAULT 1')
                cursor.execute('UPDATE models SET is_active = 1 WHERE is_active IS NULL')
            if 'description' not in columns:
                cursor.execute('ALTER TABLE models ADD COLUMN description TEXT')
        except Exception:
            pass
        
        try:
            cursor.execute("PRAGMA table_info(tags)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'preview_image_path' not in columns:
                cursor.execute('ALTER TABLE tags ADD COLUMN preview_image_path TEXT')
            if 'is_active' not in columns:
                cursor.execute('ALTER TABLE tags ADD COLUMN is_active INTEGER DEFAULT 1')
                cursor.execute('UPDATE tags SET is_active = 1 WHERE is_active IS NULL')
            if 'description' not in columns:
                cursor.execute('ALTER TABLE tags ADD COLUMN description TEXT')
            if 'category_id' not in columns:
                cursor.execute('ALTER TABLE tags ADD COLUMN category_id TEXT')
            if 'file_count' not in columns:
                cursor.execute('ALTER TABLE tags ADD COLUMN file_count INTEGER DEFAULT 0')
                self._needs_tag_count_recalc = True
        except Exception:
            pass
        
        # 检查并添加sort_order字段（如果不存在）
        try:
            cursor.execute("PRAGMA table_info(models)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'sort_order' not in columns:
                cursor.execute('ALTER TABLE models ADD COLUMN sort_order INTEGER DEFAULT 0')
                # 为现有记录设置sort_order
                cursor.execute('UPDATE models SET sort_order = (SELECT COUNT(*) FROM models m2 WHERE m2.id <= models.id) WHERE sort_order = 0 OR sort_order IS NULL')
        except Exception:
            pass
        
        try:
            cursor.execute("PRAGMA table_info(tags)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'sort_order' not in columns:
                cursor.execute('ALTER TABLE tags ADD COLUMN sort_order INTEGER DEFAULT 0')
                # 为现有记录设置sort_order
                cursor.execute('UPDATE tags SET sort_order = (SELECT COUNT(*) FROM tags t2 WHERE t2.id <= tags.id) WHERE sort_order = 0 OR sort_order IS NULL')
        except Exception:
            pass
        
        # 创建文件表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS files (
                id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL UNIQUE,
                file_name TEXT NOT NULL,
                file_size INTEGER,
                md5 TEXT,
                file_type TEXT,
                media_kind TEXT,
                thumbnail_path TEXT,
                image_width INTEGER,
                image_height INTEGER,
                video_width INTEGER,
                video_height INTEGER,
                duration_ms INTEGER,
                heat_value INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        
        # 检查并添加md5字段（如果不存在）
        try:
            cursor.execute("PRAGMA table_info(files)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'md5' not in columns:
                cursor.execute('ALTER TABLE files ADD COLUMN md5 TEXT')
        except Exception:
            pass
        
        # 检查并添加original_file_name字段（如果不存在）
        try:
            cursor.execute("PRAGMA table_info(files)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'original_file_name' not in columns:
                cursor.execute('ALTER TABLE files ADD COLUMN original_file_name TEXT')
                # 对于现有记录，将file_name的值复制到original_file_name
                cursor.execute('UPDATE files SET original_file_name = file_name WHERE original_file_name IS NULL')
        except Exception:
            pass

        # 检查并添加file_type字段（如果不存在）
        try:
            cursor.execute("PRAGMA table_info(files)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'file_type' not in columns:
                cursor.execute('ALTER TABLE files ADD COLUMN file_type TEXT')
        except Exception:
            pass

        # 检查并添加 media_kind 字段（图片/音频/视频自动识别结果）
        try:
            cursor.execute("PRAGMA table_info(files)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'media_kind' not in columns:
                cursor.execute('ALTER TABLE files ADD COLUMN media_kind TEXT')
            # 存量记录按 file_type 扩展名回填空缺值；新增文件在 add_file 时已做内容识别。
            # 这里对 NULL 幂等补齐，兼容列已存在但尚未回填的中间状态。
            def _backfill_kind(kind, extensions):
                values = sorted({str(e).lower().lstrip('.') for e in extensions if str(e).lstrip('.')})
                if not values:
                    return
                placeholders = ','.join(['?'] * len(values))
                cursor.execute(
                    f"UPDATE files SET media_kind = ? WHERE media_kind IS NULL "
                    f"AND LOWER(COALESCE(file_type, '')) IN ({placeholders})",
                    [kind] + values,
                )
            _backfill_kind(MEDIA_KIND_IMAGE, IMAGE_EXTENSIONS)
            _backfill_kind(MEDIA_KIND_VIDEO, VIDEO_EXTENSIONS)
            _backfill_kind(MEDIA_KIND_AUDIO, AUDIO_EXTENSIONS)
            cursor.execute("UPDATE files SET media_kind = ? WHERE media_kind IS NULL", [MEDIA_KIND_UNKNOWN])
        except Exception:
            pass

        # 检查并添加thumbnail_path字段（如果不存在）
        try:
            cursor.execute("PRAGMA table_info(files)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'thumbnail_path' not in columns:
                cursor.execute('ALTER TABLE files ADD COLUMN thumbnail_path TEXT')
        except Exception:
            pass

        # 检查并添加图片尺寸字段（如果不存在）
        try:
            cursor.execute("PRAGMA table_info(files)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'image_width' not in columns:
                cursor.execute('ALTER TABLE files ADD COLUMN image_width INTEGER')
            if 'image_height' not in columns:
                cursor.execute('ALTER TABLE files ADD COLUMN image_height INTEGER')
        except Exception:
            pass

        # 检查并添加视频尺寸与时长字段（如果不存在）
        try:
            cursor.execute("PRAGMA table_info(files)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'video_width' not in columns:
                cursor.execute('ALTER TABLE files ADD COLUMN video_width INTEGER')
            if 'video_height' not in columns:
                cursor.execute('ALTER TABLE files ADD COLUMN video_height INTEGER')
            if 'duration_ms' not in columns:
                cursor.execute('ALTER TABLE files ADD COLUMN duration_ms INTEGER')
        except Exception:
            pass
        
        # 检查并添加热度与推荐字段（如果不存在）
        try:
            cursor.execute("PRAGMA table_info(files)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'heat_value' not in columns:
                cursor.execute('ALTER TABLE files ADD COLUMN heat_value INTEGER DEFAULT 0')
                cursor.execute('UPDATE files SET heat_value = 0 WHERE heat_value IS NULL')
        except Exception:
            pass
        
        # 迁移：移除 recommend_value 字段（如果存在）
        try:
            cursor.execute("PRAGMA table_info(files)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'recommend_value' in columns:
                self._migrate_remove_recommend_value(cursor)
        except Exception:
            pass
        
        # 迁移：移除image_data字段，添加md5字段（如果image_data存在）
        try:
            cursor.execute("PRAGMA table_info(files)")
            columns = [col[1] for col in cursor.fetchall()]
            if 'image_data' in columns:
                # 如果存在image_data字段，需要迁移
                # SQLite不支持直接删除列，需要重建表
                self._migrate_remove_image_data(cursor)
        except Exception:
            pass
        
        # 创建文件和模特关联表（一对多）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_models (
                id TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                model_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE,
                UNIQUE(file_id, model_id)
            )
        ''')
        
        # 创建文件和标签关联表（一对多）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS file_tags (
                id TEXT PRIMARY KEY,
                file_id TEXT NOT NULL,
                tag_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE,
                UNIQUE(file_id, tag_id)
            )
        ''')
        
        # 创建模特和标签关联表（一对多）
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS model_tags (
                id TEXT PRIMARY KEY,
                model_id TEXT NOT NULL,
                tag_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (model_id) REFERENCES models(id) ON DELETE CASCADE,
                FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE,
                UNIQUE(model_id, tag_id)
            )
        ''')
        
        # 创建索引以提高查询性能
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_models_file_id ON file_models(file_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_models_model_id ON file_models(model_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_tags_file_id ON file_tags(file_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_tags_tag_id ON file_tags(tag_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_model_tags_model_id ON model_tags(model_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_model_tags_tag_id ON model_tags(tag_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tags_category_id ON tags(category_id)')
        # 复合排序索引:让 ORDER BY 直接走索引,避免每次查询都全表扫描 + 临时 B 树排序。
        # 第二个键 id 保持 ASC,与现有 ORDER BY (..., f.id) 一致。
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_created_at_id ON files(created_at DESC, id ASC)')
        cursor.execute('DROP INDEX IF EXISTS idx_files_created_at')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_heat_value ON files(heat_value)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_models_sort_order ON models(sort_order)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tags_sort_order ON tags(sort_order)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_file_type ON files(file_type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_media_kind ON files(media_kind)')
        # COALESCE 表达式索引必须与查询中的 ORDER BY 表达式逐字一致,SQLite 才能命中。
        # 旧单列 duration 索引已由下方复合索引覆盖排序需求;heat 单列索引保留给范围筛选。
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_duration_order ON files(COALESCE(duration_ms, 0) DESC, created_at DESC, id ASC)')
            cursor.execute('DROP INDEX IF EXISTS idx_files_duration_ms')
        except sqlite3.OperationalError:
            # 极旧 SQLite 不支持表达式索引时保留旧索引,排序仍可工作
            pass
        try:
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_heat_order ON files(COALESCE(heat_value, 0) DESC, created_at DESC, id ASC)')
        except sqlite3.OperationalError:
            pass

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tag_categories (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                is_active INTEGER DEFAULT 1,
                description TEXT,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tag_categories_sort ON tag_categories(sort_order)')

        # 模特类型表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS model_types (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                is_active INTEGER DEFAULT 1,
                description TEXT,
                sort_order INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_model_types_sort ON model_types(sort_order)')
        self._ensure_preset_tables(cursor)
        self._ensure_true_random_cache_tables(cursor)
        self._ensure_app_settings_table(cursor)
        
        conn.commit()

    def _init_access_password(self, conn):
        """访问密码表 + 静态密码覆盖（连接由调用方关闭）"""
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS access_password (
                id TEXT PRIMARY KEY,
                code TEXT,
                created_at TEXT NOT NULL
            )
        ''')
        cursor.execute('SELECT id FROM access_password WHERE id = ?', ('current',))
        row = cursor.fetchone()
        if not row:
            now = datetime.now().isoformat()
            code = secrets.token_urlsafe(6)
            cursor.execute('INSERT INTO access_password (id, code, created_at) VALUES (?, ?, ?)', ('current', code, now))
        # 支持静态密码（仅用于本地/开发场景）
        try:
            static_code = os.environ.get('CW_PASSWORD_STATIC')
            if static_code and static_code.strip():
                now = datetime.now().isoformat()
                cursor.execute('UPDATE access_password SET code = ?, created_at = ? WHERE id = ?', (static_code.strip(), now, 'current'))
        except Exception:
            pass
        conn.commit()
        # 初始密码已变化,清空验证缓存,下一次鉴权从 DB 读取
        self._access_password_cache = (None, 0.0)

    def _migrate_database_if_needed(self, cursor):
        """迁移数据库：将INTEGER ID转换为GUID"""
        # 检查是否已经迁移过（通过检查models表的id字段类型）
        try:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='models'")
            if cursor.fetchone():
                cursor.execute("PRAGMA table_info(models)")
                columns = cursor.fetchall()
                # 如果表存在且id字段是INTEGER类型，需要迁移
                if columns:
                    id_column = next((col for col in columns if col[1] == 'id'), None)
                    if id_column and id_column[2].upper() == 'INTEGER':
                        self._perform_migration(cursor)
        except Exception as e:
            # 表不存在或出错，不需要迁移
            pass
    
    def _backup_db_file(self):
        """迁移前备份数据库文件，防止迁移中途失败导致数据损坏。"""
        try:
            import shutil
            if self.db_path and os.path.isfile(self.db_path):
                backup_path = self.db_path + '.bak'
                shutil.copy2(self.db_path, backup_path)
                print(f"[database] 迁移前已备份数据库 -> {backup_path}")
        except Exception as e:
            print(f"[database] 数据库备份失败（继续迁移）: {e}")

    def _ensure_new_table_columns(self, cursor, old_table, new_table, exclude_cols=()):
        """读取旧表实际列，给新表 ALTER TABLE 补齐缺失列，防止迁移丢列。"""
        old_info = cursor.execute(f'PRAGMA table_info({old_table})').fetchall()
        new_cols = [r[1] for r in cursor.execute(f'PRAGMA table_info({new_table})').fetchall()]
        for info in old_info:
            col, coltype = info[1], info[2]
            if col in new_cols or col == 'id' or col in exclude_cols:
                continue
            cursor.execute(f'ALTER TABLE {new_table} ADD COLUMN "{col}" {coltype or "TEXT"}')
        return [r[1] for r in old_info]

    def _copy_rows_dynamic(self, cursor, old_table, new_table, exclude_cols=(), id_map=None):
        """动态列拷贝：按旧表实际列（去掉 exclude_cols）逐行复制到新表。
        id_map 非空时 id 替换为新 GUID 并记录 old->new 映射。"""
        old_cols = self._ensure_new_table_columns(cursor, old_table, new_table, exclude_cols)
        new_cols = [r[1] for r in cursor.execute(f'PRAGMA table_info({new_table})').fetchall()]
        copy_cols = [c for c in old_cols if c in new_cols and c not in exclude_cols]
        if not copy_cols:
            return
        col_sql = ', '.join(f'"{c}"' for c in copy_cols)
        ph = ', '.join('?' for _ in copy_cols)
        insert_sql = f'INSERT INTO {new_table} ({col_sql}) VALUES ({ph})'
        for row in cursor.execute(f'SELECT * FROM {old_table}').fetchall():
            if id_map is not None:
                new_id = self._generate_guid()
                id_map[row['id']] = new_id
                vals = [row[c] for c in copy_cols]
                vals[copy_cols.index('id')] = new_id
            else:
                vals = [row[c] for c in copy_cols]
            cursor.execute(insert_sql, vals)

    def _migrate_remove_image_data(self, cursor):
        """迁移数据库：移除image_data字段，添加md5字段"""
        try:
            self._backup_db_file()
            # 禁用外键检查（SQLite默认可能未启用，但为了安全起见）
            cursor.execute('PRAGMA foreign_keys = OFF')

            # 创建新表（不包含image_data字段，包含md5字段）
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS files_new (
                    id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL UNIQUE,
                    file_name TEXT NOT NULL,
                    file_size INTEGER,
                    md5 TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')

            # 动态列复制：保留旧表除 image_data 外的全部列（含 thumbnail/heat/duration 等），md5 默认 NULL
            self._copy_rows_dynamic(cursor, 'files', 'files_new', exclude_cols=('image_data',))

            # 删除旧表并重命名新表
            cursor.execute('DROP TABLE files')
            cursor.execute('ALTER TABLE files_new RENAME TO files')

            # 重新启用外键检查
            cursor.execute('PRAGMA foreign_keys = ON')

            # 重新创建索引（如果它们不存在）
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_models_file_id ON file_models(file_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_models_model_id ON file_models(model_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_tags_file_id ON file_tags(file_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_tags_tag_id ON file_tags(tag_id)')
        except Exception as e:
            # 迁移失败，回滚
            raise Exception(f"移除image_data字段迁移失败: {str(e)}")
    
    def _perform_migration(self, cursor):
        """执行数据库迁移：将INTEGER ID转换为GUID"""
        try:
            self._backup_db_file()
            # 创建新表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS models_new (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tags_new (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS files_new (
                    id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL UNIQUE,
                    file_name TEXT NOT NULL,
                    file_size INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS file_models_new (
                    id TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(file_id, model_id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS file_tags_new (
                    id TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL,
                    tag_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(file_id, tag_id)
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS model_tags_new (
                    id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    tag_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(model_id, tag_id)
                )
            ''')
            
            # 迁移数据：创建ID映射
            model_id_map = {}  # old_id -> new_guid
            tag_id_map = {}    # old_id -> new_guid
            file_id_map = {}   # old_id -> new_guid

            # 迁移models表（动态列复制，保留 sort_order/is_active/model_type 等全部列）
            try:
                self._copy_rows_dynamic(cursor, 'models', 'models_new', id_map=model_id_map)
            except Exception:
                pass  # 表可能不存在

            # 迁移tags表
            try:
                self._copy_rows_dynamic(cursor, 'tags', 'tags_new', id_map=tag_id_map)
            except Exception:
                pass  # 表可能不存在

            # 迁移files表
            try:
                self._copy_rows_dynamic(cursor, 'files', 'files_new', id_map=file_id_map)
            except Exception:
                pass  # 表可能不存在
            
            # 迁移file_models表
            try:
                cursor.execute('SELECT * FROM file_models')
                for row in cursor.fetchall():
                    new_id = self._generate_guid()
                    new_file_id = file_id_map.get(row['file_id'])
                    new_model_id = model_id_map.get(row['model_id'])
                    if new_file_id and new_model_id:
                        cursor.execute('''
                            INSERT INTO file_models_new (id, file_id, model_id, created_at)
                            VALUES (?, ?, ?, ?)
                        ''', (new_id, new_file_id, new_model_id, row['created_at']))
            except Exception:
                pass  # 表可能不存在
            
            # 迁移file_tags表
            try:
                cursor.execute('SELECT * FROM file_tags')
                for row in cursor.fetchall():
                    new_id = self._generate_guid()
                    new_file_id = file_id_map.get(row['file_id'])
                    new_tag_id = tag_id_map.get(row['tag_id'])
                    if new_file_id and new_tag_id:
                        cursor.execute('''
                            INSERT INTO file_tags_new (id, file_id, tag_id, created_at)
                            VALUES (?, ?, ?, ?)
                        ''', (new_id, new_file_id, new_tag_id, row['created_at']))
            except Exception:
                pass  # 表可能不存在
            
            # 迁移model_tags表
            try:
                cursor.execute('SELECT * FROM model_tags')
                for row in cursor.fetchall():
                    new_id = self._generate_guid()
                    new_model_id = model_id_map.get(row['model_id'])
                    new_tag_id = tag_id_map.get(row['tag_id'])
                    if new_model_id and new_tag_id:
                        cursor.execute('''
                            INSERT INTO model_tags_new (id, model_id, tag_id, created_at)
                            VALUES (?, ?, ?, ?)
                        ''', (new_id, new_model_id, new_tag_id, row['created_at']))
            except Exception:
                pass  # 表可能不存在
            
            # 删除旧表并重命名新表
            cursor.execute('DROP TABLE IF EXISTS model_tags')
            cursor.execute('DROP TABLE IF EXISTS file_tags')
            cursor.execute('DROP TABLE IF EXISTS file_models')
            cursor.execute('DROP TABLE IF EXISTS files')
            cursor.execute('DROP TABLE IF EXISTS tags')
            cursor.execute('DROP TABLE IF EXISTS models')
            
            cursor.execute('ALTER TABLE models_new RENAME TO models')
            cursor.execute('ALTER TABLE tags_new RENAME TO tags')
            cursor.execute('ALTER TABLE files_new RENAME TO files')
            cursor.execute('ALTER TABLE file_models_new RENAME TO file_models')
            cursor.execute('ALTER TABLE file_tags_new RENAME TO file_tags')
            cursor.execute('ALTER TABLE model_tags_new RENAME TO model_tags')
        except Exception as e:
            # 迁移失败，回滚（SQLite会自动回滚未提交的事务）
            raise Exception(f"数据库迁移失败: {str(e)}")

    def _ensure_preset_tables(self, cursor):
        for media_type in ('image', 'video'):
            table = self._get_preset_table_name(media_type)
            cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS {table} (
                    preset_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    sort_order INTEGER NOT NULL,
                    tags TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    is_deleted INTEGER DEFAULT 0,
                    CHECK (media_type = '{media_type}')
                )
            ''')
            cursor.execute(f'CREATE INDEX IF NOT EXISTS idx_{table}_sort_order ON {table}(sort_order)')
            cursor.execute(
                f'''
                CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_active_name
                ON {table}(name)
                WHERE is_deleted = 0
                '''
            )
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [col[1] for col in cursor.fetchall()]
            if 'is_deleted' not in columns:
                cursor.execute(f'ALTER TABLE {table} ADD COLUMN is_deleted INTEGER DEFAULT 0')

    def _ensure_true_random_cache_tables(self, cursor):
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS true_random_cache (
                cache_id TEXT PRIMARY KEY,
                cache_key TEXT NOT NULL,
                file_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE,
                UNIQUE(cache_key, file_id)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_true_random_cache_key_file ON true_random_cache(cache_key, file_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_true_random_cache_file_key ON true_random_cache(file_id, cache_key)')

    def _ensure_app_settings_table(self, cursor):
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        ''')
        now = datetime.now().isoformat()
        cursor.execute(
            '''
            INSERT INTO app_settings (setting_key, setting_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_key) DO NOTHING
            ''',
            ('true_random_cache_enabled', '1', now)
        )

    def _get_preset_table_name(self, media_type):
        media_type = (media_type or '').strip().lower()
        if media_type == 'image':
            return 'image_presets'
        if media_type == 'video':
            return 'video_presets'
        raise ValueError("media_type 仅支持 image 或 video")

    def _normalize_preset_name(self, name):
        value = (name or '').strip()
        if not value:
            raise ValueError('预制名称不能为空')
        if len(value) > 50:
            raise ValueError('预制名称不能超过 50 个字符')
        return value

    def _normalize_preset_tags(self, tags):
        if tags is None:
            raise ValueError('tags 不能为空')
        if not isinstance(tags, list):
            raise ValueError('tags 必须为列表')
        normalized = []
        seen = set()
        for tag_id in tags:
            tag_value = str(tag_id or '').strip()
            if not tag_value or tag_value in seen:
                continue
            seen.add(tag_value)
            normalized.append(tag_value)
        return normalized

    def _validate_preset_tags(self, cursor, tag_ids):
        normalized = self._normalize_preset_tags(tag_ids)
        if not normalized:
            return normalized
        placeholders = ','.join('?' for _ in normalized)
        cursor.execute(
            f'''
            SELECT id
            FROM tags
            WHERE is_active = 1 AND id IN ({placeholders})
            ''',
            normalized
        )
        existing_ids = {row['id'] for row in cursor.fetchall()}
        missing = [tag_id for tag_id in normalized if tag_id not in existing_ids]
        if missing:
            raise ValueError(f"存在非法标签: {', '.join(missing)}")
        return normalized

    def _deserialize_preset(self, row):
        if not row:
            return None
        item = dict(row)
        try:
            item['tags'] = json.loads(item.get('tags') or '[]')
        except Exception:
            item['tags'] = []
        item['sort_order'] = int(item.get('sort_order') or 0)
        item['is_deleted'] = int(item.get('is_deleted') or 0)
        return item

    def _reindex_presets(self, cursor, table, ordered_ids):
        now = datetime.now().isoformat()
        for idx, preset_id in enumerate(ordered_ids):
            cursor.execute(
                f'''
                UPDATE {table}
                SET sort_order = ?, updated_at = ?
                WHERE preset_id = ?
                ''',
                (idx, now, preset_id)
            )

    def _get_active_preset_ids(self, cursor, table, exclude_preset_id=None):
        if exclude_preset_id:
            cursor.execute(
                f'''
                SELECT preset_id
                FROM {table}
                WHERE is_deleted = 0 AND preset_id != ?
                ORDER BY sort_order ASC, created_at ASC, preset_id ASC
                ''',
                (exclude_preset_id,)
            )
        else:
            cursor.execute(
                f'''
                SELECT preset_id
                FROM {table}
                WHERE is_deleted = 0
                ORDER BY sort_order ASC, created_at ASC, preset_id ASC
                '''
            )
        return [row['preset_id'] for row in cursor.fetchall()]

    def create_preset(self, media_type, name, sort_order, tags):
        media_type = (media_type or '').strip().lower()
        table = self._get_preset_table_name(media_type)
        normalized_name = self._normalize_preset_name(name)
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('BEGIN IMMEDIATE')
            validated_tags = self._validate_preset_tags(cursor, tags)
            cursor.execute(
                f'SELECT preset_id FROM {table} WHERE is_deleted = 0 AND lower(name) = lower(?)',
                (normalized_name,)
            )
            if cursor.fetchone():
                raise ValueError(f"预制名称 '{normalized_name}' 已存在")
            active_ids = self._get_active_preset_ids(cursor, table)
            try:
                desired_order = int(sort_order)
            except Exception:
                desired_order = len(active_ids)
            desired_order = max(0, min(desired_order, len(active_ids)))
            preset_id = self._generate_guid()
            now = datetime.now().isoformat()
            cursor.execute(
                f'''
                INSERT INTO {table} (
                    preset_id, name, sort_order, tags, media_type, created_at, updated_at, is_deleted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                ''',
                (
                    preset_id,
                    normalized_name,
                    desired_order,
                    json.dumps(validated_tags, ensure_ascii=False),
                    media_type,
                    now,
                    now,
                )
            )
            active_ids.insert(desired_order, preset_id)
            self._reindex_presets(cursor, table, active_ids)
            conn.commit()
            return preset_id
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def list_presets(self, media_type):
        media_type = (media_type or '').strip().lower()
        table = self._get_preset_table_name(media_type)
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            f'''
            SELECT preset_id, name, sort_order, tags, media_type, created_at, updated_at, is_deleted
            FROM {table}
            WHERE is_deleted = 0
            ORDER BY sort_order ASC, created_at ASC, preset_id ASC
            '''
        )
        rows = [self._deserialize_preset(row) for row in cursor.fetchall()]
        conn.close()
        return rows

    def get_preset(self, media_type, preset_id, include_deleted=False):
        media_type = (media_type or '').strip().lower()
        table = self._get_preset_table_name(media_type)
        conn = self.get_connection()
        cursor = conn.cursor()
        if include_deleted:
            cursor.execute(
                f'''
                SELECT preset_id, name, sort_order, tags, media_type, created_at, updated_at, is_deleted
                FROM {table}
                WHERE preset_id = ?
                ''',
                (preset_id,)
            )
        else:
            cursor.execute(
                f'''
                SELECT preset_id, name, sort_order, tags, media_type, created_at, updated_at, is_deleted
                FROM {table}
                WHERE preset_id = ? AND is_deleted = 0
                ''',
                (preset_id,)
            )
        row = cursor.fetchone()
        conn.close()
        return self._deserialize_preset(row)

    def update_preset(self, media_type, preset_id, name=None, sort_order=None, tags=None):
        media_type = (media_type or '').strip().lower()
        table = self._get_preset_table_name(media_type)
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('BEGIN IMMEDIATE')
            cursor.execute(
                f'''
                SELECT preset_id, name, sort_order, tags, media_type, created_at, updated_at, is_deleted
                FROM {table}
                WHERE preset_id = ? AND is_deleted = 0
                ''',
                (preset_id,)
            )
            current = cursor.fetchone()
            if not current:
                raise KeyError('预制不存在')
            current_item = self._deserialize_preset(current)
            next_name = current_item['name'] if name is None else self._normalize_preset_name(name)
            if next_name.lower() != current_item['name'].lower():
                cursor.execute(
                    f'''
                    SELECT preset_id
                    FROM {table}
                    WHERE is_deleted = 0 AND preset_id != ? AND lower(name) = lower(?)
                    ''',
                    (preset_id, next_name)
                )
                if cursor.fetchone():
                    raise ValueError(f"预制名称 '{next_name}' 已存在")
            next_tags = current_item['tags'] if tags is None else self._validate_preset_tags(cursor, tags)
            active_ids = self._get_active_preset_ids(cursor, table, exclude_preset_id=preset_id)
            current_sort = int(current_item['sort_order'])
            try:
                desired_order = current_sort if sort_order is None else int(sort_order)
            except Exception:
                desired_order = current_sort
            desired_order = max(0, min(desired_order, len(active_ids)))
            active_ids.insert(desired_order, preset_id)
            now = datetime.now().isoformat()
            cursor.execute(
                f'''
                UPDATE {table}
                SET name = ?, sort_order = ?, tags = ?, updated_at = ?
                WHERE preset_id = ?
                ''',
                (
                    next_name,
                    desired_order,
                    json.dumps(next_tags, ensure_ascii=False),
                    now,
                    preset_id,
                )
            )
            self._reindex_presets(cursor, table, active_ids)
            conn.commit()
            return self.get_preset(media_type, preset_id)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_preset(self, media_type, preset_id):
        media_type = (media_type or '').strip().lower()
        table = self._get_preset_table_name(media_type)
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('BEGIN IMMEDIATE')
            cursor.execute(
                f'''
                SELECT preset_id
                FROM {table}
                WHERE preset_id = ? AND is_deleted = 0
                ''',
                (preset_id,)
            )
            if not cursor.fetchone():
                raise KeyError('预制不存在')
            now = datetime.now().isoformat()
            cursor.execute(
                f'''
                UPDATE {table}
                SET is_deleted = 1, updated_at = ?
                WHERE preset_id = ?
                ''',
                (now, preset_id)
            )
            active_ids = self._get_active_preset_ids(cursor, table)
            self._reindex_presets(cursor, table, active_ids)
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    # ========== 模特相关操作 ==========
    
    def add_model(self, name):
        """添加模特"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            model_id = self._generate_guid()
            cursor.execute('SELECT MAX(sort_order) as max_order FROM models')
            result = cursor.fetchone()
            max_order = result['max_order'] if result and result['max_order'] is not None else 0
            try:
                cursor.execute('''
                    INSERT INTO models (id, name, sort_order, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (model_id, name, max_order + 1, now, now))
                return model_id
            except sqlite3.IntegrityError:
                raise ValueError(f"模特 '{name}' 已存在")
    
    def get_all_models(self):
        return self._query('''
            SELECT m.*, COALESCE(fm.cnt, 0) AS file_count
            FROM models m
            LEFT JOIN (
                SELECT model_id, COUNT(*) AS cnt FROM file_models GROUP BY model_id
            ) fm ON m.id = fm.model_id
            ORDER BY m.sort_order, m.name
        ''')

    def get_active_models(self):
        return self._query('SELECT * FROM models WHERE is_active = 1 ORDER BY sort_order, name')
    
    def get_model(self, model_id):
        """获取单个模特"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM models WHERE id = ?', (model_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def update_model(self, model_id, name):
        """更新模特名称"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            try:
                cursor.execute('''
                    UPDATE models
                    SET name = ?, updated_at = ?
                    WHERE id = ?
                ''', (name, now, model_id))
                return True
            except sqlite3.IntegrityError:
                raise ValueError(f"模特 '{name}' 已存在")
    
    def update_model_preview(self, model_id, preview_image_path):
        """更新模特预览图（支持文件路径或base64字符串）"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            preview_data = None
            if preview_image_path:
                if os.path.exists(preview_image_path):
                    try:
                        with open(preview_image_path, 'rb') as f:
                            image_data = f.read()
                            preview_data = base64.b64encode(image_data).decode('utf-8')
                    except Exception as e:
                        raise ValueError(f"读取图片文件失败: {str(e)}")
                else:
                    preview_data = preview_image_path
            cursor.execute('''
                UPDATE models
                SET preview_image_path = ?, updated_at = ?
                WHERE id = ?
            ''', (preview_data, now, model_id))
            return True
    
    def update_model_sort_order(self, model_id, new_sort_order):
        """更新模特排序"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute('''
                UPDATE models
                SET sort_order = ?, updated_at = ?
                WHERE id = ?
            ''', (new_sort_order, now, model_id))
            return True
    
    def swap_model_order(self, model_id1, model_id2):
        """交换两个模特的排序"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute('SELECT sort_order FROM models WHERE id = ?', (model_id1,))
            order1 = cursor.fetchone()['sort_order']
            cursor.execute('SELECT sort_order FROM models WHERE id = ?', (model_id2,))
            order2 = cursor.fetchone()['sort_order']
            cursor.execute('UPDATE models SET sort_order = ?, updated_at = ? WHERE id = ?', (order2, now, model_id1))
            cursor.execute('UPDATE models SET sort_order = ?, updated_at = ? WHERE id = ?', (order1, now, model_id2))
            return True
    
    def delete_model(self, model_id):
        """删除模特（会自动删除关联关系）"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM models WHERE id = ?', (model_id,))
        # 级联删除 file_models 影响大量文件的继承标签,低频操作直接全量重算
        self.recalc_tag_file_counts()
        return True
    
    # ========== 标签相关操作 ==========
    
    def add_tag(self, name, category_id=None):
        """添加标签"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            tag_id = self._generate_guid()
            cursor.execute('SELECT MAX(sort_order) as max_order FROM tags')
            result = cursor.fetchone()
            max_order = result['max_order'] if result and result['max_order'] is not None else 0
            try:
                cursor.execute('''
                    INSERT INTO tags (id, name, sort_order, category_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (tag_id, name, max_order + 1, category_id, now, now))
                return tag_id
            except sqlite3.IntegrityError:
                raise ValueError(f"标签 '{name}' 已存在")
    
    def get_all_tags(self):
        return self._query('SELECT * FROM tags ORDER BY sort_order, name')

    def get_active_tags(self):
        return self._query('SELECT * FROM tags WHERE is_active = 1 ORDER BY sort_order, name')

    def recalc_tag_file_counts(self):
        """全量重算所有标签的文件计数（直接关联 ∪ 通过模特继承）。

        只应在低频场景调用（迁移后、删除模特后、测试），单次约几百毫秒。
        日常计数由写路径通过 _adjust_tag_counts 增量维护。
        只 UPDATE 实际发生变化的标签,避免每次启动兜底重算时无差别写 tags 表。
        """
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id, file_count FROM tags')
            old_counts = [(r['id'], int(r['file_count'] or 0)) for r in cursor.fetchall()]
            for tag_id, old_count in old_counts:
                cursor.execute('''
                    SELECT COUNT(DISTINCT file_id) AS n FROM (
                        SELECT file_id FROM file_tags WHERE tag_id = ?
                        UNION
                        SELECT fm.file_id
                        FROM model_tags mt
                        JOIN file_models fm ON fm.model_id = mt.model_id
                        WHERE mt.tag_id = ?
                    )
                ''', (tag_id, tag_id))
                row = cursor.fetchone()
                new_count = int((row['n'] if row else 0) or 0)
                if new_count != old_count:
                    cursor.execute('UPDATE tags SET file_count = ? WHERE id = ?', (new_count, tag_id))

    def _get_inherited_tags_for_models(self, cursor, model_ids):
        """获取指定模特集合继承的所有标签 id（模特标签并集）"""
        if not model_ids:
            return set()
        placeholders = ','.join('?' * len(model_ids))
        cursor.execute(
            f'SELECT DISTINCT tag_id FROM model_tags WHERE model_id IN ({placeholders})',
            list(model_ids)
        )
        return {r['tag_id'] for r in cursor.fetchall()}

    def _get_inherited_tags(self, cursor, file_id):
        """获取文件通过其模特继承的所有标签 id"""
        cursor.execute('SELECT model_id FROM file_models WHERE file_id = ?', (file_id,))
        model_ids = [r['model_id'] for r in cursor.fetchall()]
        return self._get_inherited_tags_for_models(cursor, model_ids)

    def _adjust_tag_counts(self, cursor, old_direct, new_direct, old_inherited, new_inherited):
        """事务内对 tags.file_count 应用单文件增量（集合差,微秒级）"""
        old_set = set(old_direct) | set(old_inherited)
        new_set = set(new_direct) | set(new_inherited)
        inc = new_set - old_set
        dec = old_set - new_set
        if inc:
            ph = ','.join('?' * len(inc))
            cursor.execute(
                f'UPDATE tags SET file_count = COALESCE(file_count, 0) + 1 WHERE id IN ({ph})',
                list(inc)
            )
        if dec:
            ph = ','.join('?' * len(dec))
            cursor.execute(
                # MAX(0, …) 兜底:任何异常扣减都不得让计数跌为负数
                f'UPDATE tags SET file_count = MAX(0, COALESCE(file_count, 0) - 1) WHERE id IN ({ph})',
                list(dec)
            )

    def get_tags_with_category_name(self, only_active=False, with_file_count=True, include_preview=True):
        # file_count 持久化在 tags.file_count 列（写路径增量维护），
        # 直接读列避免每次实时聚合 file_tags ∪ model_tags×file_models 的几十万行
        preview_col = 't.preview_image_path' if include_preview else 'NULL AS preview_image_path'
        if with_file_count:
            base_sql = f'''
                SELECT t.*, c.name AS category_name, COALESCE(t.file_count, 0) AS file_count
                FROM tags t
                LEFT JOIN tag_categories c ON t.category_id = c.id
            '''
        else:
            base_sql = f'''
                SELECT t.id, t.name, t.is_active, t.sort_order, t.category_id,
                       {preview_col}, t.description, t.created_at, t.updated_at,
                       c.name AS category_name
                FROM tags t
                LEFT JOIN tag_categories c ON t.category_id = c.id
            '''
        if only_active:
            return self._query(
                base_sql + ' WHERE t.is_active = 1 ORDER BY c.sort_order, c.name, t.sort_order, t.name'
            )
        return self._query(
            base_sql + ' ORDER BY c.sort_order, c.name, t.sort_order, t.name'
        )

    def get_all_tags_grouped(self, only_active=False):
        rows = self.get_tags_with_category_name(only_active=only_active)
        grouped = {}
        for r in rows:
            key = r.get('category_id') or 'UNCATEGORIZED'
            if key not in grouped:
                grouped[key] = []
            grouped[key].append(r)
        return grouped

    def add_tag_category(self, name):
        """添加标签分类"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            category_id = self._generate_guid()
            cursor.execute('SELECT MAX(sort_order) as max_order FROM tag_categories')
            result = cursor.fetchone()
            max_order = result['max_order'] if result and result['max_order'] is not None else 0
            try:
                cursor.execute('''
                    INSERT INTO tag_categories (id, name, sort_order, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (category_id, name, max_order + 1, now, now))
                return category_id
            except sqlite3.IntegrityError:
                raise ValueError(f"标签分类 '{name}' 已存在")

    def get_all_tag_categories(self):
        return self._query('SELECT * FROM tag_categories ORDER BY sort_order, name')

    def get_active_tag_categories(self):
        return self._query('SELECT * FROM tag_categories WHERE is_active = 1 ORDER BY sort_order, name')

    def update_tag_category(self, category_id, name=None, is_active=None, description=None):
        """更新标签分类"""
        updates = []
        params = []
        if name is not None:
            updates.append('name = ?')
            params.append(name)
        if is_active is not None:
            updates.append('is_active = ?')
            params.append(1 if is_active else 0)
        if description is not None:
            updates.append('description = ?')
            params.append(description)
        if not updates:
            return False
        updates.append('updated_at = ?')
        params.append(datetime.now().isoformat())
        params.append(category_id)
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE tag_categories SET {', '.join(updates)} WHERE id = ?", params)
            return True

    def update_tag_category_sort_order(self, category_id, new_sort_order):
        """更新标签分类排序"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE tag_categories SET sort_order = ?, updated_at = ? WHERE id = ?', (new_sort_order, datetime.now().isoformat(), category_id))
            return True

    def delete_tag_category(self, category_id):
        """删除标签分类"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE tags SET category_id = NULL WHERE category_id = ?', (category_id,))
            cursor.execute('DELETE FROM tag_categories WHERE id = ?', (category_id,))
            return True

    def set_tag_category(self, tag_id, category_id):
        """设置标签所属分类"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE tags SET category_id = ?, updated_at = ? WHERE id = ?', (category_id, datetime.now().isoformat(), tag_id))
            return True

    def ensure_tag_category(self, name):
        try:
            return self.add_tag_category(name)
        except ValueError:
            row = self._query('SELECT id FROM tag_categories WHERE name = ?', (name,), fetch='one')
            return row['id'] if row else None

    def set_tag_category_by_names(self, tag_name, category_name):
        row = self._query('SELECT id FROM tags WHERE name = ?', (tag_name,), fetch='one')
        if not row:
            return False
        tag_id = row['id']
        category_id = self.ensure_tag_category(category_name)
        return self.set_tag_category(tag_id, category_id)

    def get_tags_by_category(self, category_id, only_active=False):
        """根据分类获取标签"""
        conn = self.get_connection()
        cursor = conn.cursor()
        if only_active:
            cursor.execute('SELECT * FROM tags WHERE category_id = ? AND is_active = 1 ORDER BY sort_order, name', (category_id,))
        else:
            cursor.execute('SELECT * FROM tags WHERE category_id = ? ORDER BY sort_order, name', (category_id,))
        tags = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return tags

    def update_model_active(self, model_id, is_active):
        """更新模特有效性"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('UPDATE models SET is_active = ?, updated_at = ? WHERE id = ?', (1 if is_active else 0, now, model_id))
        conn.commit()
        conn.close()
        return True

    def update_model_description(self, model_id, description):
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('UPDATE models SET description = ?, updated_at = ? WHERE id = ?', (description, now, model_id))
        conn.commit()
        conn.close()
        return True

    def update_model_type(self, model_id, model_type):
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('UPDATE models SET model_type = ?, updated_at = ? WHERE id = ?', (model_type, now, model_id))
        conn.commit()
        conn.close()
        return True

    def update_model_type_id(self, model_id, type_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('UPDATE models SET model_type_id = ?, updated_at = ? WHERE id = ?', (type_id, now, model_id))
        conn.commit()
        conn.close()
        return True

    # ========== 模特类型相关操作 ==========
    def add_model_type(self, name, description=None, is_active=True):
        with self.transaction() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            type_id = self._generate_guid()
            cursor.execute('''
                INSERT INTO model_types (id, name, is_active, description, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, ?, ?)
            ''', (type_id, name, 1 if is_active else 0, description, now, now))
            return type_id

    def get_all_model_types(self):
        return self._query('SELECT * FROM model_types ORDER BY sort_order, name')

    def get_model_type(self, type_id):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM model_types WHERE id = ?', (type_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def update_model_type_name(self, type_id, name):
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('UPDATE model_types SET name = ?, updated_at = ? WHERE id = ?', (name, now, type_id))
        conn.commit()
        conn.close()
        return True

    def update_model_type_active(self, type_id, is_active):
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('UPDATE model_types SET is_active = ?, updated_at = ? WHERE id = ?', (1 if is_active else 0, now, type_id))
        conn.commit()
        conn.close()
        return True

    def delete_model_type(self, type_id):
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM model_types WHERE id = ?', (type_id,))
            cursor.execute('UPDATE models SET model_type_id = NULL WHERE model_type_id = ?', (type_id,))
            return True

    def swap_model_type_order(self, id1, id2):
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT sort_order FROM model_types WHERE id = ?', (id1,))
            row1 = cursor.fetchone()
            cursor.execute('SELECT sort_order FROM model_types WHERE id = ?', (id2,))
            row2 = cursor.fetchone()
            if row1 and row2:
                cursor.execute('UPDATE model_types SET sort_order = ? WHERE id = ?', (row2['sort_order'], id1))
                cursor.execute('UPDATE model_types SET sort_order = ? WHERE id = ?', (row1['sort_order'], id2))
            return True

    def update_tag_active(self, tag_id, is_active):
        """更新标签有效性"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('UPDATE tags SET is_active = ?, updated_at = ? WHERE id = ?', (1 if is_active else 0, now, tag_id))
        conn.commit()
        conn.close()
        return True

    def update_tag_description(self, tag_id, description):
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('UPDATE tags SET description = ?, updated_at = ? WHERE id = ?', (description, now, tag_id))
        conn.commit()
        conn.close()
        return True
    
    def get_tag(self, tag_id):
        """获取单个标签"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM tags WHERE id = ?', (tag_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def update_tag(self, tag_id, name):
        """更新标签名称"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        try:
            cursor.execute('''
                UPDATE tags 
                SET name = ?, updated_at = ?
                WHERE id = ?
            ''', (name, now, tag_id))
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            conn.close()
            raise ValueError(f"标签 '{name}' 已存在")
    
    def update_tag_preview(self, tag_id, preview_image_path):
        """更新标签预览图（支持文件路径或base64字符串）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        # 如果传入的是文件路径，转换为base64
        preview_data = None
        if preview_image_path:
            if os.path.exists(preview_image_path):
                # 是文件路径，读取并转换为base64
                try:
                    with open(preview_image_path, 'rb') as f:
                        image_data = f.read()
                        preview_data = base64.b64encode(image_data).decode('utf-8')
                except Exception as e:
                    raise ValueError(f"读取图片文件失败: {str(e)}")
            else:
                # 可能是base64字符串，直接使用
                preview_data = preview_image_path
        
        cursor.execute('''
            UPDATE tags 
            SET preview_image_path = ?, updated_at = ?
            WHERE id = ?
        ''', (preview_data, now, tag_id))
        conn.commit()
        conn.close()
        return True
    
    def update_tag_sort_order(self, tag_id, new_sort_order):
        """更新标签排序"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute('''
            UPDATE tags 
            SET sort_order = ?, updated_at = ?
            WHERE id = ?
        ''', (new_sort_order, now, tag_id))
        conn.commit()
        conn.close()
        return True
    
    def swap_tag_order(self, tag_id1, tag_id2):
        """交换两个标签的排序"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        # 获取两个标签的当前排序
        cursor.execute('SELECT sort_order FROM tags WHERE id = ?', (tag_id1,))
        order1 = cursor.fetchone()['sort_order']
        cursor.execute('SELECT sort_order FROM tags WHERE id = ?', (tag_id2,))
        order2 = cursor.fetchone()['sort_order']
        # 交换排序
        cursor.execute('UPDATE tags SET sort_order = ?, updated_at = ? WHERE id = ?', (order2, now, tag_id1))
        cursor.execute('UPDATE tags SET sort_order = ?, updated_at = ? WHERE id = ?', (order1, now, tag_id2))
        conn.commit()
        conn.close()
        return True
    
    def delete_tag(self, tag_id):
        """删除标签（会自动删除关联关系）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM tags WHERE id = ?', (tag_id,))
        conn.commit()
        conn.close()
        return True
    
    # ========== 文件相关操作 ==========
    
    def add_file(self, file_path, file_name=None, file_size=None, md5_value=None, media_kind=None):
        """添加文件记录，自动计算MD5值

        md5_value: 外部已算好的 MD5 时传入,跳过文件读取(避免大文件重复计算)。
        file_path 入库前自动转为 data/ 相对路径（换盘零迁移，见 to_rel）。
        """
        raw_path = file_path
        if file_name is None:
            file_name = os.path.basename(raw_path)
        if file_size is None and os.path.exists(raw_path):
            file_size = os.path.getsize(raw_path)
        now = datetime.now().isoformat()

        # 计算MD5值(未传入时兜底计算)
        if md5_value is None and os.path.exists(raw_path):
            try:
                md5_value = compute_md5(raw_path)
            except Exception:
                pass

        # 自动识别文件类别（优先文件头魔数，失败回退扩展名）
        if media_kind is None:
            try:
                media_kind = (detect_media_file(raw_path) or {}).get('kind') or MEDIA_KIND_UNKNOWN
            except Exception:
                media_kind = media_kind_from_extension(file_name or raw_path)

        file_path = to_rel(raw_path)
        with self.transaction() as conn:
            cursor = conn.cursor()
            file_id = self._generate_guid()
            original_file_name = file_name
            ext = os.path.splitext(file_name)[1].lower().lstrip('.') if file_name else None
            file_type = ext or 'unknown'
            try:
                cursor.execute('''
                    INSERT INTO files (id, file_path, file_name, original_file_name, file_size, md5, file_type, media_kind, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (file_id, file_path, file_name, original_file_name, file_size, md5_value, file_type, media_kind, now, now))
                return file_id
            except sqlite3.IntegrityError:
                cursor.execute('SELECT id FROM files WHERE file_path = ?', (file_path,))
                row = cursor.fetchone()
                return dict(row)['id'] if row else None

    def get_file(self, file_path):
        """根据路径获取文件记录（查询参数自动转 data/ 相对，与入库格式一致）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM files WHERE file_path = ?', (to_rel(file_path),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def get_file_by_md5(self, md5_value):
        """按 MD5 查找已入库文件（批量导入去重用）"""
        if not md5_value:
            return None
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT id FROM files WHERE md5 = ? LIMIT 1', (md5_value,))
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    
    def get_file_by_id(self, file_id):
        return self._query('SELECT * FROM files WHERE id = ?', (file_id,), fetch='one')
    
    def update_file(self, file_id, file_path=None, file_name=None, file_size=None, file_type=None, media_kind=None):
        """更新文件记录"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        # 如果更新file_name，需要检查并保存原始文件名
        if file_name is not None:
            cursor.execute('SELECT file_name, original_file_name FROM files WHERE id = ?', (file_id,))
            row = cursor.fetchone()
            if row:
                current_file_name = row['file_name']
                try:
                    current_original_file_name = row['original_file_name']
                except (KeyError, IndexError):
                    current_original_file_name = None
                if not current_original_file_name and current_file_name:
                    cursor.execute('UPDATE files SET original_file_name = ? WHERE id = ?', (current_file_name, file_id))

        updates = []
        params = []

        if file_path is not None:
            raw_file_path = file_path
            file_path = to_rel(file_path)  # 入库统一 data/ 相对
            updates.append('file_path = ?')
            params.append(file_path)
            if file_type is None:
                try:
                    ext = os.path.splitext(file_path)[1].lower().lstrip('.')
                    file_type = ext or 'unknown'
                except Exception:
                    file_type = None
            if media_kind is None:
                try:
                    media_kind = (detect_media_file(raw_file_path) or {}).get('kind') or MEDIA_KIND_UNKNOWN
                except Exception:
                    media_kind = media_kind_from_extension(raw_file_path)
        if file_name is not None:
            updates.append('file_name = ?')
            params.append(file_name)
        if file_size is not None:
            updates.append('file_size = ?')
            params.append(file_size)

        if file_type is not None:
            updates.append('file_type = ?')
            params.append(file_type)

        if media_kind is not None:
            updates.append('media_kind = ?')
            params.append(media_kind)

        if not updates:
            conn.close()
            return False

        updates.append('updated_at = ?')
        params.append(now)
        params.append(file_id)

        cursor.execute(f"UPDATE files SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        conn.close()
        return True

    def update_file_thumbnail(self, file_id, thumbnail_path):
        conn = self.get_connection()
        cursor = conn.cursor()
        thumbnail_path = to_rel(thumbnail_path)  # 入库统一 data/ 相对
        cursor.execute('UPDATE files SET thumbnail_path = ?, updated_at = ? WHERE id = ?', (thumbnail_path, datetime.now().isoformat(), file_id))
        conn.commit()
        conn.close()
        return True
    
    def get_files_by_paths(self, file_paths):
        """批量查询已入库路径，返回 {入库相对路径: file_id}。

        扫描识别页面用它与磁盘文件做去重，避免对每个文件单独开连接查询。
        """
        result = {}
        paths = list(dict.fromkeys([to_rel(str(p)) for p in (file_paths or []) if p]))
        if not paths:
            return result
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            for i in range(0, len(paths), 900):
                chunk = paths[i:i + 900]
                placeholders = ','.join(['?'] * len(chunk))
                cursor.execute(f'SELECT id, file_path FROM files WHERE file_path IN ({placeholders})', chunk)
                for row in cursor.fetchall():
                    result[row['file_path']] = row['id']
        finally:
            conn.close()
        return result

    def update_file_media_kind(self, file_id, media_kind=None, file_path=None):
        """更新（或重新识别）单个文件的 media_kind。"""
        if media_kind is None:
            path = file_path
            if path is None:
                row = self.get_file_by_id(file_id)
                path = row.get('file_path') if row else None
                if path:
                    path = resolve_abs(path)
            if path:
                media_kind = (detect_media_file(path) or {}).get('kind') or MEDIA_KIND_UNKNOWN
        if media_kind not in (MEDIA_KIND_IMAGE, MEDIA_KIND_VIDEO, MEDIA_KIND_AUDIO, MEDIA_KIND_UNKNOWN):
            media_kind = MEDIA_KIND_UNKNOWN
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute('UPDATE files SET media_kind = ?, updated_at = ? WHERE id = ?', (media_kind, datetime.now().isoformat(), file_id))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def update_files_media_kind(self, file_ids, media_kind):
        """批量手动设置多个文件的 media_kind。"""
        ids = list(dict.fromkeys([str(fid) for fid in (file_ids or []) if str(fid)]))
        if not ids:
            return 0
        if media_kind not in (MEDIA_KIND_IMAGE, MEDIA_KIND_VIDEO, MEDIA_KIND_AUDIO, MEDIA_KIND_UNKNOWN):
            media_kind = MEDIA_KIND_UNKNOWN
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            updated = 0
            for i in range(0, len(ids), 900):
                chunk = ids[i:i + 900]
                placeholders = ','.join(['?'] * len(chunk))
                cursor.execute(
                    f'UPDATE files SET media_kind = ?, updated_at = ? WHERE id IN ({placeholders})',
                    [media_kind, now] + chunk,
                )
                updated += cursor.rowcount
            conn.commit()
            return updated
        finally:
            conn.close()

    def update_original_file_name(self, file_id, original_file_name):
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE files SET original_file_name = ?, updated_at = ? WHERE id = ?', (original_file_name, datetime.now().isoformat(), file_id))
            return True

    def delete_file(self, file_id):
        """删除文件记录（外键 CASCADE 自动清理 file_models / file_tags 关联）"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            # 级联删除前先取关联,用于扣减标签计数
            direct = {r['tag_id'] for r in cursor.execute('SELECT tag_id FROM file_tags WHERE file_id = ?', (file_id,))}
            inherited = self._get_inherited_tags(cursor, file_id)
            cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
            self._adjust_tag_counts(cursor, direct, set(), inherited, set())
            return True
    
    def save_image_data(self, file_id, image_path, md5_value=None):
        """计算并保存图片的MD5值与尺寸到数据库

        md5_value: 外部已算好的 MD5 时传入,跳过文件读取(避免大文件重复计算)。
        """
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()

        try:
            # 计算图片文件的MD5值(未传入时兜底计算)
            if md5_value is None:
                md5_value = compute_md5(image_path)
            # 读取图片尺寸
            width = None
            height = None
            try:
                with Image.open(image_path) as img:
                    width, height = img.size
            except Exception:
                pass
            
            # 更新文件记录，添加MD5值
            if width is not None and height is not None:
                cursor.execute('''
                    UPDATE files 
                    SET md5 = ?, image_width = ?, image_height = ?, updated_at = ?
                    WHERE id = ?
                ''', (md5_value, width, height, now, file_id))
            else:
                cursor.execute('''
                    UPDATE files 
                    SET md5 = ?, updated_at = ?
                    WHERE id = ?
                ''', (md5_value, now, file_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            raise Exception(f"保存图片MD5失败: {str(e)}")

    def save_video_data(self, file_id, video_path):
        """计算并保存视频的分辨率与时长到数据库"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        try:
            # 音频文件优先使用可选依赖计算时长
            try:
                ext = os.path.splitext(video_path)[1].lower()
            except Exception:
                ext = ""
            if ext in {'.mp3', '.m4a'}:
                duration_ms = None
                try:
                    if ext == '.mp3':
                        try:
                            from mutagen.mp3 import MP3  # type: ignore
                            audio = MP3(video_path)
                            if getattr(audio, "info", None) and getattr(audio.info, "length", None):
                                duration_ms = int(float(audio.info.length) * 1000)
                        except Exception:
                            duration_ms = None
                    else:
                        try:
                            from mutagen.mp4 import MP4  # type: ignore
                            audio = MP4(video_path)
                            # MP4 时长可通过 tags 或内部 atoms 计算；mutagen 提供 info.length
                            info = getattr(audio, "info", None)
                            length = getattr(info, "length", None)
                            if length:
                                duration_ms = int(float(length) * 1000)
                        except Exception:
                            duration_ms = None
                except Exception:
                    duration_ms = None
                cursor.execute('''
                    UPDATE files
                    SET video_width = ?, video_height = ?, duration_ms = ?, updated_at = ?
                    WHERE id = ?
                ''', (None, None, duration_ms, now, file_id))
                conn.commit()
                conn.close()
                return True
            if cv2 is None:
                cursor.execute('UPDATE files SET updated_at = ? WHERE id = ?', (now, file_id))
                conn.commit()
                conn.close()
                return False
            cap = cv2.VideoCapture(video_path)
            if not cap or not cap.isOpened():
                # 若无法打开，仍然更新时间戳
                cursor.execute('UPDATE files SET updated_at = ? WHERE id = ?', (now, file_id))
                conn.commit()
                conn.close()
                return False
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            cap.release()
            duration_ms = None
            if fps and fps > 0 and total_frames > 0:
                duration_ms = int((total_frames / fps) * 1000)
            # 更新文件记录
            cursor.execute('''
                UPDATE files
                SET video_width = ?, video_height = ?, duration_ms = ?, updated_at = ?
                WHERE id = ?
            ''', (width or None, height or None, duration_ms, now, file_id))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            conn.close()
            raise Exception(f"保存视频元数据失败: {str(e)}")
    
    def get_file_md5(self, file_id):
        """从数据库获取文件的MD5值"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT md5 FROM files WHERE id = ?', (file_id,))
        row = cursor.fetchone()
        conn.close()
        return row['md5'] if row and row['md5'] else None
    
    # ========== 文件和模特关联操作 ==========
    
    def add_file_model(self, file_id, model_id):
        """为文件添加模特关联"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        try:
            # 必须在 INSERT 之前取旧继承集,否则新模特标签会被误当成旧状态,导致继承标签漏计数
            old_inherited = self._get_inherited_tags(cursor, file_id)
            old_direct = {r['tag_id'] for r in cursor.execute('SELECT tag_id FROM file_tags WHERE file_id = ?', (file_id,))}
            relation_id = self._generate_guid()
            cursor.execute('''
                INSERT INTO file_models (id, file_id, model_id, created_at)
                VALUES (?, ?, ?, ?)
            ''', (relation_id, file_id, model_id, now))
            # 新增模特可能带来新的继承标签
            new_inherited = old_inherited | self._get_inherited_tags_for_models(cursor, [model_id])
            self._adjust_tag_counts(cursor, old_direct, old_direct, old_inherited, new_inherited)
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            conn.close()
            return False  # 关联已存在

    def remove_file_model(self, file_id, model_id):
        """移除文件的模特关联"""
        conn = self.get_connection()
        cursor = conn.cursor()
        old_inherited = self._get_inherited_tags(cursor, file_id)
        old_direct = {r['tag_id'] for r in cursor.execute('SELECT tag_id FROM file_tags WHERE file_id = ?', (file_id,))}
        cursor.execute('''
            DELETE FROM file_models
            WHERE file_id = ? AND model_id = ?
        ''', (file_id, model_id))
        new_inherited = self._get_inherited_tags(cursor, file_id)
        self._adjust_tag_counts(cursor, old_direct, old_direct, old_inherited, new_inherited)
        conn.commit()
        conn.close()
        return True
    
    def get_file_models(self, file_id):
        return self._query(
            'SELECT m.* FROM models m INNER JOIN file_models fm ON m.id = fm.model_id WHERE fm.file_id = ? ORDER BY m.name',
            (file_id,)
        )
    
    def set_file_models(self, file_id, model_ids):
        """设置文件关联的模特（先删除旧的，再添加新的）"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            old_inherited = self._get_inherited_tags(cursor, file_id)
            old_direct = {r['tag_id'] for r in cursor.execute('SELECT tag_id FROM file_tags WHERE file_id = ?', (file_id,))}
            cursor.execute('DELETE FROM file_models WHERE file_id = ?', (file_id,))
            for model_id in model_ids:
                relation_id = self._generate_guid()
                cursor.execute('''
                    INSERT INTO file_models (id, file_id, model_id, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (relation_id, file_id, model_id, now))
            new_inherited = self._get_inherited_tags_for_models(cursor, list(model_ids))
            self._adjust_tag_counts(cursor, old_direct, old_direct, old_inherited, new_inherited)
            return True
    
    # ========== 文件和标签关联操作 ==========
    
    def add_file_tag(self, file_id, tag_id):
        """为文件添加标签关联"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        try:
            relation_id = self._generate_guid()
            cursor.execute('''
                INSERT INTO file_tags (id, file_id, tag_id, created_at)
                VALUES (?, ?, ?, ?)
            ''', (relation_id, file_id, tag_id, now))
            # 该 tag 之前已通过模特继承计入时,不重复计数
            if tag_id not in self._get_inherited_tags(cursor, file_id):
                cursor.execute('UPDATE tags SET file_count = COALESCE(file_count, 0) + 1 WHERE id = ?', (tag_id,))
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            conn.close()
            return False  # 关联已存在

    def remove_file_tag(self, file_id, tag_id):
        """移除文件的标签关联"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM file_tags
            WHERE file_id = ? AND tag_id = ?
        ''', (file_id, tag_id))
        if cursor.rowcount == 0:
            # 关联本就不存在(重复移除/批量移除未命中),不得扣减计数
            conn.commit()
            conn.close()
            return True
        # 该 tag 仍通过模特继承计入时,不扣减
        if tag_id not in self._get_inherited_tags(cursor, file_id):
            cursor.execute('UPDATE tags SET file_count = MAX(0, COALESCE(file_count, 0) - 1) WHERE id = ?', (tag_id,))
        conn.commit()
        conn.close()
        return True
    
    def get_file_tags(self, file_id):
        return self._query(
            'SELECT t.* FROM tags t INNER JOIN file_tags ft ON t.id = ft.tag_id WHERE ft.file_id = ? ORDER BY t.name',
            (file_id,)
        )

    def get_files_models_batch(self, file_ids, include_preview=True):
        if not file_ids:
            return {}
        conn = self.get_connection()
        cursor = conn.cursor()
        result = {fid: [] for fid in file_ids}
        if include_preview:
            select_cols = 'm.*'
        else:
            # /api/media 的卡片只需 id/name/type,不读可能很大的 base64 预览列
            select_cols = ('m.id, m.name, NULL AS preview_image_path, m.model_type, '
                           'm.model_type_id, m.is_active, m.description, m.sort_order, '
                           'm.created_at, m.updated_at')
        chunk_size = 900
        for i in range(0, len(file_ids), chunk_size):
            chunk = file_ids[i:i + chunk_size]
            placeholders = ','.join(['?'] * len(chunk))
            cursor.execute(
                f'SELECT fm.file_id, {select_cols} FROM file_models fm INNER JOIN models m ON fm.model_id = m.id WHERE fm.file_id IN ({placeholders}) ORDER BY m.name',
                chunk
            )
            for row in cursor.fetchall():
                r = dict(row)
                result.setdefault(r.pop('file_id'), []).append(r)
        conn.close()
        return result

    def get_files_tags_batch(self, file_ids, include_preview=True):
        if not file_ids:
            return {}
        conn = self.get_connection()
        cursor = conn.cursor()
        result = {fid: [] for fid in file_ids}
        select_cols = 't.*' if include_preview else ('t.id, t.name, NULL AS preview_image_path, '
                                                     't.is_active, t.description, t.sort_order, '
                                                     't.category_id, t.created_at, t.updated_at, t.file_count')
        chunk_size = 900
        for i in range(0, len(file_ids), chunk_size):
            chunk = file_ids[i:i + chunk_size]
            placeholders = ','.join(['?'] * len(chunk))
            cursor.execute(
                f'SELECT ft.file_id, {select_cols} FROM file_tags ft INNER JOIN tags t ON ft.tag_id = t.id WHERE ft.file_id IN ({placeholders}) ORDER BY t.name',
                chunk
            )
            for row in cursor.fetchall():
                r = dict(row)
                result.setdefault(r.pop('file_id'), []).append(r)
        conn.close()
        return result

    def get_models_tags_batch(self, model_ids, include_preview=True):
        if not model_ids:
            return {}
        conn = self.get_connection()
        cursor = conn.cursor()
        result = {mid: [] for mid in model_ids}
        select_cols = 't.*' if include_preview else ('t.id, t.name, NULL AS preview_image_path, '
                                                     't.is_active, t.description, t.sort_order, '
                                                     't.category_id, t.created_at, t.updated_at, t.file_count')
        chunk_size = 900
        for i in range(0, len(model_ids), chunk_size):
            chunk = model_ids[i:i + chunk_size]
            placeholders = ','.join(['?'] * len(chunk))
            cursor.execute(
                f'SELECT mt.model_id, {select_cols} FROM model_tags mt INNER JOIN tags t ON mt.tag_id = t.id WHERE mt.model_id IN ({placeholders}) ORDER BY t.name',
                chunk
            )
            for row in cursor.fetchall():
                r = dict(row)
                result.setdefault(r.pop('model_id'), []).append(r)
        conn.close()
        return result

    def set_file_tags(self, file_id, tag_ids):
        """设置文件关联的标签（先删除旧的，再添加新的）"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            old_direct = {r['tag_id'] for r in cursor.execute('SELECT tag_id FROM file_tags WHERE file_id = ?', (file_id,))}
            old_inherited = self._get_inherited_tags(cursor, file_id)
            cursor.execute('DELETE FROM file_tags WHERE file_id = ?', (file_id,))
            for tag_id in tag_ids:
                relation_id = self._generate_guid()
                cursor.execute('''
                    INSERT INTO file_tags (id, file_id, tag_id, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (relation_id, file_id, tag_id, now))
            # 只改直接集,继承集不变
            self._adjust_tag_counts(cursor, old_direct, set(tag_ids), old_inherited, old_inherited)
            return True
    
    # ========== 模特和标签关联操作 ==========
    
    def add_model_tag(self, model_id, tag_id):
        """为模特添加标签关联"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        try:
            relation_id = self._generate_guid()
            cursor.execute('''
                INSERT INTO model_tags (id, model_id, tag_id, created_at)
                VALUES (?, ?, ?, ?)
            ''', (relation_id, model_id, tag_id, now))
            # 仅"本模特下、无直接标签、且未从其他模特继承该标签"的文件新增计数
            # (直接标签/其他模特继承都已计过数,不能重复累加)
            cursor.execute('''
                SELECT COUNT(DISTINCT fm.file_id) AS n
                FROM file_models fm
                WHERE fm.model_id = ?
                  AND NOT EXISTS (
                      SELECT 1 FROM file_tags ft
                      WHERE ft.file_id = fm.file_id AND ft.tag_id = ?
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM file_models fm2
                      JOIN model_tags mt2 ON mt2.model_id = fm2.model_id
                      WHERE fm2.file_id = fm.file_id AND mt2.tag_id = ? AND fm2.model_id != ?
                  )
            ''', (model_id, tag_id, tag_id, model_id))
            n = cursor.fetchone()['n']
            if n:
                cursor.execute('UPDATE tags SET file_count = COALESCE(file_count, 0) + ? WHERE id = ?', (n, tag_id))
            conn.commit()
            conn.close()
            return True
        except sqlite3.IntegrityError:
            conn.close()
            return False  # 关联已存在

    def remove_model_tag(self, model_id, tag_id):
        """移除模特的标签关联"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM model_tags
            WHERE model_id = ? AND tag_id = ?
        ''', (model_id, tag_id))
        if cursor.rowcount == 0:
            # 关联本就不存在(重复移除),不得扣减计数
            conn.commit()
            conn.close()
            return True
        # 仅"本模特下、无直接标签、且移除后不再从其他模特继承该标签"的文件扣减计数
        cursor.execute('''
            SELECT COUNT(DISTINCT fm.file_id) AS n
            FROM file_models fm
            WHERE fm.model_id = ?
              AND NOT EXISTS (
                  SELECT 1 FROM file_tags ft
                  WHERE ft.file_id = fm.file_id AND ft.tag_id = ?
              )
              AND NOT EXISTS (
                  SELECT 1 FROM file_models fm2
                  JOIN model_tags mt2 ON mt2.model_id = fm2.model_id
                  WHERE fm2.file_id = fm.file_id AND mt2.tag_id = ? AND fm2.model_id != ?
              )
        ''', (model_id, tag_id, tag_id, model_id))
        n = cursor.fetchone()['n']
        if n:
            cursor.execute('UPDATE tags SET file_count = MAX(0, COALESCE(file_count, 0) - ?) WHERE id = ?', (n, tag_id))
        conn.commit()
        conn.close()
        return True
    
    def get_model_tags(self, model_id):
        return self._query(
            'SELECT t.* FROM tags t INNER JOIN model_tags mt ON t.id = mt.tag_id WHERE mt.model_id = ? ORDER BY t.name',
            (model_id,)
        )
    
    def set_model_tags(self, model_id, tag_ids):
        """设置模特关联的标签（先删除旧的，再添加新的）"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            old_tags = {r['tag_id'] for r in cursor.execute('SELECT tag_id FROM model_tags WHERE model_id = ?', (model_id,))}
            new_tags = set(tag_ids)
            removed = old_tags - new_tags
            added = new_tags - old_tags
            # 移除的标签:该模特仍持有旧标签,查询时排除自身,统计"移除后真正不再计入"的文件
            for tag_id in removed:
                cursor.execute('''
                    SELECT COUNT(DISTINCT fm.file_id) AS n
                    FROM file_models fm
                    WHERE fm.model_id = ?
                      AND NOT EXISTS (
                          SELECT 1 FROM file_tags ft
                          WHERE ft.file_id = fm.file_id AND ft.tag_id = ?
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM file_models fm2
                          JOIN model_tags mt2 ON mt2.model_id = fm2.model_id
                          WHERE fm2.file_id = fm.file_id AND mt2.tag_id = ? AND fm2.model_id != ?
                      )
                ''', (model_id, tag_id, tag_id, model_id))
                n = cursor.fetchone()['n']
                if n:
                    cursor.execute('UPDATE tags SET file_count = MAX(0, COALESCE(file_count, 0) - ?) WHERE id = ?', (n, tag_id))
            cursor.execute('DELETE FROM model_tags WHERE model_id = ?', (model_id,))
            for tag_id in tag_ids:
                relation_id = self._generate_guid()
                cursor.execute('''
                    INSERT INTO model_tags (id, model_id, tag_id, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (relation_id, model_id, tag_id, now))
            # 新增的标签:该模特已持有新标签,查询时排除自身,统计"真正新计入"的文件
            for tag_id in added:
                cursor.execute('''
                    SELECT COUNT(DISTINCT fm.file_id) AS n
                    FROM file_models fm
                    WHERE fm.model_id = ?
                      AND NOT EXISTS (
                          SELECT 1 FROM file_tags ft
                          WHERE ft.file_id = fm.file_id AND ft.tag_id = ?
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM file_models fm2
                          JOIN model_tags mt2 ON mt2.model_id = fm2.model_id
                          WHERE fm2.file_id = fm.file_id AND mt2.tag_id = ? AND fm2.model_id != ?
                      )
                ''', (model_id, tag_id, tag_id, model_id))
                n = cursor.fetchone()['n']
                if n:
                    cursor.execute('UPDATE tags SET file_count = COALESCE(file_count, 0) + ? WHERE id = ?', (n, tag_id))
            return True
    
    # ========== 文件查询相关操作 ==========
    
    def get_all_files(self, limit=1000):
        """获取所有文件（仅files表的数据），默认限制 1000 条"""
        return self._query('SELECT * FROM files ORDER BY created_at DESC LIMIT ?', (int(limit),))

    def get_files_page(self, offset=0, limit=200, search_text=None):
        """分页获取文件（支持按名称/路径搜索）"""
        conn = self.get_connection()
        cursor = conn.cursor()
        base_sql = 'SELECT * FROM files'
        where = []
        params = []
        if search_text:
            q = f"%{search_text.strip()}%"
            where.append('(file_name LIKE ? OR original_file_name LIKE ? OR file_path LIKE ?)')
            params.extend([q, q, q])
        if where:
            base_sql += ' WHERE ' + ' AND '.join(where)
        base_sql += ' ORDER BY created_at DESC LIMIT ? OFFSET ?'
        params.extend([int(limit), int(offset)])
        cursor.execute(base_sql, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        # 查询出口统一解析为绝对路径（DB 存 data/ 相对，调用方直接做文件系统操作）
        for row in rows:
            if row.get('file_path'):
                row['file_path'] = resolve_abs(row['file_path'])
            if row.get('thumbnail_path'):
                row['thumbnail_path'] = resolve_abs(row['thumbnail_path'])
        return rows

    def get_app_setting(self, setting_key, default_value=None):
        row = self._query('SELECT setting_value FROM app_settings WHERE setting_key = ?', (str(setting_key),), fetch='one')
        if not row:
            return default_value
        return row['setting_value']

    def set_app_setting(self, setting_key, setting_value):
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(
            '''
            INSERT INTO app_settings (setting_key, setting_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET
                setting_value = excluded.setting_value,
                updated_at = excluded.updated_at
            ''',
            (str(setting_key), str(setting_value), now)
        )
        conn.commit()
        conn.close()
        return True

    def get_true_random_cache_enabled(self):
        now = _time.monotonic()
        value, expires = self._true_random_enabled_cache
        if expires > now:
            return bool(value)
        raw = str(self.get_app_setting('true_random_cache_enabled', '1')).strip().lower()
        value = raw not in ('0', 'false', 'off', 'no')
        self._true_random_enabled_cache = (value, now + 5.0)
        return value

    def set_true_random_cache_enabled(self, enabled):
        self.set_app_setting('true_random_cache_enabled', '1' if bool(enabled) else '0')
        value = bool(enabled)
        self._true_random_enabled_cache = (value, _time.monotonic() + 5.0)
        return value

    def get_auto_save_enabled(self):
        """获取自动保存开关状态，默认关闭"""
        value = str(self.get_app_setting('auto_save_enabled', '0')).strip().lower()
        return value not in ('0', 'false', 'off', 'no')

    def set_auto_save_enabled(self, enabled):
        """设置自动保存开关状态并持久化"""
        self.set_app_setting('auto_save_enabled', '1' if bool(enabled) else '0')
        return self.get_auto_save_enabled()

    def cache_true_random_results(self, cache_key, file_ids):
        cache_value = str(cache_key or '').strip()
        if not cache_value:
            return 0
        normalized_ids = []
        seen = set()
        for file_id in file_ids or []:
            value = str(file_id or '').strip()
            if not value or value in seen:
                continue
            seen.add(value)
            normalized_ids.append(value)
        if not normalized_ids:
            return 0
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        try:
            cursor.execute('BEGIN IMMEDIATE')
            inserted = 0
            for file_id in normalized_ids:
                cursor.execute(
                    '''
                    INSERT OR IGNORE INTO true_random_cache (cache_id, cache_key, file_id, created_at)
                    VALUES (?, ?, ?, ?)
                    ''',
                    (self._generate_guid(), cache_value, file_id, now)
                )
                inserted += int(cursor.rowcount or 0)
            conn.commit()
            if inserted:
                self._true_random_count_cache = (None, 0.0)
            return inserted
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_true_random_cache(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) AS total FROM true_random_cache')
        row = cursor.fetchone()
        total = int((row['total'] if row else 0) or 0)
        cursor.execute('DELETE FROM true_random_cache')
        conn.commit()
        conn.close()
        self._true_random_count_cache = (0, _time.monotonic() + 2.0)
        return total

    def count_true_random_cache(self):
        now = _time.monotonic()
        total, expires = self._true_random_count_cache
        if expires > now:
            return int(total or 0)
        row = self._query('SELECT COUNT(*) AS total FROM true_random_cache', fetch='one')
        total = int((row['total'] if row else 0) or 0)
        self._true_random_count_cache = (total, now + 2.0)
        return total

    def _build_file_filter_clauses(self, model_ids=None, tag_ids=None, exclude_tag_ids=None, strict=True, min_heat=None, max_heat=None, name=None, media_kind=None):
        """构建 files 筛选 WHERE 子句(列表)与参数,供分页查询和排位查询共用。

        - 传入 id 先去重,避免严格匹配 COUNT(DISTINCT ...) 因重复参数改变语义。
        - strict model 匹配使用「IN 子查询 + HAVING COUNT(DISTINCT model_id)」,
          实测比逐模特 EXISTS 快一个数量级(直接走 idx_file_models_model_id)。
        """
        where = []
        params = []
        mids = list(dict.fromkeys(model_ids or []))
        tids = list(dict.fromkeys(tag_ids or []))
        ex_tids = list(dict.fromkeys(exclude_tag_ids or []))
        if name:
            q = f"%{str(name).strip().lower()}%"
            where.append('('
                         'LOWER(f.file_name) LIKE ? OR '
                         'LOWER(IFNULL(f.original_file_name, "")) LIKE ? OR '
                         'LOWER(f.file_path) LIKE ?'
                         ')')
            params.extend([q, q, q])
        if media_kind in (MEDIA_KIND_IMAGE, MEDIA_KIND_VIDEO, MEDIA_KIND_AUDIO, MEDIA_KIND_UNKNOWN):
            if media_kind == MEDIA_KIND_UNKNOWN:
                where.append('(f.media_kind = ? OR f.media_kind IS NULL)')
            else:
                where.append('f.media_kind = ?')
            params.append(media_kind)
        if min_heat is not None:
            where.append('f.heat_value >= ?')
            params.append(int(min_heat))
        if max_heat is not None:
            where.append('f.heat_value <= ?')
            params.append(int(max_heat))
        if mids:
            if strict:
                placeholders = ','.join(['?'] * len(mids))
                where.append(
                    f'f.id IN ('
                    f'SELECT fm.file_id FROM file_models fm '
                    f'WHERE fm.model_id IN ({placeholders}) '
                    f'GROUP BY fm.file_id '
                    f'HAVING COUNT(DISTINCT fm.model_id) = ?'
                    f')'
                )
                params.extend(mids)
                params.append(len(mids))
            else:
                placeholders = ','.join(['?'] * len(mids))
                where.append(f'EXISTS (SELECT 1 FROM file_models fm WHERE fm.file_id = f.id AND fm.model_id IN ({placeholders}))')
                params.extend(mids)
        if tids:
            if strict:
                for tid in tids:
                    where.append('('
                                 'EXISTS (SELECT 1 FROM file_tags ft WHERE ft.file_id = f.id AND ft.tag_id = ?)' 
                                 ' OR '
                                 'EXISTS (SELECT 1 FROM model_tags mt JOIN file_models fm ON fm.model_id = mt.model_id '
                                 '        WHERE fm.file_id = f.id AND mt.tag_id = ?)' 
                                 ')')
                    params.extend([tid, tid])
            else:
                placeholders = ','.join(['?'] * len(tids))
                where.append('('
                             f'EXISTS (SELECT 1 FROM file_tags ft WHERE ft.file_id = f.id AND ft.tag_id IN ({placeholders}))'
                             ' OR '
                             f'EXISTS (SELECT 1 FROM model_tags mt JOIN file_models fm ON fm.model_id = mt.model_id '
                             f'        WHERE fm.file_id = f.id AND mt.tag_id IN ({placeholders}))'
                             ')')
                params.extend(tids)
                params.extend(tids)
        if ex_tids:
            placeholders = ','.join(['?'] * len(ex_tids))
            where.append(f'NOT EXISTS (SELECT 1 FROM file_tags ft WHERE ft.file_id = f.id AND ft.tag_id IN ({placeholders}))')
            where.append('NOT EXISTS (SELECT 1 FROM model_tags mt JOIN file_models fm ON fm.model_id = mt.model_id '
                         f'WHERE fm.file_id = f.id AND mt.tag_id IN ({placeholders}))')
            params.extend(ex_tids)
            params.extend(ex_tids)
        return where, params

    def _get_rows_by_ids(self, cursor, file_ids):
        """按给定顺序批量取回完整 file 行(避免随机模式把全表所有列拉进 Python)。"""
        file_ids = [str(fid) for fid in (file_ids or [])]
        if not file_ids:
            return []
        row_map = {}
        chunk_size = 900
        for i in range(0, len(file_ids), chunk_size):
            chunk = file_ids[i:i + chunk_size]
            placeholders = ','.join(['?'] * len(chunk))
            cursor.execute(f'SELECT f.* FROM files f WHERE f.id IN ({placeholders})', chunk)
            for r in cursor.fetchall():
                row_map[r['id']] = dict(r)
        return [row_map[fid] for fid in file_ids if fid in row_map]

    def query_files_with_filters(self, model_ids=None, tag_ids=None, exclude_tag_ids=None, strict=True, min_heat=None, max_heat=None, offset=0, limit=30, order='recent', seed=None, name=None, blacklist_cache_key=None, cursor=None, media_kind=None):
        """按筛选条件分页查询文件，支持严格/任意匹配与排序；当提供 seed 且 order=random 时，使用可复现的伪随机顺序

        cursor: 游标分页键（keyset），形如 "v1|v2|v3"，各段与 ORDER BY 列一一对应
            (recent/recent_asc: created_at|id; duration*/heat*: 值|created_at|id)。
            提供时忽略 offset（游标分页对滚动期间的新增/删除免疫，避免 OFFSET 跳页漏数据）。
        """
        conn = self.get_connection()
        cur = conn.cursor()
        sql = 'SELECT f.* FROM files f'
        where, params = self._build_file_filter_clauses(
            model_ids=model_ids,
            tag_ids=tag_ids,
            exclude_tag_ids=exclude_tag_ids,
            strict=strict,
            min_heat=min_heat,
            max_heat=max_heat,
            name=name,
            media_kind=media_kind,
        )
        if blacklist_cache_key:
            where.append('NOT EXISTS (SELECT 1 FROM true_random_cache trc WHERE trc.cache_key = ? AND trc.file_id = f.id)')
            params.append(str(blacklist_cache_key).strip())
        # 游标分页键（仅 SQL 原生排序使用；random/seed 路径忽略）
        cursor_parts = None
        if cursor and order in ('recent', 'recent_asc', 'duration', 'duration_asc', 'heat', 'heat_asc'):
            parts = [str(p) for p in str(cursor).split('|')]
            # 轻量校验：created_at 段须为 ISO 时间形态、id 段非空，非法游标直接忽略（回退 OFFSET）
            def _valid_ts_id(p0, p1):
                return bool(p0) and len(p0) >= 19 and p0[4] == '-' and p0[7] == '-' and bool(p1)
            if order == 'recent' and len(parts) >= 2 and _valid_ts_id(parts[0], parts[1]):
                # 显式展开排序键比较:created_at DESC, id ASC
                cursor_parts = (
                    '(f.created_at < ? OR f.created_at = ? AND f.id > ?)',
                    [parts[0], parts[0], parts[1]],
                )
            elif order == 'recent_asc' and len(parts) >= 2 and _valid_ts_id(parts[0], parts[1]):
                # created_at ASC, id ASC
                cursor_parts = (
                    '(f.created_at > ? OR f.created_at = ? AND f.id > ?)',
                    [parts[0], parts[0], parts[1]],
                )
            elif order in ('duration', 'duration_asc') and len(parts) >= 3 and _valid_ts_id(parts[1], parts[2]):
                primary_op = '<' if order == 'duration' else '>'
                # 数值段必须转 int：SQLite 中 TEXT 恒大于数值，字符串 '7' 会让比较恒真导致死循环
                try:
                    first = int(parts[0])
                except (TypeError, ValueError):
                    first = None
                if first is not None:
                    # duration DESC/ASC 的次排序列均为 created_at DESC, id ASC
                    cursor_parts = (
                        f'(COALESCE(f.duration_ms, 0) {primary_op} ? OR '
                        f'COALESCE(f.duration_ms, 0) = ? AND f.created_at < ? OR '
                        f'COALESCE(f.duration_ms, 0) = ? AND f.created_at = ? AND f.id > ?)',
                        [first, first, parts[1], first, parts[1], parts[2]],
                    )
            elif order in ('heat', 'heat_asc') and len(parts) >= 3 and _valid_ts_id(parts[1], parts[2]):
                primary_op = '<' if order == 'heat' else '>'
                try:
                    first = int(parts[0])
                except (TypeError, ValueError):
                    first = None
                if first is not None:
                    cursor_parts = (
                        f'(COALESCE(f.heat_value, 0) {primary_op} ? OR '
                        f'COALESCE(f.heat_value, 0) = ? AND f.created_at < ? OR '
                        f'COALESCE(f.heat_value, 0) = ? AND f.created_at = ? AND f.id > ?)',
                        [first, first, parts[1], first, parts[1], parts[2]],
                    )
        if cursor_parts:
            where.append(cursor_parts[0])
            params.extend(cursor_parts[1])
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        if order in ('heat', 'heat_asc') and seed is not None:
            # 只拉排序所需的 id + heat_value 两列,排序后再按 id 取回当前页完整行,
            # 避免把全表所有列(含大字段)读进 Python。
            sort_sql = sql.replace('SELECT f.*', 'SELECT f.id AS id, f.heat_value AS heat_value', 1)
            cur.execute(sort_sql, params)
            sort_rows = cur.fetchall()
            def _k(row):
                s = f"{seed}:{row['id'] or ''}"
                h = hashlib.md5(s.encode('utf-8')).hexdigest()
                rand_key = int(h[:8], 16)
                hv = row['heat_value']
                try:
                    hvn = int(hv) if hv is not None else 0
                except Exception:
                    try:
                        hvn = int(float(hv)) if hv is not None else 0
                    except Exception:
                        hvn = 0
                # heat uses desc (-hvn), heat_asc uses asc (hvn)
                val = -hvn if order == 'heat' else hvn
                return (val, rand_key)
            sort_rows.sort(key=_k)
            selected_ids = [r['id'] for r in sort_rows[int(offset):int(offset)+int(limit)]]
            rows = self._get_rows_by_ids(cur, selected_ids)
            conn.close()
            return rows
        if order == 'random':
            # 仅在完全无筛选且无 seed 的随机浏览模式下做「每模特最多 2 张」分散。
            # 只需 id + 首个 model_id 两列,再按 id 取回当前页完整行。
            per_model_limit = 2 if (
                not model_ids
                and not tag_ids
                and not exclude_tag_ids
                and not name
                and media_kind is None
                and min_heat is None
                and max_heat is None
                and seed is None
            ) else None
            if per_model_limit:
                cur.execute('''
                    SELECT f.id AS id, g.model_id AS first_model_id
                    FROM files f
                    LEFT JOIN (
                        SELECT fm.file_id, MIN(fm.model_id) AS model_id
                        FROM file_models fm
                        GROUP BY fm.file_id
                    ) g ON g.file_id = f.id
                ''')
                counts = {}
                limited_ids = []
                for r in cur.fetchall():
                    fid = r['id']
                    key = r['first_model_id'] or '__none__'
                    n = counts.get(key, 0)
                    if n >= per_model_limit:
                        continue
                    counts[key] = n + 1
                    limited_ids.append(fid)
                random.shuffle(limited_ids)
                selected_ids = limited_ids[int(offset):int(offset)+int(limit)]
                rows = self._get_rows_by_ids(cur, selected_ids)
                conn.close()
                return rows
            if seed is not None:
                sort_sql = sql.replace('SELECT f.*', 'SELECT f.id AS id', 1)
                cur.execute(sort_sql, params)
                sort_rows = cur.fetchall()
                def _key(row):
                    s = f"{seed}:{row['id'] or ''}"
                    h = hashlib.md5(s.encode('utf-8')).hexdigest()
                    return int(h[:8], 16)
                sort_rows.sort(key=_key)
                selected_ids = [r['id'] for r in sort_rows[int(offset):int(offset)+int(limit)]]
                rows = self._get_rows_by_ids(cur, selected_ids)
                conn.close()
                return rows
            # 无 seed 无模特分散：使用 SQL 级别随机排序，避免加载全部行
            sql += ' ORDER BY RANDOM() LIMIT ? OFFSET ?'
            params.extend([int(limit), int(offset)])
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
            conn.close()
            return rows
        if order == 'duration':
            sql += ' ORDER BY COALESCE(f.duration_ms, 0) DESC, f.created_at DESC, f.id'
        elif order == 'duration_asc':
            sql += ' ORDER BY COALESCE(f.duration_ms, 0) ASC, f.created_at DESC, f.id'
        elif order == 'heat':
            sql += ' ORDER BY COALESCE(f.heat_value, 0) DESC, f.created_at DESC, f.id'
        elif order == 'heat_asc':
            sql += ' ORDER BY COALESCE(f.heat_value, 0) ASC, f.created_at DESC, f.id'
        elif order == 'recent_asc':
            sql += ' ORDER BY f.created_at ASC, f.id'
        elif order == 'name':
            sql += " ORDER BY COALESCE(NULLIF(f.original_file_name, ''), f.file_name) COLLATE NOCASE ASC, f.id"
        else:
            sql += ' ORDER BY f.created_at DESC, f.id'
        # 游标分页：LIMIT 不带 OFFSET；无游标时退回 OFFSET 分页
        if cursor_parts:
            sql += ' LIMIT ?'
            params.append(int(limit))
        else:
            sql += ' LIMIT ? OFFSET ?'
            params.extend([int(limit), int(offset)])
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    def get_file_rank(self, file_id, model_ids=None, tag_ids=None, exclude_tag_ids=None, strict=True, min_heat=None, max_heat=None, name=None, order='recent', media_kind=None):
        """返回文件在给定筛选+排序下的 0-based 排位；仅支持 SQL 原生排序，不支持 random / seed 排序

        用「统计排在该文件之前的行数」代替 ROW_NUMBER() 全表窗口,
        配合复合排序索引只扫描索引范围,不构建窗口临时 B 树。
        """
        sql_orders = {'recent', 'recent_asc', 'duration', 'duration_asc', 'heat', 'heat_asc'}
        if order not in sql_orders:
            raise ValueError(f'get_file_rank 不支持排序: {order}')
        conn = self.get_connection()
        cursor = conn.cursor()
        where, params = self._build_file_filter_clauses(
            model_ids=model_ids,
            tag_ids=tag_ids,
            exclude_tag_ids=exclude_tag_ids,
            strict=strict,
            min_heat=min_heat,
            max_heat=max_heat,
            name=name,
            media_kind=media_kind,
        )
        # 先取目标行的排序字段;文件不存在时与旧实现一致返回 None
        cursor.execute('SELECT id, created_at, duration_ms, heat_value FROM files WHERE id = ?', (file_id,))
        target = cursor.fetchone()
        if target is None:
            conn.close()
            return None
        # 目标行自身也必须满足筛选条件,否则不在结果集中
        if where:
            target_where = ' AND '.join(where + ['f.id = ?'])
            cursor.execute(f'SELECT 1 FROM files f WHERE {target_where} LIMIT 1', params + [file_id])
            if cursor.fetchone() is None:
                conn.close()
                return None

        def _to_int(value):
            if value is None:
                return 0
            try:
                return int(value)
            except (TypeError, ValueError):
                try:
                    return int(float(value))
                except (TypeError, ValueError):
                    return 0

        target_duration = _to_int(target['duration_ms'])
        target_heat = _to_int(target['heat_value'])
        # 行值比较在含 NULL/COALESCE 的列上不可靠,这里展开成等价的 AND/OR 条件,
        # 让 SQLite 能命中复合索引并且结果与 ROW_NUMBER() 一致。
        clauses = list(where)
        if order == 'duration':
            expr = 'COALESCE(f.duration_ms, 0)'
            primary_op = '>'
            target_primary = target_duration
        elif order == 'duration_asc':
            expr = 'COALESCE(f.duration_ms, 0)'
            primary_op = '<'
            target_primary = target_duration
        elif order == 'heat':
            expr = 'COALESCE(f.heat_value, 0)'
            primary_op = '>'
            target_primary = target_heat
        elif order == 'heat_asc':
            expr = 'COALESCE(f.heat_value, 0)'
            primary_op = '<'
            target_primary = target_heat
        else:
            expr = None

        if expr is not None:
            # 次排序列固定为 created_at DESC, id ASC
            clauses.append(f'({expr} {primary_op} ? OR '
                           f'{expr} = ? AND f.created_at > ? OR '
                           f'{expr} = ? AND f.created_at = ? AND f.id < ?)')
            params.extend([target_primary,
                           target_primary, target['created_at'],
                           target_primary, target['created_at'], target['id']])
        elif order == 'recent_asc':
            clauses.append('(f.created_at < ? OR f.created_at = ? AND f.id < ?)')
            params.extend([target['created_at'], target['created_at'], target['id']])
        else:  # recent (默认): created_at DESC, id ASC
            clauses.append('(f.created_at > ? OR f.created_at = ? AND f.id < ?)')
            params.extend([target['created_at'], target['created_at'], target['id']])
        count_sql = f'SELECT COUNT(*) AS total FROM files f WHERE ' + ' AND '.join(clauses)
        cursor.execute(count_sql, params)
        row = cursor.fetchone()
        conn.close()
        return int((row['total'] if row else 0) or 0)

    def _migrate_remove_recommend_value(self, cursor):
        cursor.execute('PRAGMA foreign_keys = OFF')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS files_new (
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
            )
        ''')
        cursor.execute('SELECT id, file_path, file_name, original_file_name, file_size, md5, file_type, thumbnail_path, image_width, image_height, video_width, video_height, duration_ms, heat_value, created_at, updated_at FROM files')
        for row in cursor.fetchall():
            cursor.execute('''
                INSERT INTO files_new (id, file_path, file_name, original_file_name, file_size, md5, file_type, thumbnail_path, image_width, image_height, video_width, video_height, duration_ms, heat_value, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, 0), ?, ?)
            ''', (
                row['id'], row['file_path'], row['file_name'], row['original_file_name'],
                row['file_size'], row['md5'], row['file_type'], row['thumbnail_path'],
                row['image_width'], row['image_height'], row['video_width'], row['video_height'],
                row['duration_ms'], row['heat_value'], row['created_at'], row['updated_at']
            ))
        cursor.execute('DROP TABLE files')
        cursor.execute('ALTER TABLE files_new RENAME TO files')
        cursor.execute('PRAGMA foreign_keys = ON')

    def increment_file_heat(self, file_id, delta=1):
        conn = self.get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            cursor.execute('UPDATE files SET heat_value = COALESCE(heat_value, 0) + ?, updated_at = ? WHERE id = ?', (int(delta), now, file_id))
            conn.commit()
            cursor.execute('SELECT heat_value FROM files WHERE id = ?', (file_id,))
            row = cursor.fetchone()
            return (row['heat_value'] if row else 0)
        finally:
            conn.close()

    def get_all_files_with_relations(self):
        """获取所有文件及其关联的模特和标签信息（批量查询，3条SQL）"""
        files = self._query('SELECT * FROM files ORDER BY created_at DESC')
        if not files:
            return []
        # 查询出口统一解析为绝对路径（DB 存 data/ 相对）
        for f in files:
            if f.get('file_path'):
                f['file_path'] = resolve_abs(f['file_path'])
            if f.get('thumbnail_path'):
                f['thumbnail_path'] = resolve_abs(f['thumbnail_path'])
        file_ids = [f['id'] for f in files]
        # 导出/筛选只需要 id/name,不带预览大字段,避免把 base64 图片整表读进内存
        models_map = self.get_files_models_batch(file_ids, include_preview=False)
        tags_map = self.get_files_tags_batch(file_ids, include_preview=False)
        result = []
        for file in files:
            file_id = file['id']
            result.append({
                'file': file,
                'models': models_map.get(file_id, []),
                'tags': tags_map.get(file_id, []),
            })
        return result
    
    def _get_access_password(self):
        """读取当前访问码(带 2 秒内存缓存)。

        require_access 会对每张缩略图/媒体文件请求做鉴权;若每次 SELECT 一次 DB,
        等于每加载一张图就多一次数据库读。缓存后只有密码轮换时才重新读库。
        TTL 让多 worker 场景下轮换后最多 2 秒即可收敛。
        """
        now = _time.monotonic()
        code, expires = self._access_password_cache
        if expires > now:
            return code
        row = self._query('SELECT code FROM access_password WHERE id = ?', ('current',), fetch='one')
        code = (str(row['code']) if row and row['code'] else None)
        self._access_password_cache = (code, now + 2.0)
        return code

    def rotate_access_password(self):
        with self.transaction() as conn:
            cursor = conn.cursor()
            code = secrets.token_urlsafe(6)
            now = datetime.now().isoformat()
            cursor.execute('UPDATE access_password SET code = ?, created_at = ? WHERE id = ?', (code, now, 'current'))
        self._access_password_cache = (code, _time.monotonic() + 2.0)
        return code
    
    def validate_access_password(self, code):
        current = self._get_access_password()
        return bool(current and current == str(code or ''))
    
    def get_current_access_password(self):
        return self._get_access_password()
