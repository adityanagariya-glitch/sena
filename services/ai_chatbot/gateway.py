"""ai_chatbot gateway — one origin fronting Staff + Policy/Proc.

Serves a shell page (toggle + two pre-loaded iframes) and reverse-proxies both
existing Streamlit apps (and the policy FastAPI) under this single origin, so
they embed without cross-origin / X-Frame-Options trouble. Optionally spawns and
health-checks the children itself (MANAGE_CHILDREN).

Run:
    cd services/ai_chatbot && ./run.sh
    # or: uvicorn gateway:app --host 0.0.0.0 --port 9000
"""
import asyncio
import contextlib
import os
import signal
import sys
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import config
from proxy import proxy_http, proxy_websocket

templates = Jinja2Templates(directory=str(config.TEMPLATES_DIR))

_HTTP_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]


async def _wait_healthy(client: httpx.AsyncClient, url: str, timeout: float) -> bool:
    """Poll a child health URL until it answers 2xx or the timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = await client.get(url, timeout=3)
            if r.status_code < 400:
                return True
        except Exception:
            pass
        await asyncio.sleep(0.5)
    return False


async def _is_up(client: httpx.AsyncClient, url: str) -> bool:
    try:
        r = await client.get(url, timeout=2)
        return r.status_code < 400
    except Exception:
        return False


async def _pump_logs(name: str, proc: asyncio.subprocess.Process) -> None:
    """Stream a child's stdout/stderr to the gateway terminal (prefixed) AND to
    logs/<name>.log so you can `tail -f` a single service in isolation."""
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = config.LOGS_DIR / f"{name}.log"
    prefix = f"[{name}] ".encode()
    with open(log_path, "wb", buffering=0) as fh:
        async for line in proc.stdout:
            sys.stderr.buffer.write(prefix + line)
            sys.stderr.buffer.flush()
            fh.write(line)


async def _spawn_children(app: FastAPI) -> None:
    client: httpx.AsyncClient = app.state.client
    procs = []
    for spec in config.child_specs():
        # Reuse an already-running instance instead of double-spawning (avoids
        # port collisions when the service is started separately).
        if await _is_up(client, spec["health_url"]):
            print(f"[gateway] {spec['name']} already running — reusing", file=sys.stderr)
            procs.append({"name": spec["name"], "proc": None, "health_url": spec["health_url"]})
            continue

        # PYTHONUNBUFFERED so child logs stream live through the pipe (no buffering).
        env = {**os.environ, "PYTHONUNBUFFERED": "1", **(spec.get("env") or {})}
        print(f"[gateway] starting {spec['name']}: {' '.join(spec['argv'])}", file=sys.stderr)
        proc = await asyncio.create_subprocess_exec(
            *spec["argv"], cwd=spec["cwd"], env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        # Background task drains the child's output (prefixed + to a log file).
        asyncio.create_task(_pump_logs(spec["name"], proc))
        procs.append({"name": spec["name"], "proc": proc, "health_url": spec["health_url"]})
    app.state.children = procs

    # Health-gate so the shell only shows once children can serve.
    for child in procs:
        ok = await _wait_healthy(client, child["health_url"], config.CHILD_HEALTH_TIMEOUT)
        child["healthy_at_start"] = ok
        status = "ready" if ok else "TIMEOUT (continuing anyway)"
        print(f"[gateway] {child['name']} {status}", file=sys.stderr)


async def _terminate_children(app: FastAPI) -> None:
    for child in getattr(app.state, "children", []):
        proc = child["proc"]
        if proc is None or proc.returncode is not None:
            continue  # reused/already-exited — nothing to stop
        print(f"[gateway] stopping {child['name']} (pid {proc.pid})", file=sys.stderr)
        with contextlib.suppress(ProcessLookupError):
            proc.send_signal(signal.SIGTERM)
    for child in getattr(app.state, "children", []):
        proc = child["proc"]
        if proc is None:
            continue
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Shared pooled client = lower latency (connection reuse) for proxy + health.
    app.state.client = httpx.AsyncClient(timeout=httpx.Timeout(None), follow_redirects=False)
    app.state.children = []
    if config.MANAGE_CHILDREN:
        await _spawn_children(app)
    try:
        yield
    finally:
        if config.MANAGE_CHILDREN:
            await _terminate_children(app)
        await app.state.client.aclose()


app = FastAPI(title="SENA ai_chatbot gateway", version="1.0.0", lifespan=lifespan)


# ---- Shell + health ----

@app.get("/", response_class=HTMLResponse)
async def shell(request: Request):
    return templates.TemplateResponse(
        request,
        "shell.html",
        {
            "staff_url": f"/{config.STAFF_PREFIX}/",
            "policy_url": f"/{config.POLICY_PREFIX}/",
        },
    )


@app.get("/healthz")
async def healthz(request: Request):
    client: httpx.AsyncClient = app.state.client
    results = {}
    for spec in config.child_specs():
        try:
            r = await client.get(spec["health_url"], timeout=2)
            results[spec["name"]] = r.status_code < 400
        except Exception:
            results[spec["name"]] = False
    return JSONResponse({"gateway": True, "children": results})


# ---- Bare-prefix redirects to trailing slash (Streamlit expects /staff/) ----

@app.get("/staff")
async def _staff_root():
    return RedirectResponse(url=f"/{config.STAFF_PREFIX}/")


@app.get("/policy")
async def _policy_root():
    return RedirectResponse(url=f"/{config.POLICY_PREFIX}/")


# ---- WebSocket proxy (register before HTTP catch-alls) ----

@app.websocket("/staff/{path:path}")
async def _staff_ws(ws: WebSocket, path: str):
    await proxy_websocket(ws, config.STAFF_WS_ORIGIN)


@app.websocket("/policy/{path:path}")
async def _policy_ws(ws: WebSocket, path: str):
    await proxy_websocket(ws, config.POLICY_WS_ORIGIN)


# ---- HTTP proxy catch-alls ----

@app.api_route("/staff/{path:path}", methods=_HTTP_METHODS)
async def _staff_http(request: Request, path: str):
    return await proxy_http(request, app.state.client, config.STAFF_ORIGIN)


@app.api_route("/policy/{path:path}", methods=_HTTP_METHODS)
async def _policy_http(request: Request, path: str):
    return await proxy_http(request, app.state.client, config.POLICY_ORIGIN)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.GATEWAY_PORT)
