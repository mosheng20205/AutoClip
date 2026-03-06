import asyncio
import os
import uuid
from pathlib import Path


async def clip_segments(
    video_path: str,
    segments: list[dict],
    output_dir: str,
    merge: bool = True,
) -> str:
    """
    根据 segments 列表剪辑视频。
    每个 segment: {"start": float, "end": float}
    merge=True 时合并所有片段为一个视频，否则返回第一个片段路径。
    返回最终输出视频路径。
    """
    os.makedirs(output_dir, exist_ok=True)
    task_id = uuid.uuid4().hex[:8]
    stem = Path(video_path).stem

    if not segments:
        raise ValueError("没有选中任何片段")

    part_paths: list[str] = []

    for i, seg in enumerate(segments):
        part_path = os.path.join(output_dir, f"{stem}_{task_id}_part{i}.mp4")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-i", video_path,
            "-ss", str(seg["start"]),
            "-to", str(seg["end"]),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            part_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"FFmpeg 剪辑片段 {i} 失败: {stderr.decode()}")
        part_paths.append(part_path)

    if not merge or len(part_paths) == 1:
        final = part_paths[0]
        if len(part_paths) == 1:
            renamed = os.path.join(output_dir, f"{stem}_highlight_{task_id}.mp4")
            os.rename(final, renamed)
            return renamed
        return final

    final_path = os.path.join(output_dir, f"{stem}_highlight_{task_id}.mp4")
    concat_list = os.path.join(output_dir, f"concat_{task_id}.txt")

    with open(concat_list, "w", encoding="utf-8") as f:
        for p in part_paths:
            f.write(f"file '{p}'\n")

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", concat_list, "-c", "copy", final_path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg 合并失败: {stderr.decode()}")

    for p in part_paths:
        os.remove(p)
    os.remove(concat_list)

    return final_path
