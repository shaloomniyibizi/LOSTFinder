import shutil
import tempfile
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

from accounts.models import UserProfile
from api.tests import make_user
from items.matching import MIN_MATCH_SCORE, _refresh_suggestion, match_lost_item
from items.models import FoundItem, ItemCategory, LostItem, MatchSuggestion
from items.services import run_matching

from . import dataset, predictor, synthetic, training
from .features import FEATURE_NAMES, pair_features
from .models import CategoryPrediction, ModelVersion


def report(kind="lost", **values):
    defaults = dict(
        title="Black Dell laptop", description="Black Dell laptop with a sticker on the back",
        location="Main Library reading room", category_id="Electronics",
    )
    date_attr = "date_lost" if kind == "lost" else "date_found"
    defaults[date_attr] = values.pop("day", date(2026, 3, 1))
    return SimpleNamespace(**(defaults | values))


class FeatureTests(TestCase):
    def test_vector_matches_feature_names(self):
        self.assertEqual(len(pair_features(report(), report("found"))), len(FEATURE_NAMES))

    def test_same_report_scores_high(self):
        f = dict(zip(FEATURE_NAMES, pair_features(report(), report("found"))))
        self.assertEqual(f["same_category"], 1.0)
        self.assertGreater(f["title_similarity"], 0.95)
        self.assertEqual(f["days_apart"], 0)
        self.assertEqual(f["colour_conflict"], 0.0)
        self.assertEqual(f["shared_colours"], 1.0)

    def test_colour_conflict_and_found_before_lost(self):
        found = report("found", title="White Dell laptop", description="White laptop",
                       day=date(2026, 2, 20))
        f = dict(zip(FEATURE_NAMES, pair_features(report(), found)))
        self.assertEqual(f["colour_conflict"], 1.0)
        self.assertEqual(f["found_before_lost"], 1.0)
        self.assertEqual(f["days_apart"], 9)


class SyntheticDataTests(TestCase):
    def test_seeded_and_balanced(self):
        first = synthetic.match_pairs(n_objects=50, seed=3)
        second = synthetic.match_pairs(n_objects=50, seed=3)
        self.assertEqual([p[0].title for p in first], [p[0].title for p in second])
        labels = [label for *_, label in first]
        self.assertEqual(labels.count(1), 50)
        self.assertGreater(labels.count(0), 50)

    def test_category_samples_cover_every_category(self):
        names = {c for *_, c in synthetic.category_samples(n=400, seed=1)}
        self.assertEqual(names, set(synthetic.all_categories()))


