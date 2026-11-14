"""
Synthetic campus lost-and-found data.

A real campus produces only a handful of decided matches, far too few to
train on, so we simulate the process that creates the data:

1. An object exists (category, kind, brand, colour, a distinguishing detail).
2. Its owner loses it somewhere on campus and writes a *lost* report in
   their own words.
3. Someone else finds it nearby, a few days later, and writes a *found*
   report in different words, often missing details or with small errors.

A lost/found pair describing the same object is a positive example (1).
Negatives (0) pair reports of different objects; "hard" negatives share
the category and kind but differ in colour, brand, place or time.

All randomness goes through a seeded random.Random, so a training run is
reproducible.
"""

import random
from datetime import date, timedelta
from types import SimpleNamespace


CATEGORY_SPECS = {
    "Electronics": {
        "kinds": {
            "laptop": ["laptop", "notebook computer", "laptop computer"],
            "phone": ["phone", "smartphone", "mobile phone"],
            "earbuds": ["earbuds", "wireless earphones", "earbuds case"],
            "charger": ["charger", "power adapter", "charging cable"],
            "tablet": ["tablet", "iPad", "tablet computer"],
            "power bank": ["power bank", "portable battery"],
        },
        "brands": ["Apple", "Samsung", "Dell", "HP", "Lenovo", "Sony", "Tecno", "Infinix", "JBL"],
        "details": [
            "with a cracked screen corner", "with a sticker on the back",
            "in a clear silicone case", "with a scratched edge",
            "with engraved initials", "with a blue sticker near the hinge",
            "in a black leather case", "with a small dent on one side",
        ],
    },
    "ID Cards": {
        "kinds": {
            "student id": ["student ID card", "student card", "university ID"],
            "staff id": ["staff ID card", "staff badge", "employee card"],
            "bank card": ["bank card", "debit card", "ATM card"],
            "library card": ["library card", "library pass"],
        },
        "brands": ["University", "Equity", "BK", "Campus", "Faculty"],
        "details": [
            "on a blue lanyard", "in a plastic holder", "with Economics printed on it",
            "with Engineering faculty printed", "on a red lanyard", "with a photo of a young man",
            "with a photo of a young woman", "in a card sleeve",
        ],
    },
    "Keys": {
        "kinds": {
            "key bunch": ["bunch of keys", "set of keys", "keys on a ring"],
            "car key": ["car key", "car remote key", "vehicle key fob"],
            "key card": ["key card", "room access card", "door card"],
            "padlock key": ["padlock key", "locker key"],
        },
        "brands": ["Toyota", "Honda", "Hostel", "Yale", "Suzuki"],
        "details": [
            "with a red keyring", "with three keys on a ring", "with a bottle-opener keychain",
            "with a small teddy bear keychain", "with a numbered tag", "with a football keyring",
        ],
    },
    "Water Bottles": {
        "kinds": {
            "bottle": ["water bottle", "bottle", "drinking bottle"],
            "tumbler": ["tumbler", "insulated tumbler", "travel mug"],
            "flask": ["flask", "thermos flask", "vacuum flask"],
        },
        "brands": ["Hydro Flask", "Stanley", "Contigo", "Nalgene", "Milton"],
        "details": [
            "with a dent near the base", "covered in stickers", "missing its lid strap",
            "with a silver rim", "with a straw lid", "with a name written on tape",
        ],
    },
    "Apparel": {
        "kinds": {
            "jacket": ["jacket", "rain jacket", "windbreaker"],
            "hoodie": ["hoodie", "hooded sweatshirt", "sweater"],
            "scarf": ["scarf", "wool scarf"],
            "cap": ["cap", "baseball cap", "hat"],
            "sweater": ["jumper", "cardigan", "pullover"],
        },
        "brands": ["Nike", "Adidas", "Zara", "North Face", "Puma", "H&M"],
        "details": [
            "with a torn zip pocket", "with a name tag inside the collar", "size M",
            "size L", "with a university logo", "with a stain on the sleeve",
        ],
    },
    "Textbooks": {
        "kinds": {
            "textbook": ["textbook", "course book", "book"],
            "notebook": ["notebook", "exercise book", "spiral notebook"],
            "lab manual": ["lab manual", "practical manual"],
            "novel": ["novel", "paperback"],
        },
        "brands": ["Calculus", "Organic Chemistry", "Microeconomics", "Data Structures",
                   "Physics", "Accounting"],
        "details": [
            "with highlighted pages", "with a name written inside the cover",
            "with a coffee stain on the cover", "with lecture notes tucked inside",
            "with a torn spine", "with sticky notes on many pages",
        ],
    },
    "Bags": {
        "kinds": {
            "backpack": ["backpack", "school bag", "rucksack"],
            "tote": ["tote bag", "shopping bag", "canvas bag"],
            "laptop sleeve": ["laptop sleeve", "laptop bag", "laptop case"],
            "handbag": ["handbag", "purse", "shoulder bag"],
        },
        "brands": ["JanSport", "Herschel", "Samsonite", "Nike", "Adidas", "Targus"],
        "details": [
            "with a broken zip", "with a keychain attached", "with a patch on the front",
            "with a water bottle pocket", "with books inside", "with a laptop compartment",
        ],
    },
    "Other": {
        "kinds": {
            "umbrella": ["umbrella", "folding umbrella"],
            "glasses": ["glasses", "spectacles", "sunglasses"],
            "wallet": ["wallet", "card wallet", "leather wallet"],
            "watch": ["watch", "wristwatch", "smart watch"],
            "calculator": ["calculator", "scientific calculator"],
        },
        "brands": ["Ray-Ban", "Casio", "Fossil", "Xiaomi", "Tommy Hilfiger"],
        "details": [
            "in a hard case", "with a broken strap", "with a scratched lens",
            "with initials on it", "with a few coins inside", "with a cracked face",
        ],
    },
}

