import os
import uuid
import subprocess
import requests
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

API_KEY = os.getenv("API_KEY", "changeme")
TMP = "/tmp"
FONT_DIR = "/app/fonts"
MAX_SECONDS = 180

PRESETS = {
    "top": 8,
    "middle": 5,
    "bottom": 2
}

app = FastAPI(title="Timed Subtitle Burner API")

# ---------- Models ----------
class SubtitleTrack(BaseModel):
    srt: str                 # FULL SRT WITH TIMESTAMPS
    color: str = "#FFFFFF"
    size: Optional[int] = None
    font: str = "Inter-Bold.ttf"
    preset: Optional[str] = "bottom"

class BurnRequest(BaseModel):
    video_url: str
    subtitle_1: SubtitleTrack
    subtitle_2: Optional[SubtitleTrack] = None

# ---------- Utils ----------
def auth(key: str):
    if key != API_KEY:
        raise HTTPException(401, "Invalid API key")

def run(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode())

def auto_font_size():
    return 48  # TikTok-safe default

def write_srt(content: str, path: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content.strip())

def style(track: SubtitleTrack):
    align = PRESETS.get(track.preset, 2)
    size = track.size or auto_font_size()
    color = track.color.lstrip("#")
    bgr = color[4:6] + color[2:4] + color[0:2]

    return (
        f"FontName={track.font.replace('.ttf','')},"
        f"FontSize={size},"
        f"PrimaryColour=&H{bgr}&,"
        f"Outline=2,"
        f"Shadow=2,"
        f"Alignment={align}"
    )

# ---------- Routes ----------
@app.get("/ping")
def ping():
    return {"status": "alive"}

@app.post("/burn-subtitles")
def burn(req: BurnRequest, x_api_key: str = Header(...)):
    auth(x_api_key)

    uid = str(uuid.uuid4())
    video = f"{TMP}/{uid}.mp4"
    out = f"{TMP}/{uid}_out.mp4"

    r = requests.get(req.video_url, stream=True)
    if r.status_code != 200:
        raise HTTPException(400, "Video download failed")

    with open(video, "wb") as f:
        for c in r.iter_content(1024 * 1024):
            f.write(c)

    filters = []

    srt1 = f"{TMP}/{uid}_1.srt"
    write_srt(req.subtitle_1.srt, srt1)
    filters.append(
        f"subtitles={srt1}:fontsdir={FONT_DIR}:force_style='{style(req.subtitle_1)}'"
    )

    if req.subtitle_2:
        srt2 = f"{TMP}/{uid}_2.srt"
        write_srt(req.subtitle_2.srt, srt2)
        filters.append(
            f"subtitles={srt2}:fontsdir={FONT_DIR}:force_style='{style(req.subtitle_2)}'"
        )

    cmd = [
        "ffmpeg", "-y",
        "-i", video,
        "-vf", ",".join(filters),
        "-c:a", "copy",
        out
    ]

    try:
        run(cmd)
    except Exception as e:
        raise HTTPException(500, str(e))

    return {"download_url": f"/download/{uid}"}

@app.get("/download/{job_id}")
def download(job_id: str):
    path = f"{TMP}/{job_id}_out.mp4"
    if not os.path.exists(path):
        raise HTTPException(404, "Not found")
    return FileResponse(path, media_type="video/mp4", filename="final.mp4")
