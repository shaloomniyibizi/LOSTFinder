"""
Train the match and category models.

    python manage.py train_model                # API snapshot (if any) + synthetic data
    python manage.py train_model --synthetic-only
    python manage.py train_model --objects 3000 --rescore

The API snapshot is ml/data/api_snapshot.json, written by
`manage.py fetch_api_data`. --rescore re-runs matching and refreshes every
stored prediction (suggestion probabilities, report categories) with the
new models.
"""

from django.core.management.base import BaseCommand

from ml import dataset, predictor, training
from ml.models import ModelVersion
from ml.services import rescore_all


class Command(BaseCommand):
    help = "Train the ML match and category models and save them to ml/artifacts/."

    def add_arguments(self, parser):
        parser.add_argument("--synthetic-only", action="store_true",
                            help="Ignore the API snapshot.")
        parser.add_argument("--objects", type=int, default=1500,
                            help="Synthetic objects for the match model (3 pairs each).")
        parser.add_argument("--category-samples", type=int, default=3000,
                            help="Synthetic reports for the category model.")
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--rescore", action="store_true",
                            help="Re-run matching afterwards with the new model.")

    def handle(self, *args, **options):
        data = None
        if not options["synthetic_only"]:
            data = dataset.read_snapshot()
            if data is None:
                self.stdout.write(self.style.WARNING(
                    "No API snapshot found (run `manage.py fetch_api_data`); "
                    "training on synthetic data only."
                ))
            else:
                self.stdout.write(
                    f"API snapshot from {data['generated_at']}: "
                    f"{len(data['lost_items'])} lost, {len(data['found_items'])} found, "
                    f"{len(data['matches'])} decided matches."
                )

        self.stdout.write("Training... (this takes a few seconds)")
        result = training.train_all(
            data, n_objects=options["objects"],
            n_category_samples=options["category_samples"], seed=options["seed"],
        )
        self._report_match(result["match"])
        self._report_category(result["category"])

        if options["rescore"]:
            done = rescore_all()
            self.stdout.write(self.style.SUCCESS(
                f"\nRe-scored: {done['live_suggestions']} live suggestions, "
                f"{done['scored_suggestions']} suggestions given probabilities, "
                f"{done['categorised_reports']} reports categorised."
            ))

        # Prove the saved files load.
        for kind in ModelVersion.Kind.values:
            if predictor.load(kind) is None:
                self.stdout.write(self.style.WARNING(
                    f"The {kind} model was saved but is not loaded "
                    "(is ML_ENABLED false?)."
                ))

    def _report_match(self, meta):
        m, base, n = meta["metrics"], meta["baseline_rules"], meta["samples"]
        self.stdout.write(self.style.SUCCESS(f"\nMatch model {meta['version']}"))
        self.stdout.write(
            f"  samples: {n['train']} train / {n['test']} test "
            f"({n['real']} real from API, {n['synthetic']} synthetic)"
        )
        self.stdout.write(f"  {'model':<22} {'acc':>6} {'prec':>6} {'rec':>6} {'F1':>6} {'AUC':>6}")
        rows = list(meta["compared"].items()) + [("Rule-based (baseline)", base)]
        for name, r in rows:
            marker = " *" if name == meta["algorithm"] else ""
            self.stdout.write(
                f"  {name:<22} {r['accuracy']:>6.3f} {r['precision']:>6.3f} "
                f"{r['recall']:>6.3f} {r['f1']:>6.3f} {r.get('roc_auc', 0):>6.3f}{marker}"
            )
        self.stdout.write(f"  kept: {meta['algorithm']} (F1 {m['f1']:.3f})")
        top = ", ".join(f"{f['label']} {f['importance']:.0%}" for f in meta["feature_importances"][:4])
        self.stdout.write(f"  top features: {top}")

    def _report_category(self, meta):
        m, n = meta["metrics"], meta["samples"]
        self.stdout.write(self.style.SUCCESS(f"\nCategory model {meta['version']}"))
        self.stdout.write(
            f"  samples: {n['train']} train / {n['test']} test "
            f"({n['real']} real from API, {n['synthetic']} synthetic)"
        )
        self.stdout.write(f"  accuracy {m['accuracy']:.3f}, macro F1 {m['f1_macro']:.3f}")
