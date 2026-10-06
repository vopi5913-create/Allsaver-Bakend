import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

app = FastAPI(title="AllSaver TikTok MP4 Downloader")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)
MAX_FILE_SIZE = 150 * 1024 * 1024


class DownloadRequest(BaseModel):
    url: str


def valid_tiktok_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
        return host == "tiktok.com" or host.endswith(".tiktok.com")
    except Exception:
        return False


@app.get("/api/health")
def health():
    return {"ok": True, "service": "AllSaver TikTok MP4 Downloader"}


@app.post("/api/download")
def download_video(req: DownloadRequest):
    url = req.url.strip()

    if not valid_tiktok_url(url):
        raise HTTPException(
            status_code=400,
            detail="Please enter a valid TikTok URL."
        )

    job = uuid.uuid4().hex
    job_dir = DOWNLOAD_DIR / job
    job_dir.mkdir(parents=True, exist_ok=True)

    output_template = str(job_dir / "%(id)s.%(ext)s")

    options = {
        # Prefer a single MP4 stream so the server does not need FFmpeg.
        "format": "best[ext=mp4]/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "socket_timeout": 30,
        "retries": 2,
    }

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            file_path = Path(filename)

            # In case yt-dlp chose a different extension.
            if not file_path.exists():
                candidates = list(job_dir.iterdir())
                if not candidates:
                    raise RuntimeError("Downloaded file was not found.")
                file_path = candidates[0]

        if not file_path.exists():
            raise RuntimeError("Downloaded file was not found.")

        if file_path.stat().st_size > MAX_FILE_SIZE:
            file_path.unlink(missing_ok=True)
            raise RuntimeError("Video is larger than the 150 MB limit.")

        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", file_path.name)

        return {
            "ok": True,
            "filename": safe_name,
            "download_url": f"/api/file/{job}/{file_path.name}",
        }

    except Exception as e:
        # Remove incomplete files.
        for p in job_dir.glob("*"):
            try:
                p.unlink()
            except Exception:
                pass
        try:
            job_dir.rmdir()
        except Exception:
            pass

        raise HTTPException(
            status_code=500,
            detail=f"Download failed: {str(e)[:500]}"
        )


@app.get("/api/file/{job}/{filename}")
def get_file(job: str, filename: str):
    # Prevent path traversal.
    if Path(filename).name != filename or Path(job).name != job:
        raise HTTPException(status_code=400, detail="Invalid file path.")

    path = DOWNLOAD_DIR / job / filename

    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found.")

    return FileResponse(
        path,
        media_type="video/mp4",
        filename=filename,
    )
