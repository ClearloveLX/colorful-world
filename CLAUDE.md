# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# One-click launch (Windows PowerShell) - auto-creates venv, installs deps, builds frontend, starts open helper + server on :8000
.\start.ps1

# Manual setup: install backend + frontend deps
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend && npm ci && cd ..

# Manual: build frontend, then start backend (production mode, no hot reload)
cd frontend && npm run build && cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.server:app --host 0.0.0.0 --port 8000

# Frontend dev server with hot reload (Vite on :5173, proxies /api → :8000)
cd frontend && npm run dev

# Launch Tkinter desktop GUI (image classification tool)
.\run.bat
# or directly:
.\.venv\Scripts\python.exe main.py

# Run all tests
.\.venv\Scripts\python.exe -m pytest tests/ -v

# Run a single test file
.\.venv\Scripts\python.exe -m pytest tests/test_presets.py -v

# Audio duration backfill script
.\.venv\Scripts\python.exe -m backend.backfill_audio_duration [limit]

# Scripts: verify dependencies, initialize preset tables
.\.venv\Scripts\python.exe scripts/check_dependencies.py
.\.venv\Scripts\python.exe scripts/migrate_presets.py

# Windows: install startup shortcut or run as a service
.\install-startup-shortcut.ps1
.\install-winservice.ps1
.\uninstall-winservice.ps1

# Free port 8000 if something is occupying it
.\tools\free_port_8000.ps1
```

## Architecture

This is a **local media gallery** for browsing, filtering, and managing images/videos/audio files. It has two modes:

### 1. Web App (primary)
- **Backend**: FastAPI (`backend/server.py`) on port 8000. Serves REST API + built frontend static files from `frontend/dist/`. A single process handles both.
- **Frontend**: React 18 + TypeScript + Vite (`frontend/`). Masonry-layout media grid with collapsible sidebar filters (models, tags with categories, heat range, name search), lightbox viewer, bulk tag/heat operations in edit mode, password-gated access.
  - Entry point: `frontend/src/main.tsx` → `App.tsx`
  - Types: `frontend/src/types.ts` defines `Model`, `Tag`, `MediaItem`, `ID`
  - API layer: `frontend/src/api.ts` — all requests use retry logic (`getRetry`, 3 attempts) with 15s timeout and `AbortController`
  - Vite dev config (`frontend/vite.config.ts`): proxies `/api` to `localhost:8000`, strict port 5173
- **Data root**: Controlled by `CW_DATA_ROOT` env var. Defaults to `L:\data` if that drive exists, otherwise `./data`. File paths served via base64-encoded query params (`/api/file?path=...`) to support files on any drive.
- A secondary **open helper** (`backend/open_helper.py`) runs on port 8001, launched by `start.ps1` via `run_open_helper.ps1` in the user's desktop session. It exists because opening files with GUI applications (via `ShellExecuteW`/`os.startfile`) requires running in the user's session — the FastAPI server may run in a different context and cannot directly launch GUI apps. The frontend POSTs to `localhost:8001/open?path=<b64>` to open files.
- **`backend/simple_server.py`** is a standalone minimal HTTP API on port 3000 — a lighter alternative to the FastAPI server using only stdlib `http.server`. Shares the same `Database` class.
- **`backend/services/face_cluster.py`** — face detection and clustering via insightface (`buffalo_l` model, CPUExecutionProvider). Provides `detect_faces()` (returns face embeddings), `cluster_faces()` (groups by cosine similarity), and `face_available()` check. Lazily initializes on first use.
- **`backend/services/image_similarity.py`** — image similarity using three features: dHash (64-bit difference hash), HSV histogram correlation, and face embeddings. Provides `find_similar_groups()` and `find_similar_groups_safe()` (graceful degradation if insightface unavailable). Used for duplicate/near-duplicate detection.

### 2. Desktop GUI (`main.py`, ~5500 lines)
- Tkinter-based image classifier (`ImageClassifierApp`). Used for initial ingestion and tagging workflow. Shares the same `Database` and `FileManager` classes.
- `run.bat` auto-creates venv, installs `requirements.txt`, sets `CW_DATA_ROOT` (preferring `L:\data` if it exists), then launches `main.py`.
- The GUI has three main panels: **source folder browser** (scan directories for media), **classification workspace** (view one image at a time, assign models/tags, rate heat, copy/move to output or good folders), and **database browser** (query and edit existing records). Keyboard shortcuts drive the classification workflow for speed.
- **`FileManager`** (`backend/services/file_manager.py`) handles image/video file operations: scanning source directories for media files (by extension, including audio: `.mp3`, `.m4a`), copying files to output/good/recycle_bin folders, computing MD5 hashes, and generating thumbnails.

### Database (SQLite — `data/image_classifier.db`)
Single `Database` class in `backend/data/database.py` (~2400 lines). Core tables:
- **files** — media records with path, dimensions, duration, thumbnail, MD5, heat_value
- **models** — people/models with preview images, grouped by `model_types`
- **tags** — labels, grouped by `tag_categories`, with sort_order
- Join tables: `file_models` (N:N), `file_tags` (N:N), `model_tags` (N:N)
- **presets** — saved filter configs per media type (`image_presets`, `video_presets`) with soft delete
- **true_random_cache** — blacklist of previously-shown file IDs per filter key, so "true random" mode never repeats
- **app_settings** — key/value store (e.g., `true_random_cache_enabled`)
- **access_password** — rotating access code for the web frontend

IDs are UUIDs (hex, no dashes). The database auto-migrates on first connection, adding missing columns and converting legacy INTEGER IDs.

### Tests
- `tests/test_presets.py` — CRUD + sort_order + soft-delete tests for presets (isolated temp DB)
- `tests/test_true_random_cache.py` — cache blacklisting behavior via FastAPI `TestClient` with temp DB injection (`server.db = self.db`)

### Frontend Component Tree
```
App
├── Filters (sidebar: model/tag pickers, sort order, heat range, name search, system settings)
└── MediaGrid (masonry layout, infinite scroll, bulk select mode)
    ├── MediaCard (thumbnail, models, tags, heat/like/dislike buttons, tilt/ripple effects)
    ├── Lightbox (full-size viewer with prev/next, metadata sidebars)
    ├── VideoPlayer (custom video element wrapper)
    ├── TagPicker (modal for bulk tag add/remove)
    └── BulkBar (selection toolbar: add/remove tags, adjust heat, select all/clear)
