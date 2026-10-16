"""Unit tests for the hosted/Ollama adapter. No network: httpx.MockTransport only."""

import json
import logging

import httpx
import pytest

from app.adapters.llm.hosted import HostedLLMProvider, opt_float, simplify_schema
from app.pipeline.errors import LLMInvalidOutput, LLMTimeout, LLMUnavailable

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
SECRET = "OWNER-TEXT-THAT-MUST-NEVER-BE-LOGGED"


def ok(content, **extra):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        },
        **extra,
    )


def make(handler, **kw):
    sleeps: list[float] = []
    provider = HostedLLMProvider(
        "https://x.test/v1",
        "KEY",
        "m1",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        **kw,
    )
    return provider, sleeps


def call(p, user="hello"):
    return p.complete_json(system="sys", user=user, json_schema=SCHEMA, timeout_s=5)


# ---- parsing ---------------------------------------------------------------
def test_valid_json_and_usage():
    p, _ = make(lambda r: ok('{"ok": true}'))
    assert call(p) == {"ok": True}
    assert p.last_usage == {"prompt_tokens": 10, "completion_tokens": 3}
    assert p.last_latency_ms is not None


def test_markdown_fence_is_stripped():
    p, _ = make(lambda r: ok('```json\n{"ok": true}\n```'))
    assert call(p) == {"ok": True}


def test_short_preamble_is_tolerated():
    p, _ = make(lambda r: ok('Sure, here you go: {"ok": true}'))
    assert call(p) == {"ok": True}


@pytest.mark.parametrize("content", ["not json at all", "[1, 2]", "", None])
def test_invalid_output_is_mapped(content):
    p, _ = make(lambda r: ok(content))
    with pytest.raises(LLMInvalidOutput):
        call(p)


def test_missing_choices_is_invalid_output():
    p, _ = make(lambda r: httpx.Response(200, json={"choices": []}))
    with pytest.raises(LLMInvalidOutput):
        call(p)


# ---- retries and rate limits ----------------------------------------------
def test_429_with_retry_after_then_success():
    seq = iter([httpx.Response(429, headers={"retry-after": "3"}), ok('{"ok": true}')])
    p, sleeps = make(lambda r: next(seq))
    assert call(p) == {"ok": True}
    assert sleeps == [3.0]


def test_429_beyond_http_retries_raises_unavailable():
    calls = []

    def handler(r):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "1"})

    p, sleeps = make(handler, http_retries=2)
    with pytest.raises(LLMUnavailable):
        call(p)
    assert len(calls) == 3 and p.last_error_kind == "rate_limited"


def test_retry_after_longer_than_budget_fails_fast():
    p, sleeps = make(
        lambda r: httpx.Response(429, headers={"retry-after": "120"}), rate_limit_wait_s=20
    )
    with pytest.raises(LLMUnavailable):
        call(p)
    assert sleeps == []  # did not sit and wait for a daily-quota reset


def test_500_then_success():
    seq = iter([httpx.Response(503), ok('{"ok": true}')])
    p, sleeps = make(lambda r: next(seq))
    assert call(p) == {"ok": True} and len(sleeps) == 1


def test_400_is_not_retried_and_detail_is_kept_for_dev_scripts():
    calls = []

    def handler(r):
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "Invalid JSON schema"}})

    p, _ = make(handler)
    with pytest.raises(LLMUnavailable):
        call(p)
    assert len(calls) == 1 and p.last_error_kind == "bad_request"
    assert p.last_error_detail == "Invalid JSON schema"


def test_401_is_auth():
    p, _ = make(lambda r: httpx.Response(401, json={"error": {"message": "bad key"}}))
    with pytest.raises(LLMUnavailable):
        call(p)
    assert p.last_error_kind == "auth"


def test_timeout_is_mapped():
    def handler(r):
        raise httpx.ReadTimeout("slow")

    p, _ = make(handler)
    with pytest.raises(LLMTimeout):
        call(p)


def test_connection_error_is_unavailable():
    def handler(r):
        raise httpx.ConnectError("refused")

    p, _ = make(handler)
    with pytest.raises(LLMUnavailable):
        call(p)


