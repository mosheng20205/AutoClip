import asyncio
import os
import httpx
from pathlib import Path

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/api/v1"


async def _get_upload_policy(client: httpx.AsyncClient, api_key: str) -> dict:
    """获取 DashScope 文件上传凭证。"""
    resp = await client.get(
        f"{DASHSCOPE_BASE}/uploads",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        params={"action": "getPolicy", "model": "paraformer-v2"},
    )
    resp.raise_for_status()
    return resp.json()["data"]


async def _upload_to_oss(client: httpx.AsyncClient, policy: dict, file_path: str) -> str:
    """上传文件到阿里云 OSS 临时空间，返回 oss:// URL（48小时有效）。"""
    filename = Path(file_path).name
    key = f"{policy['upload_dir']}/{filename}"

    with open(file_path, "rb") as f:
        resp = await client.post(
            policy["upload_host"],
            data={
                "OSSAccessKeyId": policy["oss_access_key_id"],
                "Signature": policy["signature"],
                "policy": policy["policy"],
                "x-oss-object-acl": policy["x_oss_object_acl"],
                "x-oss-forbid-overwrite": policy["x_oss_forbid_overwrite"],
                "key": key,
                "success_action_status": "200",
            },
            files={"file": (filename, f)},
        )
    resp.raise_for_status()
    return f"oss://{key}"


async def _submit_transcription(client: httpx.AsyncClient, api_key: str, file_url: str) -> str:
    """提交 Paraformer 转录任务，返回 task_id。"""
    resp = await client.post(
        f"{DASHSCOPE_BASE}/services/audio/asr/transcription",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
            "X-DashScope-OssResourceResolve": "enable",
        },
        json={
            "model": "paraformer-v2",
            "input": {"file_urls": [file_url]},
            "parameters": {"language_hints": ["zh", "en"]},
        },
    )
    if resp.status_code != 200:
        print(f"  [transcriber] 提交失败 HTTP {resp.status_code}: {resp.text}")
    resp.raise_for_status()
    data = resp.json()
    if data.get("output", {}).get("task_id"):
        return data["output"]["task_id"]
    raise RuntimeError(f"提交转录任务失败: {data}")


async def _poll_transcription(client: httpx.AsyncClient, api_key: str, task_id: str) -> dict:
    """轮询转录任务直到完成，返回 output。"""
    headers = {"Authorization": f"Bearer {api_key}"}
    poll_count = 0
    while True:
        resp = await client.get(f"{DASHSCOPE_BASE}/tasks/{task_id}", headers=headers)
        resp.raise_for_status()
        data = resp.json()
        status = data["output"]["task_status"]
        poll_count += 1
        if poll_count % 5 == 1:
            print(f"  [transcriber] 轮询 #{poll_count}, 状态: {status}")
        if status == "SUCCEEDED":
            return data["output"]
        if status == "FAILED":
            results = data["output"].get("results", [])
            err_msg = results[0].get("message", "未知错误") if results else str(data["output"])
            raise RuntimeError(f"转录任务失败: {err_msg}")
        await asyncio.sleep(3)


async def transcribe_audio(audio_path: str) -> list[dict]:
    """
    调用阿里云 DashScope Paraformer API 转录音频。
    流程: 上传文件 → 提交任务 → 轮询结果 → 解析句子时间戳。
    返回: [{"text": str, "start": float, "end": float}, ...]
    支持最大 2GB 文件 / 12 小时时长。
    """
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("请在 .env 中配置 DASHSCOPE_API_KEY（阿里云百炼平台 API Key）")

    async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=30)) as client:
        print("  [transcriber] 获取上传凭证...")
        policy = await _get_upload_policy(client, api_key)
        print("  [transcriber] 上传音频到 OSS...")
        oss_url = await _upload_to_oss(client, policy, audio_path)
        print(f"  [transcriber] 上传完成: {oss_url}")
        print("  [transcriber] 提交转录任务...")
        task_id = await _submit_transcription(client, api_key, oss_url)
        print(f"  [transcriber] 任务已提交: {task_id}, 等待转录完成...")
        output = await _poll_transcription(client, api_key, task_id)
        print("  [transcriber] 转录完成, 解析结果...")

        results = output.get("results", [])
        if not results or results[0].get("subtask_status") != "SUCCEEDED":
            err = results[0].get("message", "未知错误") if results else "无结果"
            raise RuntimeError(f"转录失败: {err}")

        transcription_url = results[0]["transcription_url"]
        resp = await client.get(transcription_url)
        resp.raise_for_status()
        transcript_data = resp.json()

    all_segments: list[dict] = []
    for transcript in transcript_data.get("transcripts", []):
        for sent in transcript.get("sentences", []):
            text = sent.get("text", "").strip()
            if text:
                all_segments.append({
                    "text": text,
                    "start": round(sent["begin_time"] / 1000, 2),
                    "end": round(sent["end_time"] / 1000, 2),
                })

    return all_segments
