"""M2 step 6b: does the provider accept our REAL extraction schema (nested, nullable fields)?"""

import sys

from app.core.config import get_settings
from app.pipeline.types import ExtractionOutput
from scripts._llm import provider_from_settings

TEXT = (
    "Male cat, 3 years old. Since this morning he keeps going to the litter box and cries, "
    "but nothing comes out. He vomited twice. No blood seen."
)


def main() -> int:
    llm = provider_from_settings(get_settings())
    try:
        raw = llm.complete_json(
            system="You extract clinical facts from a pet owner's description for a veterinary "
            "clinic. Output JSON only. Do not diagnose. For any list field with nothing "
            "to report, output an empty list [], never null.",
            user=f"Species: CAT\n\n<owner_description>\n{TEXT}\n</owner_description>",
            json_schema=ExtractionOutput.model_json_schema(),
            timeout_s=90,
        )
        out = ExtractionOutput.model_validate(raw)
    except Exception as exc:  # noqa: BLE001
        print("FAIL:", type(exc).__name__, str(exc)[:300])
        print("kind:", llm.last_error_kind, "| provider said:", llm.last_error_detail)
        print(
            "Try, in this order: LLM_SCHEMA_SIMPLIFY=true -> LLM_JSON_MODE=json_object "
            "-> LLM_JSON_MODE=prompt_only"
        )
        return 1
    print("OK  schema accepted and the answer validates as ExtractionOutput")
    print("complaints:", [(c.code, c.is_primary) for c in out.presenting_complaints])
    print("negated:", out.negated_findings, "| red_flags:", out.red_flags)
    print(f"latency={llm.last_latency_ms} ms usage={llm.last_usage}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
