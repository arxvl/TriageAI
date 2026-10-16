"""OpenAI-compatible chat-completions adapter (M2).

Works with any provider that exposes /chat/completions: Gemini (OpenAI-compatible
endpoint), Groq, OpenRouter, and a local Ollama. Provider differences are handled by
settings, not by code: JSON mode, temperature, seed, reasoning effort, rate limit.

Privacy rule (CLAUDE.md section 9): this class never logs the prompt, the response
text, or the provider's error message. It logs status codes, timings and token counts.
"""

from __future__ import annotations

import copy
import json
import logging
import random
import re
import time

import httpx

from app.adapters.llm.ratelimit import RateLimiter
from app.pipeline.errors import LLMInvalidOutput, LLMTimeout, LLMUnavailable

log = logging.getLogger(__name__)

FENCE = re.compile(r"^`{3}(?:json)?\s*|\s*`{3}$")


def opt_float(value) -> float | None:
    """'' or None -> None (send nothing); '0' -> 0.0. pydantic-settings rejects '' for floats."""
    if value is None or str(value).strip() == "":
        return None
    return float(value)


def opt_int(value) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(value)


def simplify_schema(schema: dict) -> dict:
    """Inline $ref/$defs and drop 'title'. Some providers reject Pydantic's raw schema."""
    defs = schema.get("$defs", {})

    def walk(node, depth=0):
        if depth > 12:
            return node
        if isinstance(node, dict):
            if "$ref" in node:
                target = defs.get(node["$ref"].split("/")[-1], {})
                return walk(copy.deepcopy(target), depth + 1)
            return {k: walk(v, depth + 1) for k, v in node.items() if k not in ("$defs", "title")}
        if isinstance(node, list):
            return [walk(v, depth + 1) for v in node]
        return node

    return walk(schema)


