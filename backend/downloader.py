import os
import sys
import asyncio
import time
import shutil
import subprocess
import urllib.parse
from datetime import datetime
import m3u8
import httpx
from Crypto.Cipher import AES
from typing import Callable, Optional, Dict, Any

from database import save_task, get_task

# Check if ffmpeg is available
FFMPEG_CMD = shutil.which("ffmpeg") or (
    "/opt/homebrew/bin/ffmpeg" if os.path.exists("/opt/homebrew/bin/ffmpeg") else (
        "/usr/local/bin/ffmpeg" if os.path.exists("/usr/local/bin/ffmpeg") else None
    )
)

def strip_fake_header(data: bytes) -> bytes:
    """Detect and strip fake image headers (PNG, JPEG, BMP) or garbage bytes prepended to TS segments."""
    if not data or len(data) < 188:
        return data
        
    # Standard MPEG-TS starts with 0x47 sync byte
    if data[0] == 0x47 and len(data) >= 188 * 2 and data[188] == 0x47:
        return data

    # Check for fMP4 box (ftyp, styp, moof)
    if len(data) >= 8 and (b'ftyp' in data[:64] or b'styp' in data[:64] or b'moof' in data[:64]):
        for box in [b'ftyp', b'styp', b'moof']:
            idx = data.find(box)
            if idx >= 4:
                return data[idx - 4:]
        return data

    # Search for MPEG-TS 0x47 sync pattern within first 20,000 bytes
    max_search = min(20000, len(data) - 188 * 5)
    for offset in range(max_search):
        if data[offset] == 0x47:
            # Check 5 consecutive 188-byte sync markers
            if all(offset + i * 188 < len(data) and data[offset + i * 188] == 0x47 for i in range(5)):
                return data[offset:]
                
    return data

