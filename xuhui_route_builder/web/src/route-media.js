export const ROUTE_MEDIA = Object.freeze({});

export function routeMediaFor(routeId, mediaMap = ROUTE_MEDIA) {
  const configured = mediaMap?.[routeId];
  if (!configured) {
    return { cover: null, gallery: [] };
  }
  const cover = cleanMediaPath(configured.cover);
  const gallery = Array.isArray(configured.gallery)
    ? configured.gallery.map(cleanMediaPath).filter(Boolean).slice(0, 3)
    : [];
  return { cover, gallery };
}

function cleanMediaPath(value) {
  const path = typeof value === "string" ? value.trim() : "";
  return path || null;
}
