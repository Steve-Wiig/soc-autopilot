from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import json
import asyncio
import time
import urllib.request
from pathlib import Path
from openai import OpenAI

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Initialize OpenRouter client
openrouter_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
)

SYSTEM_PROMPT = "You are an expert SOC/SIEM pipeline developer. Provide concise, actionable Python code or architectural advice."

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
        
    paused_file = BASE_DIR / ".swarm_paused"
    is_paused = paused_file.exists()
        
    return {"current_task": current_task, "skipped_files": skip_count, "paused": is_paused}

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

@app.get("/api/logs/download")
async def download_logs():
    log_file = BASE_DIR / "logs" / "swarm_systemd.log"
    if log_file.exists():
        return FileResponse(log_file, filename='swarm_systemd.log')
    return JSONResponse(status_code=404, content={'detail': 'Log file not found'})

@app.get("/api/usage")
async def get_usage():
    usage_file = BASE_DIR / "overnight" / "openrouter_usage.json"
    api_key = os.getenv("OPENROUTER_API_KEY")
    now = time.time()
    
    # Try to read existing cache
    cached_data = {}
    if usage_file.exists():
        try:
            cached_data = json.loads(usage_file.read_text())
        except json.JSONDecodeError:
            pass

    # Check if cache is fresh (< 24 hours)
    if cached_data and "last_updated" in cached_data:
        if now - cached_data["last_updated"] < 86400:
            return cached_data

    # Cache is stale or missing - fetch from OpenRouter API
    total_credits = 0.0
    if api_key:
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/credits",
                headers={"Authorization": f"Bearer {api_key}"}
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode())
                # OpenRouter returns credits in a specific format
                total_credits = data.get("data", {}).get("total_credits", 0.0)
        except Exception as e:
            print(f"Failed to fetch OpenRouter credits: {e}")
            # Fall back to cached total_credits if available
            total_credits = cached_data.get("total_credits", 0.0)

    # Preserve local_calls from cache (or backward compat with "used")
    local_calls = cached_data.get("local_calls", cached_data.get("used", 0))

    # Build new cache data
    new_data = {
        "total_credits": total_credits,
        "local_calls": local_calls,
        "last_updated": now
    }
    
    # Save to file
    usage_file.write_text(json.dumps(new_data, indent=4))
    return new_data

@app.post("/api/chat")
async def chat(request: Request):
    data = await request.json()
    message = data.get("message", "")
    file_path = data.get("file_path")

    # If file_path provided, sanitize and read file contents
    if file_path:
        if ".." in file_path:
            return {"reply": "Error: Directory traversal attempt detected."}
        try:
            requested_path = (BASE_DIR / file_path).resolve()
            if not requested_path.is_relative_to(BASE_DIR):
                return {"reply": "Error: File path must be within the project directory."}
            if requested_path.exists() and requested_path.is_file():
                file_contents = requested_path.read_text(encoding="utf-8")
                message = f"Here is the content of {file_path}:\n\n{file_contents}\n\nUser Question: {message}"
            else:
                return {"reply": f"Error: File not found at {file_path}"}
        except Exception as e:
            return {"reply": f"Error reading file: {str(e)}"}

    try:
        completion = openrouter_client.chat.completions.create(
            model="nvidia/nemotron-3-ultra-550b-a55b:free",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            temperature=0.3,
            max_tokens=2048,
        )
        if completion.choices and len(completion.choices) > 0:
            reply = completion.choices[0].message.content

            # Increment local_calls on successful completion
            usage_file = BASE_DIR / "overnight" / "openrouter_usage.json"
            try:
                usage_data = json.loads(usage_file.read_text()) if usage_file.exists() else {"local_calls": 0, "total_credits": 0.0, "last_updated": 0}
                usage_data["local_calls"] = usage_data.get("local_calls", 0) + 1
                usage_file.write_text(json.dumps(usage_data, indent=4))
            except Exception:
                pass  # Fail silently on usage tracking so chat still works

        else:
            reply = "AI provider is currently overloaded. Please try again in a moment."
    except Exception as e:
        reply = f"Error calling OpenRouter: {str(e)}"

    return {"reply": reply}

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
