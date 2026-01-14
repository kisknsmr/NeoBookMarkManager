from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import os
import sys

# Ensure project root is on path so we can import core modules
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.storage import load_bookmarks
from core.model import Node

app = FastAPI(title="NeoBookmarkManager - Web API")

# Serve static files (web/static)
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


def node_to_dict(node: Node) -> dict:
    return {
        "type": node.type,
        "title": node.title,
        "url": node.url,
        "add_date": node.add_date,
        "last_modified": node.last_modified,
        "icon": node.icon,
        "children": [node_to_dict(c) for c in node.children]
    }


@app.get("/api/bookmarks")
def api_bookmarks(path: str | None = None):
    """Return parsed bookmarks as JSON. If `path` omitted, a sample fixture is used."""
    if not path:
        # default sample fixture
        path = os.path.join(ROOT, 'fixtures', 'sampleHTML', 'bookmarks_2026_01_10.html')
    path = os.path.abspath(path)
    try:
        root, rules, rules_path = load_bookmarks(path)
        return JSONResponse({"root": node_to_dict(root), "rules": rules or {}, "rules_path": rules_path})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/ping")
def api_ping():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("web.backend:app", host="127.0.0.1", port=8000, reload=True)
