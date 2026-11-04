"""智能语音聊天助手 · 阶段一前端 + 阶段二语音链路。

运行方式：
    1) 先启动阶段二后端（8010/8000/8003）
    2) python app.py
    3) 打开 http://127.0.0.1:7860

说明：
    录音、对话历史、状态提示、语音回复都是真实组件；
    识别、回复、合成分别调用阶段二的 /asr、/chat、/tts。
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = BASE_DIR / ".runtime"
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 所有运行时临时文件都放在项目目录，避免写入 C 盘用户临时目录。
for _sub in ("gradio", "tmp"):
    (RUNTIME_DIR / _sub).mkdir(parents=True, exist_ok=True)
os.environ["GRADIO_TEMP_DIR"] = str(RUNTIME_DIR / "gradio")
os.environ["TMP"] = os.environ["TEMP"] = str(RUNTIME_DIR / "tmp")

import tempfile  # noqa: E402

tempfile.tempdir = str(RUNTIME_DIR / "tmp")
os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"

import requests  # noqa: E402
import gradio as gr  # noqa: E402  (必须在设置临时目录之后导入)

API_BASE = os.environ.get("STAGE2_API_BASE", "http://127.0.0.1:8010").rstrip("/")
CSS = (BASE_DIR / "styles.css").read_text(encoding="utf-8")

HEADER_HTML = """
<div class="app-header">
  <div class="app-title">
    <span class="app-logo" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
        <rect x="8.6" y="2.1" width="6.8" height="12.3" rx="3.4" fill="currentColor"/>
        <path d="M5.2 10.7v1a6.8 6.8 0 0 0 13.6 0v-1" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>
        <path d="M12 18.5v3.3M8.4 21.8h7.2" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>
      </svg>
    </span>
    <h1>智能语音聊天助手</h1>
  </div>
  <p class="app-subtitle">点击下方按钮开始录音，松开按钮后系统会自动处理</p>
