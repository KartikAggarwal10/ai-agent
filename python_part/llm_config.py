# llm_config.py
"""
Multi-provider LLM configuration.

TEXT models (no vision):
  Primary  : Google AI Studio  – Gemini 2.0 Flash     (1,500 req/day free)
  Fallback1: Alibaba DashScope – Qwen3-235B-A22B       (1M free tokens, 90d)
  Fallback2: NVIDIA NIM        – Llama 3.1 70B         (1,000 free credits)
  Fallback3: Z.ai              – GLM-4.5-Flash         (genuinely free, no cap)
  Fallback4: Token Harbor      – DeepSeek V4.1 Flash   (free-plan / ":free" ids)

VISION models (image + text):
  Primary  : Google AI Studio  – Gemini 2.0 Flash   (same quota, supports vision)
  Fallback1: NVIDIA NIM        – Llama 3.2 90B Vision (~40 req/min)
  Fallback2: Z.ai              – GLM-4.6V-Flash     (genuinely free, no cap)
"""

import os
import time
import asyncio
import logging
from openai import RateLimitError
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

# .env.local holds real keys and takes priority over .env (template)
load_dotenv(".env.local")
load_dotenv()  # fallback template
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# API keys – put these in your .env file
# ---------------------------------------------------------------------------
GOOGLE_AI_KEY   = os.getenv("GOOGLE_AI_KEY")
DASHSCOPE_KEY   = os.getenv("DASHSCOPE_KEY")
NVIDIA_KEY      = os.getenv("NVIDIA_KEY")
ZAI_KEY         = os.getenv("ZAI_KEY")
TOKENHARBOR_KEY = os.getenv("TOKENHARBOR_KEY")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY")
# ---------------------------------------------------------------------------
# Raw LLM instances
# ---------------------------------------------------------------------------

# ── TEXT models ─────────────────────────────────────────────────────────────
_groq_text = ChatOpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
    model="openai/gpt-oss-120b",
    temperature=0,
    timeout=60,
    max_retries=1,
)
_google_text = ChatOpenAI(
    api_key=GOOGLE_AI_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    model="gemini-3.6-flash",
    temperature=0, 
    timeout=60,
    max_retries=1,
) if GOOGLE_AI_KEY else None

_dashscope_text = ChatOpenAI(
    api_key=DASHSCOPE_KEY,
    base_url="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    model="qwen-plus",          # stable paid-tier alias; free grant covers it
    timeout=60,
    max_retries=1,
) if DASHSCOPE_KEY else None

_nvidia_text = ChatOpenAI(
    api_key=NVIDIA_KEY,
    base_url="https://integrate.api.nvidia.com/v1",
    model="deepseek-ai/deepseek-v4.1-flash",   # llama-3.1-70b reached EOL 2026-08-26
    timeout=60,
    max_retries=1,
) if NVIDIA_KEY else None

_zai_text = ChatOpenAI(
    api_key=ZAI_KEY,
    base_url="https://api.z.ai/api/paas/v4/",
    model=os.getenv("ZAI_TEXT_MODEL", "glm-4.5-flash"),   # FREE model
    timeout=60,
    max_retries=1,
) if ZAI_KEY else None

# Same ZAI_KEY also tried against the mainland Zhipu endpoint, in case the key
# was issued by open.bigmodel.cn (international and mainland keys are not
# interchangeable). Whichever endpoint accepts the key serves; the other just
# fails and the chain moves on.
_bigmodel_text = ChatOpenAI(
    api_key=ZAI_KEY,
    base_url="https://open.bigmodel.cn/api/paas/v4/",
    model=os.getenv("BIGMODEL_TEXT_MODEL", "glm-4-flash"),  # free on bigmodel.cn
    timeout=60,
    max_retries=1,
) if ZAI_KEY else None

_tokenharbor_text = ChatOpenAI(
    api_key=TOKENHARBOR_KEY,
    base_url="https://tokenharbor.ai/v1",
    # ":free"-suffixed ids never charge the balance; override via .env
    model=os.getenv("TOKENHARBOR_MODEL", "deepseek-v4.1-flash:free"),
    timeout=60,
    max_retries=1,
) if TOKENHARBOR_KEY else None

# ── VISION models ────────────────────────────────────────────────────────────

_google_vision = ChatOpenAI(
    api_key=GOOGLE_AI_KEY,
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    model="gemini-3.6-flash",
) if GOOGLE_AI_KEY else None

_nvidia_vision = ChatOpenAI(
    api_key=NVIDIA_KEY,
    base_url="https://integrate.api.nvidia.com/v1",
    model="deepseek-ai/deepseek-v4.1-flash",
) if NVIDIA_KEY else None

_zai_vision = ChatOpenAI(
    api_key=ZAI_KEY,
    base_url="https://api.z.ai/api/paas/v4/",
    model=os.getenv("ZAI_VISION_MODEL", "glm-4.6v-flash"),  # FREE vision model
) if ZAI_KEY else None

_bigmodel_vision = ChatOpenAI(
    api_key=ZAI_KEY,
    base_url="https://open.bigmodel.cn/api/paas/v4/",
    model=os.getenv("BIGMODEL_VISION_MODEL", "glm-4v-flash"),  # free on bigmodel.cn
) if ZAI_KEY else None

