"""Instagram tools through Composio Connect (consumer keys that start with ck_).

Those keys only work on the Connect MCP endpoint, so this speaks plain MCP over HTTP
and runs each Instagram tool through COMPOSIO_MULTI_EXECUTE_TOOL."""
import itertools
import json
import threading

import httpx

from . import config

URL = "https://connect.composio.dev/mcp"
PROTOCOL = "2025-06-18"

_lock = threading.Lock()
_session_id = None
_ids = itertools.count(1)


class ConnectError(Exception):
    pass


def _headers():
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
         "x-consumer-api-key": config.COMPOSIO_API_KEY, "MCP-Protocol-Version": PROTOCOL}
    if _session_id:
        h["Mcp-Session-Id"] = _session_id
    return h


def _parse(resp, want_id):
    """A reply is either plain JSON or a short event stream; return the message with our id."""
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                try:
                    msg = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if msg.get("id") == want_id:
                    return msg
        raise ConnectError(f"no reply in stream: {resp.text[:300]}")
    return resp.json()


def _post(payload, timeout=120):
    resp = httpx.post(URL, headers=_headers(), json=payload, timeout=timeout)
    if resp.status_code in (401, 403):
        raise ConnectError(f"{resp.status_code} مفتاح Composio مرفوض: {resp.text[:200]}")
    if resp.status_code == 404 and _session_id:
        raise _Expired()
    if resp.status_code >= 400:
        raise ConnectError(f"{resp.status_code}: {resp.text[:300]}")
    return resp


class _Expired(Exception):
    pass


def _initialize():
    global _session_id
    _session_id = None
    rid = next(_ids)
    resp = _post({"jsonrpc": "2.0", "id": rid, "method": "initialize", "params": {
        "protocolVersion": PROTOCOL, "capabilities": {},
        "clientInfo": {"name": "jawa-app", "version": "1.0"}}}, timeout=30)
    _session_id = resp.headers.get("mcp-session-id")
    msg = _parse(resp, rid)
    if "error" in msg:
        raise ConnectError(f"initialize: {msg['error']}")
    _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, timeout=30)


def _call_tool(name, arguments):
    rid = next(_ids)
    resp = _post({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                  "params": {"name": name, "arguments": arguments}})
    msg = _parse(resp, rid)
    if "error" in msg:
        raise ConnectError(str(msg["error"])[:500])
    result = msg.get("result") or {}
    text = "".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
    if result.get("isError"):
        raise ConnectError(text[:500] or "tool error")
    try:
        return json.loads(text)
    except ValueError:
        raise ConnectError(f"unexpected reply: {text[:300]}")


def execute(slug: str, arguments: dict) -> dict:
    """Run one Instagram tool and return a dict shaped like the SDK's: {successful, data, error}."""
    args = {"tools": [{"tool_slug": slug, "arguments": arguments, "account": config.COMPOSIO_ACCOUNT}],
            "sync_response_to_workbench": False}
    with _lock:
        for attempt in range(2):
            try:
                if not _session_id:
                    _initialize()
                out = _call_tool("COMPOSIO_MULTI_EXECUTE_TOOL", args)
                break
            except _Expired:
                _initialize_needed()
                if attempt:
                    raise ConnectError("session expired twice")
    if not out.get("successful", True) and out.get("error"):
        return {"successful": False, "error": out.get("error"), "data": {}}
    results = ((out.get("data") or {}).get("results") or [])
    if not results:
        return {"successful": False, "error": out.get("error") or f"no result: {str(out)[:300]}", "data": {}}
    r = results[0]
    resp = r.get("response") or {}
    if r.get("error") or not resp.get("successful", True):
        return {"successful": False, "error": r.get("error") or resp.get("error") or resp, "data": {}}
    return {"successful": True, "data": resp.get("data") or {}, "error": None}


def _initialize_needed():
    global _session_id
    _session_id = None
