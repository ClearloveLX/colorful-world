# AGENTS.md

This file provides guidance to AI coding agents working in this repository.

## Commands

```bash
# One-click launch (Windows PowerShell) - auto-creates venv, installs deps, builds frontend, starts open helper + server on :4396
.\start.ps1

# Manual setup: install backend + frontend deps
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend && npm ci && cd ..

# Manual: build frontend, then start backend (production mode, no hot reload)
cd frontend && npm run build && cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.server:app --host 0.0.0.0 --port 4396

# Frontend dev server with hot reload (Vite on :4398, proxies /api → :4396)
cd frontend && npm run dev

# Launch Tkinter desktop GUI (image classification tool)
.\run.bat
# or directly:
.\.venv\Scripts\python.exe main.py

# Run all backend tests (unittest via pytest runner)
.\.venv\Scripts\python.exe -m pytest tests/ -v

# Run a single test file
.\.venv\Scripts\python.exe -m pytest tests/test_presets.py -v

# Run frontend unit tests (vitest)
cd frontend && npm test

# Audio duration backfill script
.\.venv\Scripts\python.exe -m backend.backfill_audio_duration [limit]

# Scripts: verify dependencies, initialize preset tables
.\.venv\Scripts\python.exe scripts/check_dependencies.py
.\.venv\Scripts\python.exe scripts/migrate_presets.py

# Windows: install startup shortcut or run as a service
.\install-startup-shortcut.ps1
.\install-winservice.ps1
.\uninstall-winservice.ps1

# Free the default app port (4396) if something is occupying it
.\tools\free_port_8000.ps1
```

## Architecture

This is a **local media gallery** for browsing, filtering, and managing images/videos/audio files. It has three run modes:

### Three Servers

| Server | Port | Technology | Purpose |
|--------|------|------------|---------|
| `backend/server.py` | 4396 | FastAPI + uvicorn | Primary: REST API + built frontend static files |
| `backend/simple_server.py` | 3000 | Python stdlib `http.server` | Lightweight read-only alternative (no FastAPI needed) |
| `backend/open_helper.py` | 4397 | Python stdlib `http.server` | Single endpoint `POST /open` — opens files in system default app |

**Why two separate HTTP servers?** `open_helper.py` is launched in the user's desktop session (via `run_open_helper.ps1`) because `ShellExecuteW`/`os.startfile` requires running in the user's session. The FastAPI server may run in a different context (e.g. Windows service) and cannot directly launch GUI apps.

