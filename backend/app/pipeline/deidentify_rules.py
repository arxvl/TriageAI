from __future__ import annotations

import re

from app.pipeline.errors import PipelineError

class DeidentificationFailed(PipelineError):
    pass

PH_MOBILE = re.compile(r"(?<!\d)(?:\+?63|0)\s?9\d{2}[\s-]?\d{3}[\s-]?\d{4}(?!\d)")
LANDLINE = re.compile(r"(?<!\d)(?:\(0\d{1,2}\)|0\d{1,2})?[\s-]?\d{3,4}[\s-]\d{4}(?!\d)")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ADDRESS = re.compile(
    r"\b(?:(?:blk|block|lot|purok|zone)\.?\s*\d+[A-Za-z]?"
    r"|(?:brgy|barangay|sitio)\.?\s+[A-Z][\w-]*(?:\s[A-Z][\w-]*)?"
    r"|\d+\s+[A-Z][\w.-]*(?:\s[A-Z][\w.-]*)*\s(?:St|Street|Ave|Avenue|Road|Rd)\b\.?)",
    re.IGNORECASE,
)

def _digits_pattern(number: str) -> re.Pattern[str] | None:
    digits = re.sub(r"\D", "", number or "")
    if len(digits) < 7:
        return None
    return re.compile(r"[\s-]?".join(re.escape(d) for d in digits))

class RuleBasedDeidentifier:
    model_id = "rules"            # stage attributes required by CLAUDE.md §8.2
    prompt_version = "deidentify-rules-v1"
    last_latency_ms = 0

    @classmethod
    def from_settings(cls, settings, deps) -> "RuleBasedDeidentifier":
        return cls()

    def deidentify(self, text: str, owner_name: str | None, owner_contact: str | None) -> str:
        try:
            out = text
            if owner_name and owner_name.strip():
                full = owner_name.strip()
                out = re.sub(re.escape(full), "[OWNER]", out, flags=re.IGNORECASE)
                for part in re.split(r"\s+", full):
                    if len(part) >= 3 and part[0].isalpha():
                        cap = part[0].upper() + part[1:]
                        out = re.sub(rf"\b{re.escape(cap)}\b", "[OWNER]", out)
            if owner_contact:
                pat = _digits_pattern(owner_contact)
                if pat:
                    out = pat.sub("[PHONE]", out)
            out = EMAIL.sub("[EMAIL]", out)
            out = PH_MOBILE.sub("[PHONE]", out)
            out = LANDLINE.sub("[PHONE]", out)
            out = ADDRESS.sub("[ADDRESS]", out)
        except Exception as exc:  # fail closed (ADR-10)
            raise DeidentificationFailed("de-identification error") from exc

        # Final safety check: nothing that still looks like a phone or e-mail may pass.
        if EMAIL.search(out) or PH_MOBILE.search(out):
            raise DeidentificationFailed("identifier remained after de-identification")
        return out
