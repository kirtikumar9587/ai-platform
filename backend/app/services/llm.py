"""Gemini wrapper: structured output, retries, rate-limit handling, model fallback, token tracking, caching."""
import dataclasses
import hashlib
import logging
import random
import re
import time
from dataclasses import dataclass, field
from cachetools import TTLCache
from pydantic import BaseModel
from app.config import settings
from app.db import SessionLocal
from app.models import LLMLog

logger = logging.getLogger("app.llm")

RETRYABLE_CODES = {0, 408, 429, 500, 502, 503, 504}  # 0 = network / unknown error
_cache: TTLCache = TTLCache(maxsize=256, ttl=3600)
_client = None


class LLMError(Exception):
    """Raised when every model/attempt failed."""


class LLMCallError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class LLMResult:
    text: str
    parsed: object
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    fallback_used: bool
    cached: bool = False


@dataclass
class Usage:
    """Accumulates token / latency / model info across several LLM calls in one request."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    latency_ms: int = 0
    fallback_used: bool = False
    cached_calls: int = 0
    models: set = field(default_factory=set)

    def add(self, r: LLMResult) -> None:
        self.prompt_tokens += r.prompt_tokens
        self.completion_tokens += r.completion_tokens
        self.calls += 1
        self.latency_ms += r.latency_ms
        self.fallback_used = self.fallback_used or r.fallback_used
        self.cached_calls += 1 if r.cached else 0
        self.models.add(r.model)

    def as_dict(self) -> dict:
        return {"prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                "total_tokens": self.prompt_tokens + self.completion_tokens, "llm_calls": self.calls,
                "fallback_used": self.fallback_used, "cached_calls": self.cached_calls,
                "models": sorted(self.models)}


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def _call(model: str, prompt: str, system: str, schema, temperature: float) -> tuple[str, int, int]:
    """One raw Gemini call. Translates SDK errors into LLMCallError(code)."""
    from google.genai import types, errors
    cfg = {"temperature": temperature}
    if system:
        cfg["system_instruction"] = system
    if schema is not None:
        cfg["response_mime_type"] = "application/json"
        cfg["response_schema"] = schema
    try:
        resp = _get_client().models.generate_content(model=model, contents=prompt,
                                                     config=types.GenerateContentConfig(**cfg))
    except errors.APIError as e:
        raise LLMCallError(getattr(e, "code", 0) or 0, str(e)) from e
    except Exception as e:
        raise LLMCallError(0, str(e)) from e
    um = resp.usage_metadata
    pt = (getattr(um, "prompt_token_count", 0) or 0) if um else 0
    ct = ((getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0)) if um else 0
    text = resp.text or ""
    if not text.strip():
        raise LLMCallError(0, "Empty response from model")
    return text, pt, ct


def _parse(schema, text: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return schema.model_validate_json(t)  # response validation: raises if shape is wrong


def _log(user_id, kind, model, pt, ct, latency, success, cached=False, fallback=False, error=None):
    try:
        db = SessionLocal()
        db.add(LLMLog(user_id=user_id, kind=kind, model=model, prompt_tokens=pt, completion_tokens=ct,
                      latency_ms=latency, success=success, cached=cached, fallback_used=fallback,
                      error=(error or None) and error[:500]))
        db.commit()
        db.close()
    except Exception:
        logger.exception("Could not write LLM log")


def generate(prompt: str, *, system: str = "", schema: type[BaseModel] | None = None, kind: str = "chat",
             user_id: int | None = None, temperature: float = 0.2, cache: bool = False,
             usage: Usage | None = None) -> LLMResult:
    key = None
    if cache:
        key = hashlib.sha256(f"{system}|{prompt}|{schema.__name__ if schema else ''}".encode()).hexdigest()
        hit = _cache.get(key)
        if hit is not None:
            res = dataclasses.replace(hit, cached=True, latency_ms=0, prompt_tokens=0, completion_tokens=0)
            _log(user_id, kind, hit.model, 0, 0, 0, True, cached=True, fallback=hit.fallback_used)
            if usage:
                usage.add(res)
            return res

    models = [settings.PRIMARY_MODEL]
    if settings.FALLBACK_MODEL and settings.FALLBACK_MODEL != settings.PRIMARY_MODEL:
        models.append(settings.FALLBACK_MODEL)

    seen: list[str] = []
    for idx, model in enumerate(models):
        is_fallback = idx > 0
        for attempt in range(settings.LLM_MAX_RETRIES + 1):
            t0 = time.perf_counter()
            try:
                text, pt, ct = _call(model, prompt, system, schema, temperature)
                parsed = _parse(schema, text) if schema is not None else None
                lat = int((time.perf_counter() - t0) * 1000)
                _log(user_id, kind, model, pt, ct, lat, True, fallback=is_fallback)
                res = LLMResult(text, parsed, model, pt, ct, lat, is_fallback)
                if key:
                    _cache[key] = res
                if usage:
                    usage.add(res)
                if is_fallback:
                    logger.warning("Fallback model %s used for %s", model, kind)
                return res
            except ValueError as e:  # invalid / non-conforming structured output
                lat = int((time.perf_counter() - t0) * 1000)
                _log(user_id, kind, model, 0, 0, lat, False, fallback=is_fallback, error=f"invalid output: {e}")
                seen.append(f"{model}: invalid structured output")
                if attempt >= 1:
                    break
            except LLMCallError as e:
                lat = int((time.perf_counter() - t0) * 1000)
                _log(user_id, kind, model, 0, 0, lat, False, fallback=is_fallback, error=f"{e.code}: {e}")
                seen.append(f"{model}: {e.code} {str(e)[:120]}")
                if e.code in RETRYABLE_CODES and attempt < settings.LLM_MAX_RETRIES:
                    time.sleep(min(2 ** attempt + random.random(), 8))  # exponential backoff
                    continue
                break  # non-retryable (bad key / bad model name) or retries exhausted -> next model
    raise LLMError("All models failed. " + " | ".join(seen[-4:]))
