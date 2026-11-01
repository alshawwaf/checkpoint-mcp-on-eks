"""HTTP API for the security-operations agent.

    GET  /healthz      liveness (process is up)
    GET  /readyz       readiness (settings valid; provider constructed)
    GET  /metrics      Prometheus metrics
    POST /v1/chat      {"prompt": "...", "model"?: "...", "stream"?: false}
                       -> JSON result, or text/event-stream when stream=true

Every /v1/chat request must carry a bearer token accepted by the configured
issuer (Amazon Cognito by default) unless AUTH_DISABLED=true (local dev only).
Logs are one JSON object per line; prompts are logged by length only and
tokens, headers and tool arguments never.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from . import __version__
from .auth import AuthError, JWTValidator
from .gateway_token import TokenProvider
from .loop import run_task, to_sse
from .providers import ProviderError, make_factory
from .settings import load

TASK_KEYS = ("prompt", "task", "input", "query")

REQUESTS = Counter("chkp_agent_requests_total", "Chat requests", ["outcome"])
TOOL_CALLS = Counter("chkp_agent_tool_calls_total", "Tool calls made by the agent", ["tool", "error"])
TOKENS = Counter("chkp_agent_tokens_total", "LLM tokens", ["kind"])
LATENCY = Histogram("chkp_agent_request_seconds", "End-to-end chat latency",
                    buckets=(1, 2, 5, 10, 20, 30, 60, 120, 300))


class JsonFormatter(logging.Formatter):
    def format(self, record):
        doc = {"ts": round(record.created, 3), "level": record.levelname, "logger": record.name,
               "msg": record.getMessage()}
        doc.update(getattr(record, "fields", {}) or {})
        return json.dumps(doc, default=str)


def setup_logging(level):
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
    for noisy in ("httpx", "httpx2", "botocore", "urllib3", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


log = logging.getLogger("chkp_agent")


def extract_task(payload):
    if isinstance(payload, str):
        return payload.strip()
    if isinstance(payload, dict):
        for k in TASK_KEYS:
            v = payload.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return ""


def create_app(settings=None, factory=None, validator=None, token_provider=None, session_factory=None):
    settings = settings or load()
    setup_logging(settings.log_level)
    state = {"factory": factory, "validator": validator, "error": None}
    tokens = token_provider or TokenProvider(settings.token_url, settings.client_id,
                                             settings.client_secret, settings.token_scope)
    try:
        if state["factory"] is None:
            state["factory"] = make_factory(settings)
        if state["validator"] is None and not settings.auth_disabled:
            state["validator"] = JWTValidator(settings.auth_issuer, settings.auth_jwks_url, settings.auth_audience,
                                              settings.auth_allowed_client_ids, settings.auth_required_scope)
    except Exception as e:  # noqa: BLE001 -- surfaced through /readyz instead of a crash loop
        state["error"] = f"{type(e).__name__}: {e}"
        log.error("startup configuration error", extra={"fields": {"error": state["error"]}})

    app = FastAPI(title="Check Point security-ops agent", version=__version__, docs_url=None, redoc_url=None)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz():
        if state["error"]:
            return JSONResponse({"status": "error", "error": state["error"]}, status_code=503)
        return {"status": "ready", "provider": settings.provider, "auth": not settings.auth_disabled}

    @app.get("/metrics")
    def metrics():
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/v1/chat")
    async def chat(request: Request):
        if state["error"]:
            return JSONResponse({"error": "agent misconfigured", "detail": state["error"]}, status_code=503)
        principal = None
        if state["validator"] is not None:
            try:
                principal = state["validator"].validate(request.headers.get("authorization", ""))
            except AuthError as e:
                REQUESTS.labels("unauthorized").inc()
                return JSONResponse({"error": str(e)}, status_code=e.status)
        try:
            payload = await request.json()
        except ValueError:
            return JSONResponse({"error": "invalid JSON body"}, status_code=400)
        task = extract_task(payload)
        if not task:
            return JSONResponse({"error": "no prompt (expected one of " + "/".join(TASK_KEYS) + ")"},
                                status_code=400)
        opts = payload if isinstance(payload, dict) else {}
        model = opts.get("model") or None
        who = principal.client_id if principal else "anonymous"
        try:
            gw_token = await asyncio.to_thread(tokens.get)
        except Exception as e:  # noqa: BLE001
            REQUESTS.labels("gateway_token_error").inc()
            return JSONResponse({"error": "could not obtain a gateway token", "detail": type(e).__name__},
                                status_code=502)

        def record(result):
            for t in result.get("tool_calls", []):
                TOOL_CALLS.labels(t["name"], str(t["error"]).lower()).inc()
            for k, v in result.get("usage", {}).items():
                TOKENS.labels(k).inc(v)
            log.info("chat complete", extra={"fields": {
                "client": who, "model": result["model"], "tools": len(result["tool_calls"]),
                "usage": result["usage"], "seconds": result["seconds"], "prompt_chars": len(task)}})

        t0 = time.time()
        if opts.get("stream"):
            queue: asyncio.Queue = asyncio.Queue()

            async def produce():
                try:
                    result = await run_task(task, state["factory"], settings, gw_token, model,
                                            emit=queue.put_nowait, session_factory=session_factory)
                    record(result)
                    REQUESTS.labels("ok").inc()
                except Exception as e:  # noqa: BLE001
                    REQUESTS.labels("error").inc()
                    queue.put_nowait({"type": "error", "error": _public_error(e)})
                finally:
                    LATENCY.observe(time.time() - t0)
                    queue.put_nowait(None)

            async def events():
                task_ = asyncio.create_task(produce())
                while True:
                    ev = await queue.get()
                    if ev is None:
                        break
                    yield to_sse(ev)
                await task_

            return StreamingResponse(events(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
        try:
            result = await run_task(task, state["factory"], settings, gw_token, model,
                                    session_factory=session_factory)
        except Exception as e:  # noqa: BLE001
            REQUESTS.labels("error").inc()
            LATENCY.observe(time.time() - t0)
            log.warning("chat failed", extra={"fields": {"client": who, "error": _public_error(e)}})
            return JSONResponse({"result": "", "error": True, "detail": _public_error(e)}, status_code=502)
        LATENCY.observe(time.time() - t0)
        REQUESTS.labels("ok").inc()
        record(result)
        return result

    return app


def _public_error(e):
    if isinstance(e, ProviderError):
        return str(e)
    inner = getattr(e, "exceptions", None)
    if inner:
        return _public_error(inner[0])
    return f"{type(e).__name__}: {str(e)[:200]}"


def main():  # pragma: no cover -- container entrypoint
    import uvicorn

    s = load()
    uvicorn.run(create_app(s), host="0.0.0.0", port=s.port, log_config=None, access_log=False)  # noqa: S104


if __name__ == "__main__":  # pragma: no cover
    main()
