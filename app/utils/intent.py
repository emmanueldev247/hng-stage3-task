import re

PRICE_RE = re.compile(r"(?:price|worth|value|rate)\s+of\s+([\w\-]+)", re.I)
TOP_RE   = re.compile(r"(?:top|best)\s+(\d{1,2})?\s*(?:coins|cryptos?)", re.I)
WORST_RE = re.compile(r"(?:worst|losers?)\s+(\d{1,2})?\s*(?:coins|cryptos?)", re.I)
TREND_RE = re.compile(r"(?:trending|hot)\s+(\d{1,2})?\s*(?:coins|cryptos?)", re.I)

def classify(text: str) -> str:
    t = text.lower()
    if "news" in t or "headline" in t:
        return "news"
    if PRICE_RE.search(t):
        return "price"
    if TOP_RE.search(t):
        return "top"
    if WORST_RE.search(t):
        return "worst"
    if TREND_RE.search(t):
        return "trending"
    if "detail" in t or "info" in t:
        return "detail"
    return "unknown"

def extract_coin_from_price(text: str) -> str | None:
    m = PRICE_RE.search(text)
    return m.group(1).lower() if m else None

def extract_count(text: str, default: int = 10) -> int:
    for rx in (TOP_RE, WORST_RE, TREND_RE):
        m = rx.search(text)
        if m:
            try:
                n = int(m.group(1)) if m.group(1) else default
                return max(1, min(50, n))
            except Exception:
                return default
    return default
