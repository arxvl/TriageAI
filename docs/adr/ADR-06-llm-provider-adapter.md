# ADR-06: LLM access through a provider adapter, hosted API first

- **Status:** Accepted (model selection recorded in the decision log below)
- **Requirements:** IR-12, IR-18, IR-19, NFR-01, NFR-09, NFR-28, SR-08
- **Open item:** TBD-1 is closed once the selection table below is filled in
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
    def complete_json(self, *, system: str, user: str,
                      json_schema: dict, timeout_s: float) -> dict: ...
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
- Temperature is 0 and the prompt version is recorded with every output
  (ADR-14, NFR-23).
- Credentials come from `.env` only. Never committed, never logged.
- A monthly spending cap is set in the provider console.

## Selection record (TBD-1)

Fill in from the M2 spike (`evaluation/results/spike_<date>.csv`), 10 fictitious
descriptions, 3 runs each:

| Candidate | JSON valid % | Complaint correct % | p50 ms | p95 ms | Cost / 100 cases | Data used for training? | Decision |
|---|---|---|---|---|---|---|---|
| *(hosted candidate A)* | | | | | | | |
| *(hosted candidate B)* | | | | | | | |
| *(local 7–8B via Ollama)* | | | | | | | |

Selection rule, in order: JSON validity at least 90% and p50 at most 5 s per
call; then higher accuracy; then lower cost.

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
