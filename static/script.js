const API = "/api/v1";
const DELHI = [28.6139, 77.2090];
const PAGE_SIZE = 50;
let transitData = null;
let vehicleData = [];
let vehicleSnapshotStale = false;
let fleetPage = 1;
let fleetPages = 0;
let fleetRequest = 0;
let selectedBusId = null;
let lastFocusedElement = null;
let fleetSearchTimer;
let transitCanvas;
let stopLayer;
let routeLayer;
let vehicleLayer;
let destinationRouteLayer;
let destinationMarkerLayer;
const vehicleMarkers = new Map();
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "—").replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
})[char]);

const map = L.map("transit-map", { preferCanvas: true }).setView(DELHI, 11);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>',
}).addTo(map);
transitCanvas = L.canvas({ padding: 0.5 });
stopLayer = L.layerGroup().addTo(map);
routeLayer = L.geoJSON(null, { style: { color: "#278866", weight: 4, opacity: 0.76 } }).addTo(map);
vehicleLayer = L.layerGroup().addTo(map);
destinationRouteLayer = L.geoJSON(null, { style: { color: "#1679df", weight: 7, opacity: 0.94, lineCap: "round", lineJoin: "round" } }).addTo(map);
destinationMarkerLayer = L.layerGroup().addTo(map);

async function fetchJson(path) {
  const response = await fetch(`${API}${path}`, { headers: { Accept: "application/json" } });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error?.message || payload.message || `Request failed (${response.status})`);
  return payload;
}

function statusLabel(status) {
  return ({ IN_TRANSIT_TO: "In transit", STOPPED_AT: "Stopped at stop", INCOMING_AT: "Approaching stop", UNKNOWN: "Status unavailable" })[status] || "Status unavailable";
}

function statusColor(status) {
  return ({ IN_TRANSIT_TO: "#278866", STOPPED_AT: "#cf8a30", INCOMING_AT: "#547fcb" })[status] || "#78858c";
}