**open_helper origin rule (don't regress):** `_is_local_origin()` rejects requests with NO Origin/Referer header (missing → rejected, not allowed); `server.py`'s internal call (`/api/open` fallback) explicitly sends `Origin: http://127.0.0.1:4397` to satisfy it. Any new internal caller must do the same.

`simple_server.py` is a minimal read-only alternative — no password, no presets, no true-random cache, no write operations, loads entire dataset into memory. Security constraints (don't regress): binds `127.0.0.1` only (it has no auth), refuses `.db`/`.sqlite`/`.bak` files via `_is_blacklisted()`, and `db` is lazily initialized via `_db()` so importing the module has no DB side effects. Import uses a try/except dual path (`data.database` vs `backend.data.database`).

### 1. Web App (primary)
- **Backend**: FastAPI (`backend/server.py`) on port 4396. Serves REST API + built frontend static files from `frontend/dist/`. A single process handles both.
- **Frontend**: React 18 + TypeScript + Vite (`frontend/`). Masonry-layout media grid with collapsible sidebar filters (models, tags with categories, heat range, name search), lightbox viewer, bulk tag/heat operations in edit mode, password-gated access.
  - Entry point: `frontend/src/main.tsx` → `App.tsx`
  - Types: `frontend/src/types.ts` defines `Model`, `Tag`, `MediaItem`, `ID`
  - API layer: `frontend/src/api.ts` — `getRetry()` retries 3x with 400ms delay; `get()` uses 15s AbortController timeout; `fetchMedia()` has custom retry (not `getRetry`, uses its own 600ms delay retry in `MediaGrid`)

  - **Media type auto-detection** (`backend/services/media_detector.py`): content-signature-first (magic bytes) + extension fallback for image/video/audio. `main.py` save/import paths and `Database.add_file()` use it to record `media_kind`; the web grid can filter by this stored type.
- **Data root**: Controlled by `CW_DATA_ROOT` env var. Defaults to `L:\data` if that drive exists, otherwise `./data`. File paths served via base64-encoded query params (`/api/file?path=...`) to support files on any drive.
- **Vite dev config** (`frontend/vite.config.ts`): `strictPort: true` on 4398, proxies `/api` → `localhost:4396`.

### 2. Desktop GUI (`main.py`, ~5500 lines — includes image classification UI)
- Tkinter-based image classifier (`ImageClassifierApp`). Used for initial ingestion and tagging workflow. Shares the same `Database` and `FileManager` classes.
- `run.bat` auto-creates venv, installs `requirements.txt`, sets `CW_DATA_ROOT` (preferring `L:\data` if it exists), then launches `main.py`.
- The GUI has three main panels: **source folder browser** (scan directories for media), **classification workspace** (view one image at a time, assign models/tags, rate heat, copy/move to output or good folders), and **database browser** (query and edit existing records). Keyboard shortcuts drive the classification workflow for speed.
- **External file opening** (`open_file_externally`, module-level): fallback chain `ShellExecuteW` → `os.startfile` → `rundll32 url.dll,FileProtocolHandler` → `explorer`; always uses `subprocess.Popen` with argument lists (never `cmd /c start`) to avoid command injection. Used by the video preview panel's "系统播放器打开" button.
- **Batch import** (工具栏"批量导入"按钮): 一次选好**模特(必选)**和标签后整文件夹一键入库——可递归子文件夹(默认关)；按 MD5 跳过已导入(`Database.get_file_by_md5`，默认关)，重复/失败的文件保留在源文件夹；默认**剪切**（与单文件保存一致，可改为复制）；目录规则与单文件保存完全一致：入库到 `data/good/<模特ID>/<001|002|…>/<文件ID><扩展名>`，图片每子文件夹 1000 个、视频/音频每子文件夹 500 个（`_resolve_good_subfolder`，满额自动滚动序号）；图片写尺寸、视频/音频写元数据、视频自动提取首帧缩略图；后台线程跑任务，进度经 `root.after` 回主线程刷新。
- Video preview panel: Ctrl+S saves the selected video (ignores repeats while a save is running); closing the panel (`on_close2`) must set `gen_state["cancel"]=True` and cancel the `after_id` to stop the thumbnail worker thread. Auto-save: enabling it asks for confirmation (`askyesno`), `save_image()` has a `_saving` re-entry guard, and the loop auto-disables itself when the list is empty.
- **`FileManager`** (`backend/services/file_manager.py`) handles image/video file operations: scanning source directories for media files (by extension, including audio: `.mp3`, `.m4a`), copying files to output/good/recycle_bin folders, computing MD5 hashes, and generating thumbnails.

### Database (SQLite — `data/image_classifier.db`)
Single `Database` class in `backend/data/database.py` (~2400 lines). Core tables:
- **files** — media records with path, dimensions, duration, thumbnail, MD5, heat_value, `media_kind` (image/video/audio/unknown, auto-detected)
- **models** — people/models with preview images, grouped by `model_types`
- **tags** — labels, grouped by `tag_categories`, with sort_order
- Join tables: `file_models` (N:N), `file_tags` (N:N), `model_tags` (N:N)
- **presets** — saved filter configs per media type (`image_presets`, `video_presets`) with soft delete
- **true_random_cache** — blacklist of previously-shown file IDs per filter key, so "true random" mode never repeats
- **app_settings** — key/value store (e.g., `true_random_cache_enabled`)
- **access_password** — rotating access code for the web frontend

IDs are UUIDs (hex, no dashes). The database auto-migrates on every startup (`init_database()` called in `__init__`): checks for INTEGER→UUID migration, runs column-level `ALTER TABLE` additions, and historical table rebuilds (removing retired `image_data`, `recommend_value` columns).

- Runs in **WAL mode** (set once in `_init_schema`; journal_mode is persisted on the file). `init_database()` delegates to `_init_schema(conn)` / `_init_access_password(conn)`, both try/finally-closed.
- Module-level `compute_md5()` (chunked 4096B, no try/except — caller decides). `add_file()` / `save_image_data()` accept an optional `md5_value` to skip re-reading large files; `main.py` computes it once on first save and passes it to both.

### Tests
- `tests/test_presets.py` — CRUD + sort_order + soft-delete tests for presets (unittest, isolated temp DB)
- `tests/test_security.py` — /api/static whitelist, auth, Range streaming, password endpoints, open_helper origin checks
- `tests/test_true_random_cache.py` — cache blacklisting behavior via FastAPI `TestClient` with temp DB injection (`server.db = self.db`)
- `tests/test_tag_file_counts.py` — incremental tag/model file-count maintenance + recalc semantics
- `tests/test_md5_reuse.py` — `compute_md5()` chunked hashing + precomputed-MD5 fast paths in `add_file`/`save_image_data`
- `tests/test_media_detector.py` — magic-byte/extension media detection and `media_kind` DB storage/filter
- `tests/test_open_video_external.py` — `open_file_externally()` fallback chain (ShellExecuteW → startfile → rundll32 → explorer)
- `tests/test_video_preview_helpers.py` — Tkinter GUI video preview helpers (LRU cache, image resize)
- `tests/test_video_toolbar_layout.py` — Tkinter toolbar row placement
- `frontend/src/utils/*.test.ts` — vitest unit tests (cardWidth, toggleGroupOpen, scrollToTop)
- No `conftest.py` or pytest fixtures exist

### Frontend State Management
- **No router, no context, no Redux.** All state is lifted to `App.tsx` via `useState`/`useRef`, passed down as props.
- "Routing" is done via a single `?mode=edit` URL search parameter + `popstate` events.
- `Filters` and `MediaGrid` receive filter state + callbacks as props; `MediaGrid` passes down to `MediaCard`, `Lightbox`, `BulkBar`, `TagPicker`.
- Key refs: `idleTimerRef`, `abortControllerRef`, `IntersectionObserver`, `ResizeObserver`, `filterKeyRef` (to discard stale responses).
- **Card width slider**: `frontend/src/utils/cardWidth.ts` persists a sanitized 180–360px width to `localStorage` (`cw_card_width`); the slider saves only on pointerup/keyup (not on every change event).
- **Edit-mode exit sync**: MediaGrid's "exit select mode" deletes the `?mode=edit` URL param via `history.replaceState` AND manually dispatches a `PopStateEvent` — `replaceState` alone doesn't fire `popstate`, which would leave `App.tsx`'s `editMode` stale (settings panel + 15s polling keep running).

### CSS Architecture
- Single file: `frontend/src/styles.css` (~2000 lines). No CSS modules, no Tailwind, no CSS-in-JS.
- Dark theme with warm gold accent (`#b89a67`). Design tokens in `:root` block: surfaces (4 levels), borders (3), text (3), accent colors, semantic colors, shadows (6), radii (7), motion easings.
- Naming: semantic kebab-case (`.lock-overlay`, `.card-cover`, `.bulk-bar`).
- Responsive: 1200px (sidebar narrows), 920px (sidebar collapses to top), 640px (tight), `prefers-reduced-motion`.

### Frontend Performance Patterns
- **IntersectionObserver** for infinite scroll (sentinel div) and lazy image loading (`rootMargin: 80px`)
- **ResizeObserver** for masonry column recalculation
- **requestAnimationFrame** for heat animation, drag selection rect, scroll auto-scroll
- **Stale request discarding**: `filterKeyRef` checks before applying results to prevent race conditions
- **Optimistic updates** for like/dislike
- **Per-model limit** in random mode (max 2 items per model per page)
- **Video prefetching**: adjacent video files pre-fetched (first 64KB via Range request) when lightbox is open
- **Masonry layout**: custom shortest-column algorithm via `useMemo`, no CSS Grid masonry, no third-party library
- **Skeleton loading**: 24 placeholder cards before first page loads
- No `React.lazy` / `Suspense` — entire app is one bundle

### Frontend Component Tree
```
App
├── Filters (sidebar: model/tag pickers, sort order, heat range, name search, system settings)
└── MediaGrid (masonry layout, infinite scroll, bulk select mode)
    ├── MediaCard (thumbnail, models, tags, heat/like/dislike buttons, tilt/ripple effects)
    ├── Lightbox (full-size viewer with prev/next, metadata sidebars — uses createPortal)
    ├── VideoPlayer (custom video element wrapper — speed menu via createPortal)
    ├── TagPicker (modal for bulk tag add/remove — uses createPortal)
    └── BulkBar (selection toolbar: add/remove tags, adjust heat, select all/clear)
```

### Backend Data Flow (typical `/api/media` request)
1. Parse query params via FastAPI `Query()`
2. Build `cache_key` (MD5 of filter params) if true_random mode
3. `db.query_files_with_filters(...)` → page of file rows
4. Batch-fetch models (`db.get_files_models_batch()`), tags (`db.get_files_tags_batch()`), model-level tags (`db.get_models_tags_batch()`)
5. Merge file-tags + model-inherited tags, sort by category `sort_order`
6. Optionally cache shown file IDs via `db.cache_true_random_results()`
7. Convert internal paths to API URLs via `_to_static_url()`

The server uses a **module-level singleton** `db = Database()` — no FastAPI `Depends()` or `APIRouter`. Tests monkey-patch `server.db = self.db`.

### Authentication Flow (Frontend)
1. On first load, `locked = true` → lock screen shown
2. Password form submits → `GET /api/password/validate?code=...` → on success the server sets an httpOnly cookie `cw_access_code` (24h) and `locked = false`
3. Lock screen pre-fetches the current code from `/api/password/current` into `localStorage.cw_access_code` for the user to consult, then types it **manually — the input is never auto-filled**. This localStorage write is a **user-mandated feature — do not remove** (it was once deleted as a security issue and the user required it back); `/api/password/current` must therefore stay exempt in `_AUTH_EXEMPT_PATHS`
4. **Password rotation happens only on `GET /` page load** (`serve_root`, disable with `CW_PASSWORD_ROTATE=0`). Idle lockout is an SPA-internal `setLocked(true)` and does NOT rotate the password — a locked screen keeps the same valid code
5. **10-minute idle lockout**: listens to mouse/keyboard/scroll/touch events; after 600s of inactivity → re-locks (input cleared, password unchanged)
6. No JWT, no token management on the frontend — the httpOnly cookie is the session

### Key API Endpoints (all under `/api/`)

**Media query:**
- `GET /api/media` — filtered, paginated media with model_ids, tag_ids, exclude_tag_ids, strict/loose matching, heat range, `media_kind` (image/video/audio), sort order (random/duration/recent/heat), seed-based random, name search, true_random cache blacklisting
- `GET /api/media/{file_id}/position` — find a file's page/rank in current filter context
- `POST /api/media/:id/like`, `/dislike` — increment/decrement heat

**File serving:**
- `GET /api/file?path=<b64>` — serve local file by base64-encoded path (supports Range requests for video seeking)
- `HEAD /api/file?path=<b64>` — file metadata (Content-Length, Accept-Ranges) for video progressive download
- `POST /api/open?path=<b64>` — open file in system app via ShellExecuteW → os.startfile → cmd → powershell → explorer
- `GET /api/static/{path}` — static file serving from project root

**Bulk operations:**
- `POST /api/files/bulk/add_tags`, `/remove_tags` — bulk add/remove tags; returns `{updated, skipped, errors}` (not transactional)
- `POST /api/files/bulk/heat` — bulk heat adjustment
- `POST /api/files/bulk/media-kind` — batch set `media_kind` to image/video/audio/other, for manually correcting unrecognized files

**Metadata:**
- `GET /api/models`, `GET /api/tags`, `GET /api/model_types` — metadata with file counts

**Auth & settings:**
- `GET /api/password/validate`, `/current` — password validation and retrieval
- `GET/PUT /api/settings/true-random-cache` — toggle cache behavior
- `POST /api/true-random-cache/clear` — clear cache

**Presets:**
- `GET/POST /api/presets/{media_type}` — list/create (image or video)
- `GET/PUT/DELETE /api/presets/{media_type}/{id}` — single preset CRUD

**SPA:**
- `GET /` — serves `index.html`, with password rotation unless `CW_PASSWORD_ROTATE=0`
- `GET /{path}` — SPA fallback to `index.html` (only when `frontend/dist/` exists)

### Startup Flow (`start.ps1`)
1. Ensures Python venv exists, installs backend deps (fastapi, uvicorn, etc.)
2. Builds frontend (`npm ci`/`npm install` → `npm run build`)
3. Launches `run_open_helper.ps1` to start `open_helper.py` on port 4397 in user session
4. Starts FastAPI server on port 4396 (serves both API and built frontend static files)

### Environment Variables
- `CW_DATA_ROOT` — media files directory (default: `L:\data` if exists, else `./data`)
- `CW_DB_PATH` — override SQLite database path
- `CW_PASSWORD_STATIC` — fixed access password (bypasses rotation)
- `CW_PASSWORD_ROTATE` — set to `0` to disable password rotation on page load

### Dependencies
- **Backend** (`requirements.txt`): opencv-python>=4.8.0, Pillow>=10.0.0, numpy>=1.24.0, fastapi>=0.115.0, uvicorn[standard]>=0.32.0, mutagen>=1.47.0
  - `mutagen` for mp3/m4a audio duration extraction
- **Frontend** (`package.json`): React 18, TypeScript 5, Vite 5 — no UI framework, no state management library, no CSS framework. Dev deps: `@types/react`, `@types/react-dom`, `@vitejs/plugin-react`, `typescript`, `vite`, `vitest`

### Scripts & Tools
- **`start.ps1`** — one-click launcher (see Commands). Also references `run_open_helper.ps1` and `run_server.ps1`.
- **`start.cmd`** — thin CMD wrapper around `start.ps1`.
- **`run_server.ps1`** — parametric uvicorn launcher with configurable port, bind, workers, optional frontend build.
- **`run_open_helper.ps1`** — launches `open_helper.py` as a subprocess in user session.
- **`install-startup-shortcut.ps1`** — creates a Windows startup shortcut so the server auto-launches on login.
- **`install-winservice.ps1` / `uninstall-winservice.ps1`** — install/uninstall as a Windows service via NSSM (`tools/nssm/nssm.exe`).
- **`安装依赖.bat`** — Chinese-language helper to install Python + npm dependencies.
- **`tools/cleanup_service.ps1`** — remove stale Windows service registrations.
- **`tools/free_port_8000.ps1`** — kill any process occupying the default app port (4396).
- **`docs/presets-api.md`** — presets API reference.
- **`docs/presets-test-report.md`** — presets test coverage report.
