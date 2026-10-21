CASES = [
    {
        "species": "DOG",
        "text": (
            "My dog is panting heavily and gasping for air. He is having difficulty breathing."
        ),
        "expected_entry_title": "Respiratory Distress in Dogs and Cats",
        "expected_category": "RED",
    },
    {
        "species": "CAT",
        "text": (
            "My cat has been repeatedly going to the litter box "
            "since this morning, but nothing comes out."
        ),
        "expected_entry_title": "Urinary Obstruction in Cats",
        "expected_category": "ORANGE",
    },
    {
        "species": "DOG",
        "text": (
            "My dog has had a small itchy patch on his back leg for a few months. "
            "It comes and goes but hasn't gotten any worse, and he's eating and "
            "acting completely normal otherwise."
        ),
        "expected_entry_title": "Itching (Pruritus) in Dogs",
        "expected_category": "BLUE",
    },
]
