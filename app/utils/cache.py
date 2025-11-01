import time
import json
from typing import Any, Optional

from .redis_client import redis_client


# very small in-memory TTL cache as fallback
_mem: dict[str, tuple[float, str]] = {}

def _mem_get(key: str) -> Optional[str]:
    if key not in _mem:
        return None
    exp, val = _mem[key]
    if exp and exp < time.time():
        _mem.pop(key, None)
        return None
    return val

def _mem_set(key: str, value: str, ex: Optional[int]) -> None:
    _mem[key] = (time.time() + ex if ex else 0, value)

def get_json(key: str) -> Optional[Any]:
    if redis_client:
        try:
            raw = redis_client.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            pass
    raw = _mem_get(key)
    return json.loads(raw) if raw else None

def set_json(key: str, value: Any, ex: Optional[int] = None) -> None:
    raw = json.dumps(value)
    if redis_client:
        try:
            redis_client.set(key, raw, ex=ex)
            return
        except Exception:
            pass
    _mem_set(key, raw, ex)
