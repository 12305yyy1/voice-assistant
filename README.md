# 智能语音聊天助手 · 阶段一 + 阶段二

一个本地的完整语音助手项目：

- **frontend/**：Gradio 可视化界面（录音、对话历史、状态、语音回复）。
- **backend/**：`xiaozhi-esp32-server`（SherpaASR、DeepSeek、EdgeTTS、OTA/WebSocket）。
- **frontend 已接入 backend 的真实接口**，不再使用演示数据。

```text
浏览器录音
  → 8010 /asr（SherpaASR）→ 文本
  → 8010 /chat（DeepSeek deepseek-flash）→ 回复
  → 8010 /tts（EdgeTTS）→ MP3
  → 7860 界面显示气泡并自动播放
```

---

## 目录

```text
F:\PBL\voice-assistant\
├─ .venv\                    共享 Python 3.11 虚拟环境（前后端共用）
├─ frontend\                 阶段一：Gradio 前端
│  ├─ app.py
│  ├─ styles.css
│  ├─ screenshots\
│  ├─ outputs\
│  └─ README.md
├─ backend\                  阶段二：原项目 + 验证接口
│  ├─ main\xiaozhi-server\   原项目服务，未修改源码
│  ├─ stage2\
│  │  ├─ asr_tts_api.py      8010 ASR/LLM/TTS
│  │  ├─ run_services.py / stop_services.py
│  │  ├─ verify_*.py
│  │  └─ 阶段二-接口与部署文档.md
│  └─ ...
├─ logs\                     一键启动时的前端日志
├─ README.md
├─ start_all.py              一键启动两个阶段
├─ requirements.txt          共享 venv 的完整依赖入口
└─ .gitignore
```

> `F:\PBL\.cache` 是 pip/临时缓存目录，放在项目外，不参与项目结构；运行时会自动使用。

---

## 关于 .venv：已经复用为一个

**可以复用，而且已经合并了。** 现在只有一个：

```text
F:\PBL\voice-assistant\.venv
```

- 由原阶段二的 venv 移动到根目录，再安装 Gradio 5.50 + requests；
- 原来的阶段一 venv（约 432 MB）已删除；
- 共享 venv 同时包含：
  - 前端：Gradio 5.50.0、requests 2.34.2
  - 后端：FastAPI 0.162.0、pydantic 2.12.3、starlette 0.52.1、Sherpa-ONNX、EdgeTTS、openai、mcp 等
- 已实测通过：前端 7860、8010 `/asr`、`/chat`、`/tts`、8003 OTA、8000 WebSocket、111 帧 TTS 音频。

**兼容性注意**：Gradio 5.50 要求 `pydantic<=2.12.3`，所以共享 venv 的 pydantic 是 2.12.3（不是 2.14）。如果以后升级后端依赖，注意不要把它升到与 Gradio 冲突的版本；升级前先跑一次启动与 `/chat` 验证。

---

## 启动

```powershell
cd F:\PBL\voice-assistant
python start_all.py
```

它会按顺序启动：

1. 阶段二：8010 ASR/LLM/TTS + 8000/8003
2. 阶段一：7860 Gradio

也可以手动分别启动：

```powershell
cd F:\PBL\voice-assistant
.\.venv\Scripts\python.exe .\backend\stage2\run_services.py
.\.venv\Scripts\python.exe .\frontend\app.py
```

### 访问地址

| 地址 | 用途 |
| --- | --- |
| <http://127.0.0.1:7860> | 前端聊天界面：真实录音 → ASR → DeepSeek → TTS |
| <http://127.0.0.1:8010/docs> | 后端 Swagger：/asr /chat /tts |
| <http://127.0.0.1:8010/health> | 健康检查（含 llm_model） |
| `http://127.0.0.1:8003/xiaozhi/ota/` | OTA 接口（不是网页） |
| `ws://127.0.0.1:8000/xiaozhi/v1/` | WebSocket 服务（不是网页） |

局域网设备把 `127.0.0.1` 换成 `192.168.0.110`；前端 7860 默认只绑定 `127.0.0.1`。

---

## 已验证

- ASR：中文 WAV → 文本。
- LLM：DeepSeek `deepseek-flash` → 中文回复。
- TTS：EdgeTTS → MP3。
- 前端 Gradio `/respond` → 8010 全链路 → 对话气泡 + 音频。
- 原项目 OTA 200；WebSocket `hello` 返回 `welcome`，`listen.detect` 文本输入 → LLM → TTS 音频 111 帧 / 6.66 秒。

阶段一集成记录：[frontend/outputs/integration_test.json](frontend/outputs/integration_test.json)  
后端接口文档：[backend/stage2/阶段二-接口与部署文档.md](backend/stage2/阶段二-接口与部署文档.md)

---

## 依赖

共享 venv 的入口：

```powershell
cd F:\PBL\voice-assistant
.\.venv\Scripts\python.exe -m pip install -r requirements.txt --cache-dir F:\PBL\.cache\pip
```

`requirements.txt` 会合并：

- `frontend/requirements.txt`：Gradio 5.50、requests
- `backend/stage2/requirements-core.txt`：ASR/LLM/TTS 最小依赖
- `mcp`、`bs4`、`cnlunar`、`markitdown`：原项目插件依赖

**没有安装** PyTorch / FunASR（当前 ASR 使用项目支持的 SherpaASR）。`opus.dll` 位于 `backend/stage2/bin`，由启动脚本加入 PATH。

---

## 限制

- A3 服务器未部署：没有 A3 地址/SSH 凭据，当前是本机/局域网。
- 8000 的 Opus 音频流入设备协议未联调；前端走 HTTP 全链路。
- 8010/8000/8003 无鉴权、无 TLS，只适合本机/局域网。
- ASR 使用 SherpaASR，精度不如完整 FunASR/云端服务。
- DeepSeek Key 只在本机 `backend/main/xiaozhi-server/data/.config.yaml`，不写入文档/日志；它已在本次对话中出现过，如对话会共享建议轮换。
- 前端截图是早期布局演示内容，布局未变，当前对话内容来自真实后端。

上游项目：[xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server)  
接口文档：[backend/stage2/阶段二-接口与部署文档.md](backend/stage2/阶段二-接口与部署文档.md)
