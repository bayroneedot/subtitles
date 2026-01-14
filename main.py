import os
import uuid
import subprocess
import requests
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional

# ================= CONFIG =================
API_KEY = os.getenv("API_KEY", "changeme")
TMP_DIR = "/tmp"
MAX_VIDEO_SECONDS = 180  # 3 minutes
FONT_DIR = "/app/fonts"

# =========================================

app = FastAPI(title="Subtitle Burner API")

# ---------- Models ----------
class SubtitleTrack(BaseModel):
    srt: str
    position: dict  # { "x": "50%", "y": "85%" }
    color: str      # hex "#FFFFFF"
    size: int

class BurnRequest(BaseModel):
    video_url: str
    subtitle_1: SubtitleTrack
    subtitle_2: Optional[SubtitleTrack] = None

# ---------- Utils ----------
def check_api_key(key: str):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")

def run(cmd):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode())

def write_ass(track: SubtitleTrack, filename: str):
    x = track.position.get("x", "50%")
    y = track.position.get("y", "90%")

    def pct(v): return int(float(v.replace("%","")))

    ass = f"""
[Script Info]
ScriptType: v4.00+

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,OutlineColour,BackColour,Bold,Outline,Shadow,Alignment,MarginL,MarginR,MarginV
Style: Default,Inter,{track.size},&H{track.color[5:7]}{track.color[3:5]}{track.color[1:3]},&H00000000,&H80000000,0,2,2,2,10,10,10

[Events]
Format: Layer,Start,End,Style,Text
Dialogue: 0,0:00:00.00,9:59:59.99,Default,{{\\pos({pct(x)},{pct(y)})}}{track.srt.replace(chr(10), '\\N')}
"""
    with open(filename, "w", encoding="utf-8") as f:
        f.write(ass)

# ---------- Routes ----------
@app.get("/ping")
def ping():
    return {"status": "alive"}

@app.post("/burn-subtitles")
def burn(req: BurnRequest, x_api_key: str = Header(...)):
    check_api_key(x_api_key)

    job_id = str(uuid.uuid4())
    video_path = f"{TMP_DIR}/{job_id}.mp4"
    out_path = f"{TMP_DIR}/{job_id}_out.mp4"

    # download video
    r = requests.get(req.video_url, stream=True)
    if r.status_code != 200:
        raise HTTPException(400, "Failed to download video")

    with open(video_path, "wb") as f:
        for chunk in r.iter_content(1024 * 1024):
            f.write(chunk)

    # subtitle files
    ass_files = []
    ass1 = f"{TMP_DIR}/{job_id}_1.ass"
    write_ass(req.subtitle_1, ass1)
    ass_files.append(ass1)

    if req.subtitle_2:
        ass2 = f"{TMP_DIR}/{job_id}_2.ass"
        write_ass(req.subtitle_2, ass2)
        ass_files.append(ass2)

    filters = ",".join([f"ass={a}" for a in ass_files])

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", filters,
        "-c:a", "copy",
        out_path
    ]

    try:
        run(cmd)
    except Exception as e:
        raise HTTPException(500, str(e))

    return {
        "download_url": f"/download/{job_id}"
    }

@app.get("/download/{job_id}")
def download(job_id: str):
    path = f"{TMP_DIR}/{job_id}_out.mp4"
    if not os.path.exists(path):
        raise HTTPException(404, "File not found")

    return fastapi.responses.FileResponse(
        path,
        media_type="video/mp4",
        filename="final.mp4"
    )
