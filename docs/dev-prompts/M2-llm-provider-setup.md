# M2 — LLM Provider Setup and Model Selection (Manual)

**Owner:** Lane B · **Branch:** `feat/m2-llm-provider` (plus `spike/m2-llm-selection` for the comparison)
**Do after:** P05 · **Closes:** TBD-1 · **Updates:** ADR-06
**Requirements:** IR-12, IR-18, IR-19, NFR-01, NFR-28, SR-08, SR-11

You will connect TriageAI to a real transformer LLM behind the `LLMProvider` interface. Then you will compare two or three candidates and choose one with evidence.

## Prerequisites

- [ ] P05 merged: the pipeline runs on mocks.
- [ ] M1 done, or at least `PIPELINE_DEIDENTIFIER=rules` works. The app refuses a real LLM with the mock de-identifier.
- [ ] Only fictitious test descriptions exist (CLAUDE.md §9).

---

## Step 1. Shortlist candidates

Pick **one hosted API** and **one local model**. Hosted is the default; local is the fallback (ADR-06).

| Criterion | What to check in the provider docs |
|---|---|
| JSON output | Does it support a JSON mode or JSON-schema ("structured output")? |
| API style | Does it offer an **OpenAI-compatible** Chat Completions endpoint? If yes, you can reuse the adapter in Step 3. If not, write a small adapter with the provider's SDK that implements the same interface. |
| Data use | Is API data excluded from model training by default, or can you opt out? Record this for ADR-06 and RA 10173. |
| Cost | The price per million input and output tokens. Budget roughly 1,500 input and 400 output tokens per call, and 2 calls per case. |
| Rate limits | Requests per minute on your tier. |
| Latency | Measured in Step 6, not taken from marketing pages. |

