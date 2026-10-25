# API contract

Base path: `/api/v1`. Source failures return a JSON `error` object and HTTP 503; they are not replaced with sample data.

## `GET /transit`

Fetches normalized Delhi bus stops and mapped bus route relations from OpenStreetMap via Overpass. Top-level response is `{ "data": { ... } }`. The `data` object contains:

- `city`, `region`, and `bounds` for the selected source area.
- `stops`: OSM element id, name, latitude/longitude, optional operator/reference/wheelchair tag, and source feature URL.
- `routes`: relation id, name, optional reference/operator/from/to tags, and source relation URL.
- `route_features`: GeoJSON FeatureCollection built from mapped way geometry in route relations.
- `counts`, `source`, `source_url`, `license`, `fetched_at`, and `cached_seconds`.

Requests use a 15-minute cache. Local development persists snapshots in SQLite; deployment can use `TRANSIT_CACHE_BACKEND=memory`, which keeps them only in process memory. While a cached snapshot is less than seven days old, source refresh can happen in the background and the API returns it with `stale: true` and `cache_age_seconds`. Memory snapshots are lost when the process restarts or sleeps. The current Delhi bounding box is configured in `transit/osm.py`.

## `GET /directions`

Searches `from` and `to` query parameters against OSM stop names/references and route relation `from`/`to` tags. Both parameters are required and limited to 120 characters. The response uses `status: "routes_found"`, `"no_direct_route"`, or `"unmatched_locations"`. Matching routes include their route reference, mapped boarding/destination endpoint labels, any matching OTD vehicles, and only the corresponding route geometry. No ETA or duration is returned because this app has no timetable data. Intermediate stops are empty because the current normalized OSM source does not provide a dependable stop sequence. When there is no direct match, `alternatives` may include routes that match one of the entered endpoints; these are suggestions, not connecting itineraries. OTD vehicle positions are optional and are omitted when the live feed is unavailable.

## `GET /vehicles`

Fetches GTFS-Realtime positions from Delhi OTD. The feed is cached for 15 seconds by default (`OTD_CACHE_SECONDS`). Non-empty successful snapshots can be served stale for up to ten minutes (`OTD_STALE_MAX_AGE_SECONDS`) while refresh runs in the background; responses then set `live: false`, `status: "stale"`, and `cache_age_seconds`. With no key it returns HTTP 200 with `status: "key_required"`. If no recent snapshot exists and OTD fails, it returns HTTP 503. The private key is never included in API responses or error messages. When `TRANSIT_CACHE_BACKEND=memory`, snapshots do not survive a process restart.

Successful data includes bus identifier/label, route/trip ids, current stop id and sequence, transit status, occupancy where supplied, latitude/longitude, bearing, speed, and source timestamp.

By default this endpoint returns a paginated list. Optional query parameters are `q` (bus id/label, route, trip, or stop), `route_id`, `status` (`IN_TRANSIT_TO`, `STOPPED_AT`, `INCOMING_AT`, or `UNKNOWN`), `page` (1 based), and `page_size` (1 to 100). The response includes `total`, `page`, `page_size`, and `pages`. Add `all=1` to request all positions for map rendering; use this sparingly.

## `GET /vehicles/{vehicle_id}`

Returns the latest vehicle record currently in the cached OTD snapshot, with the feed timestamp and source. Returns 404 if that vehicle is no longer present in the current feed.

## `GET /health`

Reports that the Flask process is responding. It does not guarantee that an upstream transit-data provider is healthy.

## Source data caveats

OpenStreetMap route/stops are community-maintained and may be incomplete or stale. Delhi OTD documentation says static schedule times are rough estimates. Do not interpret either source as a guaranteed dispatch feed without confirming its update cadence and intended use with the provider.
