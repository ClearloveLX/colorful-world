from fastapi import FastAPI, Query, Request, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from typing import Optional
import logging
import os
import base64
import hashlib
import json
from fastapi import HTTPException
import sys
import subprocess
import urllib.request
import urllib.parse
import ctypes
import shutil
from datetime import datetime

logger = logging.getLogger("colorfulworld")
from typing import List
from pydantic import BaseModel

from backend.data.database import Database, resolve_abs

# CORS 白名单：生产同源访问不经过 CORS；仅 Vite dev (5173→8000) 与同源端口需要放行
_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

# 登录流程自身所需的端点豁免鉴权；其余全部 /api/* 必须携带有效访问码。
# /api/password/current 必须豁免：锁屏页需预取访问码写入 localStorage 以便自动填入。
_AUTH_EXEMPT_PATHS = {"/api/password/validate", "/api/password/current"}

def require_access(request: Request) -> None:
    """全局 API 鉴权：优先 cookie（登录后浏览器自动携带），兼容 header / query 通道。"""
    path = request.url.path
    if not path.startswith("/api/"):
        return  # SPA 页面与前端静态资源
    if path in _AUTH_EXEMPT_PATHS:
        return
    code = (
        request.cookies.get("cw_access_code")
        or request.headers.get("X-Access-Code")
        or request.query_params.get("code", "")
    )
    if not code or not db.validate_access_password(code):
        raise HTTPException(status_code=401, detail="invalid access code")

app = FastAPI(title="Media Gallery API", dependencies=[Depends(require_access)])

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Length", "Content-Range"],
)

# /api/static 只允许公开子目录，避免项目根（源码/数据库/.git）被下载
_STATIC_ALLOWED_PREFIXES = ("data", "output", "frontend/dist", "frontend/public")
# 白名单内仍禁止下载数据库文件（默认库位于项目 data/ 下）
_STATIC_DENY_SUFFIXES = (".db", ".db-wal", ".db-shm", ".db.bak", ".sqlite", ".sqlite3", ".bak")

@app.middleware("http")
async def static_path_guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/static/"):
        rel = path[len("/api/static/"):].lstrip("/")
        rel_norm = os.path.normpath(rel).replace("\\", "/")
        allowed = any(rel_norm == p or rel_norm.startswith(p + "/") for p in _STATIC_ALLOWED_PREFIXES)
        if not allowed:
            # middleware 中不能 raise HTTPException（不会被异常处理器捕获），直接返回响应
            return Response(status_code=403, content=b'{"detail":"access denied"}', media_type="application/json")
        if rel_norm.lower().endswith(_STATIC_DENY_SUFFIXES):
            return Response(status_code=403, content=b'{"detail":"access denied"}', media_type="application/json")
    return await call_next(request)

# 以项目根目录作为静态基准，便于通过 /api/static/data/... 访问文件
STATIC_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_ENV_ROOT = os.environ.get('CW_DATA_ROOT')
if _ENV_ROOT and _ENV_ROOT.strip():
    DATA_ROOT = os.path.abspath(_ENV_ROOT)
else:
    # 优先使用 L:\data（若存在），否则退回项目内 data
    candidate = r"L:\data"
    DATA_ROOT = os.path.abspath(candidate) if os.path.isdir(candidate) else os.path.abspath(os.path.join(STATIC_BASE, 'data'))
app.mount("/api/static", StaticFiles(directory=STATIC_BASE), name="static")

db = Database()

def _normalize_media_type(media_type: str) -> str:
    value = (media_type or '').strip().lower()
    if value not in {'image', 'video'}:
        raise HTTPException(status_code=400, detail='media_type 仅支持 image 或 video')
    return value

def _handle_preset_error(exc: Exception):
    if isinstance(exc, KeyError):
        raise HTTPException(status_code=404, detail=str(exc).strip("'"))
    raise HTTPException(status_code=400, detail=str(exc))

