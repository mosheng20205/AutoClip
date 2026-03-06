import json
import os
import httpx


def find_by_keywords(segments: list[dict], keywords: list[str]) -> list[int]:
    """关键词匹配，返回命中的 segment 索引列表。"""
    matched: list[int] = []
    kw_lower = [k.lower() for k in keywords if k.strip()]
    for i, seg in enumerate(segments):
        text_lower = seg["text"].lower()
        if any(kw in text_lower for kw in kw_lower):
            matched.append(i)
    return matched


async def find_by_llm(segments: list[dict]) -> list[int]:
    """
    调用 DeepSeek API 分析转录文本，返回 LLM 认为是精华的 segment 索引列表。
    """
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    numbered_lines = []
    for i, seg in enumerate(segments):
        start = _fmt_time(seg["start"])
        end = _fmt_time(seg["end"])
        numbered_lines.append(f"[{i}] ({start}-{end}) {seg['text']}")
    transcript_text = "\n".join(numbered_lines)

    prompt = f"""以下是一段视频的语音转录文本，每行前面有编号和时间戳。
请分析内容，挑选出最精彩、最有价值、最核心的片段。
选择标准：有信息量、有观点、有故事性、有情感高潮的部分。
不要选择寒暄、重复、过渡性的内容。

请只返回一个 JSON 数组，包含你选中的片段编号（整数），不要有其他文字。
例如：[0, 3, 5, 8]

转录文本：
{transcript_text}"""

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{base_url}/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "你是一个视频内容分析专家，擅长找出视频中最精彩的片段。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    content = data["choices"][0]["message"]["content"].strip()
    # 提取 JSON 数组（兼容 markdown code block 包裹）
    if "```" in content:
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]
        content = content.strip()

    indices = json.loads(content)
    max_idx = len(segments) - 1
    return [idx for idx in indices if isinstance(idx, int) and 0 <= idx <= max_idx]


def _fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