# ---- request shape ---------------------------------------------------------
def sent(handler_store):
    return json.loads(handler_store[0].content)


def capture(**kw):
    store = []

    def handler(r):
        store.append(r)
        return ok('{"ok": true}')

    p, _ = make(handler, **kw)
    call(p)
    return store[0], json.loads(store[0].content)


def test_default_request_is_json_schema_with_bearer_and_no_temperature():
    req, body = capture()
    assert req.headers["authorization"] == "Bearer KEY"
    assert req.url.path.endswith("/chat/completions")
    assert body["response_format"]["type"] == "json_schema"
    assert "temperature" not in body  # blank means "provider default" (Gemini 3 family)
    assert "JSON Schema" in body["messages"][0]["content"]


def test_temperature_zero_is_sent_when_configured():
    _, body = capture(temperature=0.0)
    assert body["temperature"] == 0.0


def test_reasoning_effort_and_seed_only_when_set():
    _, body = capture(reasoning_effort="low", seed=7)
    assert body["reasoning_effort"] == "low" and body["seed"] == 7
    _, body = capture()
    assert "reasoning_effort" not in body and "seed" not in body


def test_prompt_only_mode_sends_no_response_format_but_keeps_the_schema_hint():
    _, body = capture(json_mode="prompt_only")
    assert "response_format" not in body
    assert '"ok"' in body["messages"][0]["content"]


def test_json_object_mode():
    _, body = capture(json_mode="json_object")
    assert body["response_format"] == {"type": "json_object"}


def test_no_authorization_header_without_key():
    p = HostedLLMProvider(
        "https://x.test/v1", None, "m", transport=httpx.MockTransport(lambda r: ok("{}"))
    )
    assert "authorization" not in p._client.headers


# ---- privacy ---------------------------------------------------------------
def test_content_never_appears_in_logs(caplog):
    caplog.set_level(logging.DEBUG)
    p, _ = make(lambda r: httpx.Response(400, json={"error": {"message": f"echo {SECRET}"}}))
    with pytest.raises(LLMUnavailable):
        p.complete_json(system="sys", user=SECRET, json_schema=SCHEMA, timeout_s=5)
    assert SECRET not in caplog.text


# ---- helpers ---------------------------------------------------------------
def test_opt_float():
    assert opt_float("") is None and opt_float(None) is None and opt_float("0") == 0.0


def test_simplify_schema_inlines_refs_and_drops_titles():
    raw = {
        "title": "Root",
        "type": "object",
        "$defs": {"Item": {"title": "Item", "type": "string"}},
        "properties": {
            "a": {"$ref": "#/$defs/Item"},
            "b": {"type": "array", "items": {"$ref": "#/$defs/Item"}},
        },
    }
    out = simplify_schema(raw)
    assert (
        "$defs" not in json.dumps(out)
        and "$ref" not in json.dumps(out)
        and "title" not in json.dumps(out)
    )
    assert out["properties"]["a"] == {"type": "string"}
    assert out["properties"]["b"]["items"] == {"type": "string"}


# ---- Ollama defaults -------------------------------------------------------
def test_ollama_defaults_to_temperature_zero_and_no_key():
    from types import SimpleNamespace

    from app.adapters.llm.ollama import OllamaLLMProvider

    cfg = SimpleNamespace(
        OLLAMA_BASE_URL="http://host.docker.internal:11434/v1",
        OLLAMA_MODEL="m",
        LLM_TEMPERATURE="",
        LLM_SEED="",
        OLLAMA_JSON_MODE="json_schema",
        LLM_SCHEMA_IN_PROMPT=True,
        LLM_SCHEMA_SIMPLIFY=True,
    )
    p = OllamaLLMProvider.from_settings(cfg)
    assert p.name == "ollama" and p.temperature == 0.0 and p.json_mode == "json_schema"
    assert "authorization" not in p._client.headers
    cfg.LLM_TEMPERATURE = "0.3"
    assert OllamaLLMProvider.from_settings(cfg).temperature == 0.3
