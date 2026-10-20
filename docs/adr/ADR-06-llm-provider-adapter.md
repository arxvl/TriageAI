# ADR-06: LLM access through a provider adapter, hosted API first

- **Requirements:** IR-12, IR-18, IR-19, NFR-01, NFR-09, NFR-28, SR-08
- **Related:** ADR-05, ADR-08, ADR-09, ADR-10, ADR-17

## Context

The system needs a transformer LLM for two tasks: extracting clinical entities
into JSON (FR-11) and generating a categorised, cited recommendation (FR-21).
The model has to be chosen with evidence, and the project must survive the model
being unavailable, rate-limited, too slow or too expensive — during a graded
demonstration.

Provider APIs also differ in how they enforce JSON output, and their terms of
service differ on whether submitted data may be used for training, which matters
under RA 10173 even with de-identified text (ADR-10).

## Decision

All model access goes through one narrow port:

```python
class LLMProvider(Protocol):
    name: str
    model_id: str

    def complete_json(
        self, *, system: str, user: str, json_schema: dict, timeout_s: float
    ) -> dict:
        ...
        # raises LLMTimeout, LLMUnavailable, LLMInvalidOutput
```

Implementations:

| `LLM_PROVIDER` | Class | Use |
|---|---|---|
| `mock` | `app.adapters.llm.mock:MockLLMProvider` | Default. Tests, CI, front-end work |
| `hosted` | `app.adapters.llm.hosted:HostedLLMProvider` | Primary. Any OpenAI-compatible chat-completions endpoint |
| `ollama` | `app.adapters.llm.ollama:OllamaLLMProvider` | Local fallback; subclass of the hosted adapter |

Rules:

- No pipeline code imports a provider SDK. Stages receive a `LLMProvider`.
- Transport errors are mapped to the three pipeline exceptions above, so the
  orchestrator's failure path is provider-independent (NFR-09).
- Temperature is set where the provider honours it and otherwise left at the provider default (see the amendment below); the prompt version is recorded with every output
  (ADR-14, NFR-23).
- Credentials come from `.env` only. Never committed, never logged.
- A monthly spending cap is set in the provider console.

## Selection record (TBD-1)

| Candidate | JSON valid % | Complaint correct % | Red-flag correct % | p50 ms | p95 ms | Stable across runs % | Cost / data terms | Decision |
|---|---:|---:|---:|---:|---:|---:|---|---|
| **Gemini (model ID: `gemini-3.5-flash-lite`)** | 97% | 69% | 100% | 925 | 46,695 | 90% | Free tier; prompts may be used to improve products | Best red-flag accuracy; investigate high p95 latency and rate-limit error |
| **Groq (model ID: `openai/gpt-oss-120b`)** | 100% | 70% | 83% | 3,324 | 8,491 | 90% | Free tier | Best JSON validity and complaint accuracy; strongest overall balance |
| **Local Ollama (model: `qwen2.5:3b-instruct`)** | 70% | 57% | 90% | 3,333 | 5,184 | 50% | Free; stays on the machine | Best privacy; improve JSON validity, complaint accuracy, and consistency |

### Evaluation Notes

- **Gemini:** 30 calls; 1 rate-limit error.
- **Groq:** 30 calls; no errors.
- **Ollama:** 30 calls; no errors.
- Latency measurements are in milliseconds.
- Stability is based on descriptions consistent across three runs, out of 10 descriptions.

### Recommendation

Groq is the strongest initial candidate for a balanced deployment because it achieved 100% JSON validity, 70% complaint accuracy, and 90% stability, with substantially lower p95 latency than Gemini.

However, Gemini's 100% red-flag accuracy makes it worth further testing for safety-critical red-flag detection. These results are based on a small evaluation set, so validate them on a larger representative dataset before making a production decision.

## Consequences

**Positive**

- Switching providers is a settings change plus one adapter file, not a pipeline
  rewrite.
- The mock provider lets the entire application — and CI — run with no API key,
  no cost and deterministic results.
- The local Ollama path means an outage or an exhausted quota does not stop the
  PD8 demonstration.

**Negative**

- The adapter is limited to a chat-completions-shaped interface. A provider with
  a very different API needs its own adapter class.
- JSON-mode support varies, so `LLM_JSON_MODE` (`json_schema`, `json_object`,
  `prompt_only`) exists and must be set per provider. Pydantic validation is what
  actually guarantees the contract.
- A local model on the evaluation VM needs RAM the hosted path does not
  (ADR-13).

## Alternatives considered

| Option | Why rejected |
|---|---|
| Call one provider SDK directly from the pipeline | Vendor lock-in; no mock path; every test would need network access |
| Local model only | Slower on CPU, weaker JSON adherence, and heavier hardware requirements for the evaluation server |
| LangChain or similar framework | Large dependency surface for two prompt calls; hides the retry and error mapping the safety design depends on |

## Amendment, 2026-10-12: temperature and free-tier terms

- **Temperature is not fixed at 0.** It is set where the provider honours it (Groq, local Ollama) and **left blank, meaning the
  provider default, for the Gemini 3 family**, where Google recommends 1.0 and one third-party report says lower values are
  silently ignored from Gemini 3.6 onward. Reproducibility (NFR-23) is therefore **measured per candidate** (M2 Step 9), not assumed.
- **Free-tier use is limited to fictitious or de-identified text.** Free tiers may use submitted text to improve provider
  products, and Google's free-tier terms allow human review. A clinical deployment requires a paid no-training agreement or a
  self-hosted model. This is a stated limitation of the project.
- **The adapter rate-limits itself** (`LLM_MAX_RPM`) and honours `Retry-After`, because free tiers throttle by requests per minute
  and per day. A daily-quota 429 fails fast instead of holding a job (`LLM_RATE_LIMIT_WAIT_S`).
- **The schema is repeated in the prompt** (`LLM_SCHEMA_IN_PROMPT`), so providers without schema enforcement still work, and the
  Pydantic validation in M3 remains the actual guarantee of correctness.