class HostedLLMProvider:
    name = "hosted"

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        model_id: str,
        *,
        temperature: float | None = None,
        seed: int | None = None,
        json_mode: str = "json_schema",
        schema_in_prompt: bool = True,
        simplify: bool = True,
        reasoning_effort: str | None = None,
        max_rpm: int = 0,
        http_retries: int = 2,
        rate_limit_wait_s: float = 20.0,
        transport: httpx.BaseTransport | None = None,
        sleep=time.sleep,
    ):
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id
        self.temperature, self.seed = temperature, seed
        self.json_mode, self.schema_in_prompt, self.simplify = json_mode, schema_in_prompt, simplify
        self.reasoning_effort = reasoning_effort or None
        self.http_retries, self.rate_limit_wait_s = http_retries, rate_limit_wait_s
        self._sleep = sleep
        self.limiter = RateLimiter(max_rpm, sleep=sleep)
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(headers=headers, transport=transport)
        # Filled after each call. The app reads none of these except usage and latency.
        self.last_usage: dict | None = None
        self.last_latency_ms: int | None = None
        self.last_error_kind: str | None = None  # rate_limited | server_error | bad_request | auth
        self.last_error_detail: str | None = None  # DEV SCRIPTS ONLY. The app must never log this.

    @classmethod
    def from_settings(cls, settings, deps=None) -> HostedLLMProvider:
        return cls(
            settings.LLM_BASE_URL,
            settings.LLM_API_KEY or None,
            settings.LLM_MODEL,
            temperature=opt_float(settings.LLM_TEMPERATURE),
            seed=opt_int(settings.LLM_SEED),
            json_mode=settings.LLM_JSON_MODE,
            schema_in_prompt=settings.LLM_SCHEMA_IN_PROMPT,
            simplify=settings.LLM_SCHEMA_SIMPLIFY,
            reasoning_effort=settings.LLM_REASONING_EFFORT or None,
            max_rpm=settings.LLM_MAX_RPM,
            http_retries=settings.LLM_HTTP_RETRIES,
            rate_limit_wait_s=settings.LLM_RATE_LIMIT_WAIT_S,
        )

    # ---- request building -------------------------------------------------
    def _schema(self, json_schema: dict) -> dict:
        return simplify_schema(json_schema) if self.simplify else json_schema

    def _response_format(self, json_schema: dict) -> dict | None:
        if self.json_mode == "json_schema":
            return {
                "type": "json_schema",
                "json_schema": {"name": "triageai_output", "schema": self._schema(json_schema)},
            }
        if self.json_mode == "json_object":
            return {"type": "json_object"}
        return None  # prompt_only

    def _system_with_hint(self, system: str, json_schema: dict) -> str:
        # Ollama's docs advise repeating the schema in the prompt even when it is enforced,
        # and json_object / prompt_only modes cannot work without it.
        if not self.schema_in_prompt and self.json_mode == "json_schema":
            return system
        hint = json.dumps(self._schema(json_schema), separators=(",", ":"))
        return (
            f"{system}\n\nReturn ONLY one JSON object that validates against this JSON "
            f"Schema. No prose, no markdown fences.\n{hint}"
        )

    def _body(self, system: str, user: str, json_schema: dict) -> dict:
        body: dict = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": self._system_with_hint(system, json_schema)},
                {"role": "user", "content": user},
            ],
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if self.seed is not None:
            body["seed"] = self.seed
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        fmt = self._response_format(json_schema)
        if fmt:
            body["response_format"] = fmt
        return body

    # ---- response handling ------------------------------------------------
    @staticmethod
    def _retry_after(resp: httpx.Response) -> float | None:
        raw = resp.headers.get("retry-after")
        try:
            return float(raw) if raw is not None else None
        except ValueError:
            return None

    @staticmethod
    def _error_message(resp: httpx.Response) -> str:
        try:
            err = resp.json().get("error", resp.json())
            msg = err.get("message") if isinstance(err, dict) else str(err)
        except Exception:  # noqa: BLE001
            msg = resp.text
        return (msg or "")[:300]

    @staticmethod
    def _parse(content: str) -> dict:
        text = FENCE.sub("", content.strip()).strip()
        try:
            out = json.loads(text)
        except json.JSONDecodeError:
            start, end = text.find("{"), text.rfind("}")
            if start == -1 or end <= start:
                raise
            out = json.loads(text[start : end + 1])  # tolerate a short preamble
        if not isinstance(out, dict):
            raise ValueError("top-level JSON is not an object")
        return out

    # ---- the one public method (LLMProvider protocol) ---------------------
    def complete_json(self, *, system: str, user: str, json_schema: dict, timeout_s: float) -> dict:
        body = self._body(system, user, json_schema)
        url = f"{self.base_url}/chat/completions"
        self.last_error_kind = self.last_error_detail = None
        attempt, waited = 0, 0.0
        start = time.perf_counter()
        while True:
            self.limiter.acquire()
            try:
                resp = self._client.post(url, json=body, timeout=timeout_s)
            except httpx.TimeoutException as exc:
                raise LLMTimeout("provider timed out") from exc
            except httpx.HTTPError as exc:
                raise LLMUnavailable("provider unreachable") from exc

            status = resp.status_code
            if status in (408, 429) or status >= 500:
                kind = "rate_limited" if status == 429 else "server_error"
                attempt += 1
                wait = self._retry_after(resp)
                if wait is None:
                    # Backoff jitter, not a secret: a weak PRNG is the right tool here.
                    wait = min(2**attempt, 8) + random.random()  # noqa: S311
                if attempt > self.http_retries or waited + wait > self.rate_limit_wait_s:
                    self.last_error_kind = kind
                    log.warning(
                        "llm call failed status=%s kind=%s attempts=%s", status, kind, attempt
                    )
                    raise LLMUnavailable(f"HTTP {status}")
                self._sleep(wait)
                waited += wait
                continue
            if status >= 400:
                self.last_error_kind = "auth" if status in (401, 403) else "bad_request"
                self.last_error_detail = self._error_message(resp)
                log.warning("llm call rejected status=%s kind=%s", status, self.last_error_kind)
                raise LLMUnavailable(f"HTTP {status}")
            break

        self.last_latency_ms = int((time.perf_counter() - start) * 1000)
        data = resp.json()
        self.last_usage = data.get("usage")
        try:
            content = data["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty content")
            return self._parse(content)
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as exc:  # JSONDecodeError is a ValueError
            raise LLMInvalidOutput("model did not return a JSON object") from exc
