import requests
import threading

from typing import Dict, Optional

from app.core.config import Config
from app.core.logger import logger
from app.utils.cache import get_json, set_json


_CACHE_KEY = "coin_aliases:v1"
_LOCK = threading.Lock()
_DEFAULT_TTL = getattr(Config, "ALIAS_TTL", 3600)

def _fetch_aliases() -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    try:
        r = requests.get(
            f"{Config.COINGECKO_API_URL}/coins/markets",
            params={"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250, "page": 1},
            timeout=getattr(Config, "COINGECKO_TIMEOUT", 10),
        )
        r.raise_for_status()
        for c in r.json() or []:
            cid = (c.get("id") or "").lower()
            sym = (c.get("symbol") or "").lower()
            nm  = (c.get("name") or "").lower()
            if cid:
                if sym: aliases.setdefault(sym, cid)
                if nm:  aliases.setdefault(nm,  cid)

        r2 = requests.get(f"{Config.COINGECKO_API_URL}/coins/list", timeout=getattr(Config, "COINGECKO_TIMEOUT", 10))
        r2.raise_for_status()
        for c in r2.json() or []:
            cid = (c.get("id") or "").lower()
            sym = (c.get("symbol") or "").lower()
            nm  = (c.get("name") or "").lower()
            if cid:
                if sym: aliases.setdefault(sym, cid)
                if nm:  aliases.setdefault(nm,  cid)

        logger.info("[aliases] built %d entries", len(aliases))
    except Exception:
        logger.exception("[aliases] fetch failed")
    return aliases

def get_aliases() -> Dict[str, str]:
    cached = get_json(_CACHE_KEY)
    if isinstance(cached, dict) and cached:
        return cached

    with _LOCK:
        cached = get_json(_CACHE_KEY)
        if isinstance(cached, dict) and cached:
            return cached
        aliases = _fetch_aliases()
        if aliases:
            set_json(_CACHE_KEY, aliases, ex=_DEFAULT_TTL)
        return aliases or {}

def resolve_coin_id(maybe: str) -> Optional[str]:
    """
    Accept 'btc', 'bitcoin', 'Bitcoin', 'ETH', etc → 'bitcoin', 'ethereum', …
    Returns None if unknown.
    """
    if not maybe:
        return None
    key = maybe.strip().lower()
    aliases = get_aliases()
    cid = aliases.get(key)
    if cid:
        return cid
    key2 = "".join(ch for ch in key if ch.isalnum())
    if key2 != key:
        return aliases.get(key2)
    return None
