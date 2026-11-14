"""
Live predictions with the saved models.

Models are loaded lazily and cached per process; the cache is keyed on the
file's modification time, so a retrain (from the dashboard or the command
line) is picked up without restarting the server.

Every function returns None when ML is switched off (settings.ML_ENABLED)
or no model has been trained yet, and callers fall back to the rule-based
behaviour.
"""

import logging
import threading

import joblib
from django.conf import settings

from .features import pair_features
from .models import ModelVersion
from .training import model_path


logger = logging.getLogger(__name__)

_cache = {}
_lock = threading.Lock()


def load(kind):
    """The {"model", "meta"} bundle for `kind`, or None."""
    if not getattr(settings, "ML_ENABLED", True):
        return None
    path = model_path(kind)
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return None

    with _lock:
        cached = _cache.get(kind)
        if cached and cached[0] == (str(path), mtime):
            return cached[1]
        try:
            bundle = joblib.load(path)
        except Exception:  # a corrupt or incompatible file must not break saving reports
            logger.exception("Could not load the %s model from %s", kind, path)
            return None
        _cache[kind] = ((str(path), mtime), bundle)
        return bundle


def model_info(kind):
    bundle = load(kind)
    return bundle["meta"] if bundle else None


def match_probabilities(pairs):
    """
    Probability that each (lost, found) pair is the same object, as a list
    of floats in the same order, or None when no match model is available.
    """
    bundle = load(ModelVersion.Kind.MATCH)
    if bundle is None or not pairs:
        return None if bundle is None else []
    rows = [pair_features(lost, found) for lost, found in pairs]
    return [float(p) for p in bundle["model"].predict_proba(rows)[:, 1]]


def match_probability(lost, found):
    result = match_probabilities([(lost, found)])
    return result[0] if result else None


def predict_category(text, top=3):
    """
    {"name", "confidence", "alternatives": [{"name", "confidence"}]} for a
    report's text, or None when no category model is available.
    """
    bundle = load(ModelVersion.Kind.CATEGORY)
    if bundle is None or not (text or "").strip():
        return None
    model = bundle["model"]
    probs = model.predict_proba([text])[0]
    ranked = sorted(zip(model.classes_, probs), key=lambda pair: pair[1], reverse=True)
    options = [{"name": str(name), "confidence": round(float(p), 4)} for name, p in ranked[:top]]
    return {**options[0], "alternatives": options[1:], "model_version": bundle["meta"]["version"]}
