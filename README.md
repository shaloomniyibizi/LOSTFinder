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
- [Machine learning](#machine-learning)
- [How claims work](#how-claims-work)
- [Configuration](#configuration)
- [Management commands](#management-commands)
- [Running the tests](#running-the-tests)
- [Project structure](#project-structure)
- [Pages and URLs](#pages-and-urls)
- [REST API](#rest-api)
- [Troubleshooting](#troubleshooting)
- [Known issues](#known-issues)

## Features

- **Public home page** with a live feed of recent reports, campus statistics, search, and the busiest campus zones. Only visitors see it; signed-in users go straight to their dashboard.
- **Accounts:** register and sign in with an email address, then complete a short onboarding profile before using the app.
- **Lost and found reports** with a photo (up to 5 MB), category, location, and date. You can search and filter them, and only the person who reported an item can edit or delete it.
- **Machine learning:** a trained match model scores every lost/found pair, a category model checks each new report, and the dashboard shows the predictions live. The training data comes from the app's own REST API plus synthetic data. See [Machine learning](#machine-learning).
- **Automatic matching:** every time a report is saved, it is compared against the opposite type, and you are told how many possible matches were found.
- **Claims workflow:** submit proof of ownership, security reviews it, then the handover is recorded. Every step is logged and notifies the people involved.
- **Role-based dashboard** built with AdminLTE: summary cards, live-updating charts, and recent-record tables, plus a claim queue for security staff.
- **Notifications** inside the app, with an unread count in the header.
- **Light, dark, and auto themes**, remembered in your browser.
- **REST API** (`/api/v1/`) covering everything the pages do, for mobile apps or other front ends, with interactive Swagger docs at `/api/docs/`. See [REST API](#rest-api).
- **Works offline from a CDN:** AdminLTE, Bootstrap, Bootstrap Icons, and Chart.js are bundled in `static/vendor/`, and Swagger UI comes from the installed `drf-spectacular-sidecar` package.

## Tech stack

| Part | Technology |
| --- | --- |
| Backend | Python 3.14, Django 6.1 |
| API | Django REST Framework 3.18, drf-spectacular 0.30 (OpenAPI 3, Swagger UI) |
| Database | SQLite (default) or PostgreSQL |
| UI | AdminLTE 4.9.1 (Bootstrap 5.3.8), Bootstrap Icons 1.13.1 |
| Charts | Chart.js 4.5.1 |
| Machine learning | scikit-learn 1.9, NumPy, joblib; requests (API client) |
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

## Machine learning

The `ml` app adds two trained models on top of the rule-based engine.

| Model | Input | Output | Algorithm |
| --- | --- | --- | --- |
| **Match model** | 10 features of a lost/found pair: same category, title, description, location and overall text similarity, shared keywords, shared or conflicting colours, days apart, found-before-lost | Probability that both reports describe the same item | Logistic regression **and** random forest are trained; the one with the better F1 is kept |
| **Category model** | Report title and description | Item category | TF-IDF (1–2 word n-grams) + logistic regression |

### The pipeline

```text
REST API ──► fetch_api_data ──► ml/data/api_snapshot.json ─┐
                                                           ├─► train_model ──► ml/artifacts/*.joblib
ml/synthetic.py (simulated owners and finders) ────────────┘                          │
                                                                                      ▼
new report (web form or API) ──► run_matching ──► predictions saved ──► dashboard (live)
```

1. **Read data from the API.** `manage.py fetch_api_data` signs in at `POST /api/v1/auth/token/` and downloads every report and every accepted/rejected match from `GET /api/v1/ml/training-data/` (security staff and administrators only). Accepted matches are positive examples, rejected ones negative; every report is a labelled example for the category model.
2. **Add synthetic data.** A campus produces only a handful of decided matches, so `ml/synthetic.py` simulates the process behind the data: an owner and a finder describe the same object in their own words (different nouns, a missing brand, a misjudged colour, a nearby spot, a delay of a few days, sometimes the wrong category), and look-alike objects (same kind, different colour, brand, place or time) are used as hard negatives. It is seeded, so every run is reproducible.
3. **Train and evaluate.** `manage.py train_model` uses a stratified 80/20 split and reports accuracy, precision, recall, F1, ROC AUC and the confusion matrix. The old rule-based score (35 or more) is evaluated on the same test set as a baseline. A typical run gives:

   | Approach | Precision | Recall | F1 | ROC AUC |
   | --- | --- | --- | --- | --- |
   | Rule-based engine (baseline) | 0.49 | 0.96 | 0.65 | 0.88 |
   | Logistic regression | 0.83 | 0.95 | 0.89 | 0.98 |
   | Random forest | 0.84 | 0.94 | 0.89 | 0.98 |

   The rules find almost every match but also flag many look-alikes; the model keeps the recall with far fewer false alarms. The category model reaches about 92% accuracy.
4. **Deploy in Django.** Models are saved with joblib in `ml/artifacts/` (with a `.json` summary) and recorded as `ModelVersion` rows. `ml/predictor.py` loads them once per process and reloads automatically when the file changes, so a retrain needs no restart.
5. **Predict on new data.** Every time a report is saved, from the web form or the API, matching scores all candidate pairs with the model in one batch and stores the probability on each suggestion (`MatchSuggestion.ml_probability`). A pair the rules score too low is still suggested when the model is at least **60%** sure. The category model's guess is stored as a `CategoryPrediction`, which flags reports that may be filed under the wrong category.

If no model file exists, or `ML_ENABLED=False`, everything falls back to the rule-based engine. The test suite runs with ML switched off, except `ml/tests.py`, which trains small models into a temporary folder.

### Where the predictions appear

- **Dashboard → AI insights** (refreshes every 30 seconds): matches scored today, average confidence, matches found only by the model, how often the model agrees with users' accept/reject decisions, category agreement, the latest predictions with probability bars, a confidence histogram, a feature-importance chart, category checks on new reports, and the active models' metrics. Reviewers see campus-wide numbers; everyone else sees their own reports. Administrators get a **Retrain models** button.
- **AI models page** (`/ml/`, security staff and admins): the full comparison table, confusion matrices, per-category F1, feature importance and training history.
- **Match cards:** "AI model: 87% likely the same item" next to the rule score.
- **Report form:** while you type the title and description, the category model suggests a category with a one-click **Use** button.

### Try it end to end

```bash
python manage.py seed_demo                 # demo accounts and reports
python manage.py runserver                 # terminal 1, leave running

# terminal 2
python manage.py fetch_api_data --email officer@lostfinder.test --password "Demo-Pass-2026!"
python manage.py train_model --rescore     # train, save, re-score existing data
python manage.py simulate_incoming --count 10 --interval 5
```

`simulate_incoming` posts new found and lost reports through the API (as the demo accounts `grace` and `amina`); usually the lost report describes the same object as the found one. Sign in as `officer@lostfinder.test` and watch the dashboard update.

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
| `ML_ENABLED` | `True` | Use the trained models. `False` falls back to rule-based matching only. |
| `LOSTFINDER_API_URL` | `http://127.0.0.1:8000/api/v1/` | API used by `fetch_api_data` and `simulate_incoming` |

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
| `python manage.py fetch_api_data --email … --password …` | Download ML training data from the REST API into `ml/data/api_snapshot.json` (needs a running server and a security/staff account) |
| `python manage.py train_model [--rescore] [--synthetic-only]` | Train the match and category models, print their metrics against the rule-based baseline, and save them to `ml/artifacts/`. `--rescore` refreshes every stored prediction. |
| `python manage.py simulate_incoming [--count N --interval S]` | Post synthetic lost/found reports through the API to demo live predictions |
| `python manage.py test` | Run the test suite |

## Running the tests

```bash
python manage.py test
```

187 tests cover:

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
- the REST API: authentication, onboarding, permissions, privacy rules, the claim workflow, and the OpenAPI schema (`python manage.py test api`)

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
├── items/           Lost/found reports, matching engine (matching.py), report services (services.py), match pages
│   └── management/commands/   run_matching.py, seed_demo.py
├── claims/          Claims workflow (services.py), review queue, handovers, notifications
├── dashboard/       Public home page, role-based dashboard, metrics (metrics.py)
├── api/             REST API: serializers, viewsets, permissions, URLs (/api/); ML endpoints in ml_views.py
├── ml/              Machine learning: features.py, synthetic.py, dataset.py, training.py, predictor.py,
│   │                insights.py (dashboard panel), model report page
│   ├── management/commands/   fetch_api_data.py, train_model.py, simulate_incoming.py
│   └── artifacts/   Trained models (joblib) and their metrics (json)
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
| `/ml/` | AI models report | Security officers and staff |
| `/ml/retrain/` | Retrain the models (POST) | Staff |
| `/admin/` | Django admin | Staff |
| `/api/v1/` | REST API (see below) | API clients |
| `/api/docs/`, `/api/schema/` | Swagger UI, OpenAPI schema | Anyone |

## REST API

LOSTFinder is API-driven: the web pages and the REST API are two front doors to the same service layer, so both apply exactly the same rules.

```text
 Browser pages (templates)        Mobile app / SPA / scripts
          │                                  │
   Django views (items/, claims/)     REST API (api/, /api/v1/)
          └──────────────┬───────────────────┘
                 Service layer
   items/services.py · items/matching.py · claims/services.py · dashboard/metrics.py
                         │
                  Models / database
```

Neither front door changes records itself. Matching, claim status changes, review logs, notifications and handovers all happen in the service functions.

### Interactive documentation

With the server running, open <http://127.0.0.1:8000/api/docs/>. Every endpoint, parameter and response is listed there, and you can try requests from the page. The raw OpenAPI 3 schema is at `/api/schema/`. To save it to a file, run `python manage.py spectacular --file schema.yml`.

### Authentication

- **Browser:** if you are signed in to the site, the API uses your session. Write requests (`POST`, `PATCH`, `DELETE`) need the CSRF token, as forms do.
- **Other clients:** get a token, then send it in the `Authorization` header with every request.

```bash
# Get a token (or create an account with POST /api/v1/auth/register/)
curl -X POST http://127.0.0.1:8000/api/v1/auth/token/ \
     -H "Content-Type: application/json" \
     -d '{"email": "amina@lostfinder.test", "password": "Demo-Pass-2026!"}'

# Use it
curl http://127.0.0.1:8000/api/v1/matches/ -H "Authorization: Token <token>"
```

New accounts must complete onboarding before using the other endpoints, as on the website: send `PATCH /api/v1/me/` with the profile fields. Until then, the other endpoints answer `403`.

### Endpoints

All paths start with `/api/v1/`. Lists are paginated: 12 per page, `?page=N`, with `count`, `next`, `previous` and `results` in the response.

| Method and path | What it does | Who |
| --- | --- | --- |
| `POST auth/register/` | Create an account (`email`, `password`, `password_confirm`); returns a token | Anyone |
| `POST auth/token/` | Exchange email and password for a token | Anyone |
| `POST auth/logout/` | Revoke the token (or end the session) | Signed in |
| `GET`, `PATCH`, `PUT me/` | Your account and profile; `PATCH` completes onboarding. Accepts `multipart/form-data` for `profile_photo` | Signed in |
| `GET categories/` | Active item categories | Onboarded |
| `GET`, `POST lost-items/`, `found-items/` | List (filters: `q`, `category`, `status`, `mine=true`) or create a report. Creating runs matching and returns `matches_found`. Photos via `multipart/form-data` | Onboarded |
| `GET`, `PATCH`, `PUT`, `DELETE lost-items/{id}/`, `found-items/{id}/` | One report. Only its reporter can change or delete it. Deleting a found item that has claims answers `409` | Onboarded |
| `GET lost-items/{id}/matches/`, `found-items/{id}/matches/` | Live match suggestions for a report (empty unless it is yours) | Onboarded |
| `GET matches/` | Matches involving your reports (`status`: `active` (default), `pending`, `accepted`, `rejected`, `all`; `side`: `lost` or `found`) | Onboarded |
| `POST matches/{id}/decision/` | `{"action": "accept" \| "reject" \| "reset"}` | Owner of the lost item |
| `GET claims/` | `scope=mine` (default), `scope=found` (claims on items you turned in) or `scope=review` (review queue: `status=active\|approved\|closed\|all`, `q`) | Onboarded; `review` for reviewers |
| `POST claims/` | Claim a found item: `{"found_item": id, "evidence_description": "..."}` | Onboarded |
| `GET claims/{id}/` | A claim with its timeline and handover. The finder never sees the evidence or the claimant's email | Claimant, finder, reviewers |
| `POST claims/{id}/cancel/` | Cancel your claim | Claimant |
| `POST claims/{id}/review/` | `{"decision": "under_review" \| "approved" \| "rejected", "comments": "..."}` | Security officers and staff |
| `POST claims/{id}/handover/` | `{"handover_location": "...", "handed_over_at": "<ISO datetime, optional>", "notes": "..."}` | Security officers and staff |
| `GET notifications/` | Your notifications (`unread=true` for unread only) | Signed in |
| `POST notifications/{id}/read/`, `notifications/read-all/` | Mark one, or all, as read | Signed in |
| `GET dashboard/` | Dashboard card values and chart series for your role, including the AI insights | Onboarded |
| `GET ml/training-data/` | Every report and every accepted/rejected match, for training (read by `fetch_api_data`) | Security officers and staff |
| `GET ml/models/` | Active match and category models: version, test metrics, feature importances | Onboarded |
| `POST ml/predict-match/` | `{"lost_item": id, "found_item": id}`: model probability, rule score and the feature values. `503` if no model is trained | Onboarded |
| `POST ml/predict-category/` | `{"title": "...", "description": "..."}`: predicted category, confidence and alternatives | Onboarded |

Errors use the usual HTTP status codes: `400` for invalid input or a step the workflow doesn't allow, with the reason in the body; `401` when not signed in; `403` when not allowed; `404` when not found or not visible to you; `409` for conflicts.

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
