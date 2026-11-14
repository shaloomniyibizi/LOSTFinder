"""
Read the training data from the LOSTFinder REST API and save a snapshot.

    python manage.py runserver                       # in another terminal
    python manage.py fetch_api_data --email officer@lostfinder.test --password ...

Steps, all over HTTP:
1. POST /auth/token/          exchange email + password for an API token
2. GET  /ml/training-data/    every report and every decided match
                              (security staff and administrators only)
3. GET  /categories/          the category list, kept for reference

The snapshot is written to ml/data/api_snapshot.json, which
`manage.py train_model` reads.
"""

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ml import dataset


class Command(BaseCommand):
    help = "Download training data from the LOSTFinder API into ml/data/api_snapshot.json."

    def add_arguments(self, parser):
        parser.add_argument("--url", default=settings.LOSTFINDER_API_URL,
                            help="API base URL (default: %(default)s).")
        parser.add_argument("--email", help="A security or staff account.")
        parser.add_argument("--password")
        parser.add_argument("--token", help="Use an existing API token instead of email/password.")
        parser.add_argument("--timeout", type=float, default=30)

    def handle(self, *args, **options):
        base = options["url"].rstrip("/") + "/"
        session = requests.Session()
        session.headers["Accept"] = "application/json"
        timeout = options["timeout"]

        try:
            token = options["token"] or self._login(session, base, options, timeout)
            session.headers["Authorization"] = f"Token {token}"

            response = session.get(base + "ml/training-data/", timeout=timeout)
            if response.status_code == 403:
                raise CommandError("This account may not export training data "
                                   "(security staff or administrators only).")
            response.raise_for_status()
            data = response.json()

            categories = session.get(base + "categories/", timeout=timeout)
            categories.raise_for_status()
            data["categories"] = categories.json()
        except requests.ConnectionError:
            raise CommandError(f"Could not reach {base}. Is `manage.py runserver` running?")
        except requests.HTTPError as error:
            raise CommandError(f"The API answered {error.response.status_code}: "
                               f"{error.response.text[:200]}")

        data["source"] = base
        path = dataset.save_snapshot(data)
        accepted = sum(1 for m in data["matches"] if m["status"] == "accepted")
        self.stdout.write(self.style.SUCCESS(
            f"Saved {path}\n"
            f"  {len(data['lost_items'])} lost reports, {len(data['found_items'])} found reports\n"
            f"  {len(data['matches'])} decided matches ({accepted} accepted, "
            f"{len(data['matches']) - accepted} rejected)\n"
            f"Next: python manage.py train_model"
        ))

    def _login(self, session, base, options, timeout):
        if not (options["email"] and options["password"]):
            raise CommandError("Give --email and --password, or --token.")
        response = session.post(
            base + "auth/token/",
            json={"email": options["email"], "password": options["password"]},
            timeout=timeout,
        )
        if response.status_code == 400:
            raise CommandError("Login failed: check the email and password.")
        response.raise_for_status()
        return response.json()["token"]
