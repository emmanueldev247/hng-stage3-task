from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from typing import Any, Optional, Literal, List, Dict, Union

from app.core.config import Config
from app.core.logger import logger
from app.memory.session_store import SessionStore
from app.services import ai, coingecko as cg
from app.services.news import get_headlines
from app.utils.cache import get_json, set_json
from app.utils.intent import classify, extract_coin_from_price, extract_count
from app.utils.aliases import resolve_coin_id

class InvokeParams(BaseModel):
    text: str = Field(..., min_length=1)
    channel_id: Optional[str] = None
    user_id: Optional[str] = None
    org_id: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    temperature: Optional[float] = Field(0.7, ge=0.0, le=1.0)

class JSONRPCRequest(BaseModel):
    jsonrpc: Literal["2.0"]
    id: Any
    method: Literal["invoke", "help", "message/send"]
    params: Optional[Union[InvokeParams, Dict[str, Any]]] = None

class JSONRPCResult(BaseModel):
    type: Literal["message"] = "message"
    format: Literal["markdown"] = "markdown"
    content: str

class JSONRPCResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: Any
    result: Optional[JSONRPCResult] = None
    error: Optional[dict[str, Any]] = None

# ------------------------ Constants ------------------------
HELP_TEXT = (
    "**CryptoSage (FastAPI) — A2A Agent**\n\n"
    "I can answer crypto questions:\n"
    "- `price of <coin>`\n- `top 10 coins` / `worst 5 coins`\n- `trending coins`\n- `news`\n- `details on <coin>`\n\n"
    "_All data via free public APIs. This is not financial advice._"
)

TTL_SHORT = getattr(Config, "CACHE_TTL_SHORT", 300)  # fallback to 5 minutes

# ------------------------ Utils ------------------------
def rpc_error(rid: Any, code: int, message: str) -> JSONRPCResponse:
    return JSONRPCResponse(id=rid, error={"code": code, "message": message})

def as_result(rid: Any, content: str) -> JSONRPCResponse:
    return JSONRPCResponse(id=rid, result=JSONRPCResult(content=content))

def _get_session_id(req: Request, params: InvokeParams) -> str:
    def norm(s: Optional[str]) -> str:
        return (s or "").strip().lower().replace(" ", "_")[:128]

    def pick(d: Optional[dict], *keys: str) -> Optional[str]:
        if not d:
            return None
        lowered = {str(k).lower(): v for k, v in d.items()}
        for k in keys:
            v = lowered.get(k.lower())
            if isinstance(v, (str, int)):
                return str(v)
        return None

    user_id = norm(params.user_id)
    org_id  = norm(params.org_id)
    channel = norm(params.channel_id)

    meta = params.metadata or {}
    user_id = user_id or norm(pick(meta, "user_id", "userId", "user", "telex_user_id"))
    org_id  = org_id  or norm(pick(meta, "org_id", "orgId", "organization_id",
                                    "workspace_id", "team_id", "installation_id",
                                    "telex_org_id"))

    hdr = {k.lower(): v for k, v in req.headers.items()}
    user_id = user_id or norm(hdr.get("x-user-id") or hdr.get("x-telex-user-id"))
    org_id  = org_id  or norm(hdr.get("x-org-id")  or hdr.get("x-telex-org-id") or hdr.get("x-workspace-id"))

    if org_id and user_id:
        return f"{org_id}:{user_id}"

    sid_hdr  = norm(hdr.get("x-session-id"))
    return user_id or org_id or sid_hdr or channel or "anonymous"

def _append_history_safe(session_id: str, user_text: str, assistant_text: str) -> None:
    try:
        SessionStore.append(session_id, user_text, assistant_text)
    except Exception:
        logger.exception("[history] append failed (non-fatal)")

def _get_history_safe(session_id: str) -> List[Dict[str, str]]:
    try:
        return SessionStore.get_history(session_id)
    except Exception:
        logger.exception("[history] get failed (non-fatal)")
        return []

def _safe_set_json(key: str, value: Any, ex: int = TTL_SHORT) -> None:
    try:
        set_json(key, value, ex=ex)
    except Exception:
        logger.exception("[cache] set_json failed (non-fatal)")

