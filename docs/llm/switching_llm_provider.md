# STEP 1

## Gemini

LLM_PROVIDER=hosted
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_API_KEY=<your Gemini key>
LLM_MODEL=<the exact model ID from your spike>
LLM_TEMPERATURE=
LLM_REASONING_EFFORT=low
LLM_JSON_MODE=json_schema
LLM_MAX_RPM=<~80% of your console's RPM limit>

## Groq

LLM_PROVIDER=hosted
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=<your Groq key>
LLM_MODEL=<the exact model ID from your spike>
LLM_TEMPERATURE=0
LLM_JSON_MODE=json_object
LLM_MAX_RPM=<~80% of your console's RPM limit>

## Ollama

LLM_PROVIDER=ollama
OLLAMA_MODEL=<your model>
OLLAMA_JSON_MODE=json_schema
LLM_TIMEOUT_S=90


# STEP 2

## Restart the backend
```bash
docker compose up -d --force-recreate backend
```

# STEP 3

## Verify it actually switched
```bash
docker compose exec backend python -c "from app.core.config import get_settings; s=get_settings(); print(s.LLM_PROVIDER, s.LLM_MODEL)"
docker compose exec backend python -m scripts.llm_ping
docker compose exec backend pytest -q
```

# STEP 4

## Confirm the safety guard still holds
Temporarily set PIPELINE_DEIDENTIFIER=mock, recreate the backend, and confirm it refuses to start. Then set it back to rules and recreate again. This is the one check in Step 12 that’s easy to skip and shouldn’t be.
