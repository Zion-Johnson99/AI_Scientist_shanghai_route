export function createMap(targetId) {
  const map = L.map(targetId, {
    center: [31.1763, 121.4361],
    zoom: 13,
    zoomControl: true,
  });

  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19,
  }).addTo(map);

  return map;
}

export function drawBoundary(map, boundary) {
  const layer = L.geoJSON(boundary, {
    style: {
      color: "#256f74",
      weight: 2,
      fillColor: "#d9f0ef",
      fillOpacity: 0.16,
    },
  }).addTo(map);
  map.fitBounds(layer.getBounds(), { padding: [24, 24] });
  return layer;
}

export function drawEntries(map, entries) {
  return L.geoJSON(entries, {
    pointToLayer: (_feature, latlng) =>
      L.circleMarker(latlng, {
        radius: 6,
        color: "#334e68",
        weight: 2,
        fillColor: "#f5b700",
        fillOpacity: 0.9,
      }),
    onEachFeature: (feature, layer) => {
      const props = feature.properties;
      layer.bindPopup(`<strong>${props.entry_name}</strong><br>${props.region_zone}<br>${props.entry_type}`);
    },
  }).addTo(map);
}

export function drawRoutes(map, routes) {
  const routeLayers = new Map();
  L.geoJSON(routes, {
    style: (feature) => routeStyle(feature.properties.route_mode, false),
    onEachFeature: (feature, layer) => {
      const routeId = feature.properties.route_id;
      routeLayers.set(routeId, layer);
      layer.bindPopup(`<strong>${feature.properties.route_name}</strong><br>${feature.properties.region_zone}`);
    },
  }).addTo(map);
  return routeLayers;
}

export function highlightRoute(routeLayers, selectedId) {
  for (const [routeId, layer] of routeLayers.entries()) {
    const mode = layer.feature.properties.route_mode;
    layer.setStyle(routeStyle(mode, routeId === selectedId));
    if (routeId === selectedId) {
      layer.bringToFront();
    }
  }
}

function routeStyle(mode, active) {
  const color = mode === "run" ? "#d64545" : mode === "bike" ? "#2f80ed" : "#2f855a";
  return {
    color,
    weight: active ? 6 : 4,
    opacity: active ? 0.95 : 0.72,
  };
}
