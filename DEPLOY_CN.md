# 启动与部署指南（Windows）

本文档说明本项目在 Windows 下的开发启动、前端打包、一体化运行，以及服务化/自启的操作流程。

- 前端目录：`frontend/`
- 后端入口：`backend/server.py`
- 一体化运行：后端同时托管前端构建产物与 API

## 环境要求
- Node.js LTS（含 npm）
- Python 3.10+（可使用系统 Python）
- PowerShell 执行策略允许脚本运行（脚本内已使用 Bypass，通常无需额外设置）

## 开发模式
- 启动后端（热重载）：
  - 在项目根目录执行：
    - `python -m uvicorn backend.server:app --reload --port 8000`
- 启动前端（热更新）：
  - 在 `frontend/` 执行：
    - `npm install`
    - `npm run dev`
- 访问：
  - 前端开发地址：`http://localhost:5173/`
  - 接口通过 Vite 代理到 `http://localhost:8000`，前端统一请求 `/api/*`

## 前端打包
- 在 `frontend/` 执行：
  - `npm install`（首次）
  - `npm run build`
- 产物输出：`frontend/dist/`

## 一体化运行（推荐）
后端自动托管 `frontend/dist`，统一提供页面与接口。
- 启动：
  - 在项目根目录执行：
    - `python -m uvicorn backend.server:app --host 0.0.0.0 --port 8000`
- 访问：`http://localhost:8000/`
- 托管实现位置：`backend/server.py:144-163`
  - 根路径返回 `index.html`
  - `/assets/*` 提供静态资源
  - API 路由为同源 `/api/*`

## 一键启动（开发或临时使用）
根目录提供 `start.cmd` / `start.ps1`，自动准备虚拟环境、构建前端并启动服务（非服务方式）。默认地址：`http://localhost:8000/`

## 自定义后台启动入口
- 脚本：`run_server.ps1`
- 常用参数：
  - `-Port 8000` 指定端口
  - `-Bind 0.0.0.0` 监听地址
  - `-BuildFrontend` 启动前先构建前端
- 示例：
  - `powershell -ExecutionPolicy Bypass -NoProfile -File .\run_server.ps1 -Port 8000 -Bind 0.0.0.0 -BuildFrontend`

## Windows 服务（在“服务”里可见，管理员执行，推荐且默认）
- 需要预装 NSSM（Non-Sucking Service Manager）：
  - 方式一（推荐）：管理员 PowerShell 执行 `winget install -e --id NSSM.NSSM --accept-source-agreements --accept-package-agreements`
  - 方式二：管理员 PowerShell 执行 `choco install nssm -y`
  - 方式三：手动下载 `nssm.exe` 并放到 `tools/nssm/nssm.exe`
- 安装（管理员 PowerShell）：
  - `powershell -ExecutionPolicy Bypass -NoProfile -File .\install-winservice.ps1 -Name ColorfulWorldApiService -Port 8000`
  - 服务显示名称：`ColorfulWorldApiService`（可自定义 `-Name`）
  - 安装后在“服务”中可见并自动启动；日志输出到 `logs/ColorfulWorldApiService.*.log`
- 卸载（管理员 PowerShell）：
  - `powershell -ExecutionPolicy Bypass -NoProfile -File .\uninstall-winservice.ps1 -Name ColorfulWorldApiService`
- 启动命令内部调用 `run_server.ps1`，后端将同时托管打包后的前端与 API，访问 `http://localhost:8000/`

### 服务管理（无需 NSSM 在 PATH）
- 启动：`Start-Service -Name ColorfulWorldApiService`
- 停止：`Stop-Service -Name ColorfulWorldApiService`
- 重启：`Restart-Service -Name ColorfulWorldApiService`
- 状态：`Get-Service ColorfulWorldApiService | Format-List Status,Name,DisplayName`
- 监听检查：`netstat -ano -p tcp | findstr :8000`（应看到 `LISTENING`）

### 防火墙开放（远程访问需要）
- 管理员 PowerShell执行一次：
  - `New-NetFirewallRule -DisplayName "ColorfulWorld API 8000" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000`

> 注：已移除“计划任务”和“启动快捷方式”方案，统一使用 Windows 服务实现自启动与后台常驻。

## 常见问题
- 端口被占用：
  - 修改端口参数：`--port` 或 `-Port`
  - 或停止占用程序
- 页面空白/数据不出：
  - 确认后端运行：`http://localhost:8000/api/models` 返回 200
  - 前端开发模式需保持 Vite 与后端同时运行
- 执行策略限制：
  - 已在命令中使用 `-ExecutionPolicy Bypass`，通常无需全局修改策略
- 构建后的路径问题：
  - 由后端统一托管 `frontend/dist`，无需配置额外静态服务器

### 服务启动失败（依赖未安装）
- 现象：`ModuleNotFoundError: No module named 'PIL'`（或其他依赖）
- 原因：服务使用的虚拟环境未安装项目依赖
- 解决（管理员 PowerShell）：
  - `cd d:\Code\GenCodeByAI\ColorfulWorld`
  - `.\.venv\Scripts\python.exe -m pip install -U pip`
  - `.\.venv\Scripts\python.exe -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`
  - 验证：`.\.venv\Scripts\python.exe -c "import PIL, numpy, cv2"`
  - 重启服务：`Stop-Service ColorfulWorldApiService; Start-Service ColorfulWorldApiService`

### NSSM 不在 PATH 的处理
- 直接使用完整路径（示例）：`& "d:\Code\GenCodeByAI\ColorfulWorld\tools\nssm\nssm.exe" start ColorfulWorldApiService`
- 服务安装脚本会自动探测常见 NSSM 路径（`install-winservice.ps1:23-45`），无需手动配置 PATH。

### 建议的 PyPI 镜像
- 设置持久化镜像（管理员 PowerShell）：`setx PIP_INDEX_URL https://pypi.tuna.tsinghua.edu.cn/simple`

## 变更记录（关键实现点）
- `run_server.ps1`：
  - 修正变量插值，避免解析错误：`run_server.ps1:41`
  - 增强 Python 解析与 venv 创建适配服务环境：`run_server.ps1:18-41`
  - 启动前安装并校验依赖（优先 `requirements.txt`）：`run_server.ps1:26-45`
- `install-winservice.ps1`：
  - NSSM/PowerShell 路径解析更稳：`install-winservice.ps1:23-45, 49-53`
  - 自启动与日志配置：`install-winservice.ps1:57-65`
  - 安装完成输出信息：`install-winservice.ps1:63-65`

## 文件索引
- 一体化托管与 API：`backend/server.py:58-143, 144-163`
- 一键启动脚本：`start.ps1`, `start.cmd`
- 自定义运行入口：`run_server.ps1`
 

---
如需改为 IIS 部署，可在 IIS 静态托管前端并将 `/api/*` 反代到 `http://127.0.0.1:8000`，前端无需改动（仍访问 `/api`）。
