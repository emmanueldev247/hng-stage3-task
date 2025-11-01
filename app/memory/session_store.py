import json
from typing import List, Dict
from app.utils.redis_client import redis_client as _redis
from app.core.config import Config
from app.core.logger import logger

class SessionStore:
    """Handles chat history storage and retrieval in Redis."""
    PREFIX = "history:"

    @classmethod
    def _key(cls, session_id: str) -> str:
        return f"{cls.PREFIX}{session_id}"

    @classmethod
    def append(cls, session_id: str, user_msg: str, assistant_msg: str) -> None:
        key = cls._key(session_id)
        if not _redis:
            logger.warning("[history] redis_client is None; skipping persistence")
            return
        try:
            turn = json.dumps({"user": user_msg, "assistant": assistant_msg}, ensure_ascii=False)
            _redis.rpush(key, turn)
            ttl_cfg = getattr(Config, "CHAT_HISTORY_TTL", None)
            try:
                ttl = int(ttl_cfg) if ttl_cfg is not None else None
            except Exception:
                ttl = None

            if ttl is None or ttl <= 0:
                _redis.persist(key)
            else:
                _redis.expire(key, ttl)
        except Exception as e:
            logger.exception("[history] append failed: %s", e)

    
    @classmethod
    def get_history(cls, session_id: str) -> List[Dict]:
        key = cls._key(session_id)
        if not _redis:
            logger.warning("[history] redis_client is None; get skipped")
            return []
        try:
            raw = _redis.lrange(key, 0, -1)
            return [json.loads(item) for item in raw] if raw else []
        except Exception as e:
            logger.exception("[history] get failed: %s", e)
            return []

    @classmethod
    def clear(cls, session_id: str) -> None:
        key = cls._key(session_id)
        try:
            _redis.delete(key)
        except Exception as e:
            logger.exception("[history] clear failed: %s", e)