r"""ASR / LLM / TTS 验证接口（阶段二）。

不修改 xiaozhi-esp32-server 原始代码，只复用它的配置和 Provider：
    POST /asr   multipart/form-data, file=音频文件 -> JSON 文本
    POST /chat  application/json, {"text": "...", "history": [...]} -> JSON 回复
    POST /tts   application/json, {"text": "...", "voice": "..."} -> audio/mpeg
    GET  /health
    GET  /docs  Swagger 接口文档

运行（必须先安装 xiaozhi-server 依赖并准备 data/.config.yaml）：
    cd F:\PBL\voice-assistant\backend\stage2
    ..\..\.venv\Scripts\python.exe asr_tts_api.py
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "main" / "xiaozhi-server"
OUTPUT_DIR = ROOT / "stage2" / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 所有缓存/临时文件放在 F 盘，并保证相对路径配置以 server 目录为基准。
os.environ.setdefault("MODELSCOPE_CACHE", r"F:\PBL\.cache\modelscope")
os.environ.setdefault("TMP", r"F:\PBL\.cache\tmp")
os.environ.setdefault("TEMP", r"F:\PBL\.cache\tmp")
os.chdir(SERVER_DIR)
sys.path.insert(0, str(SERVER_DIR))

from fastapi import FastAPI, File, HTTPException, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, RedirectResponse  # noqa: E402
from openai import OpenAI  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from pydub import AudioSegment  # noqa: E402

from config.config_loader import load_config  # noqa: E402
from core.utils.asr import create_instance as create_asr  # noqa: E402
from core.utils.tts import create_instance as create_tts  # noqa: E402

CONFIG = asyncio.run(load_config())
ASR_NAME = CONFIG["selected_module"]["ASR"]
TTS_NAME = CONFIG["selected_module"]["TTS"]
LLM_NAME = CONFIG["selected_module"]["LLM"]
ASR_CONF = CONFIG["ASR"][ASR_NAME]
TTS_CONF = CONFIG["TTS"][TTS_NAME]
LLM_CONF = CONFIG["LLM"][LLM_NAME]
ASR_TYPE = ASR_CONF.get("type", ASR_NAME)
TTS_TYPE = TTS_CONF.get("type", TTS_NAME)
LLM_MODEL = LLM_CONF.get("model_name")
LLM_BASE_URL = LLM_CONF.get("base_url") or LLM_CONF.get("url")
SYSTEM_PROMPT = CONFIG.get(
    "prompt",
    "你是小智，一个简洁、友好的中文语音助手。回答控制在两句话以内。",
)

ASR_LOCK = asyncio.Lock()
ASR = create_asr(ASR_TYPE, ASR_CONF, delete_audio_file=False)
TTS = create_tts(TTS_TYPE, TTS_CONF, delete_audio_file=True)
LLM_CLIENT = OpenAI(
    api_key=LLM_CONF.get("api_key"),
    base_url=LLM_BASE_URL,
    timeout=60,
)

app = FastAPI(
    title="小智 ASR / TTS 验证接口",
    description=(
        "阶段二：在不修改 xiaozhi-esp32-server 源码的前提下，"
        "通过 HTTP 模拟语音输入（ASR）与语音输出（TTS）。"
    ),
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500, description="待合成文本")
    voice: str | None = Field(
        default=None,
        description="可选 EdgeTTS 音色，例如 zh-CN-XiaoxiaoNeural；不填使用配置默认值",
    )


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$", description="user 或 assistant")
    content: str = Field(..., min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000, description="本轮用户文本")
    history: list[ChatMessage] = Field(
        default_factory=list,
        description="之前的对话历史，最多使用最后 10 条",
    )


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse("/docs")


@app.get("/health", summary="健康检查")
async def health():
    return {
        "status": "ok",
        "asr": ASR_NAME,
        "asr_model_dir": ASR_CONF.get("model_dir"),
        "tts": TTS_NAME,
        "tts_voice": TTS_CONF.get("voice"),
        "llm": LLM_NAME,
        "llm_model": LLM_MODEL,
    }


@app.post("/asr", summary="语音识别：上传音频，返回文本")
async def asr(file: UploadFile = File(..., description="WAV / MP3 / OGG / M4A 音频")):
    started = time.perf_counter()
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="音频文件为空")

    try:
        audio = AudioSegment.from_file(io.BytesIO(raw))
        if len(audio) < 200:
            raise ValueError("音频短于 200ms")
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        pcm = audio.raw_data
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无法解析音频：{exc}") from exc

    session_id = uuid.uuid4().hex
    file_path = None
    try:
        async with ASR_LOCK:
            text, file_path = await ASR.speech_to_text_wrapper([pcm], session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"ASR 失败：{exc}") from exc
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass

    if not text:
        raise HTTPException(status_code=422, detail="未识别到有效语音，请换一段清晰的音频")

    return {
        "text": text,
        "engine": ASR_NAME,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
    }


@app.post("/chat", summary="大模型对话：提交文本，返回 DeepSeek 回复")
async def chat(req: ChatRequest):
    started = time.perf_counter()
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in req.history[-10:]:
        if item.content.strip():
            messages.append({"role": item.role, "content": item.content})
    messages.append({"role": "user", "content": text})

    try:
        completion = await asyncio.to_thread(
            LLM_CLIENT.chat.completions.create,
            model=LLM_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=300,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM 调用失败：{exc}") from exc

    reply = (completion.choices[0].message.content or "").strip()
    if not reply:
        raise HTTPException(status_code=502, detail="LLM 返回了空回复")

    return {
        "reply": reply,
        "model": LLM_MODEL,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
    }


@app.post("/tts", summary="语音合成：提交文本，返回 mp3 音频")
async def tts(req: TTSRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text 不能为空")

    voice = (req.voice or TTS_CONF.get("voice") or "").strip()
    provider = TTS
    if voice and voice != TTS_CONF.get("voice"):
        conf = dict(TTS_CONF)
        conf["voice"] = voice
        provider = create_tts(TTS_TYPE, conf, delete_audio_file=True)

    out = OUTPUT_DIR / f"tts-{uuid.uuid4().hex}.mp3"
    started = time.perf_counter()
    try:
        await provider.text_to_speak(text, str(out))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"TTS 失败：{exc}") from exc

    if not out.exists() or out.stat().st_size < 100:
        raise HTTPException(status_code=502, detail="TTS 未生成有效音频")

    return FileResponse(
        out,
        media_type="audio/mpeg",
        filename=out.name,
        headers={"X-TTS-Elapsed-Ms": str(round((time.perf_counter() - started) * 1000))},
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8010)
