import os
import uuid
import secrets
import asyncio
import json
from typing import Dict, List, Any, Optional
from datetime import datetime

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, Request, Response, Depends, Cookie
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database import init_db, get_all_tasks, get_task, save_task, delete_task
from downloader import M3U8Downloader
from extractor import extract_m3u8_from_url

# Default download dir & Admin auth config
if os.path.exists("/.dockerenv"):
    DEFAULT_DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "/downloads")
else:
    DEFAULT_DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "downloads")))
os.makedirs(DEFAULT_DOWNLOAD_DIR, exist_ok=True)

ADMIN_USER = os.getenv("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

# Active valid sessions map {session_token: username}
active_sessions: Dict[str, str] = {}

app = FastAPI(title="MediaSeek M3U8 Downloader API", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active downloaders map {task_id: M3U8Downloader}
active_downloaders: Dict[str, M3U8Downloader] = {}

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

ws_manager = ConnectionManager()

def broadcast_progress(task_state: Dict[str, Any]):
    asyncio.create_task(ws_manager.broadcast({
        "type": "progress",
        "data": task_state
    }))

@app.on_event("startup")
async def startup_event():
    init_db()

# Authentication dependency
def verify_session(request: Request, session_token: Optional[str] = Cookie(None)):
    token = session_token
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            
    if not token or token not in active_sessions:
        raise HTTPException(status_code=401, detail="未授权，请先登录管理员账号")
    return active_sessions[token]

# Pydantic schemas
class TaskCreateRequest(BaseModel):
    url: str
    title: Optional[str] = None
    save_path: Optional[str] = None
    filename: Optional[str] = None
    concurrency: Optional[int] = 8

class ExtractRequest(BaseModel):
    url: str

class LoginRequest(BaseModel):
    username: str
    password: str

# --------------------------------------------------------------------------
# Auth Endpoints (Public)
# --------------------------------------------------------------------------
@app.post("/api/login")
def login(req: LoginRequest, response: Response):
    user = req.username.strip()
    pwd = req.password.strip()
    
    if user == ADMIN_USER and pwd == ADMIN_PASSWORD:
        token = secrets.token_hex(32)
        active_sessions[token] = user
        response.set_cookie(
            key="session_token",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=86400 * 30 # 30 days
        )
        return {
            "status": "success",
            "message": "登录成功",
            "token": token,
            "username": user
        }
        
    raise HTTPException(status_code=401, detail="用户名或密码错误，请重新输入")

@app.post("/api/logout")
def logout(response: Response, session_token: Optional[str] = Cookie(None)):
    if session_token and session_token in active_sessions:
        del active_sessions[session_token]
    response.delete_cookie("session_token")
    return {"status": "success", "message": "已成功退出登录"}

@app.get("/api/auth-check")
def auth_check(request: Request, session_token: Optional[str] = Cookie(None)):
    token = session_token
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            
    if token and token in active_sessions:
        return {"authenticated": True, "username": active_sessions[token]}
    return {"authenticated": False}

# --------------------------------------------------------------------------
# Protected REST API Endpoints
# --------------------------------------------------------------------------
@app.post("/api/extract")
async def extract_video_from_webpage(req: ExtractRequest, user: str = Depends(verify_session)):
    url = req.url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="请输入以 http:// 或 https:// 开头的合法网页地址。")
    
    result = await extract_m3u8_from_url(url)
    return result

@app.get("/api/debug-image")
def get_debug_image(user: str = Depends(verify_session)):
    import glob
    png_files = glob.glob(os.path.join(DEFAULT_DOWNLOAD_DIR, "debug_*.png"))
    if not png_files:
        raise HTTPException(status_code=404, detail="未找到任何调试截图，请先执行一次解析任务。")
    # Get the latest image
    latest_image = max(png_files, key=os.path.getctime)
    return FileResponse(latest_image, media_type="image/png")

@app.get("/api/config")
def get_config(user: str = Depends(verify_session)):
    return {
        "default_download_dir": DEFAULT_DOWNLOAD_DIR,
        "ffmpeg_available": shutil_ffmpeg_check()
    }

def shutil_ffmpeg_check():
    import shutil
    return shutil.which("ffmpeg") is not None or os.path.exists("/opt/homebrew/bin/ffmpeg")

@app.get("/api/folders")
def list_folders(user: str = Depends(verify_session)):
    try:
        folders = ["/"]
        if os.path.exists(DEFAULT_DOWNLOAD_DIR):
            for item in os.listdir(DEFAULT_DOWNLOAD_DIR):
                if os.path.isdir(os.path.join(DEFAULT_DOWNLOAD_DIR, item)):
                    folders.append(item)
        return folders
    except Exception as e:
        return ["/"]

@app.get("/api/tasks")
def list_tasks(user: str = Depends(verify_session)):
    all_tasks = get_all_tasks()
    active = [t for t in all_tasks if t["status"] in ["pending", "downloading", "merging", "paused"]]
    return active

@app.get("/api/history")
def list_history(user: str = Depends(verify_session)):
    all_tasks = get_all_tasks()
    history = [t for t in all_tasks if t["status"] in ["completed", "failed", "cancelled"]]
    return history

@app.post("/api/tasks")
async def create_task(req: TaskCreateRequest, background_tasks: BackgroundTasks, user: str = Depends(verify_session)):
    url = req.url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="无效的 M3U8 URL 格式，请输入以 http:// 或 https:// 开头的链接。")
    
    save_path = req.save_path.strip() if req.save_path and req.save_path.strip() else DEFAULT_DOWNLOAD_DIR
    os.makedirs(save_path, exist_ok=True)
    
    task_id = str(uuid.uuid4())
    
    title = req.title.strip() if req.title and req.title.strip() else f"video_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    filename = req.filename.strip() if req.filename and req.filename.strip() else f"{title}.mp4"
    if not filename.endswith(('.mp4', '.ts')):
        filename += '.mp4'
        
    downloader = M3U8Downloader(
        task_id=task_id,
        url=url,
        title=title,
        save_path=save_path,
        filename=filename,
        concurrency=req.concurrency or 8,
        progress_callback=broadcast_progress
    )
    
    active_downloaders[task_id] = downloader
    save_task(downloader.get_state())
    
    background_tasks.add_task(downloader.start)
    
    return downloader.get_state()

