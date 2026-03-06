import asyncio
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from services.audio_extractor import extract_audio
from services.transcriber import transcribe_audio
from services.highlight_finder import find_by_keywords, find_by_llm
from services.video_clipper import clip_segments

load_dotenv()

app = FastAPI(title="视频精华自动剪辑工具")

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "uploads")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

tasks: dict[str, dict] = {}


# ───── Models ─────

class KeywordRequest(BaseModel):
    task_id: str
    keywords: list[str]

class LLMRequest(BaseModel):
    task_id: str

class ClipRequest(BaseModel):
    task_id: str
    selected_indices: list[int]
    merge: bool = True


# ───── API Routes ─────

@app.post("/api/upload")
async def upload_video(file: UploadFile):
    if not file.filename:
        raise HTTPException(400, "未选择文件")

    ext = Path(file.filename).suffix.lower()
    if ext not in {".mp4", ".avi", ".mkv", ".mov", ".webm", ".flv"}:
        raise HTTPException(400, f"不支持的视频格式: {ext}")

    task_id = uuid.uuid4().hex[:12]
    save_path = os.path.join(UPLOAD_DIR, f"{task_id}{ext}")

    with open(save_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            f.write(chunk)

    tasks[task_id] = {
        "status": "uploaded",
        "video_path": save_path,
        "filename": file.filename,
        "segments": None,
        "error": None,
    }
    return {"task_id": task_id, "filename": file.filename}


@app.post("/api/transcribe/{task_id}")
async def start_transcribe(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task["status"] == "transcribing":
        raise HTTPException(400, "正在转录中，请勿重复提交")

    task["status"] = "transcribing"
    task["error"] = None

    asyncio.create_task(_do_transcribe(task_id))
    return {"status": "transcribing"}


async def _do_transcribe(task_id: str):
    task = tasks[task_id]
    try:
        print(f"[{task_id}] 开始提取音频...")
        audio_path = await extract_audio(task["video_path"], UPLOAD_DIR)
        print(f"[{task_id}] 音频提取完成: {audio_path}, 大小: {os.path.getsize(audio_path)/1024/1024:.1f}MB")
        print(f"[{task_id}] 开始上传并转录...")
        segments = await transcribe_audio(audio_path)
        print(f"[{task_id}] 转录完成, 共 {len(segments)} 个句子")
        task["segments"] = segments
        task["status"] = "transcribed"
        if os.path.exists(audio_path):
            os.remove(audio_path)
    except Exception as e:
        print(f"[{task_id}] 转录失败: {e}")
        task["status"] = "error"
        task["error"] = str(e)


@app.get("/api/status/{task_id}")
async def get_status(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return {
        "status": task["status"],
        "filename": task.get("filename"),
        "segments": task.get("segments"),
        "error": task.get("error"),
    }


@app.post("/api/highlights/keyword")
async def highlights_keyword(req: KeywordRequest):
    task = tasks.get(req.task_id)
    if not task or not task.get("segments"):
        raise HTTPException(400, "任务不存在或尚未完成转录")

    indices = find_by_keywords(task["segments"], req.keywords)
    return {"indices": indices}


@app.post("/api/highlights/llm")
async def highlights_llm(req: LLMRequest):
    task = tasks.get(req.task_id)
    if not task or not task.get("segments"):
        raise HTTPException(400, "任务不存在或尚未完成转录")

    try:
        indices = await find_by_llm(task["segments"])
        return {"indices": indices}
    except Exception as e:
        raise HTTPException(500, f"LLM 分析失败: {e}")


@app.post("/api/clip")
async def clip_video(req: ClipRequest):
    task = tasks.get(req.task_id)
    if not task or not task.get("segments"):
        raise HTTPException(400, "任务不存在或尚未完成转录")

    all_segs = task["segments"]
    selected = []
    for idx in sorted(set(req.selected_indices)):
        if 0 <= idx < len(all_segs):
            selected.append({"start": all_segs[idx]["start"], "end": all_segs[idx]["end"]})

    if not selected:
        raise HTTPException(400, "没有选中任何有效片段")

    try:
        output_path = await clip_segments(
            task["video_path"], selected, OUTPUT_DIR, merge=req.merge
        )
        filename = Path(output_path).name
        return {"filename": filename, "download_url": f"/api/download/{filename}"}
    except Exception as e:
        raise HTTPException(500, f"剪辑失败: {e}")


@app.get("/api/download/{filename}")
async def download_file(filename: str):
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(404, "文件不存在")
    return FileResponse(file_path, filename=filename, media_type="video/mp4")


app.mount("/", StaticFiles(directory="static", html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080)