COLOURS = ["black", "white", "grey", "silver", "red", "blue", "navy", "green",
           "yellow", "pink", "purple", "brown", "beige", "maroon"]

# Colours people confuse: a finder may say "grey" for a silver item.
SIMILAR_COLOURS = {
    "black": "navy", "navy": "black", "grey": "silver", "silver": "grey",
    "brown": "beige", "beige": "brown", "red": "maroon", "maroon": "red",
    "purple": "pink", "pink": "purple", "blue": "navy", "white": "beige",
}

CAMPUS = {
    "Main Library": ["2nd floor printer", "reading room", "ground floor entrance", "study carrels"],
    "Cafeteria": ["table near the window", "food counter", "outdoor seating"],
    "Forum amphitheater": ["stairs", "back row", "stage area"],
    "Science Block": ["lab 3", "lecture hall B", "corridor lockers"],
    "Sports Complex": ["changing room", "basketball court", "gym entrance"],
    "Engineering Building": ["computer lab", "room 204", "workshop"],
    "Student Centre": ["lounge", "bookshop", "ATM area"],
    "Parking Lot B": ["near the gate", "bus stop", "motorbike parking"],
    "Hostel A": ["common room", "laundry room", "reception"],
}

LOST_TITLES = [
    "{colour} {brand} {noun}", "Lost {colour} {noun}", "{brand} {noun}",
    "My {colour} {noun}", "{colour} {noun} ({brand})",
]
FOUND_TITLES = [
    "{colour} {noun}", "Found {noun}", "{colour} {brand} {noun}",
    "{noun} found", "{colour} {noun} left behind",
]
LOST_DESCRIPTIONS = [
    "I lost my {colour} {brand} {noun} {detail}. I last had it at the {spot} in the {zone}.",
    "{colour} {brand} {noun} {detail}. I think I left it in the {zone} near the {spot}. Please contact me if found.",
    "Lost a {brand} {noun}, {colour}, {detail}. Last seen at {zone}, {spot}.",
    "My {noun} is missing. It is {colour}, made by {brand}, {detail}. Probably dropped around the {zone}.",
]
FOUND_DESCRIPTIONS = [
    "Found a {colour} {noun} {detail} left at the {zone} {spot}. Handed to the security desk.",
    "{colour} {noun} found on the {spot} of the {zone}. {detail_sentence}",
    "Someone left a {colour} {brand} {noun} at the {zone} ({spot}). {detail_sentence}",
    "Picked up a {noun}, {colour}, near the {spot} in the {zone}.",
]