</div>
"""

# Gradio 5.50 会在波形容器里额外生成一个带原生 controls 的 audio，造成两条播放器。
# 这里只隐藏这条重复的原生控件，保留组件自带的播放按钮。
HIDE_NATIVE_PLAYER_JS = """
() => {
  const hideNativePlayers = () => {
    document.querySelectorAll("#recorder #waveform > div, #reply-audio #waveform > div").forEach((host) => {
      if (!host.shadowRoot) return;
      host.shadowRoot.querySelectorAll("audio").forEach((audio) => {
        audio.controls = false;
        audio.style.display = "none";
      });
    });
  };
  hideNativePlayers();
  new MutationObserver(hideNativePlayers).observe(document.body, { childList: true, subtree: true });
}
"""

def render_status(text: str, state: str = "ready") -> str:
    """系统状态条；state 取 ready / busy / warn。"""
    return (
        f'<div class="status-line {state}">'
        f'<span class="status-dot" aria-hidden="true"></span>'
        f'<span class="status-text">{text}</span>'
        f"</div>"
    )


def _api_error(resp: requests.Response) -> str:
    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        detail = resp.text
    return f"HTTP {resp.status_code}: {str(detail)[:160]}"


def respond(audio_path: str | None, history: list[dict] | None):
    """录音结束后调用阶段二：ASR -> DeepSeek -> TTS。"""
    history = [dict(message) for message in (history or [])]
    if not audio_path:
        yield history, None, render_status("请先点击「录音」说点什么", "warn"), gr.update()
        return

    yield history, None, render_status("正在识别语音（阶段二 ASR）…", "busy"), gr.update()
    try:
        with open(audio_path, "rb") as audio_file:
            resp = requests.post(
                f"{API_BASE}/asr",
                files={
                    "file": (
                        Path(audio_path).name,
                        audio_file,
                        "application/octet-stream",
                    )
                },
                timeout=120,
            )
        if resp.status_code == 422:
            yield history, None, render_status("没有听清，请靠近麦克风再说一次", "warn"), gr.update()
            return
        resp.raise_for_status()
        transcript = (resp.json().get("text") or "").strip()
    except requests.RequestException as exc:
        yield history, None, render_status(f"ASR 请求失败：{str(exc)[:100]}", "warn"), gr.update()
        return
    except Exception as exc:
        yield history, None, render_status(f"ASR 返回异常：{str(exc)[:100]}", "warn"), gr.update()
        return

    if not transcript:
        yield history, None, render_status("没有听清，请再说一次", "warn"), gr.update()
        return

    prior = history
    history = history + [{"role": "user", "content": transcript}]
    yield history, None, render_status("正在生成回复（DeepSeek）…", "busy"), gr.update()

    try:
        resp = requests.post(
            f"{API_BASE}/chat",
            json={"text": transcript, "history": prior},
            timeout=120,
        )
        resp.raise_for_status()
        reply = (resp.json().get("reply") or "").strip()
    except requests.RequestException as exc:
        yield history, None, render_status(f"LLM 请求失败：{str(exc)[:100]}", "warn"), gr.update()
        return
    except Exception as exc:
        yield history, None, render_status(f"LLM 返回异常：{str(exc)[:100]}", "warn"), gr.update()
        return

    if not reply:
        yield history, None, render_status("LLM 没有返回内容", "warn"), gr.update()
        return

    history = history + [{"role": "assistant", "content": reply}]
    yield history, None, render_status("正在合成语音（阶段二 TTS）…", "busy"), gr.update()

    try:
        resp = requests.post(f"{API_BASE}/tts", json={"text": reply}, timeout=120)
        resp.raise_for_status()
        tts_path = OUTPUT_DIR / f"reply-{uuid.uuid4().hex}.mp3"
        tts_path.write_bytes(resp.content)
    except Exception as exc:
        yield history, None, render_status(f"文字回复完成，语音合成失败：{str(exc)[:100]}", "warn"), None
        return

    # 回复完成后清空本次录音，方便直接开始下一轮。
    yield history, str(tts_path), render_status("回复完成 · 已自动播放", "ready"), None


def build_demo() -> gr.Blocks:
    theme = gr.themes.Base(
        primary_hue=gr.themes.colors.indigo,
        neutral_hue=gr.themes.colors.slate,
        font=["Inter", "PingFang SC", "Microsoft YaHei UI", "Microsoft YaHei", "system-ui", "sans-serif"],
    )

    with gr.Blocks(title="智能语音聊天助手", theme=theme, css=CSS, analytics_enabled=False) as demo:
        gr.HTML(HEADER_HTML, elem_id="app-header", container=False)

        with gr.Row(elem_id="workspace"):
            with gr.Column(scale=7, elem_id="left-col"):
                chatbot = gr.Chatbot(
                    label="对话历史",
                    elem_id="history",
                    type="messages",
                    height=400,
                    show_label=True,
                    show_copy_button=False,
                    show_share_button=False,
                    bubble_full_width=False,
                    placeholder=None,
                    sanitize_html=False,
                )
                status = gr.HTML(
                    value=render_status("准备就绪", "ready"),
                    label="系统状态",
                    elem_id="status-card",
                    container=True,
                    show_label=True,
                )

            with gr.Column(scale=4, elem_id="right-col"):
                audio_input = gr.Audio(
                    label="点击录音",
                    elem_id="recorder",
                    sources=["microphone"],
                    type="filepath",
                    interactive=True,
                    show_download_button=False,
                    show_share_button=False,
                    editable=False,
                    waveform_options=gr.WaveformOptions(
                        waveform_color="#cfd3ea",
                        waveform_progress_color="#5b5bd6",
                        show_recording_waveform=True,
                    ),
                )
                reply_audio = gr.Audio(
                    label="语音回复",
                    elem_id="reply-audio",
                    interactive=False,
                    autoplay=True,
                    show_download_button=False,
                    show_share_button=False,
                    waveform_options=gr.WaveformOptions(
                        waveform_color="#cfd3ea",
                        waveform_progress_color="#5b5bd6",
                        show_controls=True,
                    ),
                )

        # 录音开始 / 结束驱动状态提示与一次完整的演示对话。
        audio_input.start_recording(
            fn=lambda: render_status("正在录音…再次点击「停止」结束", "busy"),
            outputs=[status],
            show_progress="hidden",
        )
        audio_input.stop_recording(
            fn=respond,
            inputs=[audio_input, chatbot],
            outputs=[chatbot, reply_audio, status, audio_input],
            show_progress="hidden",
        )
        chatbot.clear(
            fn=lambda: (None, render_status("准备就绪", "ready")),
            outputs=[reply_audio, status],
            show_progress="hidden",
        )

        gr.HTML(
            '<div class="app-footnote">阶段一前端 · 阶段二真实链路：ASR / DeepSeek / TTS</div>',
            elem_id="app-footer",
            container=False,
        )

        demo.load(fn=None, js=HIDE_NATIVE_PLAYER_JS)

    return demo


demo = build_demo()


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1",
        server_port=7860,
        show_error=True,
        inbrowser=False,
        allowed_paths=[str(OUTPUT_DIR)],
    )

