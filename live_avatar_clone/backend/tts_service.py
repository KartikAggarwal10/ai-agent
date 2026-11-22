import asyncio
import base64
import io
import re

# We synthesize via edge-tts if available, else fallback to no audio
# Frontend will handle TTS via Web Speech API if backend TTS missing

async def synthesize_edge(text: str, voice: str = "en-US-AriaNeural") -> bytes | None:
    try:
        import edge_tts
        # clean text for TTS
        clean = re.sub(r"[\*_#`]", "", text)[:900]
        communicate = edge_tts.Communicate(clean, voice)
        buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buf.write(chunk["data"])
        data = buf.getvalue()
        return data if len(data) > 1000 else None
    except Exception as e:
        print("edge-tts fail", e)
        return None

def audio_bytes_to_b64(mp3: bytes) -> str:
    return base64.b64encode(mp3).decode("utf-8")

async def tts_to_b64(text: str, voice: str = "en-US-AriaNeural"):
    mp3 = await synthesize_edge(text, voice)
    if mp3 is None:
        return None, None
    # mp3 as base64 data url
    b64 = audio_bytes_to_b64(mp3)
    return b64, "audio/mpeg"
