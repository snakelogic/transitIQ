# Security and privacy

## Current state

The app has customer registration and login. Local development stores customer records in `instance/customers.sqlite3`; a memory-only deployment keeps them in the web process. Memory-backed accounts are lost on restart, idle sleep, redeploy, or instance replacement. Passwords are Werkzeug password hashes, never plaintext. Login and registration forms and logout use a session-bound CSRF token. Flask's signed session cookie is HttpOnly and SameSite=Lax, and becomes Secure when `APP_ENV=production`. In local development, a random session secret is generated in the ignored `instance/.secret_key` file. Production must set `SECRET_KEY` through the hosting platform's secret manager and set `APP_ENV=production` to require HTTPS cookies. Rotate that secret to invalidate all active sessions.

Customer authentication protects the rendered `/dashboard` page. The read-only `/api/v1/transit` and `/api/v1/vehicles` endpoints remain public to preserve the existing dashboard data integrations; do not add private customer data to those responses. There is no operator role system, audit trail, account recovery, verified email workflow, or login rate limiting. Do not expose this app as an operations control plane.

`OTD_API_KEY` is read server-side and never returned to the browser. The local workspace may store it in `.env`, which is ignored by Git. Keep it out of source control, logs, screenshots, and browser code. In deployment, use the platform's secret manager rather than copying the local `.env`.

The OSM tile service receives normal browser tile requests and may receive the referring website origin. Use its tile URL, attribution, caching behavior, and referrer requirements according to the [tile policy](https://operations.osmfoundation.org/policies/tiles/). Public Overpass data calls are cached to reduce request volume.

## Required before production

1. Set `SECRET_KEY` to a long random value in the hosting secret manager and enable HTTPS. Do not deploy the development `instance/.secret_key` file.
2. Add account recovery, email/mobile verification, login rate limiting, and monitoring before opening registration to the public.
3. Add organization identity (OIDC/SAML as applicable), role checks, and deny-by-default permissions before adding operator controls.
4. Store an approved OTD key in a managed secret store. Rotate it if disclosed; do not commit it, log it, or place it in a browser bundle.
5. Review Delhi OTD terms and approved use with the data provider; confirm whether redistribution, caching, and production use are allowed for your application.
6. Define data retention and privacy rules for live location history if you add storage. Avoid driver/passenger personal data unless required and reviewed.
7. If customers need accounts that survive restarts, replace the memory-only production mode with an approved persistent account store and establish backups and an incident response process.

The current browser Content Security Policy allows the specific map, font, and Leaflet CDNs needed for the dashboard. Self-host or review these dependencies for a locked-down deployment.
