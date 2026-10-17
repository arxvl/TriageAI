"""Keyword red-flag screener (M1). Deterministic; runs before any LLM call (NFR-05)."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import yaml

from app.pipeline.types import RedFlagHit

NEGATORS = {"no", "not", "never", "without", "none", "denies"}
PHRASES_PATH = Path("/knowledge_base/red_flag_phrases.yaml")  # mounted in Step 6


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9' ]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


class KeywordRedFlagScreener:
    model_id = "keywords"
    prompt_version = "redflag-phrases-v2"  # bump when the YAML changes
    last_latency_ms = 0

    def __init__(self, phrases: dict, rules_provider):
        self._rules_provider = rules_provider
        self._compiled = {
            code: {
                "negatable": spec.get("negatable", False),
                "requires": spec.get("requires", {}) or {},
                "patterns": [
                    re.compile(rf"\b{re.escape(normalize(p))}\b") for p in spec["phrases"]
                ],
            }
            for code, spec in phrases.items()
        }

    @classmethod
    def from_settings(cls, settings, deps) -> KeywordRedFlagScreener:
        with open(PHRASES_PATH, encoding="utf-8") as fh:
            phrases = yaml.safe_load(fh)
        return cls(phrases, deps.rules_provider)

    def screen(self, text: str, species, sex: str | None) -> list[RedFlagHit]:
        norm = normalize(text)
        active = {r.code: r for r in self._rules_provider()}
        hits: list[RedFlagHit] = []
        for code, spec in self._compiled.items():
            rule = active.get(code)
            if rule is None:  # rule not approved or retired → never fires
                continue
            req = spec["requires"]
            if req.get("species") and req["species"] != getattr(species, "value", species):
                continue
            if req.get("sex") and sex not in (None, "UNKNOWN", req["sex"]):
                continue  # unknown sex still triggers, on purpose
            for pat in spec["patterns"]:
                m = pat.search(norm)
                if not m:
                    continue
                if spec["negatable"]:
                    preceding = norm[: m.start()].split(" ")[-4:-1]
                    if NEGATORS.intersection(preceding):
                        continue
                hits.append(
                    RedFlagHit(
                        rule_code=code, matched_text=m.group(0), min_category=rule.min_category
                    )
                )
                break  # one hit per rule
        return hits
