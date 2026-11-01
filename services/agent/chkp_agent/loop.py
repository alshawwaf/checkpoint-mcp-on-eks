"""The provider-agnostic tool-use loop: discover tools through the gateway,
let the model reason, call the tools it asks for, feed results back, repeat.

`emit(event)` receives progress events -- the HTTP layer turns them into SSE:
    {"type": "start", "model", "provider", "tools", "caching", "note"}
    {"type": "text", "delta"}
    {"type": "tool_call", "name", "args"}
    {"type": "tool_result", "name", "error", "preview"}
    {"type": "done", ...result}
"""

from __future__ import annotations

import asyncio
import json
import time

from . import mcp_tools
from .prompt import system_prompt
from .providers.base import add_usage, empty_usage


async def run_task(task, factory, settings, token="", model=None, emit=None, session_factory=None):
    emit = emit or (lambda _e: None)
    t0 = time.time()
    conv = await asyncio.to_thread(factory.new, model)
    open_session = session_factory or (lambda: mcp_tools.gateway_session(settings.gateway_url, token))
    totals, trace, answer, stopped = empty_usage(), [], "", "end_turn"

    async with open_session() as session:
        specs = await mcp_tools.list_specs(session)
        conv.start(system_prompt(settings.tool_separator), specs)
        conv.add_user(task)
        emit({"type": "start", "model": conv.model, "provider": conv.provider, "label": conv.label,
              "tools": len(specs), "caching": conv.caching, "note": conv.note})
        loop = asyncio.get_running_loop()

        def on_text(delta):
            loop.call_soon_threadsafe(emit, {"type": "text", "delta": delta})

        for _ in range(settings.max_turns):
            turn = await asyncio.to_thread(conv.step, on_text)
            add_usage(totals, turn.usage)
            if turn.text.strip():
                answer = turn.text.strip()
            if not turn.tool_calls:
                stopped = turn.stop
                break
            results = []
            for call in turn.tool_calls:
                emit({"type": "tool_call", "name": call.name, "args": call.args})
                out = await mcp_tools.call(session, call.name, call.args)
                text = out["text"][: settings.tool_result_chars]
                trace.append({"name": call.name, "args": call.args, "error": out["error"],
                              "preview": text[:300]})
                emit({"type": "tool_result", "name": call.name, "error": out["error"],
                      "preview": text[:200]})
                results.append((call, text, out["error"]))
            conv.add_tool_results(results)
        else:
            stopped = "max_turns"

    seen = totals["in"] + totals["cache_read"]
    result = {
        "result": answer, "model": conv.model, "provider": conv.provider, "usage": totals,
        "cache_hit_pct": round(100 * totals["cache_read"] / seen) if seen else 0,
        "tool_calls": trace, "stop": stopped, "seconds": round(time.time() - t0, 2),
        "error": False,
    }
    emit({"type": "done", **result})
    return result


def to_sse(event):
    return f"event: {event['type']}\ndata: {json.dumps(event, default=str)}\n\n"
