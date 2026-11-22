# verify_providers.py
"""
Health-check for every LLM provider wired up in llm_config.py.

Usage (from the python_part folder):
    python verify_providers.py

For each provider it sends a 1-token "ping" chat request and prints OK / FAIL.
Keys left as placeholders in .env are reported as SKIP, not FAIL.
"""

import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_PLACEHOLDER_HINTS = ("your_", "here", "xxx", "paste_")


def _key_ok(v: str) -> bool:
    """Treat unset or template-looking values as 'not configured'."""
    return bool(v) and not any(h in v.lower() for h in _PLACEHOLDER_HINTS)


PROVIDERS = [
    # (label, env-var, base_url, model)
    ("Google AI Studio", "GOOGLE_AI_KEY",
     "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-2.0-flash"),
    ("DashScope", "DASHSCOPE_KEY",
     "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    ("NVIDIA NIM", "NVIDIA_KEY",
     "https://integrate.api.nvidia.com/v1", "meta/llama-3.1-70b-instruct"),
    ("Z.ai (text)", "ZAI_KEY",
     "https://api.z.ai/api/paas/v4/", os.getenv("ZAI_TEXT_MODEL", "glm-4.5-flash")),
    ("Z.ai (vision)", "ZAI_KEY",
     "https://api.z.ai/api/paas/v4/", os.getenv("ZAI_VISION_MODEL", "glm-4.6v-flash")),
    ("Token Harbor", "TOKENHARBOR_KEY",
     "https://tokenharbor.ai/v1", os.getenv("TOKENHARBOR_MODEL", "deepseek-v4.1-flash:free")),
]


def _check(label: str, env: str, base_url: str, model: str) -> str:
    key = os.getenv(env)
    if not _key_ok(key):
        return f"SKIP – {env} is unset/placeholder in .env"

    client = OpenAI(api_key=key, base_url=base_url, timeout=30, max_retries=0)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with the single word: pong"}],
            max_tokens=8,
        )
        text = (resp.choices[0].message.content or "").strip().replace("\n", " ")
        return f"OK – {model} replied: {text[:40]!r}"
    except Exception as e:
        msg = str(e).replace("\n", " ")[:150]

        # Helpful hint for Token Harbor: the free-model lineup rotates,
        # so surface the actual ids their key can see via GET /models.
        if env == "TOKENHARBOR_KEY":
            try:
                ids = [m.id for m in client.models.list().data]
                free = [i for i in ids if ":free" in i] or ids[:5]
                msg += f" | models visible to your key: {free[:10]}"
            except Exception:
                pass
        return f"FAIL – {model}: {msg}"


def main() -> None:
    print(f"{'Provider':<18} status")
    print("-" * 78)
    for label, env, base_url, model in PROVIDERS:
        print(f"{label:<18} {_check(label, env, base_url, model)}")

    print("-" * 78)
    print("Fallback chains from llm_config.py:")
    from llm_config import llm, vision_llm
    print(f"  {llm!r}")
    print(f"  {vision_llm!r}")


if __name__ == "__main__":
    main()