"""The word lists the action validator screens tailored actions against (FR-74).

Data only: no regex, no matching, no imports. Every term a reviewer might want
to argue about lives here, and all the matching logic lives in
`app.pipeline.action_validator`. That split is deliberate — adding a drug name
should never mean touching the rules that decide urgency-adjacent text, and a
list of words is something a veterinarian can check without reading Python.

The lists come from P05b §5b.2 rules 3–5, which drew the drug names from the
project's triage reference. They are **not** meant to be complete: no block list
of medications ever is. They are the floor under FR-28, and the prompt (M6b) is
what is supposed to keep action text nowhere near them in the first place. A
rejection here means the prompt needs work, not that the list needs loosening
(ADR-18 §4).

False rejections are the accepted cost. ADR-18 records it: a sentence mentioning
an oxygen flow rate may trip the dose pattern, and that is safer than letting a
dose through.
"""

# --- Rule 4: medication names ---------------------------------------------
# Specific agents, from the project's triage reference. Matched on word
# boundaries, so `dextrose` fires and a word merely containing it would not.
DRUG_NAMES: tuple[str, ...] = (
    "butorphanol",
    "acepromazine",
    "dexmedetomidine",
    "propofol",
    "alfaxalone",
    "ketamine",
    "diazepam",
    "midazolam",
    "methocarbamol",
    "levetiracetam",
    "phenobarbital",
    "furosemide",
    "terbutaline",
    "albuterol",
    "dexamethasone",
    "mannitol",
    "dextrose",
    "calcium gluconate",
    "hypertonic saline",
)

# Classes rather than agents. "Start antibiotics" names no drug and is still a
# treatment instruction, which is exactly what FR-28 forbids.
GENERIC_DRUG_TERMS: tuple[str, ...] = (
    "antibiotic",
    "steroid",
    "sedative",
    "anaesthetic",
    "anesthetic",
    "analgesic",
    "nsaid",
)

# --- Rule 5: diagnosis terms ----------------------------------------------
# Blocked only when asserted as fact. The validator allows a hedged mention,
# because "ask whether a toxin was eaten" and "rule out obstruction" are triage
# questions, not diagnoses — see `HEDGE_TERMS`.
#
# Both spellings of hypoglycaemia are listed: the UI is English (FR-18) but the
# model's spelling is not something the validator should have to guess at.
DIAGNOSIS_TERMS: tuple[str, ...] = (
    "pneumonia",
    "pyometra",
    "gdv",
    "bloat",
    "obstruction",
    "parvovirus",
    "pancreatitis",
    "hypoglycaemia",
    "hypoglycemia",
    "cardiomyopathy",
    "pleural effusion",
    "pneumothorax",
    "asthma",
    "epilepsy",
    "poisoning",
)

# A diagnosis term within `HEDGE_WINDOW` words of one of these reads as a
# question or an instruction to watch, not as an assertion (P05b §5b.2 rule 5).
HEDGE_TERMS: tuple[str, ...] = (
    "possible",
    "suspected",
    "rule out",
    "ask",
    "check",
    "if",
    "whether",
    "monitor for",
    "watch for",
)

# --- Rule 3: dose expressions ---------------------------------------------
# Units that make a number a dose. Both micro signs are present: U+00B5 (micro
# sign) and U+03BC (Greek small letter mu) are visually identical and both turn
# up in copied clinical text.
#
# The spelled-out forms go beyond the abbreviation list in P05b §5b.2 rule 3,
# because "give 1 litre of fluids" is the same instruction as "give 1 L", and
# NFR-30 is about what a staff member reads rather than about how it was
# written. The pattern allows a plural `s`, so only the singular is listed.
DOSE_UNITS: tuple[str, ...] = (
    "mg",
    "mcg",
    "µg",
    "μg",
    "g",
    "ml",
    "l",
    "iu",
    "cc",
    "microgram",
    "milligram",
    "gram",
    "millilitre",
    "milliliter",
    "litre",
    "liter",
    "unit",
)

# Per-weight forms are a dose on their own, with or without a number attached.
DOSE_RATE_TERMS: tuple[str, ...] = ("mg/kg", "ml/kg", "mg/lb")

# Routes of administration. Only ever a dose signal when a number sits next to
# them: `in`, `po`, `im` and `io` are ordinary English words or fragments, so
# matching them bare would reject most of the usable action text there is.
DOSE_ROUTES: tuple[str, ...] = ("iv", "im", "sc", "sq", "po", "in", "io")

# Dosing frequencies. Unlike the routes these are not English words, so they are
# blocked on their own. `q4h`-style intervals are handled by a pattern.
DOSE_FREQUENCIES: tuple[str, ...] = ("bid", "tid", "sid", "qid", "prn")
