# Operations and deployment

## Local operation

Install dependencies and run `python app.py` as described in the root README. `PORT` and `HOST` configure the local server. Source snapshots persist at `instance/transit-cache.sqlite3`; set `TRANSIT_CACHE_PATH` to move the file. OSM has a 15-minute fresh interval (`OSM_CACHE_SECONDS`) and seven-day stale limit (`OSM_STALE_MAX_AGE_SECONDS`). OTD has a 15-second fresh interval (`OTD_CACHE_SECONDS`) and ten-minute stale limit (`OTD_STALE_MAX_AGE_SECONDS`). `OVERPASS_URL` can point to an approved alternate/self-hosted Overpass endpoint. `OTD_API_KEY` enables official vehicle-position reads.

The first page load reaches public transit data services. If an upstream source is unreachable, a recent real snapshot may be returned with an explicit stale label. With no snapshot, the dashboard reports the source error and shows no replacement/sample features. Refresh retries have a short backoff to avoid repeatedly hitting shared services during an outage.

## Public service policies

- Keep Overpass traffic modest and cached. Public instances are shared and can be overloaded; for sustained service, use a suitable hosted provider or operate your own instance.
- Standard OpenStreetMap tiles are for interactive, visible map use. Do not prefetch tiles, create offline tile archives, or use them as an unrestricted production tile backend. Show OSM attribution and preserve normal caching/referrer behavior.
- Both public services are best effort. Add provider monitoring and a fallback plan before relying on them for operations.

## Production deployment gate

This is not yet a production dispatch system. Before deployment, complete the security requirements, confirm feed rights and provider service terms, use a production WSGI server behind TLS, and establish identity, monitoring, source freshness reporting, rate management, and an on-call owner. Do not use Flask's built-in server in production.

## Signals to monitor

- API latency and errors by endpoint.
- Overpass request duration/failure rate, cache hit rate, and returned feature counts.
- OTD feed fetch status, feed timestamp age, and valid vehicle count.
- User-visible stale/unavailable state and upstream outage duration.