# Fallback Markdown for lists (only used if AI composition fails)
def _md_top_list(title: str, coins: list[dict]) -> str:
    lines = []
    for i, c in enumerate(coins, 1):
        name = c.get("name") or c.get("id")
        sym  = (c.get("symbol") or "").upper()
        price = c.get("current_price")
        chg = c.get("price_change_percentage_24h")
        try:
            price_str = f"${float(price):,.2f}" if price is not None else "N/A"
        except Exception:
            price_str = "N/A"
        chg_str = f" ({float(chg):+,.2f}%)" if chg is not None else ""
        lines.append(f"{i}. **{name} ({sym})** — {price_str}{chg_str}")
    return f"**{title}**\n\n" + "\n".join(lines) + "\n\n_This is not financial advice._"


def _telex_extract_text_and_data(params_obj: Dict[str, Any]) -> tuple[Optional[str], List[str], str]:
    """
    Returns: (effective_text, inline_history_texts, debug_summary)
    - effective_text: parts[0].text if present, else message.text
    - inline_history_texts: last 20 messages (strings) from parts[1].data[*].text
    - debug_summary: short string for logs
    """
    eff_text = None
    inline_hist: List[str] = []
    dbg = []

    try:
        message = (params_obj or {}).get("message") or {}
        parts = message.get("parts") or []
        if isinstance(parts, list):
            if len(parts) > 0 and isinstance(parts[0], dict) and parts[0].get("kind") == "text":
                eff_text = (parts[0].get("text") or "").strip() or None
                dbg.append(f"parts[0].text_len={len(eff_text or '')}")
            if len(parts) > 1 and isinstance(parts[1], dict) and parts[1].get("kind") == "data":
                data_items = parts[1].get("data") or []
                for di in data_items:
                    if isinstance(di, dict) and di.get("kind") == "text":
                        t = (di.get("text") or "").strip()
                        if t:
                            inline_hist.append(t)
                dbg.append(f"data_text_count={len(inline_hist)}")

        if not eff_text:
            e = (message.get("text") or "").strip()
            if e:
                eff_text = e
                dbg.append("fallback:message.text")

    except Exception:
        logger.exception("[telex] extract failed")

    return eff_text, inline_hist[-20:], ";".join(dbg[:3])