**Local fallback:** use [Ollama](https://ollama.com) with a 7–8B instruction model. Ollama exposes an OpenAI-compatible endpoint at `http://localhost:11434/v1`.

## Step 2. Accounts, keys, and spending limits

1. Create the provider account under a **team** e-mail.
2. Generate an API key and store it only in `.env` (never commit it):

   ```dotenv
   LLM_PROVIDER=hosted
   LLM_BASE_URL=https://<provider-openai-compatible-base-url>/v1
   LLM_API_KEY=<secret>
   LLM_MODEL=<model-id-from-provider-docs>
   LLM_TIMEOUT_S=30
   LLM_MAX_RETRIES=1
   LLM_TEMPERATURE=0
   LLM_JSON_MODE=json_schema    # json_schema | json_object | prompt_only
   ```

3. Set a **monthly spending cap** and an alert at 50% in the provider console (roadmap risk register).
4. Add the new variables to `.env.example` with placeholder values. Add them to `Settings` in `app/core/config.py`.

**Check 2.** `git grep -n "LLM_API_KEY=" -- ':!*.example'` returns nothing.

## Step 3. Implement `backend/app/adapters/llm/hosted.py`

```python
"""OpenAI-compatible chat-completions adapter (M2)."""
from __future__ import annotations

import json
import re
import time

import httpx

from app.pipeline.errors import LLMInvalidOutput, LLMTimeout, LLMUnavailable

FENCE = re.compile(r"^`{3}(?:json)?\s*|\s*`{3}$")


class HostedLLMProvider:
    name = "hosted"

    def __init__(self, base_url: str, api_key: str | None, model_id: str,
                 temperature: float = 0.0, json_mode: str = "json_schema"):
        self.base_url = base_url.rstrip("/")
        self.model_id = model_id
        self.temperature = temperature
        self.json_mode = json_mode
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(headers=headers)
        self.last_usage: dict | None = None
        self.last_latency_ms: int | None = None

    @classmethod
    def from_settings(cls, settings, deps=None) -> "HostedLLMProvider":
        return cls(settings.LLM_BASE_URL, settings.LLM_API_KEY, settings.LLM_MODEL,
                   settings.LLM_TEMPERATURE, settings.LLM_JSON_MODE)

    def _response_format(self, json_schema: dict) -> dict | None:
        if self.json_mode == "json_schema":
            return {"type": "json_schema",
                    "json_schema": {"name": "triageai_output", "schema": json_schema, "strict": False}}
        if self.json_mode == "json_object":
            return {"type": "json_object"}
        return None  # prompt_only: the prompt itself demands JSON

    def complete_json(self, *, system: str, user: str, json_schema: dict, timeout_s: float) -> dict:
        body = {
            "model": self.model_id,
            "temperature": self.temperature,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
        }
        fmt = self._response_format(json_schema)
        if fmt:
            body["response_format"] = fmt
        start = time.perf_counter()
        try:
            resp = self._client.post(f"{self.base_url}/chat/completions", json=body, timeout=timeout_s)
        except httpx.TimeoutException as exc:
            raise LLMTimeout(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(str(exc)) from exc
        self.last_latency_ms = int((time.perf_counter() - start) * 1000)
        if resp.status_code in (408, 429) or resp.status_code >= 500:
            raise LLMUnavailable(f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise LLMUnavailable(f"HTTP {resp.status_code}: request rejected")  # e.g. bad model id
        data = resp.json()
        self.last_usage = data.get("usage")
        try:
            content = data["choices"][0]["message"]["content"]
            content = FENCE.sub("", content.strip()).strip()   # strip a markdown code fence if present
            return json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError) as exc:
            raise LLMInvalidOutput("model did not return valid JSON") from exc
```

Some providers reject `json_schema` in `response_format`. If so, set `LLM_JSON_MODE=json_object` or `prompt_only`. The Pydantic validation in M3 still guarantees correctness.

**Never log `system`, `user`, or `content`** (CLAUDE.md §9). Log only the model, latency, and token counts.

## Step 4. Implement `backend/app/adapters/llm/ollama.py`

```python
from app.adapters.llm.hosted import HostedLLMProvider


class OllamaLLMProvider(HostedLLMProvider):
    name = "ollama"

    @classmethod
    def from_settings(cls, settings, deps=None) -> "OllamaLLMProvider":
        return cls(settings.OLLAMA_BASE_URL, None, settings.OLLAMA_MODEL,
                   settings.LLM_TEMPERATURE, settings.OLLAMA_JSON_MODE)
```

Add `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, and `OLLAMA_JSON_MODE=json_object` to the settings and `.env.example`.

**Install and run Ollama on the host machine:**

```bash
# Linux:  curl -fsSL https://ollama.com/install.sh | sh
# Windows/macOS: install from https://ollama.com/download
ollama pull <model>          # e.g. a 7–8B instruct model; ~5 GB download, 8 GB RAM
ollama serve                 # if not already running as a service
curl http://localhost:11434/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model":"<model>","messages":[{"role":"user","content":"Reply with {\"ok\": true} as JSON"}],"response_format":{"type":"json_object"}}'
```

**Reach Ollama from the backend container:**

- Set `OLLAMA_BASE_URL=http://host.docker.internal:11434/v1`.
- On Linux, also add this to the `backend` service in `docker-compose.yml`:

  ```yaml
  extra_hosts: ["host.docker.internal:host-gateway"]
  ```

## Step 5. Connectivity script — `backend/scripts/llm_ping.py`

```python
import sys

from app.core.config import get_settings
from app.pipeline.registry import build_llm_provider  # or construct the class directly

schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
llm = build_llm_provider(get_settings())
out = llm.complete_json(system="You output only JSON.", user='Return {"ok": true}.',
                        json_schema=schema, timeout_s=30)
print(llm.name, llm.model_id, out, f"{llm.last_latency_ms} ms", llm.last_usage)
sys.exit(0 if out.get("ok") is True else 1)
```

If the registry has no `build_llm_provider`, construct `HostedLLMProvider.from_settings(get_settings())` directly.

**Check 5.** `docker compose exec backend python -m scripts.llm_ping` prints `{'ok': True}` for the hosted provider. Change `LLM_PROVIDER=ollama` and it works for Ollama too.

## Step 6. Selection spike (`spike/m2-llm-selection`)

1. Write `evaluation/spike/descriptions.yaml` with 10 **fictitious** descriptions covering:
   - the 4 demo cases
   - 1 case where staff translated the owner's wording and quoted an uncertain term
   - 1 case with a negation ("no blood")
   - 1 vague case ("parang matamlay")
   - 1 trauma case
   - 1 heat case
   - 1 toxin case
2. Use a *temporary* spike prompt, not the real extraction prompt. The real one comes in M3. Ask for this JSON:

   ```json
   {"primary_complaint": "<one of the 21 codes>", "duration": "<text or null>", "red_flags": ["..."]}
   ```

3. Write `backend/scripts/llm_spike.py`. For each candidate × description, run 3 times and record:
   - JSON valid (yes/no)
   - primary complaint correct (compare to your expected answer in the YAML)
   - latency in ms
   - input and output tokens

   Write the rows to `evaluation/results/spike_<date>.csv`. Print a summary per candidate:
   - validity %
   - accuracy %
   - latency p50 and p95
   - estimated cost per 100 cases
4. Fill in the decision table:

   | Candidate | JSON valid % | Complaint correct % | p50 ms | p95 ms | Cost / 100 cases | Data use OK? | Decision |
   |---|---|---|---|---|---|---|---|

   **Selection rule:**
   1. JSON validity of at least 90% and p50 of at most 5 s per call. Two calls must fit the 10-second NFR-01 median.
   2. Among the candidates that pass rule 1, choose the higher accuracy.
   3. On a tie, choose the lower cost.
5. Update `docs/adr/ADR-06.md`: change the status to *Accepted*, and add the table, the chosen model ID, and the date. Mark TBD-1 closed in the SRS TBD list for the next revision.

## Step 7. Registry and safety guard check

1. Set `LLM_PROVIDER=hosted` (still with `PIPELINE_EXTRACTOR=mock`) and restart. The app starts.
2. Temporarily set `PIPELINE_DEIDENTIFIER=mock` and restart. The app **must refuse to start** with the safety-guard error. Set it back to `rules`.
3. Add `backend/tests/unit/adapters/test_hosted_llm.py`. Use `httpx.MockTransport` to simulate each case and assert the mapped errors:
   - 200 with valid JSON → dict
   - 200 with invalid JSON → `LLMInvalidOutput`
   - 429 or 500 → `LLMUnavailable`
   - timeout → `LLMTimeout`

   These tests must **not** call the real API.

## Done when

- [ ] `llm_ping` works for both the hosted provider and Ollama.
- [ ] The adapter unit tests pass. The safety guard blocks the mock de-identifier with a real LLM.
- [ ] The spike CSV and ADR-06 are committed, with the model chosen.
- [ ] The spending cap is set, and no key is in Git.
