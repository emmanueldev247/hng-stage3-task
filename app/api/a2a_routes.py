import uuid

from fastapi import APIRouter, Body, Request
from pydantic import BaseModel, Field
from typing import Any, Optional, Literal, List, Dict

from app.a2a.jsonrpc import make_task_result, parse_jsonrpc
from app.a2a.telex import extract_text_and_data_master, extract_text_and_data_slave
from app.core.config import Config
from app.core.logger import logger
from app.memory.session_store import SessionStore
from app.services import ai, coingecko as cg
from app.services.news import get_headlines
from app.utils.aliases import resolve_coin_id
from app.utils.cache import get_json, set_json
from app.utils.intent import classify, extract_coin_from_price, extract_count


class InvokeParams(BaseModel):
    text: str = Field(..., min_length=1)
    channel_id: Optional[str] = None
    user_id: Optional[str] = None
    org_id: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None
    temperature: Optional[float] = Field(0.7, ge=0.0, le=1.0)

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

def _ai_error_result(
    rid: Any,
    session_id: str,
    user_text: str,
    merged_history: list[dict[str, str]],
    deployment_label: str,
    temperature: float,
    error: str,
    intent: str,
    requested_coin: Optional[str] = None,
    data_source: Optional[str] = None,
    extra: Optional[str] = None,
) -> JSONRPCResponse:
    facts = {
        "deployment_label": deployment_label,
        "intent": intent,
        "error": error,
        "requested_coin": requested_coin,
        "data_source": data_source,
        "extra": extra,
    }
    content = ai.compose_response(
        user_text=user_text,
        history=merged_history,
        facts=facts,
        temperature=temperature,
    )
    _append_history_safe(session_id, user_text, content)
    return as_result(rid, content)

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
                    return _ai_error_result(
                        rid, session_id, user_text, merged_history, deployment_label, temperature,
                        error="coin_not_found",
                        intent="price",
                        requested_coin=coin,
                        data_source="CoinGecko",
                        extra="System logic assumed the user wants to know the price of a coin, \
                            but the coin ID could not be resolved. [price fetch returned None]. \
                            This likely means the coin is unknown or invalid or misspelled or \
                            not supported or similar. The system logic could have assumed wrong so check the user text carefully.",
                    )
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
            return _ai_error_result(
                rid, session_id, user_text, merged_history, deployment_label, temperature,
                error="coin_not_found",
                intent="detail",
                requested_coin=coin,
                data_source="CoinGecko",
                extra="System logic assumed the user wants to know the detail of a coin, \
                    but the coin ID could not be resolved. [detail fetch returned None]. \
                    This likely means the coin is unknown or invalid or misspelled or \
                    not supported or similar. The system logic could have assumed wrong so check the user text carefully.",
            )

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

@router.post("/invoke", tags=["a2a"])
def invoke(req: Request, body: Any = Body(default_factory=dict)):
    logger.info("[invoke] Agent called with request body=%r", body)
    try:
        rid, method, params = parse_jsonrpc(body)
        if method == "help":
            content = HELP_TEXT
            resp = make_task_result(
                rid, content=content,
                context_id=str(uuid.uuid4()),
                task_id=str(uuid.uuid4()),
                state="completed",
                user_echo=None,
            )
            logger.info("[response] Agent response=%s", resp)            
            return resp

        # ---------- Telex A2A shape ----------
        if method == "message/send":
            if not isinstance(params, dict):
                resp = make_task_result(
                    rid,
                    content="Invalid params for message/send.",
                    context_id=str(uuid.uuid4()),
                    task_id=str(uuid.uuid4()),
                    state="failed",
                    user_echo=None,
                )
                logger.info("[response] Agent response=%s", resp)            
                return resp

            # Log brief snapshot of Telex parts
            message = (params or {}).get("message") or {}
            context_id = message.get("taskId") or str(uuid.uuid4())
            task_id    = message.get("messageId") or str(uuid.uuid4())
            parts = message.get("parts") or []

            logger.info("[telex] parts_count=%s kinds=%s",
                    len(parts), [p.get("kind") for p in parts[:3] if isinstance(p, dict)])

            text, inline_hist, dbg = extract_text_and_data_master(params)
            if not text:
                text, inline_hist, dbg = extract_text_and_data_slave(params)
            if not text:
                logger.warning("[telex] no text extracted")
                resp = make_task_result(
                    rid,
                    content="I didn't receive any text. Please send a crypto query.",
                    context_id=context_id,
                    task_id=task_id,
                    state="completed",
                    user_echo="",
                )
                logger.info("[response] Agent response=%s", resp)            
                return resp

            meta = (params or {}).get("metadata") or {}
            deployment_label = (
                req.headers.get("X-Deployment-Label")
                or meta.get("deployment_label")
                or Config.DEPLOYMENT_LABEL
            )
            temperature = 0.7
            params_like = InvokeParams(
                text=text, user_id=None, org_id=None, channel_id=None,
                metadata=meta, temperature=temperature
            )

            logger.info("[telex] dbg=%s", dbg)
            resp = _handle_invoke(
                req=req,
                rid=rid,
                user_text=text,
                params_like=params_like,
                deployment_label=deployment_label,
                temperature=temperature,
                inline_history=inline_hist,
            )
            if resp and resp.result and isinstance(resp.result, dict) and "content" in resp.result:
                content = resp.result["content"]
            elif resp and resp.result and hasattr(resp.result, "content"):
                content = resp.result.content
            else:
                content = (resp.error or {}).get("message", "Sorry, I couldn’t process that just now.")

            state = "failed" if resp and resp.error else "completed"

            resp = make_task_result(
                rid, content=content, context_id=context_id, task_id=task_id,
                state=state, user_echo=text
            )
            logger.info("[response] Agent response=%s", resp)            
            return resp

        resp = make_task_result(
            rid,
            content="Unknown method. Use 'message/send' or 'help'.",
            context_id=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
            state="failed",
            user_echo=None,
        )
        logger.info("[response] Agent response=%s", resp)            
        return resp

    except Exception:
        logger.exception("[invoke] unhandled error")
        resp = make_task_result(
            rid,
            content="Internal error while handling the request.",
            context_id=str(uuid.uuid4()),
            task_id=str(uuid.uuid4()),
            state="failed",
            user_echo=None,
        )
        logger.info("[response] Agent response=%s", resp)            
        return resp

@router.post("/help", tags=["a2a"])
def help_rpc():
    return make_task_result(
        rid="",
        content=HELP_TEXT,
        context_id=str(uuid.uuid4()),
        task_id=str(uuid.uuid4()),
        state="completed",
        user_echo=None,
    )