def _handle_invoke(
    req: Request,
    rid: Any,
    user_text: str,
    params_like: InvokeParams,
    deployment_label: str,
    temperature: float,
    inline_history: Optional[List[str]] = None
) -> JSONRPCResponse:
    # Build session + history (merge inline history from Telex with stored)
    session_id = _get_session_id(req, params_like)
    stored_history = _get_history_safe(session_id)
    merged_history = stored_history
    if inline_history:
        merged_history = ([{"user": t, "assistant": ""} for t in inline_history] + stored_history)[-30:]

    # Classify
    try:
        intent = classify(user_text)
    except Exception:
        logger.exception("[intent] classify failed")
        intent = "unknown"

    logger.info("[invoke-core] sid=%s intent=%s text=%r", session_id, intent, user_text)

    # -------- PRICE --------
    if intent == "price":
        try:
            coin = extract_coin_from_price(user_text)
        except Exception:
            logger.exception("[price] extract failed")
            coin = None
        coin = resolve_coin_id(coin)
        if not coin:
            content = ai.compose_response(
                user_text="User asked for a price but provided no recognized coin. Ask them to specify it clearly.",
                history=merged_history,
                facts={"deployment_label": deployment_label},
                temperature=temperature,
            )
            _append_history_safe(session_id, user_text, content)
            return as_result(rid, content)

        cache_key = f"price:{coin}:usd"
        try:
            price = get_json(cache_key)
            if price is None:
                price = cg.get_price(coin, "usd")
                if price is None:
                    return rpc_error(rid, 404, "Coin not found.")
                _safe_set_json(cache_key, price, ex=300)
        except Exception:
            logger.exception("[price] fetch failed")
            content = ai.compose_response(
                user_text=f"User asked for price of {coin} but live price could not be fetched. Apologize briefly and ask to try again.",
                history=merged_history,
                facts={"deployment_label": deployment_label, "intent": "price", "coin": coin},
                temperature=temperature,
            )
            _append_history_safe(session_id, user_text, content)
            return as_result(rid, content)

        content = ai.compose_response(
            user_text=user_text,
            history=merged_history,
            facts={
                "deployment_label": deployment_label,
                "intent": "price",
                "coin": coin,
                "price_usd": float(price),
                "data_source": "CoinGecko",
            },
            temperature=temperature,
        )
        _append_history_safe(session_id, user_text, content)
        return as_result(rid, content)

    # -------- NEWS --------
    if intent == "news":
        try:
            cache_key = "news:coindesk:5"
            headlines = get_json(cache_key) or get_headlines(5)
            if headlines:
                _safe_set_json(cache_key, headlines, ex=TTL_SHORT)
                content = ai.compose_response(
                    user_text="Summarize these headlines for the user.",
                    history=merged_history,
                    facts={
                        "deployment_label": deployment_label,
                        "intent": "market_news",
                        "headlines": "; ".join(headlines),
                        "data_source": "CoinDesk RSS",
                    },
                    temperature=temperature,
                )
            else:
                content = "⚠️ Couldn’t fetch headlines right now."
        except Exception:
            logger.exception("[news] failed")
            content = "⚠️ Couldn’t fetch headlines right now."
        _append_history_safe(session_id, user_text, content)
        return as_result(rid, content)

    # -------- TOP / WORST --------
    if intent in ("top", "worst"):
        try:
            n = extract_count(user_text, default=10)
        except Exception:
            logger.exception("[markets] extract_count failed, defaulting to 10")
            n = 10

        try:
            cache_key = f"markets:top:{n}"
            markets = get_json(cache_key) or cg.get_markets(limit=n)
            _safe_set_json(cache_key, markets, ex=TTL_SHORT)
            if intent == "worst":
                markets = sorted(markets or [], key=lambda x: (x.get("price_change_percentage_24h") or 0))[:n]

            items = [
                {
                    "rank": i + 1,
                    "name": c.get("name"),
                    "symbol": (c.get("symbol") or "").upper(),
                    "price": c.get("current_price"),
                    "change_24h": c.get("price_change_percentage_24h"),
                    "market_cap": c.get("market_cap"),
                } for i, c in enumerate(markets or [])
            ]
            facts = {
                "deployment_label": deployment_label,
                "intent": "worst" if intent == "worst" else "top",
                "count": n, "list": items, "data_source": "CoinGecko",
            }
            content = ai.compose_response(
                user_text=user_text,
                history=merged_history,
                facts=facts,
                temperature=temperature,
            ) or _md_top_list(
                "Worst {} coins (24h)".format(n) if intent == "worst" else "Top {} coins by market cap".format(n),
                markets or [],
            )
        except Exception:
            logger.exception("[markets] failed, building fallback")
            title = "Worst {} coins (24h)".format(n) if intent == "worst" else "Top {} coins by market cap".format(n)
            content = _md_top_list(title, markets or [])
        _append_history_safe(session_id, user_text, content)
        return as_result(rid, content)

    # -------- TRENDING --------
    if intent == "trending":
        try:
            cache_key = "trending"
            trending = get_json(cache_key) or cg.get_trending()
            _safe_set_json(cache_key, trending, ex=TTL_SHORT)
            items = [
                {"rank": i+1, "name": c.get("name"), "symbol": (c.get("symbol") or "").upper(),
                 "market_cap_rank": c.get("market_cap_rank")} for i, c in enumerate(trending or [])
            ]
            facts = {
                "deployment_label": deployment_label, "intent": "trending",
                "list": items, "data_source": "CoinGecko",
            }
            content = ai.compose_response(user_text=user_text, history=merged_history, facts=facts, temperature=temperature)
        except Exception:
            logger.exception("[trending] failed")
            lines = [f"{i+1}. {c.get('name')} ({(c.get('symbol') or '').upper()})" for i, c in enumerate((trending or [])[:10])]
            content = "**Trending coins**\n\n" + "\n".join(lines) + "\n\n_This is not financial advice._"
        _append_history_safe(session_id, user_text, content)
        return as_result(rid, content)

    # -------- DETAIL --------
    if intent == "detail":
        maybe = (user_text.split()[-1] if isinstance(user_text, str) else "").lower()
        coin = resolve_coin_id(maybe) or maybe
        try:
            detail = cg.get_coin_detail(coin)
        except Exception:
            logger.exception("[detail] fetch failed")
            detail = None
        if not detail:
            return rpc_error(rid, 404, "Coin not found.")

        facts = {
            "deployment_label": deployment_label, "intent": "detail",
            "name": detail.get("name"), "symbol": detail.get("symbol"),
            "price": detail.get("price"), "market_cap": detail.get("market_cap"),
            "volume_24h": detail.get("volume_24h"), "change_24h": detail.get("change_24h"),
            "data_source": "CoinGecko",
        }
        content = ai.compose_response(user_text=user_text, history=merged_history, facts=facts, temperature=temperature)
        _append_history_safe(session_id, user_text, content)
        return as_result(rid, content)

    # -------- Unknown --------
    content = ai.fallback_answer(
        user_text=user_text,
        history=merged_history,
        facts={"deployment_label": deployment_label},
        temperature=temperature,
    )
    _append_history_safe(session_id, user_text, content)
    return as_result(rid, content)

