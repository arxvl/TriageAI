"""M2 step 6a: one tiny call. Proves URL, key, model name and JSON mode work."""

import sys

from app.core.config import get_settings
from scripts._llm import provider_from_settings

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def main() -> int:
    llm = provider_from_settings(get_settings())
    try:
        out = llm.complete_json(
            system="You output only JSON.",
            user='Return {"ok": true}.',
            json_schema=SCHEMA,
            timeout_s=60,
        )
    except Exception as exc:  # noqa: BLE001
        print("FAIL:", type(exc).__name__, exc)
        print("kind:", llm.last_error_kind, "| provider said:", llm.last_error_detail)
        return 1
    print(
        f"OK  provider={llm.name} model={llm.model_id} reply={out} "
        f"latency={llm.last_latency_ms} ms usage={llm.last_usage}"
    )
    return 0 if out.get("ok") is True else 1


if __name__ == "__main__":
    sys.exit(main())