START_DATE = date(2025, 9, 1)


def all_categories():
    return list(CATEGORY_SPECS)


def random_object(rng, category=None):
    """An imaginary object someone could lose."""
    category = category or rng.choice(all_categories())
    spec = CATEGORY_SPECS[category]
    kind = rng.choice(list(spec["kinds"]))
    zone = rng.choice(list(CAMPUS))
    return SimpleNamespace(
        category=category,
        kind=kind,
        brand=rng.choice(spec["brands"]),
        colour=rng.choice(COLOURS),
        detail=rng.choice(spec["details"]),
        zone=zone,
        spot=rng.choice(CAMPUS[zone]),
        day=START_DATE + timedelta(days=rng.randrange(0, 420)),
    )


def _noun(rng, obj):
    return rng.choice(CATEGORY_SPECS[obj.category]["kinds"][obj.kind])


def _fill(template, **values):
    text = template.format(**values)
    text = " ".join(text.split())
    return text[0].upper() + text[1:]


def lost_report(rng, obj, category_noise=0.05):
    """The owner's description: detail-rich, their own wording."""
    category = obj.category
    if rng.random() < category_noise:
        category = rng.choice(all_categories())
    values = dict(colour=obj.colour, brand=obj.brand, noun=_noun(rng, obj),
                  detail=obj.detail, zone=obj.zone, spot=obj.spot)
    return SimpleNamespace(
        title=_fill(rng.choice(LOST_TITLES), **values),
        description=_fill(rng.choice(LOST_DESCRIPTIONS), **values),
        location=f"{obj.zone} {obj.spot}",
        category_id=category,
        date_lost=obj.day,
    )


def found_report(rng, obj, category_noise=0.12):
    """
    The finder's description of the same object: different words, may miss
    the brand or detail, may misjudge the colour or report a nearby spot,
    and may pick a different category (often "Other").
    """
    colour = obj.colour
    if rng.random() < 0.12:
        colour = SIMILAR_COLOURS.get(colour, colour)

    zone, spot = obj.zone, obj.spot
    roll = rng.random()
    if roll < 0.25:
        spot = rng.choice(CAMPUS[zone])          # same building, another spot
    elif roll < 0.33:
        zone = rng.choice(list(CAMPUS))          # carried somewhere else
        spot = rng.choice(CAMPUS[zone])

    category = obj.category
    if rng.random() < category_noise:
        category = "Other" if rng.random() < 0.6 else rng.choice(all_categories())

    # Usually found the same day or soon after; occasionally reported late,
    # and sometimes the owner reports the loss after it was turned in.
    delay = rng.choices([0, 1, 2, 3, 5, 7, 12, 20, -2],
                        weights=[24, 22, 14, 10, 8, 7, 5, 3, 7])[0]

    brand = obj.brand if rng.random() < 0.55 else ""
    detail = obj.detail if rng.random() < 0.6 else ""
    values = dict(colour=colour, brand=brand, noun=_noun(rng, obj), detail=detail,
                  detail_sentence=f"It is {detail}." if detail else "",
                  zone=zone, spot=spot)
    return SimpleNamespace(
        title=_fill(rng.choice(FOUND_TITLES), **values),
        description=_fill(rng.choice(FOUND_DESCRIPTIONS), **values),
        location=f"{zone} {spot}",
        category_id=category,
        date_found=obj.day + timedelta(days=delay),
    )


