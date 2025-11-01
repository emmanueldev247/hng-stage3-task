from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from app.core.config import Config

router = APIRouter()

def _build_manifest(base_url: str) -> dict:
    """Return a JSON manifest describing this agent."""
    base = base_url.rstrip("/")
    return {
        "name": Config.AGENT_NAME,
        "description": Config.AGENT_DESCRIPTION,
        "version": Config.AGENT_VERSION,
        "publisher": Config.AGENT_PUBLISHER,
        "website": Config.AGENT_WEBSITE or None,

        "protocol": "jsonrpc-2.0",
        "runtime": "python/fastapi",
        "endpoints": {
            "a2a": f"{base}/invoke",
            "health": f"{base}/health"
        },
        "methodsSupported": ["message/send", "invoke", "help"],

        # What Telex can send and what you expect
        "messageParts": ["text", "data"],
        "headersExpected": ["X-Telex-Org-Id", "X-Telex-User-Id", "X-Deployment-Label", "X-Session-Id"],

        # Features/capabilities (informational)
        "capabilities": {
            "topics": ["cryptocurrency", "defi", "nfts", "market-data", "headlines"],
            "grounding": ["CoinGecko", "CoinDesk RSS"],
            "responses": {"format": "markdown", "maxWords": 200, "disclaimer": "This is not financial advice."},
        }
    }

@router.get("/agent.json", include_in_schema=False)
async def agent_json(req: Request):
    manifest = _build_manifest(str(req.base_url))
    return JSONResponse(content=manifest, headers={"Cache-Control": "public, max-age=300"})

@router.get("/.well-known/agent.json", include_in_schema=False)
async def agent_json_wellknown(req: Request):
    manifest = _build_manifest(str(req.base_url))
    return JSONResponse(content=manifest, headers={"Cache-Control": "public, max-age=300"})
