from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import json, asyncio, os
from dotenv import load_dotenv
load_dotenv()

from llm_service import get_reply
from tts_service import tts_to_b64

app = FastAPI(title="Miko — Free Girl Avatar (i3, no GPU, no money)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"]
)

VOICES = [
    {"id":"en-US-AriaNeural","label":"Aria — warm girl (US)","gender":"female"},
    {"id":"en-US-JennyNeural","label":"Jenny — sweet girl (US)","gender":"female"},
    {"id":"en-US-AnaNeural","label":"Ana — cute girl (US)","gender":"female"},
    {"id":"en-IN-NeerjaNeural","label":"Neerja — Indian girl","gender":"female"},
    {"id":"en-GB-SoniaNeural","label":"Sonia — British girl","gender":"female"},
    {"id":"en-AU-NatashaNeural","label":"Natasha — Aussie girl","gender":"female"},
]

@app.get("/")
def root():
    return {"ok":True, "name":"Miko avatar backend", "voices": VOICES}

@app.get("/api/voices")
def voices():
    return {"voices": VOICES}

@app.post("/api/chat")
async def chat(payload: dict):
    text = (payload.get("text") or "").strip()
    persona = payload.get("persona","")
    voice = payload.get("voice","en-US-AriaNeural")
    history = payload.get("history",[])
    if not text:
        return JSONResponse({"error":"no text"}, status_code=400)
    reply = await get_reply(text, persona, history)
    b64, mime = await tts_to_b64(reply, voice)
    return {"reply": reply, "audio_b64": b64, "mime": mime}

# ----- WebSocket live loop -----
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    history = []
    persona = ""
    voice = "en-US-AriaNeural"
    # greet
    await ws.send_text(json.dumps({"type":"ready","voices":VOICES}))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except:
                continue
            t = msg.get("type")
            if t == "config":
                persona = msg.get("persona","")
                voice = msg.get("voice","en-US-AriaNeural")
                await ws.send_text(json.dumps({"type":"config_ok"}))
                continue
            if t == "user_text":
                text = (msg.get("text") or "").strip()
                if not text:
                    continue
                history.append({"role":"user","content":text})
                # notify avatar is thinking
                await ws.send_text(json.dumps({"type":"thinking"}))
                reply = await get_reply(text, persona, history)
                history.append({"role":"assistant","content":reply})
                if len(history) > 12:
                    history = history[-12:]
                # TTS
                b64, mime = await tts_to_b64(reply, voice)
                await ws.send_text(json.dumps({
                    "type":"reply",
                    "text": reply,
                    "audio_b64": b64,
                    "mime": mime
                }))
            elif t == "ping":
                await ws.send_text(json.dumps({"type":"pong"}))
    except WebSocketDisconnect:
        pass

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
