"""
LLM semantic cache: same input → same output for repeatability.
Cache key: sha256(task_name + schema_version + prompt_version + normalized_input_json)
"""
import hashlib
import json
from typing import Any

from app.config import get_settings
from app.schemas.llm_semantic import SCHEMA_VERSION, PROMPT_VERSION

CACHE_PREFIX = "llm_semantic:"
TTL_SECONDS = 86400 * 30  # 30 days


def _normalize_input(obj: Any) -> str:
    """Stable JSON for hashing."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def cache_key(task_name: str, input_payload: Any) -> str:
    """sha256(task_name + schema_version + prompt_version + normalized_input_json)."""
    blob = f"{task_name}:{SCHEMA_VERSION}:{PROMPT_VERSION}:{_normalize_input(input_payload)}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def get_cached(task_name: str, input_payload: Any) -> dict | None:
    """Return cached output JSON (the stored 'output' dict) or None."""
    try:
        import redis
        settings = get_settings()
        r = redis.from_url(settings.redis_url)
        key = CACHE_PREFIX + cache_key(task_name, input_payload)
        raw = r.get(key)
        if raw is None:
            return None
        data = json.loads(raw)
        return data.get("output")
    except Exception:
        return None


def set_cached(task_name: str, input_payload: Any, output: dict, model: str) -> None:
    """Store output and metadata."""
    try:
        import redis
        settings = get_settings()
        r = redis.from_url(settings.redis_url)
        key = CACHE_PREFIX + cache_key(task_name, input_payload)
        value = json.dumps({
            "output": output,
            "model": model,
            "schema_version": SCHEMA_VERSION,
            "prompt_version": PROMPT_VERSION,
        }, ensure_ascii=False)
        r.setex(key, TTL_SECONDS, value)
    except Exception:
        pass
