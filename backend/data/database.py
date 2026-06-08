import sqlite3
import os
import uuid
import hashlib
import random
import base64
import json
import secrets
from datetime import datetime
from pathlib import Path
from PIL import Image
try:
    import cv2  # 可选：仅用于视频元数据提取
except Exception:
    cv2 = None


class Database:
    """SQLite数据库管理类"""
    
    def __init__(self, db_path=None):
        if db_path is None:
            env_db = os.environ.get('CW_DB_PATH')
            if env_db:
                db_path = env_db
            else:
                db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'image_classifier.db'))
        self.db_path = db_path
        # 确保数据库目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.init_database()
    
    def get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
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
        """初始化数据库表结构"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
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
                updated_at TEXT NOT NULL
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
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_created_at ON files(created_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_heat_value ON files(heat_value)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_models_sort_order ON models(sort_order)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_tags_sort_order ON tags(sort_order)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_file_type ON files(file_type)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_files_duration_ms ON files(duration_ms)')

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
        conn.close()
        
        conn = self.get_connection()
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
        conn.close()
    
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
    
    def _migrate_remove_image_data(self, cursor):
        """迁移数据库：移除image_data字段，添加md5字段"""
        try:
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
            
            # 迁移数据（不迁移image_data，md5字段为NULL）
            cursor.execute('SELECT id, file_path, file_name, file_size, created_at, updated_at FROM files')
            for row in cursor.fetchall():
                cursor.execute('''
                    INSERT INTO files_new (id, file_path, file_name, file_size, md5, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (row['id'], row['file_path'], row['file_name'], row['file_size'], 
                      None, row['created_at'], row['updated_at']))
            
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
            
            # 迁移models表
            try:
                cursor.execute('SELECT * FROM models')
                for row in cursor.fetchall():
                    old_id = row['id']
                    new_id = self._generate_guid()
                    model_id_map[old_id] = new_id
                    cursor.execute('''
                        INSERT INTO models_new (id, name, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                    ''', (new_id, row['name'], row['created_at'], row['updated_at']))
            except Exception:
                pass  # 表可能不存在
            
            # 迁移tags表
            try:
                cursor.execute('SELECT * FROM tags')
                for row in cursor.fetchall():
                    old_id = row['id']
                    new_id = self._generate_guid()
                    tag_id_map[old_id] = new_id
                    cursor.execute('''
                        INSERT INTO tags_new (id, name, created_at, updated_at)
                        VALUES (?, ?, ?, ?)
                    ''', (new_id, row['name'], row['created_at'], row['updated_at']))
            except Exception:
                pass  # 表可能不存在
            
            # 迁移files表
            try:
                cursor.execute('SELECT * FROM files')
                for row in cursor.fetchall():
                    old_id = row['id']
                    new_id = self._generate_guid()
                    file_id_map[old_id] = new_id
                    cursor.execute('''
                        INSERT INTO files_new (id, file_path, file_name, file_size, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (new_id, row['file_path'], row['file_name'], row['file_size'], 
                          row['created_at'], row['updated_at']))
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
        return self._query('SELECT * FROM models ORDER BY sort_order, name')

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

    def get_tags_with_category_name(self, only_active=False):
        if only_active:
            return self._query(
                'SELECT t.*, c.name AS category_name FROM tags t LEFT JOIN tag_categories c ON t.category_id = c.id WHERE t.is_active = 1 ORDER BY c.sort_order, c.name, t.sort_order, t.name'
            )
        return self._query(
            'SELECT t.*, c.name AS category_name FROM tags t LEFT JOIN tag_categories c ON t.category_id = c.id ORDER BY c.sort_order, c.name, t.sort_order, t.name'
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
    
    def add_file(self, file_path, file_name=None, file_size=None):
        """添加文件记录，自动计算MD5值"""
        if file_name is None:
            file_name = os.path.basename(file_path)
        if file_size is None and os.path.exists(file_path):
            file_size = os.path.getsize(file_path)
        now = datetime.now().isoformat()

        # 计算MD5值
        md5_value = None
        if os.path.exists(file_path):
            try:
                md5_hash = hashlib.md5()
                with open(file_path, 'rb') as f:
                    for chunk in iter(lambda: f.read(4096), b''):
                        md5_hash.update(chunk)
                md5_value = md5_hash.hexdigest()
            except Exception:
                pass

        with self.transaction() as conn:
            cursor = conn.cursor()
            file_id = self._generate_guid()
            original_file_name = file_name
            ext = os.path.splitext(file_name)[1].lower().lstrip('.') if file_name else None
            file_type = ext or 'unknown'
            try:
                cursor.execute('''
                    INSERT INTO files (id, file_path, file_name, original_file_name, file_size, md5, file_type, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (file_id, file_path, file_name, original_file_name, file_size, md5_value, file_type, now, now))
                return file_id
            except sqlite3.IntegrityError:
                cursor.execute('SELECT id FROM files WHERE file_path = ?', (file_path,))
                row = cursor.fetchone()
                return dict(row)['id'] if row else None
    
    def get_file(self, file_path):
        """根据路径获取文件记录"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM files WHERE file_path = ?', (file_path,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    
    def get_file_by_id(self, file_id):
        return self._query('SELECT * FROM files WHERE id = ?', (file_id,), fetch='one')
    
    def update_file(self, file_id, file_path=None, file_name=None, file_size=None, file_type=None):
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
            updates.append('file_path = ?')
            params.append(file_path)
            if file_type is None:
                try:
                    ext = os.path.splitext(file_path)[1].lower().lstrip('.')
                    file_type = ext or 'unknown'
                except Exception:
                    file_type = None
        if file_name is not None:
            updates.append('file_name = ?')
            params.append(file_name)
        if file_size is not None:
            updates.append('file_size = ?')
            params.append(file_size)

        if file_type is not None:
            updates.append('file_type = ?')
            params.append(file_type)

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
        cursor.execute('UPDATE files SET thumbnail_path = ?, updated_at = ? WHERE id = ?', (thumbnail_path, datetime.now().isoformat(), file_id))
        conn.commit()
        conn.close()
        return True
    
    def update_original_file_name(self, file_id, original_file_name):
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE files SET original_file_name = ?, updated_at = ? WHERE id = ?', (original_file_name, datetime.now().isoformat(), file_id))
            return True

    def delete_file(self, file_id):
        """删除文件记录（外键 CASCADE 自动清理 file_models / file_tags 关联）"""
        with self.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM files WHERE id = ?', (file_id,))
            return True
    
    def save_image_data(self, file_id, image_path):
        """计算并保存图片的MD5值与尺寸到数据库"""
        conn = self.get_connection()
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        
        try:
            # 计算图片文件的MD5值
            md5_hash = hashlib.md5()
            with open(image_path, 'rb') as f:
                # 分块读取，避免大文件占用过多内存
                for chunk in iter(lambda: f.read(4096), b''):
                    md5_hash.update(chunk)
            md5_value = md5_hash.hexdigest()
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
            relation_id = self._generate_guid()
            cursor.execute('''
                INSERT INTO file_models (id, file_id, model_id, created_at)
                VALUES (?, ?, ?, ?)
            ''', (relation_id, file_id, model_id, now))
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
        cursor.execute('''
            DELETE FROM file_models 
            WHERE file_id = ? AND model_id = ?
        ''', (file_id, model_id))
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
            cursor.execute('DELETE FROM file_models WHERE file_id = ?', (file_id,))
            for model_id in model_ids:
                relation_id = self._generate_guid()
                cursor.execute('''
                    INSERT INTO file_models (id, file_id, model_id, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (relation_id, file_id, model_id, now))
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
        conn.commit()
        conn.close()
        return True
    
    def get_file_tags(self, file_id):
        return self._query(
            'SELECT t.* FROM tags t INNER JOIN file_tags ft ON t.id = ft.tag_id WHERE ft.file_id = ? ORDER BY t.name',
            (file_id,)
        )

    def get_files_models_batch(self, file_ids):
        if not file_ids:
            return {}
        conn = self.get_connection()
        cursor = conn.cursor()
        result = {fid: [] for fid in file_ids}
        chunk_size = 900
        for i in range(0, len(file_ids), chunk_size):
            chunk = file_ids[i:i + chunk_size]
            placeholders = ','.join(['?'] * len(chunk))
            cursor.execute(
                f'SELECT fm.file_id, m.* FROM file_models fm INNER JOIN models m ON fm.model_id = m.id WHERE fm.file_id IN ({placeholders}) ORDER BY m.name',
                chunk
            )
            for row in cursor.fetchall():
                r = dict(row)
                result.setdefault(r.pop('file_id'), []).append(r)
        conn.close()
        return result

    def get_files_tags_batch(self, file_ids):
        if not file_ids:
            return {}
        conn = self.get_connection()
        cursor = conn.cursor()
        result = {fid: [] for fid in file_ids}
        chunk_size = 900
        for i in range(0, len(file_ids), chunk_size):
            chunk = file_ids[i:i + chunk_size]
            placeholders = ','.join(['?'] * len(chunk))
            cursor.execute(
                f'SELECT ft.file_id, t.* FROM file_tags ft INNER JOIN tags t ON ft.tag_id = t.id WHERE ft.file_id IN ({placeholders}) ORDER BY t.name',
                chunk
            )
            for row in cursor.fetchall():
                r = dict(row)
                result.setdefault(r.pop('file_id'), []).append(r)
        conn.close()
        return result

    def get_models_tags_batch(self, model_ids):
        if not model_ids:
            return {}
        conn = self.get_connection()
        cursor = conn.cursor()
        result = {mid: [] for mid in model_ids}
        chunk_size = 900
        for i in range(0, len(model_ids), chunk_size):
            chunk = model_ids[i:i + chunk_size]
            placeholders = ','.join(['?'] * len(chunk))
            cursor.execute(
                f'SELECT mt.model_id, t.* FROM model_tags mt INNER JOIN tags t ON mt.tag_id = t.id WHERE mt.model_id IN ({placeholders}) ORDER BY t.name',
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
            cursor.execute('DELETE FROM file_tags WHERE file_id = ?', (file_id,))
            for tag_id in tag_ids:
                relation_id = self._generate_guid()
                cursor.execute('''
                    INSERT INTO file_tags (id, file_id, tag_id, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (relation_id, file_id, tag_id, now))
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
            cursor.execute('DELETE FROM model_tags WHERE model_id = ?', (model_id,))
            for tag_id in tag_ids:
                relation_id = self._generate_guid()
                cursor.execute('''
                    INSERT INTO model_tags (id, model_id, tag_id, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (relation_id, model_id, tag_id, now))
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
        value = str(self.get_app_setting('true_random_cache_enabled', '1')).strip().lower()
        return value not in ('0', 'false', 'off', 'no')

    def set_true_random_cache_enabled(self, enabled):
        self.set_app_setting('true_random_cache_enabled', '1' if bool(enabled) else '0')
        return self.get_true_random_cache_enabled()

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
        return total

    def count_true_random_cache(self):
        row = self._query('SELECT COUNT(*) AS total FROM true_random_cache', fetch='one')
        return int((row['total'] if row else 0) or 0)

    def query_files_with_filters(self, model_ids=None, tag_ids=None, exclude_tag_ids=None, strict=True, min_heat=None, max_heat=None, offset=0, limit=30, order='recent', seed=None, name=None, blacklist_cache_key=None):
        """按筛选条件分页查询文件，支持严格/任意匹配与排序；当提供 seed 且 order=random 时，使用可复现的伪随机顺序"""
        conn = self.get_connection()
        cursor = conn.cursor()
        sql = 'SELECT f.* FROM files f'
        where = []
        params = []
        mids = list(model_ids or [])
        tids = list(tag_ids or [])
        ex_tids = list(exclude_tag_ids or [])
        if name:
            q = f"%{str(name).strip().lower()}%"
            where.append('('
                         'LOWER(f.file_name) LIKE ? OR '
                         'LOWER(IFNULL(f.original_file_name, "")) LIKE ? OR '
                         'LOWER(f.file_path) LIKE ?'
                         ')')
            params.extend([q, q, q])
        if min_heat is not None:
            where.append('COALESCE(f.heat_value, 0) >= ?')
            params.append(int(min_heat))
        if max_heat is not None:
            where.append('COALESCE(f.heat_value, 0) <= ?')
            params.append(int(max_heat))
        if mids:
            if strict:
                for mid in mids:
                    where.append('EXISTS (SELECT 1 FROM file_models fm WHERE fm.file_id = f.id AND fm.model_id = ?)')
                    params.append(mid)
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
        if blacklist_cache_key:
            where.append('NOT EXISTS (SELECT 1 FROM true_random_cache trc WHERE trc.cache_key = ? AND trc.file_id = f.id)')
            params.append(str(blacklist_cache_key).strip())
        if where:
            sql += ' WHERE ' + ' AND '.join(where)
        if order in ('heat', 'heat_asc') and seed is not None:
            cursor.execute(sql, params)
            all_rows = [dict(r) for r in cursor.fetchall()]
            def _k(row):
                s = f"{seed}:{row.get('id') or ''}"
                h = hashlib.md5(s.encode('utf-8')).hexdigest()
                rand_key = int(h[:8], 16)
                hv = row.get('heat_value')
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
            all_rows.sort(key=_k)
            rows = all_rows[int(offset):int(offset)+int(limit)]
            conn.close()
            return rows
        if order == 'random':
            # 仅在完全无筛选且无 seed 的随机浏览模式下需要加载全部行做模特分散
            per_model_limit = 2 if (
                not mids
                and not tids
                and not ex_tids
                and not name
                and min_heat is None
                and max_heat is None
                and seed is None
            ) else None
            if per_model_limit:
                cursor.execute(sql, params)
                all_rows = [dict(r) for r in cursor.fetchall()]
                ids = [r.get('id') for r in all_rows if r.get('id')]
                model_map = {}
                if ids:
                    chunk_size = 900
                    for i in range(0, len(ids), chunk_size):
                        chunk = ids[i:i + chunk_size]
                        placeholders = ','.join(['?'] * len(chunk))
                        cursor.execute(f'SELECT file_id, model_id FROM file_models WHERE file_id IN ({placeholders})', chunk)
                        for r in cursor.fetchall():
                            model_map.setdefault(r['file_id'], []).append(r['model_id'])
                counts = {}
                limited = []
                for row in all_rows:
                    fid = row.get('id')
                    mids_for = model_map.get(fid) or []
                    key = (sorted(mids_for)[0] if mids_for else '__none__')
                    n = counts.get(key, 0)
                    if n >= per_model_limit:
                        continue
                    counts[key] = n + 1
                    limited.append(row)
                random.shuffle(limited)
                rows = limited[int(offset):int(offset)+int(limit)]
                conn.close()
                return rows
            if seed is not None:
                cursor.execute(sql, params)
                all_rows = [dict(r) for r in cursor.fetchall()]
                def _key(row):
                    s = f"{seed}:{row.get('id') or ''}"
                    h = hashlib.md5(s.encode('utf-8')).hexdigest()
                    return int(h[:8], 16)
                all_rows.sort(key=_key)
                rows = all_rows[int(offset):int(offset)+int(limit)]
                conn.close()
                return rows
            # 无 seed 无模特分散：使用 SQL 级别随机排序，避免加载全部行
            sql += ' ORDER BY RANDOM() LIMIT ? OFFSET ?'
            params.extend([int(limit), int(offset)])
            cursor.execute(sql, params)
            rows = [dict(r) for r in cursor.fetchall()]
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
        else:
            sql += ' ORDER BY f.created_at DESC, f.id'
        sql += ' LIMIT ? OFFSET ?'
        params.extend([int(limit), int(offset)])
        cursor.execute(sql, params)
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    def get_file_rank(self, file_id, model_ids=None, tag_ids=None, exclude_tag_ids=None, strict=True, min_heat=None, max_heat=None, name=None, order='recent'):
        """返回文件在给定筛选+排序下的 0-based 排位；仅支持 SQL 原生排序，不支持 random / seed 排序"""
        # 仅支持 SQL 原生排序
        sql_orders = {'recent', 'recent_asc', 'duration', 'duration_asc', 'heat', 'heat_asc'}
        if order not in sql_orders:
            raise ValueError(f'get_file_rank 不支持排序: {order}')
        conn = self.get_connection()
        cursor = conn.cursor()
        # 构建 WHERE 子句（与 query_files_with_filters 保持一致）
        where = []
        params = []
        mids = list(model_ids or [])
        tids = list(tag_ids or [])
        ex_tids = list(exclude_tag_ids or [])
        if name:
            q = f"%{str(name).strip().lower()}%"
            where.append('('
                         'LOWER(f.file_name) LIKE ? OR '
                         'LOWER(IFNULL(f.original_file_name, "")) LIKE ? OR '
                         'LOWER(f.file_path) LIKE ?'
                         ')')
            params.extend([q, q, q])
        if min_heat is not None:
            where.append('COALESCE(f.heat_value, 0) >= ?')
            params.append(int(min_heat))
        if max_heat is not None:
            where.append('COALESCE(f.heat_value, 0) <= ?')
            params.append(int(max_heat))
        if mids:
            if strict:
                for mid in mids:
                    where.append('EXISTS (SELECT 1 FROM file_models fm WHERE fm.file_id = f.id AND fm.model_id = ?)')
                    params.append(mid)
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
        # 构建排序子句
        if order == 'duration':
            order_clause = 'ORDER BY COALESCE(f.duration_ms, 0) DESC, f.created_at DESC, f.id'
        elif order == 'duration_asc':
            order_clause = 'ORDER BY COALESCE(f.duration_ms, 0) ASC, f.created_at DESC, f.id'
        elif order == 'heat':
            order_clause = 'ORDER BY COALESCE(f.heat_value, 0) DESC, f.created_at DESC, f.id'
        elif order == 'heat_asc':
            order_clause = 'ORDER BY COALESCE(f.heat_value, 0) ASC, f.created_at DESC, f.id'
        elif order == 'recent_asc':
            order_clause = 'ORDER BY f.created_at ASC, f.id'
        else:  # recent (默认)
            order_clause = 'ORDER BY f.created_at DESC, f.id'
        # 构建 CTE 查询
        where_sql = (' WHERE ' + ' AND '.join(where)) if where else ''
        sql = f'WITH filtered AS (SELECT f.id, ROW_NUMBER() OVER ({order_clause}) - 1 AS rank FROM files f{where_sql}) SELECT rank FROM filtered WHERE id = ?'
        params.append(file_id)
        cursor.execute(sql, params)
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None  # 文件不在筛选结果中
        return row['rank']

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
        file_ids = [f['id'] for f in files]
        models_map = self.get_files_models_batch(file_ids)
        tags_map = self.get_files_tags_batch(file_ids)
        result = []
        for file in files:
            file_id = file['id']
            result.append({
                'file': file,
                'models': models_map.get(file_id, []),
                'tags': tags_map.get(file_id, []),
            })
        return result
    
    def rotate_access_password(self):
        with self.transaction() as conn:
            cursor = conn.cursor()
            code = secrets.token_urlsafe(6)
            now = datetime.now().isoformat()
            cursor.execute('UPDATE access_password SET code = ?, created_at = ? WHERE id = ?', (code, now, 'current'))
            return code
    
    def validate_access_password(self, code):
        row = self._query('SELECT code FROM access_password WHERE id = ?', ('current',), fetch='one')
        return bool(row and str(row['code'] or '') == str(code or ''))
    
    def get_current_access_password(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT code FROM access_password WHERE id = ?', ('current',))
        row = cursor.fetchone()
        conn.close()
        return (row['code'] if row else None)
