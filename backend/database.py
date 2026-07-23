import sqlite3
import os
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

DATA_DIR = os.getenv("DATA_DIR", os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.getenv("DB_PATH", os.path.join(DATA_DIR, "mediaseek.db"))

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            title TEXT NOT NULL,
            save_path TEXT NOT NULL,
            filename TEXT NOT NULL,
            full_filepath TEXT,
            status TEXT NOT NULL,
            progress REAL DEFAULT 0.0,
            downloaded_bytes INTEGER DEFAULT 0,
            total_bytes INTEGER DEFAULT 0,
            total_segments INTEGER DEFAULT 0,
            downloaded_segments INTEGER DEFAULT 0,
            speed REAL DEFAULT 0.0,
            eta INTEGER DEFAULT 0,
            error_message TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            completed_at TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_task(task_data: Dict[str, Any]):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if exists
    cursor.execute("SELECT id FROM tasks WHERE id = ?", (task_data["id"],))
    exists = cursor.fetchone()
    
    if exists:
        cursor.execute('''
            UPDATE tasks SET
                url = ?, title = ?, save_path = ?, filename = ?, full_filepath = ?,
                status = ?, progress = ?, downloaded_bytes = ?, total_bytes = ?,
                total_segments = ?, downloaded_segments = ?, speed = ?, eta = ?,
                error_message = ?, completed_at = ?
            WHERE id = ?
        ''', (
            task_data.get("url"),
            task_data.get("title"),
            task_data.get("save_path"),
            task_data.get("filename"),
            task_data.get("full_filepath"),
            task_data.get("status"),
            task_data.get("progress", 0.0),
            task_data.get("downloaded_bytes", 0),
            task_data.get("total_bytes", 0),
            task_data.get("total_segments", 0),
            task_data.get("downloaded_segments", 0),
            task_data.get("speed", 0.0),
            task_data.get("eta", 0),
            task_data.get("error_message", ""),
            task_data.get("completed_at"),
            task_data["id"]
        ))
    else:
        cursor.execute('''
            INSERT INTO tasks (
                id, url, title, save_path, filename, full_filepath,
                status, progress, downloaded_bytes, total_bytes,
                total_segments, downloaded_segments, speed, eta,
                error_message, created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            task_data["id"],
            task_data.get("url"),
            task_data.get("title"),
            task_data.get("save_path"),
            task_data.get("filename"),
            task_data.get("full_filepath"),
            task_data.get("status", "pending"),
            task_data.get("progress", 0.0),
            task_data.get("downloaded_bytes", 0),
            task_data.get("total_bytes", 0),
            task_data.get("total_segments", 0),
            task_data.get("downloaded_segments", 0),
            task_data.get("speed", 0.0),
            task_data.get("eta", 0),
            task_data.get("error_message", ""),
            task_data.get("created_at", datetime.now().isoformat()),
            task_data.get("completed_at")
        ))
    conn.commit()
    conn.close()

def get_all_tasks() -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks ORDER BY COALESCE(completed_at, created_at) DESC, created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def delete_task(task_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
