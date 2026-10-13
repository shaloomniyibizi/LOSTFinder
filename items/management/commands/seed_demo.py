
"""
Seed demo data: users, categories, 6 found + 6 lost reports with photos,
match suggestions, and claims at every stage of the workflow.

Data goes through the real matching engine and claim services, so the
dashboard, matches, claims and notifications are all consistent.

    python manage.py seed_demo            # create (safe to re-run)
    python manage.py seed_demo --reset    # remove demo data, then re-create
    python manage.py seed_demo --reset --no-create   # just remove it
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import UserProfile
from claims import services as claim_services
from claims.models import Claim, ItemHandover
from items.matching import match_lost_item, sync_lost_item_status
from items.models import FoundItem, ItemCategory, LostItem, MatchSuggestion


DEMO_DOMAIN = "lostfinder.test"   # .test is reserved: never a real mailbox
DEFAULT_PASSWORD = "Demo-Pass-2026!"
IMAGE_DIR = settings.BASE_DIR / "static" / "image"

CATEGORIES = {
    "Electronics": "Laptops, phones, earbuds, chargers",
    "ID Cards": "Student and staff identity cards",
    "Keys": "Keys, key cards, lanyards",
    "Water Bottles": "Bottles, tumblers, flasks",
    "Apparel": "Jackets, scarves, hats",
    "Textbooks": "Books, notebooks, printed notes",
    "Bags": "Backpacks, tote bags, laptop sleeves",
    "Other": "Anything else",
}

USERS = {
    "amina": dict(
        first_name="Amina", last_name="Uwase", user_type="student",
        student_id="S2024-0142", faculty="Engineering",
        program="Computer Science", year_of_study=2,
    ),
    "daniel": dict(
        first_name="Daniel", last_name="Mugisha", user_type="student",
        student_id="S2023-0871", faculty="Business",
        program="Economics", year_of_study=3,
    ),
    "grace": dict(
        first_name="Grace", last_name="Ingabire", user_type="staff",
        student_id="STAFF-0310", faculty="Library Services",
        program="Information Desk", year_of_study=4,
    ),
    "officer": dict(
        first_name="Eric", last_name="Habimana", user_type="security",
        student_id="SEC-0007", faculty="Campus Security",
        program="Lost & Found Desk", year_of_study=4,
    ),
}

# (key, reporter, category, title, description, location, days_ago, image)
FOUND_ITEMS = [
    ("macbook", "grace", "Electronics", "Space Grey MacBook Pro laptop",
     "Space grey MacBook Pro laptop left on the amphitheater stairs. "
     "Small blue sticker on the lid near the hinge.",
     "Forum amphitheater stairs", 0, "item_1.jpg"),
    ("student_id", "grace", "ID Cards", "Student ID card",
     "University student ID card on a blue lanyard, found next to the "
     "printer. Economics programme printed on the card.",
     "Main Library 2nd floor printer", 1, "item_2.jpg"),
    ("tumbler", "daniel", "Water Bottles", "Matte black tumbler",
     "Matte black insulated tumbler, about 40oz, with a silver rim. "
     "Left on a cafeteria table after lunch.",
     "Cafeteria table 14", 2, "item_3.jpg"),
    ("airpods", "grace", "Electronics", "AirPods Pro case in blue silicone cover",
     "AirPods Pro charging case in a blue silicone cover with a carabiner "
     "clip. Found on a desk after the morning lecture.",
     "Seminar Room 304", 3, "item_4.jpg"),
    ("keys", "grace", "Keys", "Set of 3 keys on red lanyard",
     "Three keys on a red campus lanyard, one small bike-lock key. "
     "Handed in at the north entrance.",
     "North entrance turnstiles", 4, "item_5.jpg"),
    ("jacket", "amina", "Apparel", "Olive green rain jacket",
     "Olive green hooded rain jacket, size M, university logo on the "
     "chest. Left on a bench by the gym lockers.",
     "Gym lockers bench", 6, "item_6.jpg"),
]

LOST_ITEMS = [
    ("macbook", "amina", "Electronics", "Grey MacBook Pro laptop",
     "Space grey MacBook Pro laptop with a blue sticker on the lid. "
     "Left it on the stairs after a group meeting.",
     "Forum amphitheater stairs", 0),
    ("student_id", "daniel", "ID Cards", "Lost student ID card",
     "My university student ID card on a blue lanyard. I think I left it "
     "by the printer.",
     "Main Library 2nd floor printer", 1),
    ("airpods", "amina", "Electronics", "Blue AirPods Pro case",
     "AirPods Pro case with a blue silicone cover and a clip. Lost during "
     "the morning lecture.",
     "Seminar Room 304", 3),
    ("keys", "daniel", "Keys", "Keys on red lanyard",
     "Three keys on a red lanyard including a small bike-lock key.",
     "North entrance turnstiles", 5),
    ("textbook", "amina", "Textbooks", "Calculus textbook",
     "Stewart Calculus 8th edition, name written inside the front cover, "
     "yellow highlighter notes.",
     "Lecture Room 210", 8),
    ("backpack", "daniel", "Bags", "Black backpack",
     "Black backpack with a laptop sleeve and a grey water-resistant "
     "zip pocket.",
     "Student Centre lounge", 10),
]


def demo_email(username):
    return f"{username}@{DEMO_DOMAIN}"


class Command(BaseCommand):
    help = "Seed demo users, 6 lost + 6 found items, matches and claims."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset", action="store_true",
            help="Delete existing demo data before seeding.",
        )
        parser.add_argument(
            "--no-create", action="store_true",
            help="With --reset: only delete demo data.",
        )
        parser.add_argument(
            "--password", default=DEFAULT_PASSWORD,
            help=f"Password for the demo accounts (default: {DEFAULT_PASSWORD}).",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Allow running with DEBUG=False (not recommended).",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "Refusing to seed demo accounts with a known password while "
                "DEBUG=False. Use --force if you really mean it."
            )

        if options["reset"]:
            removed = self.reset()
            self.stdout.write(self.style.WARNING(
                f"Removed demo data: {removed} report(s) and the demo accounts."
            ))
            if options["no_create"]:
                return

        User = get_user_model()
        if User.objects.filter(email__iendswith=f"@{DEMO_DOMAIN}").exists():
            self.stdout.write(self.style.NOTICE(
                "Demo data already exists; nothing to do. "
                "Run with --reset to re-create it."
            ))
            return

        self.seed(options["password"])

    # ---------- removal ----------

    @transaction.atomic
    def reset(self):
        User = get_user_model()
        demo_users = User.objects.filter(email__iendswith=f"@{DEMO_DOMAIN}")
        found = FoundItem.objects.filter(reporter__in=demo_users)
        lost = LostItem.objects.filter(reporter__in=demo_users)

        # Real users' lost reports that matched demo items need their
        # status re-checked once those suggestions disappear.
        affected = list(
            LostItem.objects.exclude(reporter__in=demo_users)
            .filter(match_suggestions__found_item__in=found).distinct()
        )

        claims = Claim.objects.filter(found_item__in=found) | Claim.objects.filter(
            claimant__in=demo_users
        )
        ItemHandover.objects.filter(claim__in=claims).delete()
        claims.delete()

        count = found.count() + lost.count()
        for item in list(found) + list(lost):
            if item.image:
                item.image.delete(save=False)
        found.delete()
        lost.delete()
        demo_users.delete()   # cascades profiles, notifications, review logs

        for lost_item in affected:
            sync_lost_item_status(lost_item)

        return count

    # ---------- creation ----------

    @transaction.atomic
    def seed(self, password):
        today = timezone.localdate()
        now = timezone.now()

        categories = {
            name: ItemCategory.objects.get_or_create(
                name=name, defaults={"description": description}
            )[0]
            for name, description in CATEGORIES.items()
        }

        users = {name: self.make_user(name, data, password)
                 for name, data in USERS.items()}

        found = {}
        for key, who, cat, title, desc, loc, days_ago, image in FOUND_ITEMS:
            item = FoundItem(
                reporter=users[who], category=categories[cat], title=title,
                description=desc, location=loc,
                date_found=today - timedelta(days=days_ago),
            )
            with open(IMAGE_DIR / image, "rb") as fh:
                item.image.save(f"seed_{image}", File(fh), save=False)
            item.save()
            self.backdate(item, now, days_ago, hours=3)
            found[key] = item

        lost = {}
        for key, who, cat, title, desc, loc, days_ago in LOST_ITEMS:
            item = LostItem.objects.create(
                reporter=users[who], category=categories[cat], title=title,
                description=desc, location=loc,
                date_lost=today - timedelta(days=days_ago),
            )
            self.backdate(item, now, days_ago, hours=5)
            lost[key] = item

        for item in lost.values():
            match_lost_item(item)

        officer = users["officer"]

        # Returned: Daniel's student ID was matched, claimed, approved and
        # handed over.
        self.accept_match(lost["student_id"], found["student_id"])
        claim = claim_services.submit_claim(
            found["student_id"], users["daniel"],
            "Card number S2023-0871, my photo shows me wearing glasses.",
        )
        claim_services.review_claim(
            claim, officer, Claim.Status.APPROVED, "Card number verified.",
        )
        claim_services.record_handover(
            claim, officer, "Campus Security Office",
            now - timedelta(hours=20), "Student ID checked against the card.",
        )

        # Awaiting handover: Amina's MacBook claim is approved.
        self.accept_match(lost["macbook"], found["macbook"])
        claim = claim_services.submit_claim(
            found["macbook"], users["amina"],
            "Serial number ends in Q6L4; lock screen is a photo of Kigali at night.",
        )
        claim_services.review_claim(
            claim, officer, Claim.Status.APPROVED, "Serial number matches.",
        )

        # In the review queue: Daniel claimed the keys.
        claim_services.submit_claim(
            found["keys"], users["daniel"],
            "Three keys: front door, room 12B and a small Abus bike-lock key.",
        )

        # The AirPods match is left pending for Amina to review herself.

        self.report(users, password)

    def make_user(self, username, data, password):
        User = get_user_model()
        user = User.objects.create_user(
            username=f"demo_{username}",
            email=demo_email(username),
            password=password,
            first_name=data["first_name"],
            last_name=data["last_name"],
        )
        UserProfile.objects.create(
            user=user,
            user_type=data["user_type"],
            phone_number="0788000000",
            address="Campus residence",
            student_id=data["student_id"],
            faculty=data["faculty"],
            program=data["program"],
            year_of_study=data["year_of_study"],
            bio=f"Demo {data['user_type']} account.",
            onboarding_completed=True,
        )
        return user

    @staticmethod
    def backdate(item, now, days_ago, hours):
        # Spread reports across the dashboard's 14-day activity chart.
        type(item).objects.filter(pk=item.pk).update(
            created_at=now - timedelta(days=days_ago, hours=hours)
        )

    @staticmethod
    def accept_match(lost_item, found_item):
        MatchSuggestion.objects.filter(
            lost_item=lost_item, found_item=found_item
        ).update(status=MatchSuggestion.Status.ACCEPTED)
        lost_item.refresh_from_db()
        sync_lost_item_status(lost_item)

    def report(self, users, password):
        style = self.style
        self.stdout.write(style.SUCCESS("\nDemo data created."))
        self.stdout.write(
            f"  {FoundItem.objects.filter(reporter__in=users.values()).count()} found items, "
            f"{LostItem.objects.filter(reporter__in=users.values()).count()} lost items, "
            f"{MatchSuggestion.objects.filter(lost_item__reporter__in=users.values()).count()} match suggestions, "
            f"{Claim.objects.filter(claimant__in=users.values()).count()} claims\n"
        )
        self.stdout.write("  Sign in with (password for all: " + password + "):")
        roles = {"amina": "student", "daniel": "student",
                 "grace": "university staff", "officer": "security officer"}
        for name, user in users.items():
            self.stdout.write(f"    {user.email:<28} {roles[name]}")
        self.stdout.write("")
