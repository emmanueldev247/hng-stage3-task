import uuid
from datetime import datetime, timezone

def parse_jsonrpc(body: dict | None):
    """Leniently extract jsonrpc `id`, `method`, `params` without raising 422s."""
    body = body or {}
    rid = body.get("id", "")
    method = body.get("method", None)
    params = body.get("params") or {}
    return rid, method, params

def make_task_result(rid: any, *, content: str, context_id: str, task_id: str,
                      state: str = "completed", user_echo: str | None = None,
                      artifact_name: str = "assistantResponse"):
    """Return Raven-style task envelope, always HTTP 200 safe."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    result = {
        "id": task_id,
        "contextId": context_id,
        "status": {
            "state": state,
            "timestamp": now,
            "message": {
                "kind": "message",
                "role": "agent",
                "parts": [{"kind": "text", "text": content}],
                "messageId": str(uuid.uuid4()),
                "taskId": None,
                "metadata": None,
            },
        },
        "artifacts": [
            {
                "artifactId": str(uuid.uuid4()),
                "name": artifact_name,
                "parts": [{"kind": "text", "text": content}],
            }
        ],
        "history": [],
        "kind": "task",
    }
    if user_echo is not None:
        result["history"].append({
            "kind": "message",
            "role": "user",
            "parts": [{"kind": "text", "text": user_echo}],
            "messageId": str(uuid.uuid4()),
            "taskId": None,
            "metadata": None,
        })
    return {"jsonrpc": "2.0", "id": rid, "result": result}
