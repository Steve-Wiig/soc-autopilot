from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import json
import asyncio
from pathlib import Path

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent

@app.get("/", response_class=HTMLResponse)
async def get_home():
    return FileResponse(BASE_DIR / "tools" / "web_ui" / "index.html")

@app.get("/api/status")
async def get_status():
    current_task = "Idle"
    task_file = BASE_DIR / ".current_task"
    if task_file.exists():
        current_task = task_file.read_text().strip()
    
    skip_count = 0
    skip_file = BASE_DIR / "skip_list.txt"
    if skip_file.exists():
        skip_count = sum(1 for line in skip_file.read_text().splitlines() if line.strip())
        
    return {"current_task": current_task, "skipped_files": skip_count}

@app.post("/api/pause")
async def toggle_pause():
    paused_file = BASE_DIR / ".swarm_paused"
    if paused_file.exists():
        paused_file.unlink()
        return {"paused": False}
    else:
        paused_file.touch()
        return {"paused": True}

@app.get("/api/backlog")
async def get_backlog():
    backlog_file = BASE_DIR / "overnight" / "architectural_backlog.json"
    if backlog_file.exists():
        try:
            return json.loads(backlog_file.read_text())
        except json.JSONDecodeError:
            return []
    return []

@app.post("/api/backlog")
async def add_backlog(request: Request):
    data = await request.json()
    backlog_file = BASE_DIR / "overnight" / "architectural_backlog.json"
    items = []
    if backlog_file.exists():
        try:
            items = json.loads(backlog_file.read_text())
        except json.JSONDecodeError:
            items = []
    items.append({"file": data.get("file", "unknown.py"), "task": data.get("task", "No description"), "priority": "high"})
    backlog_file.write_text(json.dumps(items, indent=4))
    return {"status": "success"}

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

@app.get("/api/logs")
async def get_logs():
    log_file = BASE_DIR / "logs" / "swarm_systemd.log"
    if log_file.exists():
        return {"logs": log_file.read_text().splitlines()[-50:]}
    return {"logs": []}

@app.post("/api/chat")
async def chat(request: Request):
    data = await request.json()
    message = data.get("message", "")
    # Mock response for now. We can connect this to OpenRouter in a future tiny Aider step!
    return {"reply": f"AI is thinking about: {message}"}

@app.get("/stream/logs")
async def stream_logs():
    async def event_generator():
        yield "data: 🟢 Connected to live log stream...\n\n"
        log_file = BASE_DIR / "logs" / "swarm_systemd.log"
        if log_file.exists():
            with open(log_file, "r") as f:
                lines = f.readlines()
                for line in lines[-30:]:
                    yield f"data: {line}\n\n"
                while True:
                    line = f.readline()
                    if not line:
                        await asyncio.sleep(0.5)
                        continue
                    yield f"data: {line}\n\n"
        else:
            yield "data: ⚠️ Log file not found yet. Waiting for swarm...\n\n"
            await asyncio.sleep(2)
    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