# ---------------------------------------------------------------------------
# Fallback router
# ---------------------------------------------------------------------------

def _invoke_with_fallback(chain_of_models, messages, max_retries=2):
    """
    Try each model in order. On RateLimitError, wait briefly and try the next.
    Raises RuntimeError if all models are exhausted.
    """
    errors = []
    for model in chain_of_models:
        if model is None:
            continue
        for attempt in range(max_retries):
            try:
                return model.invoke(messages)
            except RateLimitError as e:
                wait = 2 ** attempt
                logger.warning(
                    f"[{model.model_name}] rate-limited (attempt {attempt+1}). "
                    f"Retrying in {wait}s…"
                )
                time.sleep(wait)
            except Exception as e:
                logger.warning(f"[{model.model_name}] failed: {e}")
                errors.append(str(e))
                break   # non-rate-limit error → try next provider immediately
        else:
            errors.append(f"{model.model_name}: rate-limited after {max_retries} retries")

    raise RuntimeError(
        "All LLM providers failed.\n" + "\n".join(errors)
    )


async def _ainvoke_with_fallback(chain_of_models, messages, max_retries=2):
    """Async version of _invoke_with_fallback."""
    import asyncio
    errors = []
    for model in chain_of_models:
        if model is None:
            continue
        for attempt in range(max_retries):
            try:
                return await model.ainvoke(messages)
            except RateLimitError:
                wait = 2 ** attempt
                logger.warning(
                    f"[{model.model_name}] rate-limited (attempt {attempt+1}). "
                    f"Retrying in {wait}s…"
                )
                await asyncio.sleep(wait)
            except Exception as e:
                logger.warning(f"[{model.model_name}] failed: {e}")
                errors.append(str(e))
                break
        else:
            errors.append(f"{model.model_name}: rate-limited after {max_retries} retries")

    raise RuntimeError(
        "All LLM providers failed.\n" + "\n".join(errors)
    )

# ---------------------------------------------------------------------------
# Public proxy objects – drop-in replacements for a single ChatOpenAI instance
# ---------------------------------------------------------------------------

_TEXT_CHAIN   = [_groq_text, _zai_text, _nvidia_text,_tokenharbor_text, _google_text, _dashscope_text,_bigmodel_text]
_VISION_CHAIN = [_google_vision, _nvidia_vision, _zai_vision, _bigmodel_vision]


class _MultiProviderLLM:
    """
    Wraps a chain of ChatOpenAI models.
    Exposes .invoke(), .ainvoke(), and .with_structured_output()
    so it can be used anywhere a plain ChatOpenAI is used.
    """

    def __init__(self, chain, name="MultiProviderLLM"):
        self._chain = chain
        self._name  = name

    # ── sync ────────────────────────────────────────────────────────────────
    def invoke(self, messages, **kwargs):
        return _invoke_with_fallback(self._chain, messages)

    # ── async ────────────────────────────────────────────────────────────────
    async def ainvoke(self, messages, **kwargs):
        return await _ainvoke_with_fallback(self._chain, messages)

    # ── structured output ────────────────────────────────────────────────────
    def with_structured_output(self, schema, **kwargs):
        """
        Returns a wrapper that tries each provider's structured-output chain.
        Falls back gracefully on rate-limit.
        """
        chains = []
        for m in self._chain:
            if m is not None:
                try:
                    chains.append(m.with_structured_output(schema, **kwargs))
                except Exception:
                    pass  # provider might not support the method → skip

        class _StructuredFallback:
            def invoke(self_, messages):
                errors = []
                for chain in chains:
                    for attempt in range(2):
                        try:
                            result = chain.invoke(messages)
                            if result is not None:
                                return result
                            errors.append(f"{chain}: returned None (no tool call / parse failure)")
                            break
                        except RateLimitError:
                            wait = 2 ** attempt
                            logger.warning(f"Structured output rate-limited. Retry in {wait}s…")
                            time.sleep(wait)
                        except Exception as e:
                            errors.append(str(e))
                            break
                raise RuntimeError("All structured-output providers failed.\n" + "\n".join(errors))

            async def ainvoke(self_, messages):
                errors = []
                for chain in chains:
                    for attempt in range(2):
                        try:
                            result = await chain.ainvoke(messages)
                            if result is not None:
                                return result
                            errors.append(f"{chain}: returned None (no tool call / parse failure)")
                            break
                        except RateLimitError:
                            wait = 2 ** attempt
                            logger.warning(f"Structured output rate-limited. Retry in {wait}s…")
                            await asyncio.sleep(wait)
                        except Exception as e:
                            errors.append(str(e))
                            break
                raise RuntimeError("All structured-output providers failed.\n" + "\n".join(errors))

        return _StructuredFallback()

    def __repr__(self):
        return f"<{self._name} providers={[m.model_name for m in self._chain if m]}>"


# The two objects your code imports
llm        = _MultiProviderLLM(_TEXT_CHAIN,   name="TextLLM")
vision_llm = _MultiProviderLLM(_VISION_CHAIN, name="VisionLLM")