class M3U8Downloader:
    def __init__(self, task_id: str, url: str, title: str, save_path: str, filename: str,
                 concurrency: int = 8, headers: Optional[Dict[str, str]] = None,
                 progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.task_id = task_id
        self.url = url
        self.title = title
        self.save_path = save_path
        self.filename = filename if filename.endswith(('.mp4', '.ts')) else f"{filename}.mp4"
        self.concurrency = concurrency
        self.headers = headers or {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        self.progress_callback = progress_callback
        
        self.status = "pending"
        self.progress = 0.0
        self.downloaded_bytes = 0
        self.total_bytes = 0
        self.total_segments = 0
        self.downloaded_segments = 0
        self.speed = 0.0
        self.eta = 0
        self.error_message = ""
        
        # Temp dir for segments
        self.temp_dir = os.path.join(save_path, f".tmp_{task_id}")
        self.full_filepath = os.path.join(save_path, self.filename)
        
        self._is_paused = False
        self._is_cancelled = False
        self._task_obj = None

    def get_state(self) -> Dict[str, Any]:
        return {
            "id": self.task_id,
            "url": self.url,
            "title": self.title,
            "save_path": self.save_path,
            "filename": self.filename,
            "full_filepath": self.full_filepath,
            "status": self.status,
            "progress": round(self.progress, 1),
            "downloaded_bytes": self.downloaded_bytes,
            "total_bytes": self.total_bytes,
            "total_segments": self.total_segments,
            "downloaded_segments": self.downloaded_segments,
            "speed": round(self.speed, 2),
            "eta": self.eta,
            "error_message": self.error_message,
            "completed_at": datetime.now().isoformat() if self.status in ["completed", "failed", "cancelled"] else None
        }

    def _notify(self):
        state = self.get_state()
        save_task(state)
        if self.progress_callback:
            try:
                self.progress_callback(state)
            except Exception:
                pass

    async def start(self):
        os.makedirs(self.save_path, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        
        self.status = "downloading"
        self._notify()

        try:
            async with httpx.AsyncClient(headers=self.headers, follow_redirects=True, timeout=30.0) as client:
                # 1. Fetch m3u8 playlist
                resp = await client.get(self.url)
                resp.raise_for_status()
                playlist_text = resp.text
                base_url = str(resp.url)

                playlist = m3u8.loads(playlist_text, uri=base_url)

                # Handle master playlist
                if playlist.is_variant:
                    # Pick best quality playlist
                    best_playlist = max(playlist.playlists, key=lambda p: p.stream_info.bandwidth or 0)
                    variant_url = urllib.parse.urljoin(base_url, best_playlist.uri)
                    resp = await client.get(variant_url)
                    resp.raise_for_status()
                    playlist_text = resp.text
                    base_url = str(resp.url)
                    playlist = m3u8.loads(playlist_text, uri=base_url)

                segments = playlist.segments
                self.total_segments = len(segments)
                if self.total_segments == 0:
                    raise Exception("No video segments found in M3U8 playlist.")

                self._notify()

                # 2. Fetch Keys if AES-128 encrypted
                key_cache = {}
                for seg in segments:
                    if seg.key and seg.key.uri:
                        key_uri = urllib.parse.urljoin(base_url, seg.key.uri)
                        if key_uri not in key_cache:
                            key_resp = await client.get(key_uri)
                            key_resp.raise_for_status()
                            key_cache[key_uri] = key_resp.content

                # 3. Queue segments for download
                queue = asyncio.Queue()
                for idx, seg in enumerate(segments):
                    queue.put_nowait((idx, seg))

                start_time = time.time()
                bytes_since_last = 0
                last_speed_check = start_time

                sem = asyncio.Semaphore(self.concurrency)

                async def worker():
                    nonlocal bytes_since_last, last_speed_check
                    while not queue.empty():
                        if self._is_cancelled:
                            break
                        while self._is_paused and not self._is_cancelled:
                            await asyncio.sleep(0.5)

                        try:
                            idx, seg = await queue.get()
                        except asyncio.QueueEmpty:
                            break

                        seg_url = urllib.parse.urljoin(base_url, seg.uri)
                        seg_file = os.path.join(self.temp_dir, f"seg_{idx:05d}.ts")

                        # Skip if already downloaded
                        if os.path.exists(seg_file) and os.path.getsize(seg_file) > 0:
                            self.downloaded_segments += 1
                            self.downloaded_bytes += os.path.getsize(seg_file)
                            self.progress = (self.downloaded_segments / self.total_segments) * 100.0
                            self._notify()
                            queue.task_done()
                            continue

                        async with sem:
                            for attempt in range(3):  # retry 3 times
                                if self._is_cancelled:
                                    break
                                try:
                                    seg_resp = await client.get(seg_url, timeout=20.0)
                                    seg_resp.raise_for_status()
                                    data = seg_resp.content

                                    # Decrypt if key exists
                                    if seg.key and seg.key.uri:
                                        key_bytes = key_cache.get(urllib.parse.urljoin(base_url, seg.key.uri))
                                        if key_bytes:
                                            iv = bytes.fromhex(seg.key.iv.replace("0x", "")) if seg.key.iv else idx.to_bytes(16, byteorder='big')
                                            cipher = AES.new(key_bytes, AES.MODE_CBC, iv)
                                            data = cipher.decrypt(data)
                                            # PKCS7 unpadding
                                            padding_len = data[-1]
                                            if padding_len < 16:
                                                data = data[:-padding_len]

                                    # Strip fake anti-hotlinking image headers (PNG/JPEG/etc.) if present
                                    data = strip_fake_header(data)

                                    with open(seg_file, "wb") as f:
                                        f.write(data)

                                    seg_size = len(data)
                                    self.downloaded_bytes += seg_size
                                    bytes_since_last += seg_size
                                    self.downloaded_segments += 1
                                    self.progress = (self.downloaded_segments / self.total_segments) * 100.0

                                    now = time.time()
                                    elapsed = now - last_speed_check
                                    if elapsed >= 0.8:
                                        self.speed = bytes_since_last / elapsed
                                        bytes_since_last = 0
                                        last_speed_check = now

                                        if self.speed > 0:
                                            avg_seg_size = self.downloaded_bytes / max(1, self.downloaded_segments)
                                            est_total_bytes = avg_seg_size * self.total_segments
                                            self.total_bytes = int(est_total_bytes)
                                            remaining_bytes = est_total_bytes - self.downloaded_bytes
                                            self.eta = int(max(0, remaining_bytes / self.speed))

                                    self._notify()
                                    break
                                except Exception as e:
                                    if attempt == 2:
                                        print(f"Segment {idx} failed after 3 attempts: {e}")
                                    await asyncio.sleep(1)

                        queue.task_done()

                # Start workers
                workers = [asyncio.create_task(worker()) for _ in range(self.concurrency)]
                await asyncio.gather(*workers)

                if self._is_cancelled:
                    self.status = "cancelled"
                    self._notify()
                    self._cleanup_temp()
                    return

                # 4. Merge TS segments into final file
                self.status = "merging" if self.status == "downloading" else self.status
                self._notify()
                await self._merge_segments(self.total_segments)

                self.status = "completed"
                self.progress = 100.0
                self.speed = 0.0
                self.eta = 0
                if os.path.exists(self.full_filepath):
                    self.downloaded_bytes = os.path.getsize(self.full_filepath)
                    self.total_bytes = self.downloaded_bytes
                self._notify()
                self._cleanup_temp()

        except Exception as e:
            self.status = "failed"
            self.error_message = str(e)
            self._notify()
            self._cleanup_temp()

    async def _merge_segments(self, count: int):
        concat_list_file = os.path.join(self.temp_dir, "concat_list.txt")
        segment_files = [os.path.join(self.temp_dir, f"seg_{i:05d}.ts") for i in range(count)]
        
        # Check all segments exist
        existing_files = [f for f in segment_files if os.path.exists(f)]

        if FFMPEG_CMD:
            # Write ffmpeg concat file
            with open(concat_list_file, "w", encoding="utf-8") as f:
                for seg_path in existing_files:
                    f.write(f"file '{seg_path}'\n")

            cmd = [
                FFMPEG_CMD, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_file,
                "-c", "copy",
                self.full_filepath
            ]
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
        else:
            # Direct binary TS concatenation fallback if ffmpeg is missing
            target_file = self.full_filepath
            if not target_file.endswith('.ts') and not target_file.endswith('.mp4'):
                target_file += '.mp4'
            with open(target_file, "wb") as outfile:
                for seg_path in existing_files:
                    with open(seg_path, "rb") as infile:
                        shutil.copyfileobj(infile, outfile)
            self.full_filepath = target_file

    def pause(self):
        self._is_paused = True
        self.status = "paused"
        self.speed = 0.0
        self._notify()

    def resume(self):
        self._is_paused = False
        self.status = "downloading"
        self._notify()

    def cancel(self):
        self._is_cancelled = True
        self.status = "cancelled"
        self.speed = 0.0
        self._notify()

    def _cleanup_temp(self):
        if os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception:
                pass
