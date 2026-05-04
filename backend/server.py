from fastapi import FastAPI, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional
import os
import base64
from fastapi import HTTPException
import sys
import subprocess
import urllib.request
import urllib.parse
import ctypes
from typing import List
from pydantic import BaseModel

from backend.data.database import Database

app = FastAPI(title="Media Gallery API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Length", "Content-Range"],
)

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
    return [{"id": m["id"], "name": m["name"], "type": (types.get(m.get("model_type_id")) or m.get("model_type") or None), "preview_image_path": _to_data_url(m.get("preview_image_path"))} for m in models]

@app.get("/api/tags")
def get_tags():
    tags = db.get_tags_with_category_name(only_active=False)
    return [{"id": t["id"], "name": t["name"], "category_name": t.get("category_name") or None} for t in tags]

class PresetPayload(BaseModel):
    name: str
    sort_order: int
    tags: List[str]

class PresetUpdatePayload(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None
    tags: Optional[List[str]] = None

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
):
    try:
        mset = [s for s in (model_ids or '').split(',') if s]
        tset = [s for s in (tag_ids or '').split(',') if s]
        exset = [s for s in (exclude_tag_ids or '').split(',') if s]
        offset = max((page - 1) * page_size, 0)
        rows = db.query_files_with_filters(model_ids=mset or None, tag_ids=tset or None, exclude_tag_ids=exset or None, strict=strict, min_heat=min_heat, max_heat=max_heat, offset=offset, limit=page_size, order=(order or 'recent'), seed=seed, name=name)
        slice_items = []
        tag_rows = db.get_tags_with_category_name(only_active=False)
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
        for f in rows:
            ft = (f.get("file_type") or "").lower()
            file_id = f['id']
            models = db.get_file_models(file_id)
            file_tags = db.get_file_tags(file_id)
            model_tags = []
            for m in models:
                try:
                    model_tags.extend(db.get_model_tags(m['id']))
                except Exception:
                    pass
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
        return {"items": result, "hasMore": has_more}
    except Exception as e:
        print("get_media error", str(e))
        raise HTTPException(status_code=500, detail=str(e))

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
            req = urllib.request.Request(u, method="POST")
            urllib.request.urlopen(req, timeout=1)
            return True
        except Exception:
            pass
        try:
            os.startfile(p)  # type: ignore
            return True
        except Exception:
            pass
        try:
            subprocess.Popen(f'start "" "{p}"', shell=True)
            return True
        except Exception:
            pass
        try:
            subprocess.Popen(["powershell.exe", "-NoProfile", "-Command", f'Start-Process -Verb Open -FilePath "{p}"'])
            return True
        except Exception:
            pass
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

@app.get("/api/file")
def get_file(path: str, request: Request):
    p = _decode_b64_path(path)
    if not os.path.isfile(p):
        raise HTTPException(status_code=404, detail="file not found")
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
            with open(p, "rb") as f:
                f.seek(start)
                data = f.read(length)
            headers = {
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(len(data)),
                "Content-Type": ct,
                "Cache-Control": "public, max-age=3600",
            }
            return Response(content=data, status_code=206, headers=headers, media_type=ct)
        except Exception:
            return FileResponse(p, media_type=ct)
    return FileResponse(p, media_type=ct)

@app.head("/api/file")
def head_file(path: str):
    p = _decode_b64_path(path)
    if not os.path.isfile(p):
        raise HTTPException(status_code=404, detail="file not found")
    ct = _guess_content_type(p)
    file_size = os.path.getsize(p)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Type": ct,
        "Cache-Control": "public, max-age=3600",
    }
    return Response(status_code=200, headers=headers, media_type=ct)

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
    p = _decode_b64_path(path)
    p = os.path.normpath(p.replace("/", os.sep))
    if not os.path.isfile(p):
        raise HTTPException(status_code=404, detail="file not found")
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
def password_validate(code: str):
    try:
        ok = db.validate_access_password(code)
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
if os.path.isdir(FRONTEND_DIST):
    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            from fastapi import HTTPException
            raise HTTPException(status_code=404)
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        return FileResponse(index_path)
