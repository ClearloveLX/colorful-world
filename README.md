# ColorfulWorld

一个本地的图片/视频/音频管理标记与筛选的前后端项目，启动后访问 http://localhost:4396/ 进行使用（前端开发模式为 http://localhost:4398/）。

## 功能特性

- **媒体管理**：图片 / 视频 / 音频（mp3、m4a）的统一浏览与管理
- **自动识别媒体类型**：按文件头魔数 + 扩展名识别图片/音频/视频，`main.py` 保存/导入时自动记录类型，并在图库中支持按类型筛选
- **手动纠正类型**：编辑模式的批量操作中可手动把文件设为图片/视频/音频/其他，用于修正未识别或识别错误的文件
- **标签与模特体系**：模特（models）和标签（tags）分组管理，支持类别与排序
- **多维筛选**：按模特、标签（含排除标签）、热度区间、名称搜索筛选媒体
- **随机浏览**：真随机模式基于缓存黑名单，同一批结果不重复出现
- **批量操作**：批量添加/移除标签、调整热度值
- **桌面分类工具**：Tkinter GUI，用于初始采集、分类标记与数据库浏览，键盘快捷键驱动
- **本地优先**：全部数据存储在本机，离线可用

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python / FastAPI / uvicorn (端口 4396) |
| 前端 | React 18 + TypeScript + Vite（开发服务器 4398；生产/联调访问入口为后端 4396，由后端托管前端构建产物） |
| 数据库 | SQLite (WAL 模式，自动迁移) |
| 辅助服务 | open_helper (端口 4397，用户会话内打开系统应用) |
| 依赖 | opencv-python、Pillow、numpy、mutagen |

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `CW_DATA_ROOT` | 媒体文件根目录 | `L:\data`（若存在），否则 `./data` |
| `CW_DB_PATH` | SQLite 数据库路径覆盖 | `data/image_classifier.db` |
| `CW_PASSWORD_STATIC` | 固定访问密码（绕过轮换） | 无 |
| `CW_PASSWORD_ROTATE` | 设为 `0` 禁用密码轮换 | 启用 |

## 依赖安装

### 后端

```bash
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 前端

```bash
cd frontend
npm install
```

## 运行

### 方式一：一键启动（推荐，Windows）

```powershell
.\start.ps1
```

自动创建虚拟环境、安装依赖、构建前端，并启动 open_helper + 主服务。

### 方式二：手动启动

```bash
cd frontend
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.server:app --host 0.0.0.0 --port 4396
```

### 前端开发模式（热更新）

```bash
cd frontend
npm run dev
```

### 桌面分类工具（Windows）

```bat
.\run.bat
```

### 运行测试

```bash
.\.venv\Scripts\python.exe -m pytest tests/ -v   # 后端
cd frontend && npm test                          # 前端
```

## 数据目录说明

默认数据根目录为 `L:\data`（存在时）或项目内 `./data`，包含媒体文件、缩略图与 `image_classifier.db` 数据库。该目录不会提交到版本库。
