from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import json
from pathlib import Path

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Determine project root (parent of tools/web_ui)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

@app.get("/", response_class=HTMLResponse)
async def get_home():
    return FileResponse(BASE_DIR / "tools" / "web_ui" / "index.html")

@app.post("/api/pause")
async def toggle_pause():
    paused_file = BASE_DIR / ".swarm_paused"
    if paused_file.exists():
        paused_file.unlink()
        return {"paused": False}
    else:
        paused_file.touch()
        return {"paused": True}

@app.delete("/api/skip")
async def remove_skip(request: Request):
    file_to_remove = request.query_params.get("file")
    skip_file = BASE_DIR / "tools" / "skip_list.txt"
    
    if file_to_remove and skip_file.exists():
        lines = skip_file.read_text().splitlines()
        new_lines = [line for line in lines if line.strip() != file_to_remove]
        skip_file.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))
        
    return {"status": "ok"}

@app.get("/api/backlog")
async def get_backlog():
    backlog_file = BASE_DIR / "overnight" / "architectural_backlog.json"
    if backlog_file.exists():
        try:
            return json.loads(backlog_file.read_text())
        except json.JSONDecodeError:
            return []
    return []

@app.delete("/api/backlog")
async def remove_backlog(request: Request):
    file_to_remove = request.query_params.get("file")
    backlog_file = BASE_DIR / "overnight" / "architectural_backlog.json"
    
    if file_to_remove and backlog_file.exists():
        try:
            data = json.loads(backlog_file.read_text())
            data = [item for item in data if item.get("file") != file_to_remove]
            backlog_file.write_text(json.dumps(data, indent=4))
            return data
        except json.JSONDecodeError:
            return []
    return []

@app.get("/api/skip-list")
async def get_skip_list():
    skip_file = BASE_DIR / "tools" / "skip_list.txt"
    if skip_file.exists():
        return skip_file.read_text().splitlines()
    return []

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
