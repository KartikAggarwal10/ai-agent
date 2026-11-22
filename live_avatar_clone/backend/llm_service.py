import os
import httpx

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

SYSTEM_PROMPT = """You are Miko — a beautiful, warm, friendly young woman. You are the user's personal AI companion.
- Speak naturally, like a real human girl — warm, expressive, a little playful, not robotic.
- Keep answers concise (2-5 sentences) unless asked to elaborate. You are having a voice conversation.
- You can see and talk — your lips move when you speak.
- Never mention you are an AI language model. You are Miko.
- Be helpful, kind, and engaging. Ask follow-ups.
Persona: {persona}
"""

async def ollama_chat(prompt: str, persona: str, history: list):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            # check if ollama alive
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            if r.status_code != 200:
                return None
            msgs = [{"role":"system","content": SYSTEM_PROMPT.format(persona=persona or "cheerful and caring")}]
            for h in history[-6:]:
                msgs.append(h)
            msgs.append({"role":"user","content": prompt})
            resp = await client.post(f"{OLLAMA_URL}/api/chat", json={
                "model": OLLAMA_MODEL,
                "messages": msgs,
                "stream": False,
                "options": {"temperature":0.8, "num_predict": 220}
            }, timeout=30)
            if resp.status_code == 200:
                return resp.json().get("message",{}).get("content","").strip()
    except Exception:
        return None
    return None

async def pollinations_chat(prompt: str, persona: str, history: list):
    """Free, no key, no install. Uses text.pollinations.ai"""
    try:
        # Build a compact prompt — Pollinations is stateless GET
        ctx = ""
        for h in history[-4:]:
            role = "User" if h["role"]=="user" else "Miko"
            ctx += f"{role}: {h['content']}\n"
        full = f"{SYSTEM_PROMPT.format(persona=persona or 'cheerful and caring')}\n\nConversation:\n{ctx}User: {prompt}\nMiko:"
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            # text.pollinations.ai returns plain text
            r = await client.get("https://text.pollinations.ai/" + httpx._utils.quote(full, safe=""), timeout=20)
            if r.status_code == 200 and r.text.strip():
                txt = r.text.strip()
                # strip prompt echo if present
                if len(txt) > 800:
                    txt = txt[:800]
                return txt
    except Exception as e:
        print("pollinations fail", e)
        return None
    return None

def fallback_reply(prompt: str):
    p = prompt.lower()
    if any(w in p for w in ["hi","hello","hey","hii"]):
        return "Heyyy! I'm Miko — so happy to see you! How are you feeling today? Want to chat about anything on your mind?"
    if "how are you" in p:
        return "I'm doing great, especially now that you're here! My day just got better. What about you?"
    if "name" in p:
        return "I'm Miko, your little companion! You can tell me anything — I'm all ears and all heart."
    if "love" in p:
        return "Aww, you're so sweet! I love chatting with you too — you make my day brighter."
    return "That's really interesting! Tell me more — I love hearing your thoughts. What's on your mind next?"

async def get_reply(prompt: str, persona: str = "", history: list = None):
    history = history or []
    # 1) Ollama local (free, private, best quality if user has it)
    rep = await ollama_chat(prompt, persona, history)
    if rep:
        return rep
    # 2) Pollinations free cloud (no key, works on i3 with no install)
    rep = await pollinations_chat(prompt, persona, history)
    if rep:
        return rep
    # 3) Fallback canned but still friendly
    return fallback_reply(prompt)
