import re
from html import unescape
from typing import Any, Dict, List, Optional, Tuple

_TAGS_RE = re.compile(r"<[^>]*>")
_WS_RE   = re.compile(r"\s+")

def clean_text(raw: str) -> str:
    if not raw:
        return ""
    s = unescape(raw)
    s = _TAGS_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s

def extract_text_and_data_master(params_obj: Dict[str, Any]) -> Tuple[Optional[str], List[str], str]:
    """Prefer the LAST item in parts[1].data[*].text; fallback to parts[0].text; fallback to message.text."""
    eff_text: Optional[str] = None
    inline_hist: List[str] = []
    dbg_bits: List[str] = []

    message = (params_obj or {}).get("message") or {}
    parts = message.get("parts") or []

    if len(parts) > 1 and isinstance(parts[1], dict) and parts[1].get("kind") == "data":
        data_items = parts[1].get("data") or []
        cleaned = []
        for di in data_items:
            if isinstance(di, dict) and di.get("kind") == "text":
                t = clean_text(di.get("text") or "")
                if t:
                    cleaned.append(t)
        inline_hist = cleaned[-20:]
        dbg_bits.append(f"data_text_count={len(cleaned)}")
        if inline_hist:
            eff_text = inline_hist[-1]
            dbg_bits.append("source=data:last")

    # parts[0].text
    if not eff_text and len(parts) > 0 and isinstance(parts[0], dict) and parts[0].get("kind") == "text":
        t0 = clean_text(parts[0].get("text") or "")
        if t0:
            eff_text = t0
            dbg_bits.append("source=parts0")

    # message.text
    if not eff_text:
        mt = clean_text(message.get("text") or "")
        if mt:
            eff_text = mt
            dbg_bits.append("source=message.text")

    return eff_text, inline_hist, ";".join(dbg_bits[:3])

def extract_text_and_data_slave(params_obj: Dict[str, Any]) -> Tuple[Optional[str], List[str], str]:
    """Fallback extractor (un-cleaned parts0, then message.text; also collects raw data texts)."""
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
        pass

    return eff_text, inline_hist[-20:], ";".join(dbg[:3])
