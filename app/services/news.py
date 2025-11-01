import requests
import feedparser
from typing import List, Optional
from app.core.config import Config


def _via_rss2json(limit: int) -> Optional[List[str]]:
    try:
        r = requests.get(Config.RSS2JSON_API_URL, params={"rss_url": Config.COINDESK_RSS}, timeout=6)
        r.raise_for_status()
        data = r.json()
        items = data.get("items") or data.get("articles") or []
        if not items:
            return None
        return [it.get("title", "").strip() for it in items[:limit] if it.get("title")]
    except Exception:
        return None

def _via_feedparser(limit: int) -> Optional[List[str]]:
    try:
        # fetch HTML ourselves to survive 308 redirects
        rr = requests.get(Config.COINDESK_RSS, timeout=6, allow_redirects=True)
        rr.raise_for_status()
        feed = feedparser.parse(rr.text)
        entries = getattr(feed, "entries", []) or []
        if not entries:
            return None
        return [e.title for e in entries[:limit] if getattr(e, "title", None)]
    except Exception:
        return None

def get_headlines(limit: int = 5) -> Optional[List[str]]:
    return _via_rss2json(limit) or _via_feedparser(limit)
