# Delivery roadmap

## Implemented: real public data foundation

- Delhi bus stops and mapped bus route relations from OpenStreetMap/Overpass.
- Interactive OSM tile map, source attribution, data freshness, search, and stop CSV export.
- Optional server-side Delhi OTD GTFS-Realtime vehicle-position adapter, gated by an approved key.
- Live vehicle search across bus/route/trip/stop identifiers, route and status filters, server pagination, and an individual vehicle details drawer from OTD fields.
- Short-lived source caching, incremental marker updates, stale-position indicators, and keyboard-accessible drawer controls.
- No seeded transit records or mock bus positions; source outages remain visible.

## Next: enable official live buses

1. Apply for access on the [Delhi OTD realtime page](https://otd.delhi.gov.in/data/realtime/).
2. Review the OTD terms for the intended use.
3. Set the issued key as `OTD_API_KEY` in the local server environment and restart.
4. Confirm the feed contains positions and show the source timestamp/freshness in the dashboard.

## Production milestones

- Confirm whether Delhi is the permanent target and whether DTC/cluster feeds are in scope.
- Replace public Overpass polling with a robust provider or scheduled extract/refresh if traffic grows; do not increase polling beyond public-service norms.
- Add login, role-based access, audit trail, error reporting, source health monitoring, deployment automation, and operator support process.
- Establish ETA or delay predictions only after obtaining reliable real-time history and measurable ground truth. No AI prediction should be inferred from OSM route geometry.
- Conduct accessibility, load, upstream-failure, privacy, and operational workflow reviews before dispatch use.
