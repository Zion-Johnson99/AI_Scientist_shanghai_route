import manifest from "../../data/web/route_media_manifest.json?v=20260831-ui-35" with { type: "json" };

export const ROUTE_MEDIA = Object.freeze(Object.fromEntries(
  Object.entries(manifest.routes || {}).map(([routeId, route]) => {
    const slots = route?.slots || {};
    return [routeId, Object.freeze({
      cover: cleanMediaPath(slots.cover?.src),
      gallery: Object.freeze([
        cleanMediaPath(slots.context?.src),
        cleanMediaPath(slots.detail?.src),
      ]),
    })];
  }),
));

export function routeMediaFor(routeId, mediaMap = ROUTE_MEDIA) {
  const configured = mediaMap?.[routeId];
  if (!configured) {
    return { cover: null, gallery: [] };
  }
  const cover = cleanMediaPath(configured.cover);
  const gallery = Array.isArray(configured.gallery)
    ? configured.gallery.map(cleanMediaPath).slice(0, 2)
    : [];
  return { cover, gallery };
}

function cleanMediaPath(value) {
  const path = typeof value === "string" ? value.trim() : "";
  return path || null;
}
