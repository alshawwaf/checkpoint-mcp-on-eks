from types import SimpleNamespace as NS

from botocore.exceptions import ClientError

from chkp_agent.providers import anthropic_api, base, bedrock, openai_compat


def test_sanitize_and_name_map():
    rows, mapping = base.name_map([("reputationservice_get url", "d", {"type": "object"}),
                                   ("x" * 80, "", None)])
    assert rows[0][0] == "reputationservice_get_url"
    assert mapping["reputationservice_get_url"] == "reputationservice_get url"
    assert len(rows[1][0]) == 64 and rows[1][3] == {"type": "object", "properties": {}}


def test_reconstruct_stream_text_and_tool():
    seen = []
    events = [
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "Look"}}},
        {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": "ing"}}},
        {"contentBlockStart": {"contentBlockIndex": 1, "start": {"toolUse": {"toolUseId": "t1", "name": "a_b"}}}},
        {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"toolUse": {"input": '{"q": '}}}},
        {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"toolUse": {"input": '"x"}'}}}},
        {"messageStop": {"stopReason": "tool_use"}},
        {"metadata": {"usage": {"inputTokens": 10, "outputTokens": 5, "cacheReadInputTokens": 90}}},
    ]
    msg, stop, usage = bedrock.reconstruct_stream(events, seen.append)
    assert seen == ["Look", "ing"]
    assert msg["content"][0] == {"text": "Looking"}
    assert msg["content"][1]["toolUse"] == {"toolUseId": "t1", "name": "a_b", "input": {"q": "x"}}
    assert stop == "tool_use"
    assert bedrock.normalise_usage(usage) == {"in": 10, "out": 5, "cache_read": 90, "cache_write": 0}


def test_cache_points_gated_by_model_family():
    rows, _ = base.name_map([("a_b", "d", {"type": "object"})])
    assert bedrock.build_tool_config(rows, "us.anthropic.claude-sonnet-4-6")["tools"][-1] == {
        "cachePoint": {"type": "default"}}
    assert "cachePoint" not in bedrock.build_tool_config(rows, "us.amazon.nova-2-lite-v1:0")["tools"][-1]
    assert bedrock.supports_system_caching("us.amazon.nova-lite-v1:0")


def _denied(msg):
    return ClientError({"Error": {"Code": "ResourceNotFoundException", "Message": msg}}, "Converse")


class FakeBedrock:
    def __init__(self, callable_models):
        self.callable, self.calls = set(callable_models), []

    def converse(self, modelId, **_):
        self.calls.append(modelId)
        if modelId in self.callable:
            return {"output": {"message": {"role": "assistant", "content": [{"text": "ok"}]}}}
        raise _denied("Model use case details have not been submitted for this account.")


def test_model_pick_falls_back_to_nova_with_use_case_note():
    fake = FakeBedrock({"us.amazon.nova-2-lite-v1:0"})
    f = bedrock.BedrockFactory("us-east-1", client=fake)
    model, note = f.pick_model()
    assert model == "us.amazon.nova-2-lite-v1:0"
    assert "use-case form" in note
    n = len(fake.calls)
    assert f.pick_model()[0] == model and len(fake.calls) == n  # cached


def test_forced_model_skips_probe():
    fake = FakeBedrock(set())
    assert bedrock.BedrockFactory("us-east-1", model="m", client=fake).pick_model() == ("m", None)
    assert fake.calls == []


def _chunk(content=None, tool=None, finish=None, usage=None):
    delta = NS(content=content, tool_calls=[tool] if tool else None)
    choices = [NS(delta=delta, finish_reason=finish)] if (content or tool or finish) else []
    return NS(choices=choices, usage=usage)


def test_openai_stream_accumulation_and_cached_usage():
    t1 = NS(index=0, id="c1", function=NS(name="reputationservice_", arguments='{"u":'))
    t2 = NS(index=0, id=None, function=NS(name="lookup", arguments='"x"}'))
    usage = NS(prompt_tokens=1200, completion_tokens=30,
               prompt_tokens_details=NS(cached_tokens=1024, cache_write_tokens=0))
    seen = []
    text, calls, finish, u = openai_compat.accumulate_stream(
        [_chunk(content="Hi"), _chunk(tool=t1), _chunk(tool=t2), _chunk(finish="tool_calls"), _chunk(usage=usage)],
        seen.append)
    assert text == "Hi" and seen == ["Hi"]
    assert calls == [{"id": "c1", "name": "reputationservice_lookup", "args": '{"u":"x"}'}]
    assert finish == "tool_calls"
    assert openai_compat.normalise_usage(u) == {"in": 176, "out": 30, "cache_read": 1024, "cache_write": 0}


class _FakeStream:
    def __init__(self, msg, deltas):
        self.msg, self.text_stream = msg, iter(deltas)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get_final_message(self):
        return self.msg


class _FakeAnthropic:
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kw):
        self.requests.append(kw)
        msg, deltas = self.replies.pop(0)
        return _FakeStream(msg, deltas)


def _msg(content, stop, model="claude-opus-5-5"):
    usage = NS(input_tokens=50, output_tokens=20, cache_read_input_tokens=3000, cache_creation_input_tokens=0)
    return NS(content=content, stop_reason=stop, model=model, usage=usage)


def test_anthropic_tool_turn_caching_and_history():
    tool_msg = _msg([NS(type="thinking", thinking=""), NS(type="text", text="Checking."),
                     NS(type="tool_use", id="tu1", name="reputationservice_url", input={"resource": "x"})],
                    "tool_use")
    final = _msg([NS(type="text", text="Clean.")], "end_turn")
    fake = _FakeAnthropic([(tool_msg, ["Check", "ing."]), (final, ["Clean."])])
    conv = anthropic_api.AnthropicFactory(fake, max_tokens=2048).new()
    conv.start("SYS", [("reputationservice_url", "d", {"type": "object"})])
    conv.add_user("q")
    seen = []
    turn = conv.step(seen.append)
    assert seen == ["Check", "ing."]
    assert [(c.id, c.name, c.args) for c in turn.tool_calls] == [("tu1", "reputationservice_url", {"resource": "x"})]
    assert turn.usage == {"in": 50, "out": 20, "cache_read": 3000, "cache_write": 0}
    req = fake.requests[0]
    assert req["system"][0]["cache_control"] == {"type": "ephemeral"} and req["cache_control"]
    assert req["max_tokens"] >= 16000 and req["fallbacks"] == "default"
    assert req["output_config"] == {"effort": "medium"} and "tool_choice" not in req
    # the whole assistant content (thinking included) goes back unchanged
    assert conv.messages[-1]["content"] is tool_msg.content
    conv.add_tool_results([(turn.tool_calls[0], "clean", False)])
    assert conv.messages[-1]["content"][0] == {"type": "tool_result", "tool_use_id": "tu1",
                                               "content": "clean", "is_error": False}
    assert conv.step().text == "Clean."


def test_anthropic_refusal_and_truncated_tool_call_run_no_tools():
    tu = NS(type="tool_use", id="t", name="a_b", input={})
    fake = _FakeAnthropic([(_msg([tu], "refusal"), []), (_msg([tu], "max_tokens"), [])])
    conv = anthropic_api.AnthropicFactory(fake, fallbacks=False).new()
    conv.start("S", [("a_b", "d", {})])
    conv.add_user("q")
    t1 = conv.step()
    assert t1.tool_calls == [] and t1.stop == "refusal" and t1.text
    assert "fallbacks" not in fake.requests[0]
    t2 = conv.step()
    assert t2.tool_calls == [] and t2.stop == "max_tokens"