# ------------------------ Router ------------------------

router = APIRouter()

@router.post("/invoke", tags=["a2a"], response_model=JSONRPCResponse)
def invoke(req: Request, body: JSONRPCRequest):
    try:
        if body.method == "help":
            return as_result(body.id, HELP_TEXT)

        # ---------- Telex A2A shape ----------
        if body.method == "message/send":
            if not isinstance(body.params, dict):
                return rpc_error(body.id, -32602, "Invalid params for message/send")

            # Log brief snapshot of Telex parts
            try:
                message = (body.params or {}).get("message") or {}
                parts = message.get("parts") or []
                logger.info("[telex] parts_count=%s kinds=%s",
                            len(parts), [p.get("kind") for p in parts[:3] if isinstance(p, dict)])
            except Exception:
                logger.exception("[telex] log snapshot failed")

            text, inline_hist, dbg = _telex_extract_text_and_data(body.params)
            if not text:
                return rpc_error(body.id, -32602, "No text provided in Telex message.")

            meta = (body.params or {}).get("metadata") or {}
            deployment_label = (
                req.headers.get("X-Deployment-Label")
                or meta.get("deployment_label")
                or Config.DEPLOYMENT_LABEL
            )
            temperature = 0.7

            params_like = InvokeParams(
                text=text,
                user_id=None,
                org_id=None,
                channel_id=None,
                metadata=meta,
                temperature=temperature
            )

            logger.info("[telex] dbg=%s", dbg)
            return _handle_invoke(
                req=req,
                rid=body.id,
                user_text=text,
                params_like=params_like,
                deployment_label=deployment_label,
                temperature=temperature,
                inline_history=inline_hist,
            )

        if body.method != "invoke":
            return rpc_error(body.id, -32601, "Method not found")
        if not isinstance(body.params, InvokeParams) or not body.params.text:
            return rpc_error(body.id, -32602, "Invalid params: 'text' is required")

    except Exception:
        logger.exception("[invoke] invalid request envelope")
        return rpc_error(body.id if body else None, -32603, "Internal error")

    params: InvokeParams = body.params
    user_text = params.text.strip()
    deployment_label = (
        (params.metadata or {}).get("deployment_label")
        or req.headers.get("X-Deployment-Label")
        or Config.DEPLOYMENT_LABEL
    )
    temperature = 0.7

    return _handle_invoke(
        req=req,
        rid=body.id,
        user_text=user_text,
        params_like=params,
        deployment_label=deployment_label,
        temperature=temperature,
        inline_history=None,
    )


@router.post("/help", tags=["a2a"], response_model=JSONRPCResponse)
def help_rpc(req: Optional[JSONRPCRequest] = None):
    rid = None if req is None else req.id
    return JSONRPCResponse(id=rid, result=JSONRPCResult(content=HELP_TEXT))
