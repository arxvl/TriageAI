import re

import pytest

from app.pipeline.deidentify_rules import DeidentificationFailed, RuleBasedDeidentifier


@pytest.fixture
def deid():
    return RuleBasedDeidentifier()


# (case id, text, owner_name, owner_contact, must NOT appear, must still appear)
CASES = [
    # Owner names
    (
        "full name",
        "Owner Grace Cruz brought the dog in.",
        "Grace Cruz",
        None,
        ["Grace Cruz"],
        ["dog"],
    ),
    (
        "name part in a sentence",
        "Grace said the cat stopped eating.",
        "Grace Cruz",
        None,
        ["Grace"],
        ["cat", "stopped eating"],
    ),
    (
        "lowercase word equal to a name part survives",
        "The cat is recovering with grace.",
        "Grace Cruz",
        None,
        [],
        ["grace"],
    ),

    # Philippine mobile numbers
    (
        "mobile number format 1",
        "Owner contact: 09171234567",
        None,
        "09171234567",
        ["09171234567"],
        ["Owner contact"],
    ),
    (
        "mobile number format 2",
        "Call the owner at 0917-123-4567.",
        None,
        "0917-123-4567",
        ["0917-123-4567"],
        ["Call the owner"],
    ),
    (
        "mobile number format 3",
        "Contact: +63 917 123 4567",
        None,
        "+63 917 123 4567",
        ["+63 917 123 4567"],
        ["Contact"],
    ),
    (
        "mobile number format 4",
        "Owner phone: 639171234567",
        None,
        "639171234567",
        ["639171234567"],
        ["Owner phone"],
    ),

    # Landline
    (
        "landline with area code",
        "Home phone: (054) 123 4567",
        None,
        "(054) 123 4567",
        ["(054) 123 4567"],
        ["Home phone"],
    ),

    # Email
    (
        "email address",
        "Email the owner at grace.cruz@example.com.",
        None,
        "grace.cruz@example.com",
        ["grace.cruz@example.com"],
        ["Email the owner at"],
    ),

    # Address fragments
    (
        "address block and lot",
        "Owner lives at Blk 5 Lot 12.",
        None,
        None,
        ["Blk 5 Lot 12"],
        ["Owner lives at"],
    ),
    (
        "address barangay",
        "Address: Brgy. San Felipe.",
        None,
        None,
        ["Brgy. San Felipe"],
        ["Address"],
    ),
    (
        "address street",
        "The clinic is near 12 Magsaysay Ave.",
        None,
        None,
        ["12 Magsaysay Ave"],
        ["The clinic is near"],
    ),

    # Clinical numbers must remain
    (
        "vomiting frequency",
        "The dog vomited 5 times today.",
        None,
        None,
        [],
        ["vomited 5 times"],
    ),
    (
        "weight",
        "The cat weighs 4.2 kg.",
        None,
        None,
        [],
        ["4.2 kg"],
    ),
    (
        "age",
        "The dog is 3 years old.",
        None,
        None,
        [],
        ["3 years"],
    ),
    (
        "symptom time",
        "Vomiting started since 9 am.",
        None,
        None,
        [],
        ["since 9 am"],
    ),

    # Empty owner reference
    (
        "empty owner reference",
        "The dog vomited 5 times today.",
        None,
        None,
        [],
        ["The dog vomited 5 times today."],
    ),
]


@pytest.mark.parametrize("case_id,text,name,contact,absent,present",
                         CASES, ids=[c[0] for c in CASES])
def test_deidentify(deid, case_id, text, name, contact, absent, present):
    out = deid.deidentify(text, name, contact)
    for a in absent:
        assert a not in out, f"{a!r} should have been removed from {out!r}"
    for p in present:
        assert p in out, f"{p!r} should have been kept in {out!r}"


def test_fails_closed(deid, monkeypatch):
    monkeypatch.setattr(re, "sub", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(DeidentificationFailed):
        deid.deidentify("any text", "Grace Cruz", "09171234567")