@app.post("/api/tasks/{task_id}/pause")
def pause_task(task_id: str, user: str = Depends(verify_session)):
    if task_id in active_downloaders:
        active_downloaders[task_id].pause()
        return {"status": "success", "message": "已暂停下载"}
    raise HTTPException(status_code=404, detail="未找到正在下载的任务")

@app.post("/api/tasks/{task_id}/resume")
def resume_task(task_id: str, user: str = Depends(verify_session)):
    if task_id in active_downloaders:
        downloader = active_downloaders[task_id]
        if downloader.status == "paused":
            downloader.resume()
            return {"status": "success", "message": "已恢复下载"}
    else:
        db_task = get_task(task_id)
        if db_task and db_task["status"] in ["paused", "failed", "cancelled"]:
            downloader = M3U8Downloader(
                task_id=db_task["id"],
                url=db_task["url"],
                title=db_task["title"],
                save_path=db_task["save_path"],
                filename=db_task["filename"],
                progress_callback=broadcast_progress
            )
            active_downloaders[task_id] = downloader
            asyncio.create_task(downloader.start())
            return {"status": "success", "message": "已重新开始下载"}
            
    raise HTTPException(status_code=404, detail="未找到任务或无法恢复")

@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str, user: str = Depends(verify_session)):
    if task_id in active_downloaders:
        active_downloaders[task_id].cancel()
        return {"status": "success", "message": "已取消任务"}
    raise HTTPException(status_code=404, detail="未找到正在下载的任务")

@app.delete("/api/tasks/{task_id}")
def delete_task_endpoint(task_id: str, delete_file: bool = False, user: str = Depends(verify_session)):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    if task_id in active_downloaders:
        active_downloaders[task_id].cancel()
        del active_downloaders[task_id]
        
    if delete_file and task.get("full_filepath") and os.path.exists(task["full_filepath"]):
        try:
            os.remove(task["full_filepath"])
        except Exception as e:
            print(f"Error removing file: {e}")

    delete_task(task_id)
    return {"status": "success", "message": "已删除任务记录"}

# WebSocket Endpoint with Authentication
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    token = websocket.cookies.get("session_token") or websocket.query_params.get("token")
    if not token or token not in active_sessions:
        await websocket.close(code=1008) # Policy Violation / Unauthorized
        return

    await ws_manager.connect(websocket)
    try:
        all_tasks = get_all_tasks()
        await websocket.send_json({
            "type": "init",
            "data": all_tasks
        })
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

# Serve Frontend static files
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend"))
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
