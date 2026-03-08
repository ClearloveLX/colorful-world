# ColorfulWorld

一个本地图片管理与筛选的前后端项目，启动后访问 http://localhost:8000/ 进行使用。

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

### 方式二：手动启动

```bash
cd frontend
npm run build
cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.server:app --host 0.0.0.0 --port 8000
```

### 数据处理（Windows）

```bat
.\run.bat
```



