"""M2 step 8: is the provider stable at the configured temperature? (NFR-23)

Runs the same extraction N times. Exact-text differences are normal; what matters for
reproducibility is that the KEY FIELDS (primary complaint, red flags present) never change.
"""

import argparse
import collections
import json
import sys

from app.core.config import get_settings
from app.pipeline.types import ExtractionOutput
from scripts._llm import provider_from_settings
from scripts.llm_schema_check import TEXT


def key_fields(out: ExtractionOutput) -> tuple:
    primary = next((c.code for c in out.presenting_complaints if c.is_primary), None)
    return (primary, bool(out.red_flags), bool(out.negated_findings))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=8)
    runs = ap.parse_args().runs
    s = get_settings()
    llm = provider_from_settings(s)
    exact, keys = collections.Counter(), collections.Counter()
    for i in range(runs):
        try:
            raw = llm.complete_json(
                system=(
                    "You extract clinical facts from a pet owner's description. JSON only. "
                    "For list fields, use an empty list [] when there is nothing to "
                    "report, never null. "
                    "Only exposure_history, relevant_history, onset_duration and "
                    "frequency_severity may be null."
                ),
                user=f"Species: CAT\n\n<owner_description>\n{TEXT}\n</owner_description>",
                json_schema=ExtractionOutput.model_json_schema(),
                timeout_s=90,
            )
            out = ExtractionOutput.model_validate(raw)
        except Exception as exc:  # noqa: BLE001
            print(f"run {i + 1}: {type(exc).__name__} ({llm.last_error_kind})")
            continue
        exact[json.dumps(raw, sort_keys=True)] += 1
        keys[key_fields(out)] += 1
        print(f"run {i + 1}: key fields = {key_fields(out)}")
    done = sum(keys.values())
    print(
        f"\ntemperature sent: "
        f"{s.LLM_TEMPERATURE or '(none - provider default)'} | "
        f"seed: {s.LLM_SEED or '-'}"
    )
    print(f"successful runs: {done}/{runs}")
    print(f"distinct exact outputs: {len(exact)}   (several is normal)")
    print(f"distinct KEY-FIELD results: {len(keys)}")
    if done == 0:
        return 1
    if len(keys) == 1:
        print("VERDICT: key fields are stable.")
        return 0
    print(
        "VERDICT: key fields CHANGE between identical calls. See the guide, step 8, for what to do."
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