function relativeTime(timestamp) {
  if (!timestamp) return "Timestamp unavailable";
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - timestamp));
  if (seconds < 10) return "Just now";
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor(seconds % 3600 / 60)}m ago`;
}

function readableEnum(value) {
  if (!value) return "Not reported";
  return value.toLowerCase().replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function busById(busId) {
  return vehicleData.find((bus) => String(bus.id) === String(busId));
}

function renderStops() {
  if (!transitData) return;
  const query = $("#stop-search").value.trim().toLowerCase();
  const matches = transitData.stops.filter((stop) => `${stop.name} ${stop.ref || ""} ${stop.operator || ""}`.toLowerCase().includes(query));
  $("#stops-body").innerHTML = matches.length ? matches.slice(0, 100).map((stop) => `
    <tr><td><div class="stop-name"><span class="stop-table-dot"></span><b>${escapeHtml(stop.name)}</b></div></td>
      <td>${stop.ref ? escapeHtml(stop.ref) : '<span class="not-mapped">Not tagged</span>'}</td>
      <td>${escapeHtml(stop.operator)}</td><td>${escapeHtml(stop.wheelchair)}</td>
      <td><a class="table-link" href="${escapeHtml(stop.source_url)}" target="_blank" rel="noreferrer">OSM ↗</a></td></tr>`).join("") : '<tr><td colspan="5" class="empty-state">No mapped stops match that search.</td></tr>';
  $("#stop-table-count").textContent = `Showing ${Math.min(matches.length, 100)} of ${matches.length} matching stops`;
}

function renderRoutes() {
  if (!transitData) return;
  const query = $("#route-search").value.trim().toLowerCase();
  const matches = transitData.routes.filter((route) => `${route.name} ${route.ref || ""} ${route.operator || ""} ${route.from || ""} ${route.to || ""}`.toLowerCase().includes(query));
  $("#routes-body").innerHTML = matches.length ? matches.slice(0, 100).map((route) => `
    <tr><td><b class="route-name">${escapeHtml(route.name)}</b></td><td>${escapeHtml(route.ref)}</td>
      <td>${escapeHtml(route.from)}</td><td>${escapeHtml(route.to)}</td><td>${escapeHtml(route.operator)}</td>
      <td><a class="table-link" href="${escapeHtml(route.source_url)}" target="_blank" rel="noreferrer">OSM ↗</a></td></tr>`).join("") : '<tr><td colspan="6" class="empty-state">No mapped bus routes match that search.</td></tr>';
  $("#route-table-count").textContent = `Showing ${Math.min(matches.length, 100)} of ${matches.length} matching routes`;
}

function renderMapData() {
  if (!transitData) return;
  stopLayer.clearLayers();
  routeLayer.clearLayers();
  const stopStyle = { radius: 4, color: "#fff", weight: 1, fillColor: "#27916b", fillOpacity: 0.95, renderer: transitCanvas };
  transitData.stops.forEach((stop) => {
    if (!Number.isFinite(stop.lat) || !Number.isFinite(stop.lon)) return;
    L.circleMarker([stop.lat, stop.lon], stopStyle).bindPopup(
      `<strong>${escapeHtml(stop.name)}</strong><br>Bus stop · OpenStreetMap<br><a href="${escapeHtml(stop.source_url)}" target="_blank" rel="noreferrer">View source feature ↗</a>`,
    ).addTo(stopLayer);
  });
  if ($("#routes-toggle").checked) routeLayer.addData(transitData.route_features);
  renderVehicleMarkers();
}

function renderVehicleMarkers() {
  const currentIds = new Set();
  vehicleData.forEach((bus) => {
    if (!Number.isFinite(bus.lat) || !Number.isFinite(bus.lon)) return;
    const id = String(bus.id);
    currentIds.add(id);
    let marker = vehicleMarkers.get(id);
    const style = { radius: selectedBusId === id ? 9 : 6, color: "#fff", weight: selectedBusId === id ? 3 : 1.5, fillColor: statusColor(bus.current_status), fillOpacity: vehicleSnapshotStale ? 0.55 : 1, renderer: transitCanvas };
    if (marker) {
      marker.setLatLng([bus.lat, bus.lon]);
      marker.setStyle(style);
    } else {
      marker = L.circleMarker([bus.lat, bus.lon], style).addTo(vehicleLayer);
      marker.on("click", () => openBusDetails(id));
      vehicleMarkers.set(id, marker);
    }
    if (!marker.getTooltip()) marker.bindTooltip(escapeHtml(bus.label || bus.id), { direction: "top", offset: [0, -7], opacity: 0.95 });
  });
  for (const [id, marker] of vehicleMarkers) {
    if (!currentIds.has(id)) {
      vehicleLayer.removeLayer(marker);
      vehicleMarkers.delete(id);
    }
  }
  if (selectedBusId && busById(selectedBusId)) {
    renderBusDetails(busById(selectedBusId));
  } else if (selectedBusId) {
    const freshness = $("#bus-details .freshness-card");
    if (freshness) {
      freshness.classList.add("stale");
      freshness.querySelector("b").textContent = "Vehicle is absent from the latest feed";
      freshness.querySelector("small").textContent = "Displayed details are from its last reported position.";
    }
  }
}

function vehicleQuery(page) {
  const params = new URLSearchParams({
    q: $("#bus-search").value.trim(),
    route_id: $("#bus-route-filter").value,
    status: $("#bus-status-filter").value,
    page: String(page),
    page_size: String(PAGE_SIZE),
  });
  return params.toString();
}

async function loadFleetPage(page = 1) {
  const requestId = ++fleetRequest;
  fleetPage = page;
  try {
    const payload = await fetchJson(`/vehicles?${vehicleQuery(page)}`);
    if (requestId !== fleetRequest) return;
    if (payload.pages > 0 && page > payload.pages) return loadFleetPage(payload.pages);
    if (payload.pages === 0 && page > 1) return loadFleetPage(1);
    renderFleetPage(payload);
  } catch (error) {
    if (requestId !== fleetRequest) return;
    $("#fleet-body").innerHTML = `<tr><td colspan="7" class="empty-state">Could not load vehicles: ${escapeHtml(error.message)}</td></tr>`;
  }
}

function renderFleetPage(payload) {
  const buses = payload.data || [];
  fleetPage = payload.page || 1;
  fleetPages = payload.pages || 0;
  $("#fleet-count").textContent = (payload.total ?? payload.count ?? 0).toLocaleString("en-IN");
  $("#fleet-result-count").textContent = payload.total === undefined
    ? `${buses.length.toLocaleString("en-IN")} live vehicles`
    : `Showing ${payload.total ? (fleetPage - 1) * PAGE_SIZE + 1 : 0}–${Math.min(fleetPage * PAGE_SIZE, payload.total).toLocaleString("en-IN")} of ${payload.total.toLocaleString("en-IN")} matches`;
  $("#fleet-page-label").textContent = `Page ${fleetPages ? fleetPage : 0} of ${fleetPages}`;
  $("#fleet-previous").disabled = fleetPage <= 1 || fleetPages === 0;
  $("#fleet-next").disabled = fleetPage >= fleetPages;
  $("#fleet-body").innerHTML = buses.length ? buses.map((bus) => `
    <tr class="bus-row ${String(bus.id) === selectedBusId ? "selected" : ""}" data-bus-id="${escapeHtml(bus.id)}">
      <td><div class="bus-cell"><span class="bus-glyph" style="--bus-color:${statusColor(bus.current_status)}">▣</span><div><b>${escapeHtml(bus.label || bus.id)}</b><small>${escapeHtml(bus.id)}</small></div></div></td>
      <td><span class="route-tag">${escapeHtml(bus.route_id)}</span></td>
      <td><span class="vehicle-status" style="--bus-color:${statusColor(bus.current_status)}"><i></i>${escapeHtml(statusLabel(bus.current_status))}</span></td>
      <td>${bus.speed_mps === null ? "—" : `${(bus.speed_mps * 3.6).toFixed(0)} km/h`}</td>
      <td>${escapeHtml(relativeTime(bus.timestamp || payload.feed_timestamp))}</td><td>${escapeHtml(bus.stop_id)}</td>
      <td><button class="row-open" data-open-bus="${escapeHtml(bus.id)}" aria-label="View details for ${escapeHtml(bus.label || bus.id)}">Details <span>→</span></button></td></tr>`).join("") : '<tr><td colspan="7" class="empty-state">No live vehicles match these filters.</td></tr>';
  $("#fleet-body").querySelectorAll("[data-bus-id]").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (!event.target.closest("a,button")) openBusDetails(row.dataset.busId);
    });
  });
  $("#fleet-body").querySelectorAll("[data-open-bus]").forEach((button) => button.addEventListener("click", () => openBusDetails(button.dataset.openBus)));
}

function renderTransit(data) {
  transitData = data;
  updateDestinationSuggestions(data);
  $("#map-data-status").textContent = !data.route_data_available
    ? "Showing real mapped bus stops only; route data is temporarily unavailable."
    : data.route_geometry_available
      ? "Mapped bus stops and route geometry across Delhi"
      : "Showing real mapped stops and route endpoints; route line geometry is currently unavailable.";
  $("#metric-stops").textContent = data.counts.stops.toLocaleString("en-IN");
  $("#metric-routes").textContent = data.counts.routes.toLocaleString("en-IN");
  $("#stop-count").textContent = data.counts.stops.toLocaleString("en-IN");
  $("#route-count").textContent = data.counts.routes.toLocaleString("en-IN");
  const updated = new Date(data.fetched_at * 1000).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
  $("#data-updated").textContent = `Fetched ${updated}`;
  $("#source-attribution").textContent = `Fetched ${updated} · cached ${Math.round(data.cached_seconds / 60)} min`;
  $("#stops-status").textContent = `From live Overpass query · ${data.region}`;
  $("#sync-label").textContent = data.stale
    ? `Showing cached OSM data · ${relativeTime(data.fetched_at)}`
    : `OSM data fetched ${new Date(data.fetched_at * 1000).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}`;
  $(".sync-state").classList.toggle("sync-error", Boolean(data.stale));
  $("#map-loading")?.remove();
  renderStops();
  renderRoutes();
  renderMapData();
}

function updateDestinationSuggestions(data) {
  const values = new Set();
  (data.stops || []).forEach((stop) => {
    if (stop.name && stop.name !== "Unnamed bus stop") values.add(stop.name);
    if (stop.ref) values.add(stop.ref);
  });
  (data.routes || []).forEach((route) => {
    if (route.from) values.add(route.from);
    if (route.to) values.add(route.to);
  });
  $("#location-suggestions").innerHTML = [...values].sort((a, b) => a.localeCompare(b)).map((value) => `<option value="${escapeHtml(value)}"></option>`).join("");
}

function clearDestinationMap() {
  destinationRouteLayer.clearLayers();
  destinationMarkerLayer.clearLayers();
}

function addDestinationMapResults(result) {
  clearDestinationMap();
  const features = result.route_features?.features || [];
  if (features.length) destinationRouteLayer.addData({ type: "FeatureCollection", features });
  const points = [];
  const selectedRoute = result.routes?.[0];
  const locations = selectedRoute && transitData ? [
    { location: transitData.stops.find((stop) => stop.name === selectedRoute.boarding_stop), color: "#18966d", label: "Starting point" },
    { location: transitData.stops.find((stop) => stop.name === selectedRoute.destination_stop), color: "#d45b68", label: "Destination" },
  ] : [
    { location: result.origin?.matches?.find((item) => item.type === "stop"), color: "#18966d", label: "Starting point" },
    { location: result.destination?.matches?.find((item) => item.type === "stop"), color: "#d45b68", label: "Destination" },
  ];
  locations.forEach(({ location: stop, color, label }) => {
    if (!stop || stop.lat === null || stop.lon === null || stop.lat === undefined || stop.lon === undefined) return;
    if (!Number.isFinite(Number(stop.lat)) || !Number.isFinite(Number(stop.lon))) return;
    const point = [Number(stop.lat), Number(stop.lon)];
    points.push(point);
    L.circleMarker(point, { radius: 9, color: "#fff", weight: 3, fillColor: color, fillOpacity: 1 })
      .bindTooltip(`${label}: ${escapeHtml(stop.name)}`, { permanent: true, direction: "top", offset: [0, -7] })
      .addTo(destinationMarkerLayer);
  });
  const routeBounds = destinationRouteLayer.getBounds();
  if (routeBounds.isValid()) map.fitBounds(routeBounds, { padding: [38, 38], maxZoom: 13 });
  else if (points.length) map.fitBounds(L.latLngBounds(points), { padding: [50, 50], maxZoom: 14 });
}

function locationMatchText(location) {
  const matches = location?.matches || [];
  return matches.length ? matches.map((item) => escapeHtml(item.name)).join(", ") : "No matching mapped stop or route endpoint";
}

function renderDestinationSearch(result) {
  const feedback = $("#destination-feedback");
  const panel = $("#destination-results");
  feedback.hidden = true;
  panel.hidden = false;
  const originName = escapeHtml(result.origin?.query);
  const destinationName = escapeHtml(result.destination?.query);
  if (result.status === "unmatched_locations") {
    panel.innerHTML = `<div class="search-result-heading"><span class="result-status result-error">Location not found</span><h3>Check the selected places</h3><p>${escapeHtml(result.message)}</p></div>
      <div class="location-checks"><div><small>FROM · ${originName}</small><b>${locationMatchText(result.origin)}</b></div><div><small>TO · ${destinationName}</small><b>${locationMatchText(result.destination)}</b></div></div>`;
    return;
  }
  if (result.status === "no_direct_route") {
    const alternatives = (result.alternatives || []).map((route) => `<article class="alternative-route"><b>${escapeHtml(route.ref || route.name)}</b><span>${escapeHtml(route.from)} <i>→</i> ${escapeHtml(route.to)}</span></article>`).join("");
    panel.innerHTML = `<div class="search-result-heading"><span class="result-status result-warn">No direct route</span><h3>No direct route found</h3><p>Mapped route endpoint tags don’t show a direct connection from ${originName} to ${destinationName}.</p></div>
      ${alternatives ? `<div class="alternative-list"><b>Nearby mapped route options</b>${alternatives}</div>` : ""}`;
    return;
  }
  const routes = (result.routes || []).map((route) => {
    const buses = (route.buses || []).map((bus) => `<span class="matched-bus"><i></i>${escapeHtml(bus.label || bus.id)} · ${escapeHtml(statusLabel(bus.current_status))}${result.live_stale ? " · saved position" : ""}</span>`).join("");
    const liveText = route.buses?.length
      ? `<div class="matched-buses">${buses}</div>`
      : `<p class="bus-unavailable">${escapeHtml(result.live_message || "No matching live bus positions are available for this route.")}</p>`;
    return `<article class="matched-route"><div class="matched-route-head"><div><span>BUS ROUTE ${route.ref ? `· ${escapeHtml(route.ref)}` : ""}</span><h4>${escapeHtml(route.name)}</h4></div><span class="route-match-badge">Mapped</span></div>
      <div class="journey-points"><div><i class="journey-dot journey-start"></i><small>BOARD AT</small><b>${escapeHtml(route.boarding_stop || "Not specified")}</b></div><div class="journey-connector"></div><div><i class="journey-dot journey-end"></i><small>DESTINATION</small><b>${escapeHtml(route.destination_stop || "Not specified")}</b></div></div>
      <div class="route-detail-note">Intermediate stops and travel time aren’t included in the mapped route data. <a href="#map">View highlighted route on map ↗</a></div>${liveText}</article>`;
  }).join("");
  const liveLabel = result.live_status === "connected" ? "Official live feed checked" : result.live_status === "stale" ? "Showing saved vehicle positions" : "Live vehicle positions unavailable";
  panel.innerHTML = `<div class="search-result-heading"><span class="result-status result-success">${(result.routes || []).length} direct ${result.routes?.length === 1 ? "route" : "routes"}</span><h3>Route options</h3><p>${originName} <span>→</span> ${destinationName}</p><small class="live-search-label">${escapeHtml(liveLabel)}</small></div>${routes}`;
}

async function searchDestinations(event) {
  event.preventDefault();
  clearDestinationMap();
  const origin = $("#destination-from").value.trim();
  const destination = $("#destination-to").value.trim();
  const feedback = $("#destination-feedback");
  const panel = $("#destination-results");
  panel.hidden = true;
  feedback.hidden = false;
  if (!origin || !destination) {
    feedback.textContent = !origin && !destination ? "Enter a starting point and destination." : !origin ? "Enter a starting point." : "Enter a destination.";
    (!origin ? $("#destination-from") : $("#destination-to")).focus();
    return;
  }
  const submit = $(".destination-submit");
  submit.disabled = true;
  submit.innerHTML = '<span class="search-spinner"></span> Searching…';
  feedback.textContent = "Checking mapped stops and route endpoints…";
  try {
    const query = new URLSearchParams({ from: origin, to: destination });
    const result = await fetchJson(`/directions?${query}`);
    feedback.hidden = true;
    renderDestinationSearch(result);
    addDestinationMapResults(result);
  } catch (error) {
    feedback.textContent = `Route search is temporarily unavailable. ${error.message}`;
  } finally {
    submit.disabled = false;
    submit.innerHTML = '<span>⌕</span> Search route';
  }
}

function clearDestinationSearch() {
  $("#destination-from").value = "";
  $("#destination-to").value = "";
  $("#destination-feedback").hidden = true;
  $("#destination-feedback").textContent = "";
  $("#destination-results").hidden = true;
  $("#destination-results").innerHTML = "";
  clearDestinationMap();
  map.setView(DELHI, 11);
}

$("#destination-search-form").addEventListener("submit", searchDestinations);
$("#swap-locations").addEventListener("click", () => {
  const from = $("#destination-from");
  const to = $("#destination-to");
  [from.value, to.value] = [to.value, from.value];
  $("#destination-feedback").hidden = true;
  $("#destination-results").hidden = true;
  clearDestinationMap();
  from.focus();
});
$("#clear-destination-search").addEventListener("click", clearDestinationSearch);

function renderVehicles(payload) {
  vehicleData = payload.data || [];
  vehicleSnapshotStale = Boolean(payload.stale || payload.status === "stale");
  const hasPositions = vehicleData.length > 0;
  $("#metric-vehicles").textContent = hasPositions ? vehicleData.length.toLocaleString("en-IN") : (payload.live ? "0" : "—");
  $("#metric-vehicles").classList.toggle("live-number", Boolean(payload.live));
  if (payload.live) {
    $("#vehicle-state").textContent = "live positions";
    $("#vehicle-updated").textContent = payload.feed_timestamp
      ? `Feed updated ${relativeTime(payload.feed_timestamp)}${payload.cache_age_seconds ? ` · cached ${payload.cache_age_seconds}s` : ""}`
      : "Delhi OTD feed connected";
    $("#data-notice").innerHTML = '<span class="notice-icon">✓</span><span><b>Official live vehicle feed connected.</b> Bus markers come from Delhi Open Transit Data GTFS-Realtime.</span><a href="https://otd.delhi.gov.in/data/realtime/" target="_blank" rel="noreferrer">Source ↗</a>';
  } else if (vehicleSnapshotStale && hasPositions) {
    $("#vehicle-state").textContent = "cached positions";
    $("#vehicle-updated").textContent = `Last OTD snapshot ${relativeTime(payload.fetched_at)} · refreshing in background`;
    $("#data-notice").innerHTML = `<span class="notice-icon">ⓘ</span><span><b>Showing saved OTD positions.</b> Snapshot is ${escapeHtml(relativeTime(payload.fetched_at))} old; buses may have moved.</span><a href="https://otd.delhi.gov.in/data/realtime/" target="_blank" rel="noreferrer">Source ↗</a>`;
  } else {
    $("#vehicle-state").textContent = payload.live ? "no positions" : "not connected";
    $("#vehicle-updated").textContent = payload.message || "Official Delhi OTD feed";
    $("#data-notice").innerHTML = `<span class="notice-icon">ⓘ</span><span><b>Live vehicle positions are unavailable.</b> ${escapeHtml(payload.message || "The official Delhi OTD feed is not connected.")} Mapped stops and routes remain available.</span><a href="https://otd.delhi.gov.in/data/realtime/" target="_blank" rel="noreferrer">Feed access ↗</a>`;
  }
  if (hasPositions) {
    const routeSelect = $("#bus-route-filter");
    const selectedRoute = routeSelect.value;
    const routes = [...new Set(vehicleData.map((bus) => bus.route_id).filter(Boolean))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    routeSelect.innerHTML = '<option value="">All routes</option>' + routes.map((route) => `<option value="${escapeHtml(route)}">Route ${escapeHtml(route)}</option>`).join("");
    if (routes.includes(selectedRoute)) routeSelect.value = selectedRoute;
  }
  renderVehicleMarkers();
  loadFleetPage(fleetPage);
}

async function refreshData() {
  $("#sync-label").textContent = "Refreshing live data…";
  const transitTask = fetchJson("/transit").then(({ data }) => renderTransit(data)).catch((error) => {
    $("#sync-label").textContent = "Map source unavailable";
    $(".sync-state").classList.add("sync-error");
    $("#map-loading").textContent = `Could not load transit data: ${error.message}. Retry with “Refresh data”.`;
    $("#stops-status").textContent = "Upstream source unavailable; no sample data is shown.";
  });
  const vehiclesTask = fetchJson("/vehicles?all=1")
    .then(renderVehicles)
    .catch((error) => renderVehicles({ data: [], live: false, status: "unavailable", message: error.message }));
  await Promise.allSettled([transitTask, vehiclesTask]);
}

function renderBusDetails(bus) {
  if (!bus) return;
  const age = relativeTime(bus.timestamp);
  const speed = bus.speed_mps === null ? "Not reported" : `${(bus.speed_mps * 3.6).toFixed(1)} km/h`;
  const bearing = bus.bearing === null ? "Not reported" : `${Math.round(bus.bearing)}° ${heading(bus.bearing)}`;
  const coords = `${Number(bus.lat).toFixed(5)}, ${Number(bus.lon).toFixed(5)}`;
  const locationUrl = `https://www.openstreetmap.org/?mlat=${encodeURIComponent(bus.lat)}&mlon=${encodeURIComponent(bus.lon)}#map=17/${encodeURIComponent(bus.lat)}/${encodeURIComponent(bus.lon)}`;
  const freshness = vehicleSnapshotStale || (bus.timestamp && Date.now() / 1000 - bus.timestamp > 120) ? "stale" : "fresh";
  $("#drawer-title").textContent = bus.label || bus.id;
  $("#bus-details").innerHTML = `
    <div class="drawer-bus-summary"><span class="drawer-bus-icon" style="--bus-color:${statusColor(bus.current_status)}">▣</span><div><b>${escapeHtml(bus.label || bus.id)}</b><small>Vehicle ID ${escapeHtml(bus.id)}</small></div><span class="vehicle-status drawer-status" style="--bus-color:${statusColor(bus.current_status)}"><i></i>${escapeHtml(statusLabel(bus.current_status))}</span></div>
    <div class="freshness-card ${freshness}"><span class="freshness-dot"></span><div><b>Position ${freshness === "stale" ? "may be stale" : "reported"}</b><small>${vehicleSnapshotStale ? "Saved OTD snapshot · " : ""}${escapeHtml(age)} · official feed timestamp</small></div></div>
    <section class="detail-section"><h3>TRIP</h3><dl>
      <div><dt>Route</dt><dd>${escapeHtml(bus.route_id)}</dd></div><div><dt>Trip ID</dt><dd>${escapeHtml(bus.trip_id)}</dd></div>
      <div><dt>Next stop ID</dt><dd>${escapeHtml(bus.stop_id)}</dd></div><div><dt>Stop sequence</dt><dd>${bus.stop_sequence ?? "Not reported"}</dd></div>
      <div><dt>Transit status</dt><dd>${escapeHtml(statusLabel(bus.current_status))}</dd></div></dl></section>
    <section class="detail-section"><h3>POSITION & SPEED</h3><dl>
      <div><dt>Coordinates</dt><dd>${coords}</dd></div><div><dt>Speed</dt><dd>${speed}</dd></div><div><dt>Heading</dt><dd>${bearing}</dd></div>
      <div><dt>Occupancy</dt><dd>${escapeHtml(bus.occupancy_percentage === null ? readableEnum(bus.occupancy_status) : `${bus.occupancy_percentage}% · ${readableEnum(bus.occupancy_status)}`)}</dd></div>
    </dl></section>
    <a class="drawer-map-link" href="${locationUrl}" target="_blank" rel="noreferrer">Open this position in OpenStreetMap <span>↗</span></a>`;
}

