"""Redis client for the application."""

import redis
from app.core.config import Config
from app.core.logger import logger

REDIS_HOST = Config.REDIS_HOST
REDIS_PORT = Config.REDIS_PORT
REDIS_DB = Config.REDIS_DB
REDIS_PASSWORD = Config.REDIS_PASSWORD
REDIS_URL = Config.REDIS_URL

redis_client = None

if REDIS_URL:
    try:
        redis_client = redis.from_url(REDIS_URL, decode_responses=True)
        redis_client.ping()
        logger.info("✅ Connected to Redis via URL: %s", REDIS_URL)
    except Exception as e:
        logger.warning("⚠️  Redis URL connection failed: %s", e)
        redis_client = None

if not redis_client:
    try:
        redis_client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            password=REDIS_PASSWORD or None,
            decode_responses=True,
        )
        redis_client.ping()
        logger.info(
            "✅ Connected to Redis via host=%s port=%s db=%s (password=%s)",
            REDIS_HOST,
            REDIS_PORT,
            REDIS_DB,
            "yes" if REDIS_PASSWORD else "no",
        )
    except Exception as e:
        logger.error("❌ Redis host/port connection failed: %s", e)
        redis_client = None
