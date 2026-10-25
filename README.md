# Smart Bus Tracking System

Delhi-focused transit data dashboard. It reads real bus stops and mapped bus routes from OpenStreetMap and can read live vehicle positions from Delhi's official Open Transit Data (OTD) GTFS-Realtime feed when an approved API key is configured.

**There are no seeded bus, route, alert, or GPS records.** Successful real-source snapshots are retained in a local SQLite cache so a restart or short upstream outage does not leave the dashboard blank. Older snapshots are explicitly labeled stale; no demo records are substituted. OpenStreetMap route and stop coverage can be incomplete. OSM features describe transit infrastructure; they are not live vehicle positions.

The live fleet view supports search by bus, route, trip, or stop id; route/status filters; paginated results; selectable map markers; and a per-vehicle details drawer with latest source fields and position freshness.

## Run locally

Requires Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python3 -m pip install -r requirements.txt
python3 app.py
```

Open <http://127.0.0.1:5000>. The app requests Delhi transit features from OpenStreetMap Overpass and OTD vehicle positions independently so a slow map request cannot delay the fleet. A SQLite snapshot in `instance/transit-cache.sqlite3` survives app restarts. See [operations](docs/operations.md) for freshness and expiry settings. The map requests only tiles visible in the user's browser from OpenStreetMap's tile service.

## Customer accounts

The public landing page is at `/`. Customers can register at `/signup` or log in at `/login` using their email address or mobile number. Successful registration and login open the protected `/dashboard`; logging out returns to the landing page. Local development and tests use `instance/customers.sqlite3`; production can use process memory with `CUSTOMER_STORAGE=memory`. Passwords are stored only as Werkzeug password hashes. The local Flask session secret is generated and stored with owner-only file permissions in the ignored `instance/.secret_key` file.

For production, set a strong random `SECRET_KEY` in the hosting platform's secret manager and set `APP_ENV=production` so session cookies require HTTPS. Do not use the local development secret file in a deployment. Memory-only accounts are intentionally temporary: registrations disappear whenever the host restarts, sleeps, or redeploys. This mode avoids an external database but is not appropriate when customers need durable accounts. Add account recovery, email verification, and abuse controls before operating a public customer service.

Run the authentication checks with:

```bash
python3 -m unittest discover -s tests -v
```

## Official live bus positions

Delhi OTD publishes static bus GTFS data. Its live vehicle-position endpoint is available to authorised users with a private key. Apply through the [Delhi OTD real-time access page](https://otd.delhi.gov.in/data/realtime/). For local development, put the issued key in the ignored `.env` file as `OTD_API_KEY=...`; `app.py` loads it at startup. Never commit `.env` or put the key in browser JavaScript. For deployment, inject it through the hosting platform's secret manager instead of a file:

```bash
export OTD_API_KEY='your-issued-private-key'
python app.py
```

Never commit or put the key in browser JavaScript. Without the key, the app shows real OSM stops/routes and marks live vehicles as unavailable. The [official OTD documentation](https://otd.delhi.gov.in/documentation/) warns that static GTFS stop times are approximate estimates.

## Data and API

| Method | Path | Source / purpose |
| --- | --- | --- |
| GET | `/api/v1/transit` | Real Delhi bus stops and bus route relations from OpenStreetMap; stale snapshots include `stale` and `cache_age_seconds` |
| GET | `/api/v1/directions?from=...&to=...` | Direct matches between OSM route `from`/`to` tags and mapped stops; includes matching geometry and relevant OTD vehicles when available |
| GET | `/api/v1/vehicles` | Searchable, paginated Delhi OTD GTFS-Realtime positions; recent cached snapshots are returned with `status: stale` |
| GET | `/api/v1/vehicles?all=1` | All current positions for map rendering |
| GET | `/health` | Process health check |

The transit response includes feature counts, fetch time, source, source links, and ODbL license metadata. API details are in [docs/api.md](docs/api.md).

## Data sources and attribution

- Transit infrastructure: [OpenStreetMap](https://www.openstreetmap.org/), licensed under the [ODbL](https://www.openstreetmap.org/copyright).
- Map tiles: [OpenStreetMap tile service](https://tile.openstreetmap.org/), with visible contributor attribution.
- Optional live positions: [Delhi Open Transit Data](https://otd.delhi.gov.in/), subject to its access approval and terms.

## Project layout

```text
app.py                 Flask application factory and HTTP entry point
auth.py                SQLite or in-memory customer records and password hashing
auth_routes.py         Registration, login, CSRF validation and logout
transit/osm.py         Cached Overpass integration and OSM feature normalization
transit/search.py      Destination matching over mapped stops and route endpoints
transit/vehicles.py    Optional Delhi OTD GTFS-Realtime integration
transit/cache.py       SQLite or bounded in-memory snapshots of source responses
transit/routes.py      Versioned JSON API
templates/index.html  Delhi transit dashboard
templates/landing.html Public landing page
templates/login.html  Customer login form
templates/signup.html Customer registration form
static/                Dashboard styles and map/API behavior
tests/                 Authentication and destination search tests
docs/                  Architecture, API, operations, security, roadmap
```

## Deployment status

This is an integration foundation, not yet a production dispatch system. Customer accounts protect the dashboard, but there is no operator role system or dispatch authorization. Public Overpass and community tile services do not provide a service-level agreement. Live bus GPS needs an OTD-issued key. Review [security](docs/security.md) before deployment.

Read [architecture](docs/architecture.md), [API contract](docs/api.md), [operations](docs/operations.md), [security](docs/security.md), and the [delivery roadmap](docs/roadmap.md) before deploying.

## Free public deployment (Render, memory only)

The app is a single Flask service, so its HTML, static assets, and JSON API deploy together. `render.yaml` configures a free Render web service with Gunicorn and a `/health` check. Render supplies HTTPS and an `onrender.com` subdomain; the requested service name can be unavailable, in which case choose another unique name in Render.

The Render Blueprint sets `CUSTOMER_STORAGE=memory` and `TRANSIT_CACHE_BACKEND=memory`; no database service or database URL is needed. Customer accounts exist only in the running web process. Transit snapshots use a bounded 32 MiB in-memory cache. Both are lost when Render restarts, sleeps, or redeploys; the next transit request fetches fresh data from the real upstream APIs. Render generates `SECRET_KEY` through the Blueprint. Set `OTD_API_KEY` there only if you have an approved OTD key. No `.env` file, local account database, or local session secret should be uploaded. Local development and tests continue to use SQLite.

To deploy, create a **new private GitHub repository for this project** and push this project directory (including your pending UI/auth/search work) without `.env`, `instance/`, or credentials. This checkout currently has no Git remote; do not connect it to a different project repository. In Render, choose **New → Blueprint**, connect that repository, and use its `render.yaml`. Select the free plan. After Render reports a successful deploy, open the service's `onrender.com` URL, verify `/health`, sign up a test customer, log in, and log out. That account is temporary and will be removed by a service restart or sleep.

Render free web services sleep after 15 idle minutes and can take about a minute to wake; Render documents the free tier for hobby/testing rather than production. The process-local memory cache and customer accounts are cleared when this happens. No persistent database or external storage service is used. See [Render free service limits](https://render.com/docs/free).
