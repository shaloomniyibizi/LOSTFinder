# LOSTFinder

A campus lost-and-found web app built with Django. Students and staff report items they have lost or found, the app suggests likely matches, and campus security verifies ownership claims and records the handover back to the owner.

## Contents

- [Features](#features)
- [Tech stack](#tech-stack)
- [Requirements](#requirements)
- [Installation](#installation)
- [First-time setup](#first-time-setup)
- [Using LOSTFinder](#using-lostfinder)
- [User roles](#user-roles)
- [How matching works](#how-matching-works)
- [How claims work](#how-claims-work)
- [Configuration](#configuration)
- [Management commands](#management-commands)
- [Running the tests](#running-the-tests)
- [Project structure](#project-structure)
- [Pages and URLs](#pages-and-urls)
- [Troubleshooting](#troubleshooting)
- [Known issues](#known-issues)

## Features

- **Public home page** with a live feed of recent reports, campus statistics, search, and the busiest campus zones. Only visitors see it; signed-in users go straight to their dashboard.
- **Accounts:** register and sign in with an email address, then complete a short onboarding profile before using the app.
- **Lost and found reports** with a photo (up to 5 MB), category, location, and date. You can search and filter them, and only the person who reported an item can edit or delete it.
- **Automatic matching:** every time a report is saved, it is compared against the opposite type, and you are told how many possible matches were found.
- **Claims workflow:** submit proof of ownership, security reviews it, then the handover is recorded. Every step is logged and notifies the people involved.
- **Role-based dashboard** built with AdminLTE: summary cards, live-updating charts, and recent-record tables, plus a claim queue for security staff.
- **Notifications** inside the app, with an unread count in the header.
- **Light, dark, and auto themes**, remembered in your browser.
- **Works offline from a CDN:** AdminLTE, Bootstrap, Bootstrap Icons, and Chart.js are bundled in `static/vendor/`.

## Tech stack

| Part | Technology |
| --- | --- |
| Backend | Python 3.14, Django 6.1 |
| Database | SQLite (default) or PostgreSQL |
| UI | AdminLTE 4.9.1 (Bootstrap 5.3.8), Bootstrap Icons 1.13.1 |
| Charts | Chart.js 4.5.1 |
| Images | Pillow |
| Config | python-dotenv (`.env` file) |
| Template linting | djLint |

## Requirements

- **Python 3.14 or newer.** Check with `python --version`.
- **[uv](https://docs.astral.sh/uv/)** (recommended) or pip.
- **PostgreSQL** only if you choose not to use the default SQLite database.

## Installation

### 1. Get the code

```bash
git clone <repository-url> LOSTFinder
cd LOSTFinder
```

### 2. Install dependencies

**Option A: uv (recommended).** This creates `.venv/` and installs the exact versions in `uv.lock`:

```bash
uv sync
```

Then either activate the environment (see below) or put `uv run` in front of each command, for example `uv run python manage.py migrate`.

**Option B: pip.**

```bash
python -m venv .venv
```

Activate the environment:

| Shell | Command |
| --- | --- |
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| Windows Command Prompt | `.venv\Scripts\activate.bat` |
| Git Bash | `source .venv/Scripts/activate` |
| macOS / Linux | `source .venv/bin/activate` |

Then install:

```bash
uv add -r requirements.txt
```

or

```bash
pip install -r requirements.txt
```

### 3. Create your `.env` file

Settings such as the secret key and database credentials are read from a `.env` file in the project root. That file is git-ignored, so copy the template:

```bash
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
```

Generate a secret key and paste it into `.env` as `SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

For local development, your `.env` should contain at least:

```ini
SECRET_KEY=<the key you just generated>
DEBUG=True
DB_ENGINE=sqlite
```

> **Keep `DEBUG=True` for local development.** `DEBUG` defaults to `False`, and with it off the development server refuses to start (`ALLOWED_HOSTS` is empty) and does not serve CSS, JavaScript, or uploaded images. See [Configuration](#configuration) for every variable.

### 4. Create the database

```bash
uv run manage.py migrate
```

or

```bash
python manage.py migrate
```

### 5. Create an administrator account

```bash
python manage.py createsuperuser
```

or

```bash
uv run manage.py createsuperuser
```

It asks for a username, an email address, and a password. Choose any username, but make sure the email is correct: you sign in to the app with your **email**, not the username.

### 6. Start the server

```bash
python manage.py runserver
```

or

```bash
uv run manage.py runserver
```

Open <http://127.0.0.1:8000/>.

### 7. Load demo data (optional)

To try the app straight away, seed it with sample data:

```bash
python manage.py seed_demo
```

This creates:

- **8 item categories:** Electronics, ID Cards, Keys, Water Bottles, Apparel, Textbooks, Bags, Other. With these, the "add categories" setup step below is already done.
- **6 found items with photos and 6 lost reports**, spread over the last 10 days so the dashboard charts have data.
- **Match suggestions** produced by the real matching engine.
- **Claims at every stage:** one completed (handed over), one approved and awaiting handover, one waiting in the review queue. One match is left pending, so you can accept or reject it yourself.
- **Four demo accounts**, all with the password `Demo-Pass-2026!` and onboarding already complete:

| Email | Role | What to try |
| --- | --- | --- |
| `amina@lostfinder.test` | Student | Review the pending AirPods match; follow the approved MacBook claim |
| `daniel@lostfinder.test` | Student | See a returned item and a claim in review |
| `grace@lostfinder.test` | University staff | See claims on the items she turned in |
| `officer@lostfinder.test` | Security officer | Review the keys claim; record the MacBook handover |

Options:

- `--reset` removes the demo data first, then re-creates it.
- `--reset --no-create` only removes it. Categories are kept.
- `--password <pw>` sets a different password for the demo accounts.

Running the command again without `--reset` does nothing, so it is safe to repeat. It only touches accounts ending in `@lostfinder.test` and their reports. Because the demo accounts share a known password, the command refuses to run when `DEBUG=False` unless you add `--force`. Don't use it on a public server.

## First-time setup

Do these steps once, signed in to the Django admin at <http://127.0.0.1:8000/admin/> with your superuser.

1. **Add item categories.** Every report needs a category, so the report forms have nothing to choose from until you add some. Go to **Items › Item categories › Add**. Good starting set: Electronics, ID Cards, Keys, Bags, Apparel, Water Bottles, Textbooks, Jewelry, Other.
2. **Complete your own onboarding.** Sign in to the app at <http://127.0.0.1:8000/accounts/login/> and fill in the profile form. Every account must do this once before using the app.
3. **Appoint security officers (optional).** Staff accounts can already review claims. To give a regular account the same rights, go to **Accounts › User profiles**, open the person's profile, and set **User type** to *Security Officer*. Users cannot choose this role themselves.

## Using LOSTFinder

### For students and staff

#### Get started

1. Click **Register** on the home page and sign up with your university email.
2. Complete the profile form: phone, address, student ID, faculty, program, and year.
3. You land on **My Dashboard**, which shows your open reports, matches waiting for you, and your claims.

#### You lost something

1. In the sidebar, choose **Report lost item**. Give a clear title, the category, identifying details (stickers, scratches, contents), where and when you lost it, and a photo if you have one.
2. After you save, LOSTFinder compares it with every found item in custody. If anything looks similar you'll see *"We found N possible matches"*.
3. Open **My matches** to review each suggestion. It shows a score, both reports side by side, and why they matched.
   - **This is my item:** accepts the match.
   - **Not mine:** rejects it. It won't be suggested again.
   - **Undo:** puts it back to pending.
4. On an accepted match, click **Claim this item**. You can also claim any found item from its page.
5. Describe proof of ownership: details that are *not* in the public report, such as a serial number, lock-screen photo, or contents. Only you and security can see this.
6. Follow the claim under **My claims**. You get a notification when it is reviewed. Once approved, bring your university ID to the Campus Security Office to collect the item.

New found items are matched against your report automatically, so check **My matches** and **Notifications** from time to time.

#### You found something

1. Choose **Turn in found item** and describe it: what, where, and when. Take high-value items (laptops, phones, IDs, jewelry) to the Campus Security Office.
2. Possible owners are matched automatically. You can follow claims on items you found under **My claims › Claims on items I found**. To protect the owner, you see each claim's progress but not their evidence or contact details.

#### Other pages

- **Lost items / Found items:** browse and search everything reported, with filters by category and status.
- **Notifications:** messages about your claims and items. Use **Mark all as read** to clear the badge.
- **Theme:** use the sun/moon menu in the top bar to choose Light, Dark, or Auto (follows your device).

### For security officers and staff

Your dashboard is the **Security Desk Dashboard**. It shows claims to review, items awaiting handover, items in custody, recent returns, and a claim queue ordered oldest first.

1. **Review a claim.** Open it from the queue or from **Review queue** in the sidebar. Compare the claimant's evidence with the item, then choose:
   - **Mark as under review:** tells the claimant you are checking it.
   - **Approve claim:** the item is reserved for this person. Any other open claims for the same item are rejected automatically.
   - **Reject claim:** the item goes back into custody. Your comment is sent to the claimant.
2. **Record the handover.** When the owner arrives, check their university ID, then open the approved claim (or **Awaiting handover** in the sidebar) and click **Record handover**. Enter the location and time. This completes the claim, and marks both the found item and the owner's matching lost report as returned.

You cannot review or hand over your own claims.

### For administrators

Staff accounts get everything security officers have, plus a **Registered users** count on the dashboard and a link to the **Django admin** in the sidebar. Use the admin to manage categories, profiles and roles, and to correct any record directly.

## User roles

| Role | How someone gets it | Can do |
| --- | --- | --- |
| **Student** | Default for everyone who registers | Report items, review own matches, submit and cancel own claims |
| **University staff** | Set in the admin (user type) | Same as student |
| **Security officer** | Admin sets user type to *Security Officer* | Everything above, plus the review queue, approving and rejecting claims, and recording handovers |
| **Staff / superuser** | Django `is_staff` flag (e.g. `createsuperuser`) | Everything above, plus the Django admin and user statistics |

## How matching works

Each lost report is compared with found reports, and the pair gets a score out of 100:

| Signal | Points |
| --- | --- |
| Same category | 30 |
| Title similarity | up to 25 |
| Location similarity | up to 20 |
| Description similarity | up to 15 |
| Date proximity (same day 10, 1 day 8, ≤3 days 6, ≤7 days 3, ≤14 days 1) | up to 10 |

Text similarity combines shared words with overall text similarity. A pair is suggested only if it scores **35 or more**. A person's own lost and found reports are never matched with each other. Matching runs automatically whenever a report is created or edited, in the app or in the Django admin. Your accept and reject decisions are kept when scores are recalculated.

A found item with a pending claim can still be matched, because the claimant might not be the real owner. Once a claim is approved, its remaining pending suggestions are removed.

## How claims work

```text
Submitted ──► Under review ──► Approved ──► Completed (handover recorded)
    │              │
    ├──────────────┴──► Rejected       (item returns to custody)
    └──► Cancelled by claimant          (can be re-submitted later)
```

- Marking a claim *under review* is optional: a reviewer can approve or reject a submitted claim directly. A claimant can cancel while the claim is submitted or under review.
- Each person can claim a given item once. A cancelled claim can be re-submitted; a rejected one cannot.
- Every status change is written to the claim's timeline and sends a notification.
- The found item's status follows its claims automatically: *Available* → *Claim pending* → *Claim approved* → *Returned to owner*.

## Configuration

All settings come from `.env` (see `.env.example`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `SECRET_KEY` | *(none, required)* | Django's cryptographic key. The app will not start without it. |
| `DEBUG` | `False` | Set to `True` for local development. Must be `False` in production. |
| `DB_ENGINE` | `sqlite` | `sqlite` uses `db.sqlite3` in the project root; `postgresql` uses the settings below. |
| `DB_NAME` | `lostfinder` | PostgreSQL database name |
| `DB_USER` | `postgres` | PostgreSQL user |
| `DB_PASSWORD` | *(empty)* | PostgreSQL password |
| `DB_HOST` | `localhost` | PostgreSQL host |
| `DB_PORT` | `5432` | PostgreSQL port |

**Using PostgreSQL:** create an empty database, set `DB_ENGINE=postgresql` plus the `DB_*` values in `.env`, and run `python manage.py migrate`.

**Uploaded files** (profile photos and item images) are stored in `media/`. That folder is git-ignored.

**Before deploying to a real server:**

- set `DEBUG=False`
- add your domain to `ALLOWED_HOSTS` in `config/settings.py`
- run `python manage.py collectstatic`, which gathers static files into `staticfiles/`
- serve `static/` and `media/` with your web server
- use a fresh `SECRET_KEY`

## Management commands

| Command | What it does |
| --- | --- |
| `python manage.py runserver` | Start the development server |
| `python manage.py migrate` | Create or update the database tables |
| `python manage.py createsuperuser` | Create an administrator account |
| `python manage.py seed_demo` | Load demo users, 6 lost and 6 found items, matches and claims ([details](#7-load-demo-data-optional)). Add `--reset` to re-create the data. |
| `python manage.py run_matching` | Recalculate match suggestions for every open lost report. Run it after importing data straight into the database. |
| `python manage.py test` | Run the test suite |

## Running the tests

```bash
python manage.py test
```

158 tests cover:

- matching
- the save hooks, in the app and the Django admin
- the report forms and lists
- the claim workflow and permissions
- the onboarding gate
- the role-based dashboards
- live metrics
- the bundled static assets
- the theme toggle
- the demo seed command

They create a temporary test database, so your data is not touched. With PostgreSQL, the database user needs permission to create databases.

To check template formatting, and then apply the fixes:

```bash
djlint templates --check
djlint templates --reformat
```

## Project structure

```text
LOSTFinder/
├── accounts/        Registration, email login, onboarding, profiles, role checks (decorators.py)
├── items/           Lost/found reports, matching engine (matching.py), match pages
│   └── management/commands/   run_matching.py, seed_demo.py
├── claims/          Claims workflow (services.py), review queue, handovers, notifications
├── dashboard/       Public home page, role-based dashboard, metrics (metrics.py)
├── config/          Django settings and root URLs
├── templates/
│   ├── base.html          Signed-in layout (AdminLTE with sidebar)
│   ├── base_public.html   Visitor layout (AdminLTE, top bar only)
│   ├── layouts/           Header, sidebar, theme toggle
│   └── accounts/ items/ claims/ dashboard/ home.html
├── static/
│   ├── css/app.css        Project styles and chart colours
│   ├── js/dashboard.js    Charts and live refresh
│   ├── image/             Home page images and report placeholders
│   └── vendor/            AdminLTE, Bootstrap, Bootstrap Icons, Chart.js
├── media/           Uploaded images (git-ignored)
├── .env.example     Template for your .env
├── pyproject.toml   Dependencies (uv)
├── uv.lock          Locked versions (uv)
└── requirements.txt Locked versions (pip)
```

## Pages and URLs

| URL | Page | Who |
| --- | --- | --- |
| `/` | Home page | Visitors only (signed-in users are sent to the dashboard) |
| `/accounts/register/`, `/accounts/login/` | Register, sign in | Visitors |
| `/accounts/onboarding/` | Complete your profile | Signed in |
| `/accounts/profile/` | Your profile | Signed in |
| `/dashboard/` | Role-based dashboard | Signed in, onboarding done |
| `/dashboard/metrics/` | Dashboard data (JSON, refreshed every 30 s) | Signed in, onboarding done |
| `/items/lost/`, `/items/found/` | Browse reports | Signed in, onboarding done |
| `/items/lost/create/`, `/items/found/create/` | New report | Signed in, onboarding done |
| `/items/matches/` | My match suggestions | Signed in, onboarding done |
| `/claims/` | My claims | Signed in, onboarding done |
| `/claims/review/` | Claim review queue | Security officers and staff |
| `/claims/notifications/` | Notifications | Signed in |
| `/admin/` | Django admin | Staff |

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `ImproperlyConfigured: The SECRET_KEY setting must not be empty` | `.env` is missing or has no `SECRET_KEY`. See [step 3](#3-create-your-env-file). |
| `CommandError: You must set settings.ALLOWED_HOSTS if DEBUG is False` | Add `DEBUG=True` to `.env` for local development. |
| Pages load without styling, or images are broken | `DEBUG` is off. Static and media files are only served by the development server when `DEBUG=True`. |
| The category drop-down on the report form is empty | No categories yet. Add them in the admin ([first-time setup](#first-time-setup)). |
| Every page sends me to the onboarding form | Your profile isn't complete yet. Fill in and save the onboarding form. |
| `/claims/review/` shows *403 Forbidden* | Your account isn't a reviewer. An admin must set your user type to *Security Officer* or give you staff status. |
| `Error loading psycopg2` | You're using PostgreSQL without its driver. Run `pip install psycopg2-binary` (or `uv sync`). |

## Known issues

- **Notifications are in-app only.** No emails are sent yet.
