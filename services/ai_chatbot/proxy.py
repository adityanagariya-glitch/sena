"""HTTP + WebSocket reverse-proxy helpers for embedding Streamlit under one origin.

Streamlit runs its session over a WebSocket (binary protobuf frames), so both
HTTP (assets, health, SSE) and WS must be proxied. Because each child is launched
with `--server.baseUrlPath <prefix>`, the request path already carries the prefix
(e.g. /staff/_stcore/...); we just swap host:port and keep the path verbatim.
"""
import asyncio
import inspect

import httpx
import websockets
from fastapi import Request, WebSocket, WebSocketDisconnect
from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse

# Headers that must not be forwarded verbatim across a proxy hop.
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}
# Response headers we drop: hop-by-hop + ones that break same-origin iframe
# embedding or conflict with re-streaming.
_STRIP_RESPONSE = _HOP_BY_HOP | {
    "x-frame-options", "content-security-policy",
    "content-length", "content-encoding",
}

# websockets renamed the header kwarg across versions; detect once.
_WS_CONNECT_PARAMS = inspect.signature(websockets.connect).parameters
_WS_HEADER_KW = "additional_headers" if "additional_headers" in _WS_CONNECT_PARAMS else "extra_headers"


async def proxy_http(request: Request, client: httpx.AsyncClient, upstream_origin: str) -> StreamingResponse:
    """Forward an HTTP request to `upstream_origin`, preserving path + query.

    Streams the upstream body back unbuffered so SSE (policy /query/stream) keeps
    flowing token-by-token.
    """
    url = f"{upstream_origin}{request.url.path}"
    fwd_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() not in ("host", "accept-encoding")
    }
    # Force identity so upstream replies uncompressed. httpx otherwise injects its
    # own default accept-encoding (gzip/deflate); aiter_bytes() below also decodes
    # as a safety net if anything still arrives compressed.
    fwd_headers["accept-encoding"] = "identity"
    body = await request.body()

    upstream_req = client.build_request(
        request.method, url,
        headers=fwd_headers,
        params=request.query_params,
        content=body,
    )
    upstream_resp = await client.send(upstream_req, stream=True)

    resp_headers = {
        k: v for k, v in upstream_resp.headers.items()
        if k.lower() not in _STRIP_RESPONSE
    }
    return StreamingResponse(
        upstream_resp.aiter_bytes(),
        status_code=upstream_resp.status_code,
        headers=resp_headers,
        media_type=upstream_resp.headers.get("content-type"),
        background=BackgroundTask(upstream_resp.aclose),
    )


async def proxy_websocket(ws: WebSocket, upstream_ws_origin: str) -> None:
    """Bridge the browser WebSocket <-> upstream Streamlit WebSocket.

    Pumps both directions concurrently; closes both sides when either ends.
    """
    path = ws.url.path
    query = ws.url.query
    upstream_url = f"{upstream_ws_origin}{path}" + (f"?{query}" if query else "")

    requested_subprotocols = ws.scope.get("subprotocols") or []

    # Forward cookies so upstream can tie the WS to the right session.
    fwd_headers = {}
    cookie = ws.headers.get("cookie")
    if cookie:
        fwd_headers["Cookie"] = cookie

    connect_kwargs = {"max_size": None, "open_timeout": 15, _WS_HEADER_KW: list(fwd_headers.items())}
    if requested_subprotocols:
        connect_kwargs["subprotocols"] = requested_subprotocols

    try:
        upstream = await websockets.connect(upstream_url, **connect_kwargs)
    except Exception:
        await ws.close(code=1011)
        return

    # Accept with the subprotocol the upstream negotiated (if any).
    await ws.accept(subprotocol=getattr(upstream, "subprotocol", None))

    async def client_to_upstream():
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("text") is not None:
                    await upstream.send(msg["text"])
                elif msg.get("bytes") is not None:
                    await upstream.send(msg["bytes"])
        except (WebSocketDisconnect, websockets.ConnectionClosed):
            pass

    async def upstream_to_client():
        try:
            async for msg in upstream:
                if isinstance(msg, (bytes, bytearray)):
                    await ws.send_bytes(bytes(msg))
                else:
                    await ws.send_text(msg)
        except (websockets.ConnectionClosed, RuntimeError):
            pass

    try:
        await asyncio.gather(client_to_upstream(), upstream_to_client())
    finally:
        await upstream.close()
        try:
            await ws.close()
        except RuntimeError:
            pass
