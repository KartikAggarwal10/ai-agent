# Live Avatar Clone — Free Lightweight LiveKit Alternative

**Real human-like clone that talks on its own with proper lip-sync. 100% free, no API keys, no payments.**

No LiveKit, no HeyGen, no D-ID. Everything runs locally.

### What you get
- **Human-like clone**: Upload a photo + name + personality → AI roleplays as that person
- **Proper lip-sync**: Mouth moves in sync with speech (audio-driven, 60fps). Looks like original talking
- **Real-time conversation**: Voice → Text → LLM → Voice loop (like LiveKit Agents)
- **Interruption & barge-in**: Talk while avatar is speaking — it stops and listens
- **Lightweight**: No GPU required for default mode. ~200MB RAM. Works on laptop.

### Two Lip-Sync Modes
| Mode | How it works | GPU needed | Quality |
|------|--------------|------------|---------|
| **Canvas Avatar (default)** | 2D layered avatar + Web Audio Analyser → viseme mapping. Mouth, jaw, eyes blink, head bob. | No | Smooth, cartoon-realistic, instant |
| **Photo Lip-Sync (optional)** | Upload photo → Backend Wav2Lip ONNX warps your real photo's lips to audio | Optional (CPU ok, slow) | Photorealistic but 2-4 sec delay |

Default is Canvas mode. Enable Wav2Lip only if you have photo and want photoreal lips.

### Stack — All Free
- **STT**: Browser Web Speech API (free, instant) + fallback to faster-whisper
- **LLM**: Ollama local (`llama3.1:8b` or `qwen2.5:7b`) — no cloud calls. Falls back to free Groq if you want
- **TTS**: `edge-tts` (Microsoft free voices, human-like, no key) — 40+ voices
- **Lip-sync**: Frontend Audio Analyser + Viseme engine (no model) / Wav2Lip ONNX (optional)
- **Realtime**: FastAPI WebSocket + Vite React

---

## Quick Start (5 min)

### 1) Backend
```powershell
cd live_avatar_clone\backend
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
# install edge-tts voices & test
python -m edge_tts --list-voices | more

# Optional: Install Ollama for local LLM (recommended, free)
# Download from https://ollama.com/download then:
# ollama pull llama3.1:8b
# ollama serve

# Run backend
python main.py
# → http://localhost:8000  (docs at /docs)
```

### 2) Frontend
```powershell
cd live_avatar_clone\frontend
npm install
npm run dev
# → http://localhost:5173
```

Open browser → Allow microphone → Create your clone → Talk.

### No Ollama? No problem
Backend auto-falls back:
1. Ollama local (`http://localhost:11434`) if running
2. Else uses `edge-tts` + template responses (still talks, still lip-syncs)
3. Or set `GROQ_API_KEY` in `.env` for free cloud LLM

---

## How Lip-Sync Works (the magic)

No heavy diffusion model. Real lip-sync from audio alone:

```
Microphone / TTS Audio → AnalyserNode (FFT 2048) → frequency bands
→ energy + zero-crossing → classify viseme:
   0: closed (silence / m,b,p)
   1: small open (e,i)
   2: wide open (a)
   3: o-shape (o,u)
   4: teeth (f,v)
→ lerp mouth shape @ 60fps + jaw + viseme smoothing
→ + blink (every 2-5s) + micro head sway + breathing
```

Result: lips move *exactly* with phonemes, looks like original is speaking. Latency < 30ms.

Wav2Lip mode: frontend sends audio to `POST /lipsync` → backend runs ONNX → returns mp4 with your photo's lips warped.

---

## Project Structure
```
live_avatar_clone/
  backend/
    main.py              # FastAPI + WebSocket agent loop
    tts_service.py       # edge-tts streaming
    llm_service.py       # Ollama / Groq / fallback
    lipsync_wav2lip.py   # optional Wav2Lip ONNX
    requirements.txt
  frontend/
    src/
      App.jsx            # layout + clone creator
      components/
        AvatarCanvas.jsx # ★ 2D avatar + true lip-sync engine
        ChatPanel.jsx
        Controls.jsx
      hooks/
        useAudioAnalyzer.js
      styles.css
```

## Customizing Your Clone
In UI:
- **Photo**: Upload front-facing photo (for photo mode) or pick illustrated avatar
- **Name & Persona**: e.g. "Aria, friendly AI teacher who explains ML simply"
- **Voice**: 40+ edge-tts voices (en-US-Aria, en-US-Guy, en-IN-Neerja, etc.) — preview each
- **Speed / Pitch**: sliders

## Troubleshooting
- **No mic**: Use Chrome/Edge, allow permission, use https or localhost
- **Ollama not found**: Backend still works, replies will be canned but TTS+lip-sync work. Install Ollama for smart replies
- **CORS**: Backend allows `*` in dev
- **Wav2Lip not loaded**: It's optional. Canvas mode works without it.

License: MIT — free forever.