def _build_true_random_cache_key(model_ids, tag_ids, exclude_tag_ids, strict, min_heat, max_heat, name):
    payload = {
        "model_ids": sorted([str(v) for v in (model_ids or []) if str(v).strip()]),
        "tag_ids": sorted([str(v) for v in (tag_ids or []) if str(v).strip()]),
        "exclude_tag_ids": sorted([str(v) for v in (exclude_tag_ids or []) if str(v).strip()]),
        "strict": bool(strict),
        "min_heat": min_heat,
        "max_heat": max_heat,
        "name": (name or '').strip().lower(),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.md5(raw.encode('utf-8')).hexdigest()

def _to_static_url(p: Optional[str]) -> Optional[str]:
    if not p:
        return None
    s = str(p)
    if s.startswith("http://") or s.startswith("https://") or s.startswith("/api/static/") or s.startswith("data:"):
        return s
    s_slash = s.replace("\\", "/")
    proj_data_abs = os.path.abspath(os.path.join(STATIC_BASE, 'data'))
    p_norm = os.path.normcase(os.path.normpath(s))
    prefix_norm = os.path.normcase(os.path.normpath(proj_data_abs))
    if p_norm.startswith(prefix_norm + os.sep) or p_norm == prefix_norm:
        try:
            rel_in_data = os.path.relpath(p_norm, prefix_norm).replace("\\", "/")
            fs_path = os.path.join(DATA_ROOT, rel_in_data)
            b64 = base64.urlsafe_b64encode(fs_path.encode('utf-8')).decode('ascii').rstrip('=')
            return f"/api/file?path={b64}"
        except Exception:
            pass
    if s_slash.lower().startswith("data/"):
        try:
            rel_in_data = s_slash[5:]
            fs_path = os.path.join(DATA_ROOT, rel_in_data)
            b64 = base64.urlsafe_b64encode(fs_path.encode('utf-8')).decode('ascii').rstrip('=')
            return f"/api/file?path={b64}"
        except Exception:
            pass
    try:
        rel = os.path.relpath(s_slash, STATIC_BASE).replace("\\", "/")
    except Exception:
        rel = s_slash
    if os.path.isabs(s):
        try:
            s_norm = os.path.normcase(os.path.normpath(s))
            marker = os.sep + "data" + os.sep
            if marker in s_norm:
                idx = s_norm.index(marker)
                rel_in_data = s_norm[idx + len(marker):].replace("\\", "/")
                fs_path = os.path.join(DATA_ROOT, rel_in_data)
                b64 = base64.urlsafe_b64encode(fs_path.encode('utf-8')).decode('ascii').rstrip('=')
                return f"/api/file?path={b64}"
        except Exception:
            pass
    if os.path.isabs(s):
        try:
            b64 = base64.urlsafe_b64encode(s.encode('utf-8')).decode('ascii').rstrip('=')
            return f"/api/file?path={b64}"
        except Exception:
            return None
    if rel.startswith("/"):
        rel = rel[1:]
    return "/api/static/" + rel

def _to_data_url(b64: Optional[str]) -> Optional[str]:
    if not b64:
        return None
    s = str(b64)
    if s.startswith("data:"):
        return s
    if s.startswith("http://") or s.startswith("https://") or s.startswith("/api/static/"):
        return s
    try:
        base64.b64decode(s, validate=True)
        return "data:image/jpeg;base64," + s
    except Exception:
        return _to_static_url(s)

@app.get("/api/models")
def get_models():
    models = db.get_all_models()
    types = {t['id']: t['name'] for t in db.get_all_model_types()}
    return [{"id": m["id"], "name": m["name"], "type": (types.get(m.get("model_type_id")) or m.get("model_type") or None), "preview_image_path": _to_data_url(m.get("preview_image_path")), "file_count": m.get("file_count", 0)} for m in models]

@app.get("/api/tags")
def get_tags():
    tags = db.get_tags_with_category_name(only_active=False)
    return [{"id": t["id"], "name": t["name"], "category_name": t.get("category_name") or None, "file_count": t.get("file_count", 0)} for t in tags]

class PresetPayload(BaseModel):
    name: str
    sort_order: int
    tags: List[str]

class PresetUpdatePayload(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None
    tags: Optional[List[str]] = None

class TrueRandomCacheSettingsPayload(BaseModel):
    enabled: bool

def _true_random_cache_settings_response():
    return {
        "enabled": db.get_true_random_cache_enabled(),
        "cached_count": db.count_true_random_cache(),
        "source": "database",
    }

@app.post("/api/presets/{media_type}")
def create_preset(media_type: str, payload: PresetPayload):
    media_type = _normalize_media_type(media_type)
    try:
        preset_id = db.create_preset(
            media_type=media_type,
            name=payload.name,
            sort_order=payload.sort_order,
            tags=payload.tags,
        )
        return {"preset_id": preset_id}
    except Exception as exc:
        _handle_preset_error(exc)

@app.put("/api/presets/{media_type}/{preset_id}")
def update_preset(media_type: str, preset_id: str, payload: PresetUpdatePayload):
    media_type = _normalize_media_type(media_type)
    try:
        return db.update_preset(
            media_type=media_type,
            preset_id=preset_id,
            name=payload.name,
            sort_order=payload.sort_order,
            tags=payload.tags,
        )
    except Exception as exc:
        _handle_preset_error(exc)

@app.delete("/api/presets/{media_type}/{preset_id}")
def delete_preset(media_type: str, preset_id: str):
    media_type = _normalize_media_type(media_type)
    try:
        db.delete_preset(media_type=media_type, preset_id=preset_id)
        return {"ok": True}
    except Exception as exc:
        _handle_preset_error(exc)

@app.get("/api/presets/{media_type}")
def list_presets(media_type: str):
    media_type = _normalize_media_type(media_type)
    try:
        return db.list_presets(media_type)
    except Exception as exc:
        _handle_preset_error(exc)

@app.get("/api/presets/{media_type}/{preset_id}")
def get_preset(media_type: str, preset_id: str):
    media_type = _normalize_media_type(media_type)
    try:
        preset = db.get_preset(media_type=media_type, preset_id=preset_id)
        if not preset:
            raise KeyError('预制不存在')
        return preset
    except Exception as exc:
        _handle_preset_error(exc)

@app.get("/api/model_types")
def get_model_types():
    rows = db.get_all_model_types()
    return [{"id": r["id"], "name": r["name"], "is_active": r.get("is_active", 1), "description": r.get("description") or None} for r in rows]

@app.get("/api/settings/true-random-cache")
def get_true_random_cache_settings():
    return _true_random_cache_settings_response()

@app.put("/api/settings/true-random-cache")
def update_true_random_cache_settings(payload: TrueRandomCacheSettingsPayload):
    enabled = db.set_true_random_cache_enabled(payload.enabled)
    return {
        "ok": True,
        "enabled": enabled,
        "cached_count": db.count_true_random_cache(),
        "source": "database",
    }

@app.post("/api/true-random-cache/clear")
def clear_true_random_cache():
    deleted = db.clear_true_random_cache()
    return {"ok": True, "deleted": deleted, "cached_count": 0}

@app.get("/api/media")
def get_media(
    model_ids: Optional[str] = Query(default=None),
    tag_ids: Optional[str] = Query(default=None),
    exclude_tag_ids: Optional[str] = Query(default=None),
    page: int = 1,
    page_size: int = 30,
    strict: bool = True,
    min_heat: Optional[int] = Query(default=None),
    max_heat: Optional[int] = Query(default=None),
    order: Optional[str] = Query(default=None),
    seed: Optional[int] = Query(default=None),
    name: Optional[str] = Query(default=None),
    edit_mode: bool = False,
    true_random: bool = False,
):
    try:
        mset = [s for s in (model_ids or '').split(',') if s]
        tset = [s for s in (tag_ids or '').split(',') if s]
        exset = [s for s in (exclude_tag_ids or '').split(',') if s]
        effective_order = order or 'recent'
        cache_enabled = db.get_true_random_cache_enabled()
        use_true_random_cache = bool(edit_mode and true_random and effective_order == 'random' and cache_enabled)
        blacklist_cache_key = None
        if use_true_random_cache:
            blacklist_cache_key = _build_true_random_cache_key(
                model_ids=mset,
                tag_ids=tset,
                exclude_tag_ids=exset,
                strict=strict,
                min_heat=min_heat,
                max_heat=max_heat,
                name=name,
            )
        offset = 0 if use_true_random_cache else max((page - 1) * page_size, 0)
        rows = db.query_files_with_filters(
            model_ids=mset or None,
            tag_ids=tset or None,
            exclude_tag_ids=exset or None,
            strict=strict,
            min_heat=min_heat,
            max_heat=max_heat,
            offset=offset,
            limit=page_size,
            order=effective_order,
            seed=seed,
            name=name,
            blacklist_cache_key=blacklist_cache_key,
        )
        if use_true_random_cache and rows:
            db.cache_true_random_results(blacklist_cache_key, [row.get('id') for row in rows if row.get('id')])
        file_ids = [f['id'] for f in rows]
        file_models_map = db.get_files_models_batch(file_ids)
        file_tags_map = db.get_files_tags_batch(file_ids)
        all_model_ids = set()
        for models in file_models_map.values():
            for m in models:
                all_model_ids.add(m['id'])
        model_tags_map = db.get_models_tags_batch(list(all_model_ids))
        tag_rows = db.get_tags_with_category_name(only_active=False, with_file_count=False)
        tag_meta = { r['id']: {
            'name': r['name'],
            'category_id': r.get('category_id'),
            'category_name': r.get('category_name') or None,
            'tag_order': r.get('sort_order') or 0,
        } for r in tag_rows }
        categories = db.get_all_tag_categories()
        cat_order = { c['id']: c.get('sort_order') or 0 for c in categories }
        types = { t['id']: t['name'] for t in db.get_all_model_types() }
        def sort_key(tid: str):
            info = tag_meta.get(tid)
            if not info:
                return (0, '', 0, '')
            return (cat_order.get(info['category_id']) or 0, info['category_name'] or '', info['tag_order'] or 0, info['name'] or '')
        slice_items = []
        for f in rows:
            file_id = f['id']
            models = file_models_map.get(file_id, [])
            file_tags = file_tags_map.get(file_id, [])
            model_tags = []
            for m in models:
                model_tags.extend(model_tags_map.get(m['id'], []))
            seen: set[str] = set()
            merged_ids = []
            for t in (file_tags + model_tags):
                tid = t.get('id')
                if not tid or tid in seen:
                    continue
                seen.add(tid)
                merged_ids.append(tid)
            merged_ids.sort(key=sort_key)
            merged_tags = [{ 'id': tid, 'name': (tag_meta.get(tid) or {}).get('name') or '', 'category_name': (tag_meta.get(tid) or {}).get('category_name') or None } for tid in merged_ids]
            slice_items.append({ 'file': f, 'models': models, 'tags': merged_tags })
        def to_url(p: Optional[str]) -> Optional[str]:
            return _to_static_url(p)
        result = []
        for info in slice_items:
            f = info["file"]
            sz = f.get("file_size")
            if not sz:
                try:
                    p = f.get("file_path")
                    if p and os.path.isfile(p):
                        sz = os.path.getsize(p)
                except Exception:
                    sz = None
            ft = (f.get("file_type") or "").lower()
            thumb = f.get("thumbnail_path")
            if (ft in ("mp3", "m4a")) and not thumb:
                svg = '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="100%" height="100%" fill="#eef6ff"/><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="#2563eb" font-size="72">♫</text></svg>'
                try:
                    thumb = "data:image/svg+xml," + urllib.parse.quote(svg)
                except Exception:
                    thumb = None
            result.append({
                "id": f["id"],
                "title": f.get("original_file_name") or f.get("file_name") or f.get("id"),
                "file_path": to_url(f.get("file_path")),
                "file_type": f.get("file_type") or "unknown",
                "thumbnail_path": to_url(thumb if thumb else f.get("thumbnail_path")),
                "file_size": sz,
                "image_width": f.get("image_width"),
                "image_height": f.get("image_height"),
                "video_width": f.get("video_width"),
                "video_height": f.get("video_height"),
                "duration_ms": f.get("duration_ms"),
                "heat_value": f.get("heat_value"),
                "models": [{"id": m["id"], "name": m["name"], "type": (types.get(m.get("model_type_id")) or m.get("model_type") or None), "preview_image_path": m.get("preview_image_path") or None} for m in info.get("models", [])],
                "tags": [{"id": t.get("id"), "name": t.get("name"), "category_name": t.get("category_name")} for t in info.get("tags", [])],
                "created_at": f.get("created_at"),
            })
        has_more = len(rows) == page_size
        return {
            "items": result,
            "hasMore": has_more,
            "true_random_cache": {
                "enabled": cache_enabled,
                "active": use_true_random_cache,
                "cached_count": db.count_true_random_cache(),
            },
        }
    except Exception as e:
        logger.exception("get_media error")
        raise HTTPException(status_code=500, detail="internal error")

# 直接按绝对路径返回本地文件（用于 DATA_ROOT 在其他盘符时）
def _guess_content_type(p: str) -> str:
    ext = os.path.splitext(p)[1].lower()
    if ext == ".mp4": return "video/mp4"
    if ext == ".webm": return "video/webm"
    if ext == ".mkv": return "video/x-matroska"
    if ext == ".avi": return "video/x-msvideo"
    if ext == ".mov": return "video/quicktime"
    if ext == ".m4v": return "video/x-m4v"
    if ext in (".ts", ".m2ts"): return "video/mp2t"
    if ext == ".wmv": return "video/x-ms-wmv"
    if ext in (".mpeg", ".mpg"): return "video/mpeg"
    if ext == ".3gp": return "video/3gpp"
    if ext == ".mp3": return "audio/mpeg"
    if ext == ".m4a": return "audio/mp4"
    if ext in (".jpg", ".jpeg"): return "image/jpeg"
    if ext == ".png": return "image/png"
    if ext == ".gif": return "image/gif"
    if ext == ".webp": return "image/webp"
    return "application/octet-stream"

def _decode_b64_path(path: str) -> str:
    try:
        pad = (4 - (len(path) % 4)) % 4
        padded = path + ("=" * pad)
        return base64.urlsafe_b64decode(padded).decode('utf-8')
    except Exception:
        raise HTTPException(status_code=400, detail="invalid path")

def _validate_file_path(p: str) -> str:
    p = os.path.normpath(os.path.abspath(p))
    if not os.path.isfile(p):
        raise HTTPException(status_code=404, detail="file not found")
    data_root_norm = os.path.normpath(os.path.abspath(DATA_ROOT))
    if not p.startswith(data_root_norm + os.sep) and p != data_root_norm:
        raise HTTPException(status_code=403, detail="access denied")
    return p

def _open_in_system(p: str, raw_path: str) -> bool:
    if os.name == "nt":
        try:
            r = ctypes.windll.shell32.ShellExecuteW(None, "open", p, None, os.path.dirname(p), 1)
            if r and r > 32:
                return True
        except Exception:
            pass
        try:
            u = "http://127.0.0.1:8001/open?path=" + urllib.parse.quote(raw_path)
            # open_helper 要求 Origin 存在且为本机来源（缺失时拒绝），内部调用需显式携带
            req = urllib.request.Request(u, method="POST", headers={"Origin": "http://127.0.0.1:8001"})
            urllib.request.urlopen(req, timeout=1)
            return True
        except Exception:
            pass
        try:
            os.startfile(p)  # type: ignore
            return True
        except Exception:
            pass
        # 注意：不要用 cmd /c start 或 powershell -Command —— 文件名含 & 或 " 时可注入命令
        try:
            subprocess.Popen(["rundll32.exe", "url.dll,FileProtocolHandler", p])
            return True
        except Exception:
            pass
        try:
            subprocess.Popen(["explorer.exe", p])
            return True
        except Exception:
            return False
    if sys.platform == "darwin":
        subprocess.Popen(["open", p])
        return True
    subprocess.Popen(["xdg-open", p])
    return True

def _bulk_apply_tags(file_ids: List[str], tag_ids: List[str], op):
    updated = 0
    skipped = 0
    errors = 0
    for fid in (file_ids or []):
        for tid in (tag_ids or []):
            try:
                ok = op(fid, tid)
                if ok:
                    updated += 1
                else:
                    skipped += 1
            except Exception:
                errors += 1
    return {"ok": True, "updated": updated, "skipped": skipped, "errors": errors}

def _bulk_update_heat(file_ids: List[str], delta: int):
    updated = 0
    skipped = 0
    errors = 0
    for fid in (file_ids or []):
        try:
            row = db.get_file_by_id(fid)
            if not row:
                skipped += 1
                continue
            db.increment_file_heat(fid, delta=delta)
            updated += 1
        except Exception:
            errors += 1
    return {"ok": True, "updated": updated, "skipped": skipped, "errors": errors}

def _resolve_db_file_path(file_path):
    """DB 相对路径解析（data/ 前缀 → DATA_ROOT 绝对，含逃逸检查），对齐公共实现。"""
    return resolve_abs(file_path, DATA_ROOT)


def _bulk_blacklist(file_ids: List[str]):
    """批量加入黑名单：移动到 DATA_ROOT/bad + 删除数据库记录。

    文件缺失时仍删记录（记录已无意义）；move 失败时不删记录。
    路径不做 DATA_ROOT 限制：库内文件分布多盘（与客户端 add_to_blacklist 行为一致），
    相对路径（data/good/...）按 DATA_ROOT 解析。
    """
    updated = 0
    skipped = 0
    errors = 0
    root = os.path.abspath(DATA_ROOT)
    for fid in (file_ids or []):
        try:
            row = db.get_file_by_id(fid)
            if not row:
                skipped += 1
                continue
            file_path = row.get('file_path') or ''
            if not file_path:
                skipped += 1
                continue
            ap = _resolve_db_file_path(file_path)
            if ap is None:
                errors += 1
                continue
            ap = os.path.abspath(ap)
            if os.path.isfile(ap):
                bad_folder = os.path.join(root, "bad")
                # 已在黑名单文件夹时跳过移动（与客户端 add_to_blacklist 一致）
                if os.path.dirname(ap) != bad_folder:
                    os.makedirs(bad_folder, exist_ok=True)
                    # 优先用原始文件名（便于辨认），缺失时回退当前文件名
                    orig = (row.get('original_file_name') or '').strip()
                    target_name = os.path.basename(orig) if orig else os.path.basename(ap)
                    target = os.path.join(bad_folder, target_name)
                    if os.path.exists(target):
                        name, ext = os.path.splitext(target_name)
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        target = os.path.join(bad_folder, f"{name}_{timestamp}{ext}")
                    shutil.move(ap, target)
            db.delete_file(fid)
            updated += 1
        except Exception:
            errors += 1
    return {"ok": True, "updated": updated, "skipped": skipped, "errors": errors}

_RANGE_CHUNK_SIZE = 1024 * 1024  # 1MB 分块流式，避免大文件整读进内存

def _file_range_iter(f, start, end, chunk=_RANGE_CHUNK_SIZE):
    try:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = f.read(min(chunk, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data
    finally:
        f.close()

@app.get("/api/file")
def get_file(path: str, request: Request):
    p = _validate_file_path(_decode_b64_path(path))
    ct = _guess_content_type(p)
    rng = request.headers.get("range") or request.headers.get("Range")
    if rng:
        try:
            unit, _, rng_spec = rng.partition("=")
            if unit.strip().lower() != "bytes":
                raise ValueError("unsupported range unit")
            start_s, _, end_s = rng_spec.partition("-")
            file_size = os.path.getsize(p)
            start = int(start_s) if start_s else 0
            end = int(end_s) if end_s else (file_size - 1)
            start = max(0, start)
            end = min(file_size - 1, end)
            if start > end:
                start, end = 0, file_size - 1
            length = end - start + 1
            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
                "Content-Type": ct,
                "Cache-Control": "public, max-age=3600",
            }
            f = open(p, "rb")
            return StreamingResponse(
                _file_range_iter(f, start, end),
                status_code=206,
                headers=headers,
                media_type=ct,
            )
        except Exception:
            return FileResponse(p, media_type=ct)
    return FileResponse(p, media_type=ct)

@app.head("/api/file")
def head_file(path: str):
    p = _validate_file_path(_decode_b64_path(path))
    ct = _guess_content_type(p)
    file_size = os.path.getsize(p)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Type": ct,
        "Cache-Control": "public, max-age=3600",
    }
    return Response(status_code=200, headers=headers, media_type=ct)

@app.get("/api/media/{file_id}/position")
def get_file_position(
    file_id: str,
    model_ids: Optional[str] = Query(default=None),
    tag_ids: Optional[str] = Query(default=None),
    exclude_tag_ids: Optional[str] = Query(default=None),
    strict: bool = True,
    min_heat: Optional[int] = Query(default=None),
    max_heat: Optional[int] = Query(default=None),
    order: Optional[str] = Query(default=None),
    name: Optional[str] = Query(default=None),
    page_size: int = 30,
):
    """返回文件在给定筛选+排序下的页码和排位"""
    try:
        effective_order = order or 'recent'
        if page_size < 1:
            raise HTTPException(status_code=400, detail="page_size 必须 >= 1")
        mset = [s for s in (model_ids or '').split(',') if s]
        tset = [s for s in (tag_ids or '').split(',') if s]
        exset = [s for s in (exclude_tag_ids or '').split(',') if s]
        rank = db.get_file_rank(
            file_id=file_id,
            model_ids=mset or None,
            tag_ids=tset or None,
            exclude_tag_ids=exset or None,
            strict=strict,
            min_heat=min_heat,
            max_heat=max_heat,
            name=name,
            order=effective_order,
        )
        if rank is None:
            raise HTTPException(status_code=404, detail="文件不在当前筛选结果中")
        page = rank // page_size + 1
        return {"rank": rank, "page": page, "page_size": page_size}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/media/{file_id}/like")
def like_media(file_id: str):
    row = db.get_file_by_id(file_id)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    try:
        new_heat = db.increment_file_heat(file_id, delta=1)
        return {"ok": True, "heat_value": new_heat}
    except Exception:
        raise HTTPException(status_code=500, detail="like failed")

@app.post("/api/media/{file_id}/dislike")
def dislike_media(file_id: str):
    row = db.get_file_by_id(file_id)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    try:
        new_heat = db.increment_file_heat(file_id, delta=-1)
        return {"ok": True, "heat_value": new_heat}
    except Exception:
        raise HTTPException(status_code=500, detail="dislike failed")

@app.post("/api/open")
def open_file(path: str):
    p = _validate_file_path(_decode_b64_path(path))
    try:
        if not _open_in_system(p, path):
            raise Exception("open failed")
    except Exception:
        raise HTTPException(status_code=500, detail="open failed")
    return {"ok": True}


# 前端构建产物托管（简化部署：一个进程同时服务前端与后端）
FRONTEND_DIST = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend", "dist"))
if os.path.isdir(FRONTEND_DIST):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets"), html=False), name="assets")

    def _resolve_frontend_dist_file(rel_path: str) -> Optional[str]:
        normalized = (rel_path or "").strip("/\\")
        if not normalized:
            return None
        candidate = os.path.abspath(os.path.join(FRONTEND_DIST, normalized))
        try:
            common = os.path.commonpath([FRONTEND_DIST, candidate])
        except ValueError:
            return None
        if common != FRONTEND_DIST:
            return None
        if os.path.isfile(candidate):
            return candidate
        return None

    @app.get("/")
    def serve_root():
        try:
            rotate = (os.environ.get('CW_PASSWORD_ROTATE', '1').strip() != '0')
            static_code = os.environ.get('CW_PASSWORD_STATIC')
            if rotate and not (static_code and static_code.strip()):
                db.rotate_access_password()
        except Exception:
            pass
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        return FileResponse(index_path)

    # SPA 路由回退定义放在 /api 路由之后，避免截获 /api/* 请求
    
@app.get("/api/password/validate")
def password_validate(code: str, response: Response):
    try:
        ok = db.validate_access_password(code)
        if ok:
            # 登录成功后下发 cookie，浏览器对同源 /api 请求（含 <img>/<video>）自动携带
            response.set_cookie(
                "cw_access_code", code,
                httponly=True, samesite="lax", path="/", max_age=86400,
            )
        return {"ok": bool(ok)}
    except Exception:
        return {"ok": False}
    
@app.get("/api/password/current")
def password_current():
    try:
        code = db.get_current_access_password()
        return {"code": code or ""}
    except Exception:
        return {"code": ""}

class BulkTagOp(BaseModel):
    file_ids: List[str]
    tag_ids: List[str]

class BulkHeatOp(BaseModel):
    file_ids: List[str]
    delta: int

@app.post("/api/files/bulk/add_tags")
def bulk_add_tags(payload: BulkTagOp):
    return _bulk_apply_tags(payload.file_ids, payload.tag_ids, db.add_file_tag)

@app.post("/api/files/bulk/remove_tags")
def bulk_remove_tags(payload: BulkTagOp):
    return _bulk_apply_tags(payload.file_ids, payload.tag_ids, db.remove_file_tag)

@app.post("/api/files/bulk/heat")
def bulk_update_heat(payload: BulkHeatOp):
    delta = 1 if payload.delta >= 0 else -1
    return _bulk_update_heat(payload.file_ids, delta)

class BulkBlacklistOp(BaseModel):
    file_ids: List[str]

@app.post("/api/files/bulk/blacklist")
def bulk_blacklist(payload: BulkBlacklistOp):
    return _bulk_blacklist(payload.file_ids)
if os.path.isdir(FRONTEND_DIST):
    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        file_path = _resolve_frontend_dist_file(full_path)
        if file_path:
            return FileResponse(file_path)
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        return FileResponse(index_path)
