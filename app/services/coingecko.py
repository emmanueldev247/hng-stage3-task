import requests
from typing import Any, Dict, List, Optional
from app.core.config import Config

BASE = Config.COINGECKO_API_URL
TO   = Config.COINGECKO_TIMEOUT

def get_price(coin_id: str, vs: str = "usd") -> Optional[float]:
    url = f"{BASE}/simple/price"
    r = requests.get(url, params={"ids": coin_id, "vs_currencies": vs}, timeout=TO)
    r.raise_for_status()
    return r.json().get(coin_id, {}).get(vs)

def get_markets(limit: int = 10) -> List[Dict[str, Any]]:
    url = f"{BASE}/coins/markets"
    r = requests.get(url, params={
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": limit,
        "page": 1,
        "sparkline": False,
        "price_change_percentage": "24h"
    }, timeout=TO)
    r.raise_for_status()
    return r.json()

def get_trending() -> List[Dict[str, Any]]:
    url = f"{BASE}/search/trending"
    r = requests.get(url, timeout=TO)
    r.raise_for_status()
    coins = r.json().get("coins", [])
    # normalize a minimal shape
    out = []
    for c in coins:
        item = c.get("item", {})
        out.append({
            "id": item.get("id"),
            "name": item.get("name"),
            "symbol": item.get("symbol"),
            "score": item.get("score"),
            "market_cap_rank": item.get("market_cap_rank")
        })
    return out

def get_coin_detail(coin_id: str) -> Dict[str, Any] | None:
    url = f"{BASE}/coins/{coin_id}"
    r = requests.get(url, params={"localization":"false","tickers":"false","community_data":"false","developer_data":"false","sparkline":"false"}, timeout=TO)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    data = r.json()
    md = data.get("market_data", {})
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "symbol": data.get("symbol", "").upper(),
        "price": (md.get("current_price") or {}).get("usd"),
        "market_cap": (md.get("market_cap") or {}).get("usd"),
        "volume_24h": (md.get("total_volume") or {}).get("usd"),
        "change_24h": md.get("price_change_percentage_24h")
    }