def _hard_negative(rng, obj):
    """A different object that looks similar: same category and kind."""
    other = random_object(rng, obj.category)
    other.kind = obj.kind
    changes = rng.sample(["colour", "brand", "place", "time", "detail"], k=rng.randint(2, 4))
    if "colour" not in changes:
        other.colour = obj.colour
    if "brand" not in changes:
        other.brand = obj.brand
    if "detail" not in changes:
        other.detail = obj.detail
    if "place" not in changes:
        other.zone, other.spot = obj.zone, obj.spot
    if "time" not in changes:
        other.day = obj.day
    else:
        other.day = obj.day + timedelta(days=rng.choice([-1, 1]) * rng.randint(15, 90))
    return other


def match_pairs(n_objects=1500, seed=42, negatives_per_positive=2):
    """
    Labelled (lost, found, label) pairs: one positive per object plus
    `negatives_per_positive` negatives (half of them hard).
    """
    rng = random.Random(seed)
    objects = [random_object(rng) for _ in range(n_objects)]
    pairs = []
    for obj in objects:
        lost = lost_report(rng, obj)
        pairs.append((lost, found_report(rng, obj), 1))
        for n in range(negatives_per_positive):
            if n % 2 == 0:
                other = _hard_negative(rng, obj)
            else:
                other = rng.choice(objects)
                if other is obj:
                    continue
                if rng.random() < 0.5:
                    # A busy campus: unrelated items turn up the same week.
                    other = SimpleNamespace(**vars(other))
                    other.day = obj.day + timedelta(days=rng.randint(-3, 10))
            pairs.append((lost, found_report(rng, other), 0))
    rng.shuffle(pairs)
    return pairs


VAGUE_TITLES = [
    "Lost item", "Found item", "Something {colour}", "{colour} item left behind",
    "{brand} item", "Item found at {zone}", "Missing {colour} thing",
]
VAGUE_DESCRIPTIONS = [
    "A {colour} item {detail}, left at the {zone} near the {spot}.",
    "Found something {colour} by {brand} at the {zone}. {detail_sentence}",
    "I lost a {colour} {brand} item around the {zone}. It is {detail}.",
    "Left behind at {spot}, {zone}. Not sure what it is exactly, {colour}.",
]

# Brands and details that also belong to another category, so the words
# alone do not always give the answer away.
SHARED_WORDS = {
    "Bags": "laptop", "Electronics": "case", "ID Cards": "wallet",
    "Other": "card", "Apparel": "bag", "Keys": "card",
}


def category_samples(n=3000, seed=7, vague_rate=0.12, label_noise=0.04):
    """
    (title, description, category) reports for the category model.

    Like real reports, some are vague (no item noun at all), some borrow a
    word from another category, and a few carry the wrong category because
    the reporter picked it.
    """
    rng = random.Random(seed)
    samples = []
    for _ in range(n):
        obj = random_object(rng)
        if rng.random() < vague_rate:
            detail = obj.detail if rng.random() < 0.5 else ""
            values = dict(colour=obj.colour, brand=obj.brand, detail=detail,
                          detail_sentence=f"It is {detail}." if detail else "",
                          zone=obj.zone, spot=obj.spot)
            title = _fill(rng.choice(VAGUE_TITLES), **values)
            description = _fill(rng.choice(VAGUE_DESCRIPTIONS), **values)
        else:
            report = lost_report(rng, obj, 0) if rng.random() < 0.5 else found_report(rng, obj, 0)
            title, description = report.title, report.description
            if rng.random() < 0.15 and obj.category in SHARED_WORDS:
                description += f" There is a {SHARED_WORDS[obj.category]} with it."

        category = obj.category
        if rng.random() < label_noise:
            category = rng.choice(all_categories())
        samples.append((title, description, category))
    return samples