function heading(degrees) {
  return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Math.round(degrees / 45) % 8];
}

function openBusDetails(busId) {
  const bus = busById(busId);
  if (!bus) return;
  selectedBusId = String(busId);
  lastFocusedElement = document.activeElement;
  renderBusDetails(bus);
  $("#bus-drawer").classList.add("open");
  $("#bus-drawer").setAttribute("aria-hidden", "false");
  $("#bus-drawer-scrim").hidden = false;
  document.body.classList.add("drawer-open");
  if (Number.isFinite(bus.lat) && Number.isFinite(bus.lon)) map.panTo([bus.lat, bus.lon], { animate: true });
  renderVehicleMarkers();
  $("#drawer-close").focus();
  fetchJson(`/vehicles/${encodeURIComponent(bus.id)}`).then((payload) => {
    if (selectedBusId !== String(busId)) return;
    const index = vehicleData.findIndex((item) => String(item.id) === String(busId));
    if (index >= 0) vehicleData[index] = payload.data;
    renderBusDetails(payload.data);
    renderVehicleMarkers();
  }).catch(() => {
    if (selectedBusId !== String(busId)) return;
    const freshness = $("#bus-details .freshness-card");
    if (freshness) {
      freshness.classList.add("stale");
      freshness.querySelector("b").textContent = "Could not refresh vehicle details";
      freshness.querySelector("small").textContent = "Showing the last position returned by the fleet feed.";
    }
  });
}