class MLTestCase(TestCase):
    """Trains small models once into a temporary folder."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.model_dir = Path(tempfile.mkdtemp())
        cls.data_dir = Path(tempfile.mkdtemp())
        cls.settings_override = override_settings(
            ML_ENABLED=True, ML_MODEL_DIR=cls.model_dir, ML_DATA_DIR=cls.data_dir,
        )
        cls.settings_override.enable()
        cls.match_meta, _ = training.train_match_model(n_objects=200, seed=1, register=False)
        cls.category_meta, _ = training.train_category_model(n_samples=600, seed=1, register=False)

    @classmethod
    def tearDownClass(cls):
        cls.settings_override.disable()
        shutil.rmtree(cls.model_dir, ignore_errors=True)
        shutil.rmtree(cls.data_dir, ignore_errors=True)
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user("owner")
        cls.finder = make_user("finder")
        cls.officer = make_user("officer", user_type=UserProfile.UserType.SECURITY)
        cls.admin = make_user("admin", is_staff=True)
        cls.electronics = ItemCategory.objects.create(name="Electronics")
        cls.keys = ItemCategory.objects.create(name="Keys")

    def make_lost(self, **extra):
        return LostItem.objects.create(**{
            "reporter": self.owner, "category": self.electronics,
            "title": "Black Dell laptop",
            "description": "Black Dell laptop with a sticker on the back",
            "location": "Main Library reading room",
            "date_lost": timezone.localdate() - timedelta(days=2),
        } | extra)

    def make_found(self, **extra):
        return FoundItem.objects.create(**{
            "reporter": self.finder, "category": self.electronics,
            "title": "Black laptop",
            "description": "Found a black Dell laptop with a sticker on the back in the library",
            "location": "Main Library reading room",
            "date_found": timezone.localdate() - timedelta(days=1),
        } | extra)


class TrainingTests(MLTestCase):
    def test_saved_files_and_metrics(self):
        self.assertTrue(training.model_path(ModelVersion.Kind.MATCH).exists())
        self.assertTrue(training.model_path(ModelVersion.Kind.CATEGORY).exists())
        for key in ("accuracy", "precision", "recall", "f1", "roc_auc", "confusion_matrix"):
            self.assertIn(key, self.match_meta["metrics"])
        self.assertIn(self.match_meta["algorithm"], self.match_meta["compared"])
        self.assertIn("f1", self.match_meta["baseline_rules"])
        self.assertEqual(len(self.match_meta["feature_importances"]), len(FEATURE_NAMES))
        # Even a small model must beat chance clearly.
        self.assertGreater(self.match_meta["metrics"]["roc_auc"], 0.8)
        self.assertGreater(self.category_meta["metrics"]["accuracy"], 0.6)

    def test_register_marks_only_latest_active(self):
        with override_settings(ML_MODEL_DIR=Path(tempfile.mkdtemp())):
            training.train_category_model(n_samples=300, seed=2)
            training.train_category_model(n_samples=300, seed=3)
        versions = ModelVersion.objects.filter(kind=ModelVersion.Kind.CATEGORY)
        self.assertEqual(versions.filter(is_active=True).count(), 1)

    def test_real_pairs_from_snapshot(self):
        lost, found = self.make_lost(), self.make_found()
        MatchSuggestion.objects.create(lost_item=lost, found_item=found, score=80,
                                       status=MatchSuggestion.Status.ACCEPTED)
        data = dataset.export_training_data()
        pairs = dataset.real_match_pairs(data)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0][2], 1)
        self.assertEqual(len(dataset.real_category_samples(data)), 2)


class PredictorTests(MLTestCase):
    def test_probabilities_in_range(self):
        p = predictor.match_probability(self.make_lost(), self.make_found())
        self.assertGreaterEqual(p, 0)
        self.assertLessEqual(p, 1)

    def test_similar_pair_beats_unrelated_pair(self):
        lost = self.make_lost()
        same = predictor.match_probability(lost, self.make_found())
        other = predictor.match_probability(lost, self.make_found(
            title="Red keyring", description="Red keys with a football keyring",
            category=self.keys, location="Sports Complex gym",
            date_found=timezone.localdate() - timedelta(days=40),
        ))
        self.assertGreater(same, other)

    def test_category_prediction(self):
        result = predictor.predict_category("Bunch of keys with a red keyring")
        self.assertEqual(result["name"], "Keys")

    def test_disabled_returns_none(self):
        with override_settings(ML_ENABLED=False):
            self.assertIsNone(predictor.match_probabilities([(report(), report("found"))]))
            self.assertIsNone(predictor.predict_category("keys"))

    def test_missing_model_returns_none(self):
        with override_settings(ML_MODEL_DIR=Path(tempfile.mkdtemp())):
            self.assertIsNone(predictor.model_info(ModelVersion.Kind.MATCH))


class MatchingIntegrationTests(MLTestCase):
    def test_suggestions_store_probability(self):
        self.make_found()
        suggestions = match_lost_item(self.make_lost())
        self.assertEqual(len(suggestions), 1)
        self.assertIsNotNone(suggestions[0].ml_probability)

    def test_confident_model_can_suggest_a_low_rule_score_pair(self):
        lost = self.make_lost()
        found = self.make_found(title="Notebook", description="A notebook", category=self.keys,
                                location="Cafeteria")
        self.assertIsNone(_refresh_suggestion(lost, found, None, probability=0.1))
        suggestion = _refresh_suggestion(lost, found, None, probability=0.9)
        self.assertIsNotNone(suggestion)
        self.assertLess(suggestion.score, MIN_MATCH_SCORE)
        self.assertEqual(suggestion.ml_percent, 90)

    def test_saving_a_report_records_category_prediction(self):
        lost = self.make_lost(title="Keys on a red keyring", category=self.electronics,
                              description="Bunch of keys with a red keyring")
        run_matching(lost)
        prediction = CategoryPrediction.objects.get(lost_item=lost)
        self.assertEqual(prediction.predicted_name, "Keys")
        self.assertFalse(prediction.agrees)


class MLApiTests(MLTestCase, APITestCase):
    def login(self, user):
        token, _ = Token.objects.get_or_create(user=user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def test_predict_match(self):
        self.login(self.owner)
        lost, found = self.make_lost(), self.make_found()
        response = self.client.post(reverse("api-ml-predict-match"),
                                    {"lost_item": lost.pk, "found_item": found.pk}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("probability", response.data)
        self.assertEqual(set(response.data["features"]), set(FEATURE_NAMES))

    def test_predict_category(self):
        self.login(self.owner)
        response = self.client.post(reverse("api-ml-predict-category"),
                                    {"title": "Car key", "description": "Toyota car remote key"},
                                    format="json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Keys")
        self.assertEqual(response.data["category_id"], self.keys.pk)

    def test_training_data_is_reviewers_only(self):
        self.login(self.owner)
        self.assertEqual(self.client.get(reverse("api-ml-training-data")).status_code, 403)
        self.login(self.officer)
        response = self.client.get(reverse("api-ml-training-data"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.data), {"generated_at", "lost_items", "found_items", "matches"})

    def test_models(self):
        self.login(self.owner)
        response = self.client.get(reverse("api-ml-models"))
        self.assertEqual(response.data["match"]["version"], self.match_meta["version"])

    def test_no_model_answers_503(self):
        self.login(self.owner)
        with override_settings(ML_MODEL_DIR=Path(tempfile.mkdtemp())):
            response = self.client.post(reverse("api-ml-predict-category"),
                                        {"title": "Car key"}, format="json")
        self.assertEqual(response.status_code, 503)


class DashboardAndPagesTests(MLTestCase):
    def test_dashboard_shows_ai_insights(self):
        self.make_found()
        run_matching(self.make_lost())
        self.client.force_login(self.owner)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "AI insights")
        self.assertContains(response, 'id="chart-ml-confidence"')

        data = self.client.get(reverse("dashboard_metrics")).json()
        self.assertTrue(data["ml"]["enabled"])
        self.assertIn("ml_agreement", data["values"])
        self.assertIn("ml_confidence", data["charts"])
        self.assertEqual(len(data["ml"]["latest"]), 1)

    def test_dashboard_without_model(self):
        self.client.force_login(self.owner)
        with override_settings(ML_ENABLED=False):
            response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "No match model has been trained yet")

    def test_model_report_for_reviewers(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("ml_model_report")).status_code, 403)
        self.client.force_login(self.officer)
        response = self.client.get(reverse("ml_model_report"))
        self.assertContains(response, "Rule-based engine (baseline)")

    def test_retrain_is_staff_only(self):
        self.client.force_login(self.officer)
        self.assertEqual(self.client.post(reverse("ml_retrain")).status_code, 403)

        fake = {"match": self.match_meta, "category": self.category_meta}
        self.client.force_login(self.admin)
        with mock.patch("ml.views.training.train_all", return_value=fake) as train:
            response = self.client.post(reverse("ml_retrain"))
        train.assert_called_once()
        self.assertRedirects(response, reverse("dashboard"))

    def test_suggest_category(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("ml_suggest_category"),
                                   {"title": "Car key", "description": "Toyota remote key"})
        self.assertEqual(response.json()["category"], {"id": self.keys.pk, "name": "Keys"})
