
from django.core.management.base import BaseCommand

from items.matching import match_all_lost_items


class Command(BaseCommand):
    help = "Generate or refresh match suggestions for all open lost items."

    def handle(self, *args, **options):
        total = match_all_lost_items()
        self.stdout.write(
            self.style.SUCCESS(f"{total} pending suggestion(s) refreshed.")
        )