function closeBusDetails() {
  selectedBusId = null;
  $("#bus-drawer").classList.remove("open");
  $("#bus-drawer").setAttribute("aria-hidden", "true");
  $("#bus-drawer-scrim").hidden = true;
  document.body.classList.remove("drawer-open");
  renderVehicleMarkers();
  if (lastFocusedElement?.focus) lastFocusedElement.focus();
}

function exportCsv() {
  if (!transitData) return;
  const columns = ["id", "name", "ref", "operator", "wheelchair", "lat", "lon", "source_url"];
  const csv = [columns.join(","), ...transitData.stops.map((stop) => columns.map((column) => `"${String(stop[column] ?? "").replaceAll('"', '""')}"`).join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "delhi-openstreetmap-bus-stops.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("visible"), 3200);
}

function debounceFleetSearch() {
  window.clearTimeout(fleetSearchTimer);
  fleetSearchTimer = window.setTimeout(() => loadFleetPage(1), 220);
}

$("#refresh-button").addEventListener("click", () => refreshData());
$("#export-button").addEventListener("click", exportCsv);
$("#stop-search").addEventListener("input", renderStops);
$("#route-search").addEventListener("input", renderRoutes);
$("#bus-search").addEventListener("input", debounceFleetSearch);
$("#bus-route-filter").addEventListener("change", () => loadFleetPage(1));
$("#bus-status-filter").addEventListener("change", () => loadFleetPage(1));
$("#fleet-previous").addEventListener("click", () => loadFleetPage(fleetPage - 1));
$("#fleet-next").addEventListener("click", () => loadFleetPage(fleetPage + 1));
$("#drawer-close").addEventListener("click", closeBusDetails);
$("#bus-drawer-scrim").addEventListener("click", closeBusDetails);
document.addEventListener("keydown", (event) => {
  if (!$("#bus-drawer").classList.contains("open")) return;
  if (event.key === "Escape") { closeBusDetails(); return; }
  if (event.key === "Tab") {
    const focusable = [...$("#bus-drawer").querySelectorAll("a[href],button:not([disabled])")];
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }
});
$("#routes-toggle").addEventListener("change", () => {
  if (!transitData) return;
  if ($("#routes-toggle").checked) routeLayer.addData(transitData.route_features);
  else routeLayer.clearLayers();
});
$("#fit-map").addEventListener("click", () => {
  if (transitData?.stops.length) {
    const points = transitData.stops.filter((stop) => Number.isFinite(stop.lat) && Number.isFinite(stop.lon)).map((stop) => [stop.lat, stop.lon]);
    if (points.length) map.fitBounds(L.latLngBounds(points), { padding: [20, 20], maxZoom: 12 });
  } else map.setView(DELHI, 11);
});

refreshData();
window.setInterval(() => refreshData(false), 5 * 60 * 1000);
window.setInterval(async () => {
  try { renderVehicles(await fetchJson("/vehicles?all=1")); } catch { /* retain last successful live snapshot */ }
}, 30 * 1000);
