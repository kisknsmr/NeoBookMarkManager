# Web UI Prototype

This folder contains a minimal FastAPI backend and a static `index.html` that acts as a prototype web UI for NeoBookmarkManager.

Quick start (from project root):

```powershell
# 1. install deps (use virtualenv)
pip install -r requirements.txt

# 2. run backend
python -m web.backend

# 3. open http://127.0.0.1:8000/ in your browser
```

Notes:
- The `/api/bookmarks` endpoint will load the sample fixture if no `path` parameter is provided.
- This is a scaffold to be replaced with a React/Vite frontend and Electron/Tauri wrapper later.
