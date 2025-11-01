from openai import AzureOpenAI
from typing import List, Optional, Dict, Any
from app.core.config import Config
from app.core.logger import logger
from app.core.prompt import render_system_prompt

_client: Optional[AzureOpenAI] = None
def _client_once() -> AzureOpenAI:
    global _client
    if _client is None:
        try:
            _client = AzureOpenAI(
                api_key=Config.AZURE_OPENAI_API_KEY,
                api_version=Config.AZURE_OPENAI_API_VERSION,
                azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
            )
        except Exception:
            logger.exception("Failed to create AzureOpenAI client")
            raise
    return _client

def _mk_messages(deployment_label: Optional[str], user_text: str, history: Optional[List[Dict[str, str]]], facts: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    system = render_system_prompt(deployment_label)
    messages: List[Dict[str, str]] = [{"role": "system", "content": system}]

    if history:
        recent = history[-30:]
        for turn in recent:
            u = (turn.get("user") or "").strip()
            a = (turn.get("assistant") or "").strip()
            if u:
                messages.append({"role": "user", "content": u})
            if a:
                messages.append({"role": "assistant", "content": a})

    if facts:
        facts_lines = ["[FACTS]"]
        for k, v in facts.items():
            if v is None:
                continue
            s = str(v)
            if len(s) > 1000:
                s = s[:1000] + "…"
            facts_lines.append(f"- {k}: {s}")
        messages.append({"role": "user", "content": "\n".join(facts_lines)})

    messages.append({"role": "user", "content": user_text})
    return messages

def compose_response(
    user_text: str,
    history: Optional[List[Dict[str, str]]] = None,
    facts: Optional[Dict[str, Any]] = None,
    temperature: float = Config.TEMPERATURE,
    max_tokens: int = Config.MAX_TOKENS,
) -> str:
    client = _client_once()
    deployment_label = (facts or {}).get("deployment_label") or ""
    messages = _mk_messages(deployment_label, user_text, history, facts)
    try:
        resp = client.chat.completions.create(
            model=Config.AZURE_OPENAI_DEPLOYMENT,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = (resp.choices[0].message.content or "").strip()
        return content
    except Exception:
        logger.exception("compose_response failed")
        return "Sorry, I couldn’t process that just now."

def fallback_answer(user_text: str, history: Optional[List[Dict[str, str]]] = None, facts: Optional[Dict[str, Any]] = None, temperature: float = 0.6) -> str:
    return compose_response(user_text=user_text, history=history, facts=facts, temperature=temperature, max_tokens=220)
    