"""
Feed new reports into the running site through the REST API, so the
dashboard's live predictions can be watched as data arrives.

    python manage.py runserver                       # in another terminal
    python manage.py seed_demo                       # demo accounts
    python manage.py simulate_incoming --count 10 --interval 5

Each round a "finder" turns in a synthetic found item, and usually (see
--match-rate) an "owner" then reports the same object as lost, in their own
words. Each POST runs the server's matching and the trained models, exactly
like a report filed on the website.
"""

import random
import time
from datetime import date, timedelta

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from items.management.commands.seed_demo import DEFAULT_PASSWORD, demo_email
from ml import synthetic


class Command(BaseCommand):
    help = "Post synthetic lost and found reports to the API at an interval."

    def add_arguments(self, parser):
        parser.add_argument("--url", default=settings.LOSTFINDER_API_URL)
        parser.add_argument("--finder", default=demo_email("grace"),
                            help="Account that turns in found items.")
        parser.add_argument("--owner", default=demo_email("amina"),
                            help="Account that reports lost items.")
        parser.add_argument("--password", default=DEFAULT_PASSWORD,
                            help="Password for both accounts (demo password by default).")
        parser.add_argument("--count", type=int, default=5, help="Rounds to run.")
        parser.add_argument("--interval", type=float, default=5, help="Seconds between rounds.")
        parser.add_argument("--match-rate", type=float, default=0.7,
                            help="Share of rounds where the owner reports the same object.")
        parser.add_argument("--seed", type=int, default=None)

    def handle(self, *args, **options):
        self.base = options["url"].rstrip("/") + "/"
        rng = random.Random(options["seed"])

        try:
            finder = self._client(options["finder"], options["password"])
            owner = self._client(options["owner"], options["password"])
            categories = {c["name"].lower(): c["id"] for c in self._get(finder, "categories/")}
        except requests.ConnectionError:
            raise CommandError(f"Could not reach {self.base}. Is `manage.py runserver` running?")
        if not categories:
            raise CommandError("No categories exist yet. Run `manage.py seed_demo` first.")

        for round_no in range(1, options["count"] + 1):
            obj = synthetic.random_object(rng)
            # Keep dates recent and never in the future.
            obj.day = date.today() - timedelta(days=rng.randint(2, 6))

            found = synthetic.found_report(rng, obj)
            # The server rejects future dates (and runs on UTC): stay a day back.
            found.date_found = min(found.date_found, date.today() - timedelta(days=1))
            found_row = self._post(finder, "found-items/", found, categories, "date_found")
            self.stdout.write(f"[{round_no}] found: {found_row['title']!r} "
                              f"-> {found_row['matches_found']} match(es)")

            same = rng.random() < options["match_rate"]
            lost_obj = obj if same else synthetic.random_object(rng)
            if not same:
                lost_obj.day = date.today() - timedelta(days=rng.randint(1, 6))
            lost = synthetic.lost_report(rng, lost_obj)
            lost_row = self._post(owner, "lost-items/", lost, categories, "date_lost")
            self.stdout.write(
                f"    lost:  {lost_row['title']!r} ({'same object' if same else 'different object'}) "
                f"-> {lost_row['matches_found']} match(es)"
            )

            if round_no < options["count"]:
                time.sleep(options["interval"])

        self.stdout.write(self.style.SUCCESS("Done. Open the dashboard to see the predictions."))

    # ---------- HTTP helpers ----------

    def _client(self, email, password):
        session = requests.Session()
        response = session.post(self.base + "auth/token/",
                                json={"email": email, "password": password}, timeout=30)
        if response.status_code != 200:
            raise CommandError(f"Could not sign in as {email}: {response.text[:200]}")
        session.headers["Authorization"] = f"Token {response.json()['token']}"
        return session

    def _get(self, session, path):
        response = session.get(self.base + path, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data["results"] if isinstance(data, dict) and "results" in data else data

    def _post(self, session, path, report, categories, date_field):
        # Map the synthetic category name to this site's category id.
        category = categories.get(str(report.category_id).lower(), categories.get("other"))
        if category is None:
            category = next(iter(categories.values()))
        payload = {
            "title": report.title[:200],
            "description": report.description,
            "location": report.location[:200],
            "category": category,
            date_field: getattr(report, date_field).isoformat(),
        }
        response = session.post(self.base + path, json=payload, timeout=60)
        if response.status_code != 201:
            raise CommandError(f"POST {path} failed ({response.status_code}): {response.text[:300]}")
        return response.json()
