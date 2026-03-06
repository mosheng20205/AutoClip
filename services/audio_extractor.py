import asyncio
import json
import os
from pathlib import Path


async def get_audio_duration(audio_path: str) -> float:
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", audio_path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    info = json.loads(stdout)
    return float(info["format"]["duration"])


async def extract_audio(video_path: str, output_dir: str) -> str:
    """
    从视频中提取音频为 MP3 (16kHz mono, 64kbps)。
    MP3 格式上传体积小，DashScope 直接支持。
    """
    os.makedirs(output_dir, exist_ok=True)
    stem = Path(video_path).stem
    audio_path = os.path.join(output_dir, f"{stem}.mp3")

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-acodec", "libmp3lame", "-ar", "16000", "-ac", "1", "-b:a", "64k",
        audio_path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg 音频提取失败: {stderr.decode()}")
    return audio_path
