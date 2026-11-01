"""End-to-end through the HTTP API with an in-process MCP server and a
scripted provider: tool discovery, a tool call, the answer, usage, SSE."""

import json
from contextlib import asynccontextmanager

from fastapi.testclient import TestClient
from mcp import Client
from mcp.server.mcpserver import MCPServer

from chkp_agent.app import create_app
from chkp_agent.providers.base import ToolCall, Turn, name_map
from chkp_agent.settings import Settings

server = MCPServer("fake")


@server.tool(name="reputationservice_url_reputation")
def url_reputation(url: str) -> str:
    return f"{url} is classified: Benign (risk 0)"


@asynccontextmanager
async def in_process_session():
    async with Client(server) as client:
        yield client.session


class ScriptedConversation:
    provider, label, caching, note, model = "fake", "Fake", True, None, "fake-model"

    def __init__(self):
        self.step_no, self.results, self.specs = 0, [], []

    def start(self, system, specs):
        assert "reputationservice_" in system
        self.specs = specs
        _, self.map = name_map(specs)

    def add_user(self, text):
        self.task = text

    def step(self, on_text=None):
        self.step_no += 1
        if self.step_no == 1:
            return Turn(text="", tool_calls=[ToolCall("t1", "reputationservice_url_reputation",
                                                      {"url": "https://example.com"})],
                        usage={"in": 100, "out": 10, "cache_read": 0, "cache_write": 900}, stop="tool_use")
        if on_text:
            on_text("Benign.")
        return Turn(text="Benign.", usage={"in": 20, "out": 5, "cache_read": 900, "cache_write": 0}, stop="end_turn")

    def add_tool_results(self, results):
        self.results.extend(results)


class ScriptedFactory:
    name = "fake"

    def __init__(self):
        self.last = None

    def new(self, model=None):
        self.last = ScriptedConversation()
        return self.last


class NoTokens:
    def get(self):
        return ""


def make_client():
    factory = ScriptedFactory()
    app = create_app(Settings(auth_disabled=True, provider="fake"), factory=factory,
                     token_provider=NoTokens(), session_factory=in_process_session)
    return TestClient(app), factory


def test_chat_json_round_trip():
    client, factory = make_client()
    r = client.post("/v1/chat", json={"prompt": "is example.com safe?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"] == "Benign."
    assert body["tool_calls"][0]["name"] == "reputationservice_url_reputation"
    assert "Benign (risk 0)" in body["tool_calls"][0]["preview"]
    assert body["usage"] == {"in": 120, "out": 15, "cache_read": 900, "cache_write": 900}
    assert body["cache_hit_pct"] == 88
    assert factory.last.results[0][2] is False  # tool succeeded


def test_chat_streams_sse_events():
    client, _ = make_client()
    with client.stream("POST", "/v1/chat", json={"prompt": "check", "stream": True}) as r:
        raw = "".join(r.iter_text())
    events = [json.loads(line[6:]) for line in raw.splitlines() if line.startswith("data: ")]
    kinds = [e["type"] for e in events]
    assert kinds[0] == "start" and kinds[-1] == "done"
    assert "tool_call" in kinds and "tool_result" in kinds and "text" in kinds


def test_validation_and_probes():
    client, _ = make_client()
    assert client.post("/v1/chat", json={}).status_code == 400
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200
    assert "chkp_agent_requests_total" in client.get("/metrics").text


def test_auth_required_when_enabled():
    app = create_app(Settings(provider="fake", auth_issuer=""), factory=ScriptedFactory(),
                     token_provider=NoTokens())
    c = TestClient(app)
    assert c.get("/readyz").status_code == 503      # misconfigured: no issuer -> not ready
    assert c.post("/v1/chat", json={"prompt": "x"}).status_code == 503
