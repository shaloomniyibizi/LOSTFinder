"""
Turn a (lost report, found report) pair into numbers a model can learn from.

The same function is used for training (synthetic pairs and pairs read from
the API) and for live predictions (real LostItem / FoundItem rows), so the
model always sees features computed the same way.

A "report" is anything with title, description, location, category_id and
date_lost / date_found attributes: a model instance or a SimpleNamespace.
"""

from items.matching import normalize_text, text_similarity


COLOURS = {
    "black", "white", "grey", "gray", "silver", "gold", "red", "blue", "navy",
    "green", "yellow", "orange", "pink", "purple", "brown", "beige", "maroon",
    "teal", "cream",
}

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "on", "in", "at", "to", "with", "my",
    "i", "it", "is", "was", "for", "near", "by", "from", "has", "had", "left",
    "lost", "found", "item", "this", "that", "some", "one", "last", "small",
    "please", "contact", "me", "if", "its", "be", "were", "am", "handed",
    "security", "desk", "turned",
}

MAX_DAYS = 60

# Order matters: it is the column order of the feature matrix.
FEATURE_NAMES = [
    "same_category",
    "title_similarity",
    "description_similarity",
    "location_similarity",
    "full_text_similarity",
    "keyword_overlap",
    "shared_colours",
    "colour_conflict",
    "days_apart",
    "found_before_lost",
]

FEATURE_LABELS = {
    "same_category": "Same category",
    "title_similarity": "Title similarity",
    "description_similarity": "Description similarity",
    "location_similarity": "Location similarity",
    "full_text_similarity": "Overall text similarity",
    "keyword_overlap": "Shared keywords",
    "shared_colours": "Shared colours",
    "colour_conflict": "Different colours",
    "days_apart": "Days between reports",
    "found_before_lost": "Found before it was lost",
}


def _keywords(*texts):
    words = set()
    for text in texts:
        words.update(w for w in normalize_text(text) if w not in STOPWORDS and len(w) > 1)
    return words


def _colours(*texts):
    found = set()
    for text in texts:
        found.update(w for w in normalize_text(text) if w in COLOURS)
    # "grey" and "gray" are the same colour.
    return {"grey" if c == "gray" else c for c in found}


def pair_features(lost, found):
    """Return the feature vector (a list of floats) for one pair."""
    lost_text = f"{lost.title} {lost.description}"
    found_text = f"{found.title} {found.description}"

    lost_words = _keywords(lost_text)
    found_words = _keywords(found_text)
    union = lost_words | found_words
    keyword_overlap = len(lost_words & found_words) / len(union) if union else 0.0

    lost_colours = _colours(lost_text)
    found_colours = _colours(found_text)
    shared_colours = len(lost_colours & found_colours)
    colour_conflict = float(bool(lost_colours and found_colours and not shared_colours))

    lost_date = getattr(lost, "date_lost", None)
    found_date = getattr(found, "date_found", None)
    if lost_date and found_date:
        delta = (found_date - lost_date).days
        days_apart = min(abs(delta), MAX_DAYS)
        found_before_lost = float(delta < -1)
    else:
        days_apart, found_before_lost = MAX_DAYS, 0.0

    return [
        float(lost.category_id == found.category_id),
        text_similarity(lost.title, found.title),
        text_similarity(lost.description, found.description),
        text_similarity(lost.location, found.location),
        text_similarity(lost_text, found_text),
        keyword_overlap,
        float(shared_colours),
        colour_conflict,
        float(days_apart),
        found_before_lost,
    ]


def category_text(item):
    """The text the category model reads."""
    return f"{item.title}. {item.description}"