```

### Key API Endpoints (all under `/api/`)
- `GET /api/media` — filtered, paginated media query with model_ids, tag_ids, exclude_tag_ids, strict/loose matching, heat range, sort order (random/duration/recent/heat), seed-based reproducible random, name search, true_random cache blacklisting
- `GET /api/models`, `GET /api/tags`, `GET /api/model_types` — metadata
- `POST /api/media/:id/like`, `/dislike` — increment/decrement heat
- `GET /api/file?path=<b64>` — serve any local file by base64-encoded absolute path (supports Range requests for video seeking)
- `POST /api/files/bulk/add_tags`, `/remove_tags`, `/heat` — bulk operations
- `GET/PUT /api/settings/true-random-cache` — toggle cache behavior
- `POST /api/true-random-cache/clear` — clear cache
- `GET/POST/PUT/DELETE /api/presets/:media_type` — CRUD for saved filter presets
- `GET /api/password/validate`, `/current` — access code management
- `HEAD /api/file?path=<b64>` — file metadata (Content-Length, Accept-Ranges, cache headers) for video progressive download
- `POST /api/open?path=<b64>` — open file in system default app via multi-level fallback: ShellExecuteW → os.startfile → cmd start → powershell → explorer.exe. The separate `open_helper.py` on :8001 exists for cross-session support; this endpoint handles cases where caller and server share a desktop session
- `GET /` — serves frontend `index.html`, with password rotation on each page load (unless `CW_PASSWORD_ROTATE=0`)
- `GET /{path}` — SPA fallback: non-API, non-file paths route to `index.html`

### Startup Flow (`start.ps1`)
1. Ensures Python venv exists, installs backend deps (fastapi, uvicorn)
2. Builds frontend (`npm ci`/`npm install` → `npm run build`)
3. Launches `run_open_helper.ps1` to start `open_helper.py` on port 8001 in user session
4. Starts FastAPI server on port 8000 (serves both API and built frontend static files)

### Frontend Password Display
- When the lock screen is shown (`locked === true`), the frontend fetches the current password from `/api/password/current` and stores it in `localStorage` under key `cw_access_code` — this allows viewing the password in browser devtools for sharing access.

### Environment Variables
- `CW_DATA_ROOT` — media files directory (default: `L:\data` if exists, else `./data`)
- `CW_DB_PATH` — override SQLite database path
- `CW_PASSWORD_STATIC` — fixed access password (bypasses rotation)
- `CW_PASSWORD_ROTATE` — set to `0` to disable password rotation on page load

### Dependencies
- **Backend** (`requirements.txt`): opencv-python, Pillow, numpy, fastapi, uvicorn[standard], mutagen, insightface>=0.7.0 (face detection/clustering, uses `buffalo_l` model downloaded on first use)
- **Frontend** (`package.json`): React 18, TypeScript 5, Vite 5 — no UI framework, all CSS is handwritten in `styles.css`

### Scripts & Tools
- **`start.ps1`** — one-click launcher (see Commands). Also references `run_open_helper.ps1` and `run_server.ps1`.
- **`start.cmd`** — lightweight CMD launcher, alternative to `start.ps1`.
- **`install-startup-shortcut.ps1`** — creates a Windows startup shortcut so the server auto-launches on login.
- **`install-winservice.ps1` / `uninstall-winservice.ps1`** — install/uninstall as a Windows service via NSSM (`tools/nssm/nssm.exe`).
- **`安装依赖.bat`** — Chinese-language helper to install Python + npm dependencies.
- **`tools/cleanup_service.ps1`** — remove stale Windows service registrations.
- **`tools/free_port_8000.ps1`** — kill any process occupying port 8000.
- **`docs/presets-api.md`** — presets API reference.
- **`docs/presets-test-report.md`** — presets test coverage report.
