"""
Training data read from the LOSTFinder API.

`export_training_data()` builds the payload served by
GET /api/v1/ml/training-data/. `manage.py fetch_api_data` downloads that
payload over HTTP and saves it as a snapshot; `load_snapshot()` turns the
snapshot back into training examples:

- every match a user accepted (label 1) or rejected (label 0) becomes a
  labelled pair for the match model;
- every report becomes a (text, category) example for the category model.
"""

import json
from datetime import date
from types import SimpleNamespace

from django.conf import settings
from django.utils import timezone

from items.models import FoundItem, LostItem, MatchSuggestion


def snapshot_path():
    return settings.ML_DATA_DIR / "api_snapshot.json"


def _report(item, date_field):
    return {
        "id": item.pk,
        "title": item.title,
        "description": item.description,
        "location": item.location,
        "category": item.category.name,
        "date": getattr(item, date_field).isoformat(),
    }


def export_training_data():
    """Every report and every decided match, as JSON-safe data."""
    decided = MatchSuggestion.objects.exclude(status=MatchSuggestion.Status.PENDING)
    return {
        "generated_at": timezone.now().isoformat(),
        "lost_items": [
            _report(i, "date_lost") for i in LostItem.objects.select_related("category")
        ],
        "found_items": [
            _report(i, "date_found") for i in FoundItem.objects.select_related("category")
        ],
        "matches": [
            {"lost_id": m.lost_item_id, "found_id": m.found_item_id,
             "status": m.status, "score": m.score}
            for m in decided
        ],
    }


def save_snapshot(data, path=None):
    path = path or snapshot_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def read_snapshot(path=None):
    path = path or snapshot_path()
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _as_report(row, date_attr):
    return SimpleNamespace(
        title=row["title"], description=row["description"], location=row["location"],
        category_id=row["category"], **{date_attr: date.fromisoformat(row["date"])},
    )


def real_match_pairs(data):
    """(lost, found, label) pairs from the matches users decided on."""
    if not data:
        return []
    lost = {row["id"]: _as_report(row, "date_lost") for row in data["lost_items"]}
    found = {row["id"]: _as_report(row, "date_found") for row in data["found_items"]}
    pairs = []
    for match in data["matches"]:
        if match["lost_id"] in lost and match["found_id"] in found:
            label = 1 if match["status"] == MatchSuggestion.Status.ACCEPTED else 0
            pairs.append((lost[match["lost_id"]], found[match["found_id"]], label))
    return pairs


def real_category_samples(data):
    """(title, description, category) from every report."""
    if not data:
        return []
    return [
        (row["title"], row["description"], row["category"])
        for row in data["lost_items"] + data["found_items"]
    ]
