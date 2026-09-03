// 手写地图渲染器：本地等距圆柱(equirectangular)投影，纯 canvas，无任何外部瓦片或库。
// 视图状态 = { centerLon, centerLat, scale }，scale 为“每纬度度数的像素数”。

const HIT_TOLERANCE_PX = 7; // 契约要求 >= 6px

const MODE_COLORS = {
  walk: "#2f6db3",
  run: "#c25e1a",
  bike: "#6d52c4",
};

// PM2.5 分级配色，断点与环境面板的风险标签一致（35 / 75 / 115 µg/m³）。
const PM25_STOPS = [
  { max: 35, fill: "rgba(94, 158, 106, 0.34)", ink: "#33603f" },
  { max: 75, fill: "rgba(214, 186, 92, 0.34)", ink: "#7a6320" },
  { max: 115, fill: "rgba(214, 140, 74, 0.34)", ink: "#8a4d18" },
  { max: Infinity, fill: "rgba(184, 88, 88, 0.34)", ink: "#7d2f2f" },
];

function pm25Stop(value) {
  for (const stop of PM25_STOPS) {
    if (value <= stop.max) return stop;
  }
  return PM25_STOPS[PM25_STOPS.length - 1];
}

function clamp(v, lo, hi) {
  return Math.min(hi, Math.max(lo, v));
}

export class MapView {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.onSelect = options.onSelect || null;
    this.onHover = options.onHover || null;

    this.centerLon = 121.43;
    this.centerLat = 31.18;
    this.scale = 40000; // px per degree of latitude
    this.lat0 = 31.18; // 投影参考纬度
    this.dpr = 1;

    this.boundary = null; // [[lon,lat],...]
    this.routes = []; // [{route_id, mode, coordinates:[[lon,lat],...]}]
    this.filteredIds = null; // Set 或 null(=全部)
    this.selectedId = null;
    this.hoveredId = null;
    this.originMarker = null; // {coord, label}
    this.routeEndpoints = null; // {start, end} of selected route
    this.entries = []; // [{name_zh, coord:[lon,lat]}] 运动入口
    this.envCells = []; // [{bbox, center, inside_district, values}] 54 格环境网格
    // 图层开关：边界与路线默认开，入口与网格默认关，避免首屏过密。
    this.layers = { boundary: true, routes: true, entries: false, envGrid: false };
    this.screenCache = new Map(); // route_id -> Float64Array [x0,y0,x1,y1,...]
    this.cacheValid = false;

    this._drag = null;
    this._bindEvents();
    this._bindResize();
  }

  // ---------- 投影 ----------
  project(lon, lat) {
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    const kx = Math.cos((this.lat0 * Math.PI) / 180);
    const x = w / 2 + (lon - this.centerLon) * kx * this.scale;
    const y = h / 2 - (lat - this.centerLat) * this.scale;
    return [x, y];
  }

  unproject(x, y) {
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    const kx = Math.cos((this.lat0 * Math.PI) / 180);
    const lon = this.centerLon + (x - w / 2) / (kx * this.scale);
    const lat = this.centerLat - (y - h / 2) / this.scale;
    return [lon, lat];
  }

  // ---------- 数据 ----------
  setBoundary(ring) {
    this.boundary = Array.isArray(ring) && ring.length ? ring : null;
    this.render();
  }

  setRoutes(routes) {
    this.routes = routes;
    this.screenCache.clear();
    this.render();
  }

  setFilteredIds(idSet) {
    this.filteredIds = idSet;
    this.render();
  }

  setSelected(routeId, endpoints = null) {
    this.selectedId = routeId;
    this.routeEndpoints = endpoints;
    this.render();
  }

  setHovered(routeId) {
    if (this.hoveredId === routeId) return;
    this.hoveredId = routeId;
    this.render();
  }

  setOriginMarker(coord, label) {
    this.originMarker = coord ? { coord, label: label || "出发点" } : null;
    this.render();
  }

  setEntries(entries) {
    this.entries = (Array.isArray(entries) ? entries : [])
      .filter((e) => e && Array.isArray(e.coord) && e.coord.length >= 2)
      .map((e) => ({ name_zh: e.name_zh || "", coord: [e.coord[0], e.coord[1]] }));
    this.render();
  }

  setEnvCells(cells) {
    this.envCells = (Array.isArray(cells) ? cells : []).filter(
      (c) => c && Array.isArray(c.bbox) && c.bbox.length >= 4
    );
    this.render();
  }

  setLayerVisibility(partial) {
    if (!partial) return;
    this.layers = { ...this.layers, ...partial };
    this.render();
  }

  // ---------- 视图操作 ----------
  fitBounds(bbox, padding = 40) {
    if (!bbox || bbox.length < 4) return;
    const [minLon, minLat, maxLon, maxLat] = bbox;
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    if (!w || !h) return;
    const kx = Math.cos((((minLat + maxLat) / 2) * Math.PI) / 180);
    const spanLon = Math.max(maxLon - minLon, 1e-4);
    const spanLat = Math.max(maxLat - minLat, 1e-4);
    const sx = (w - padding * 2) / (spanLon * kx);
    const sy = (h - padding * 2) / spanLat;
    this.lat0 = (minLat + maxLat) / 2;
    this.centerLon = (minLon + maxLon) / 2;
    this.centerLat = (minLat + maxLat) / 2;
    this.scale = clamp(Math.min(sx, sy), 500, 4e6);
    this.screenCache.clear();
    this.render();
  }

  fitDistrict() {
    if (this.boundary) {
      const lons = this.boundary.map((c) => c[0]);
      const lats = this.boundary.map((c) => c[1]);
      this.fitBounds([Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)]);
    }
  }

  zoomBy(factor, anchorPx = null) {
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    const ax = anchorPx ? anchorPx[0] : w / 2;
    const ay = anchorPx ? anchorPx[1] : h / 2;
    const [lonA, latA] = this.unproject(ax, ay);
    const next = clamp(this.scale * factor, 500, 4e6);
    if (next === this.scale) return;
    this.scale = next;
    // 保持锚点在缩放前后指向同一地理坐标
    const kx = Math.cos((this.lat0 * Math.PI) / 180);
    this.centerLon = lonA - (ax - w / 2) / (kx * this.scale);
    this.centerLat = latA + (ay - h / 2) / this.scale;
    this.screenCache.clear();
    this.render();
  }

  panByPx(dx, dy) {
    const kx = Math.cos((this.lat0 * Math.PI) / 180);
    this.centerLon -= dx / (kx * this.scale);
    this.centerLat += dy / this.scale;
    this.screenCache.clear();
    this.render();
  }

  // ---------- 命中检测 ----------
  hitTest(px, py) {
    let best = null;
    let bestDist = HIT_TOLERANCE_PX;
    for (const route of this.routes) {
      if (this.filteredIds && !this.filteredIds.has(route.route_id)) continue;
      const pts = this._screenPoints(route);
      for (let i = 0; i + 3 < pts.length; i += 2) {
        const d = distToSegment(px, py, pts[i], pts[i + 1], pts[i + 2], pts[i + 3]);
        if (d < bestDist) {
          bestDist = d;
          best = route.route_id;
        }
      }
    }
    return best;
  }

  _screenPoints(route) {
    let pts = this.screenCache.get(route.route_id);
    if (pts && this.cacheValid) return pts;
    const coords = route.coordinates || [];
    pts = new Float64Array(coords.length * 2);
    for (let i = 0; i < coords.length; i += 1) {
      const [x, y] = this.project(coords[i][0], coords[i][1]);
      pts[i * 2] = x;
      pts[i * 2 + 1] = y;
    }
    this.screenCache.set(route.route_id, pts);
    return pts;
  }

  _invalidateCache() {
    this.cacheValid = false;
    this.screenCache.clear();
    this.cacheValid = true;
  }

  // ---------- 事件 ----------
  _bindEvents() {
    const c = this.canvas;
    c.addEventListener("pointerdown", (ev) => {
      c.setPointerCapture(ev.pointerId);
      this._drag = { x: ev.offsetX, y: ev.offsetY, moved: false };
    });
    c.addEventListener("pointermove", (ev) => {
      if (this._drag) {
        const dx = ev.offsetX - this._drag.x;
        const dy = ev.offsetY - this._drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 2) this._drag.moved = true;
        this._drag.x = ev.offsetX;
        this._drag.y = ev.offsetY;
        if (this._drag.moved) this.panByPx(dx, dy);
        return;
      }
      const id = this.hitTest(ev.offsetX, ev.offsetY);
      c.style.cursor = id ? "pointer" : "grab";
      if (this.onHover) this.onHover(id, ev.offsetX, ev.offsetY);
      this.setHovered(id);
    });
    const endDrag = (ev) => {
      if (this._drag && !this._drag.moved) {
        const id = this.hitTest(ev.offsetX, ev.offsetY);
        if (this.onSelect) this.onSelect(id);
      }
      this._drag = null;
    };
    c.addEventListener("pointerup", endDrag);
    c.addEventListener("pointercancel", () => { this._drag = null; });
    c.addEventListener("pointerleave", () => {
      if (this.onHover) this.onHover(null, 0, 0);
      this.setHovered(null);
    });
    c.addEventListener("wheel", (ev) => {
      ev.preventDefault();
      const factor = ev.deltaY < 0 ? 1.18 : 1 / 1.18;
      this.zoomBy(factor, [ev.offsetX, ev.offsetY]);
    }, { passive: false });
    c.addEventListener("keydown", (ev) => {
      const step = 48;
      switch (ev.key) {
        case "ArrowLeft": this.panByPx(step, 0); ev.preventDefault(); break;
        case "ArrowRight": this.panByPx(-step, 0); ev.preventDefault(); break;
        case "ArrowUp": this.panByPx(0, step); ev.preventDefault(); break;
        case "ArrowDown": this.panByPx(0, -step); ev.preventDefault(); break;
        case "+": case "=": this.zoomBy(1.25); ev.preventDefault(); break;
        case "-": case "_": this.zoomBy(1 / 1.25); ev.preventDefault(); break;
        case "0": this.fitDistrict(); ev.preventDefault(); break;
        default: break;
      }
    });
  }

  _bindResize() {
    if (typeof ResizeObserver === "undefined") return;
    this._ro = new ResizeObserver(() => {
      this._resizeBackingStore();
      this._invalidateCache();
      this.render();
    });
    this._ro.observe(this.canvas.parentElement || this.canvas);
    this._resizeBackingStore();
  }

  _resizeBackingStore() {
    const dpr = window.devicePixelRatio || 1;
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    if (!w || !h) return;
    if (this.canvas.width !== Math.round(w * dpr) || this.canvas.height !== Math.round(h * dpr)) {
      this.canvas.width = Math.round(w * dpr);
      this.canvas.height = Math.round(h * dpr);
    }
    this.dpr = dpr;
  }

  // ---------- 渲染 ----------
  render() {
    const ctx = this.ctx;
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    if (!w || !h) return;
    this._resizeBackingStore();
    ctx.save();
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    // 纸面底 + 轻微纸纹网格（制图上下文层）
    ctx.fillStyle = "#edeee6";
    ctx.fillRect(0, 0, w, h);
    this._drawGraticule(ctx, w, h);

    if (this.layers.boundary && this.boundary) this._drawBoundary(ctx);
    if (this.layers.envGrid && this.envCells.length) this._drawEnvGrid(ctx);

    // 路线：先画未选中（细、低透明度），再画选中（粗、带白描边 casing）
    if (this.layers.routes) {
      for (const route of this.routes) {
        if (route.route_id === this.selectedId || route.route_id === this.hoveredId) continue;
        this._drawRoute(ctx, route, false);
      }
      if (this.hoveredId && this.hoveredId !== this.selectedId) {
        const hovered = this.routes.find((r) => r.route_id === this.hoveredId);
        if (hovered) this._drawRoute(ctx, hovered, false, true);
      }
      if (this.selectedId) {
        const selected = this.routes.find((r) => r.route_id === this.selectedId);
        if (selected) this._drawRoute(ctx, selected, true);
      }
    }

    if (this.routeEndpoints) this._drawEndpoints(ctx);
    if (this.originMarker) this._drawOrigin(ctx);
    if (this.layers.entries && this.entries.length) this._drawEntries(ctx);
    ctx.restore();
  }

  _drawGraticule(ctx, w, h) {
    // 选择让格网间距落在 50-160px 的经纬步长
    const candidates = [0.002, 0.005, 0.01, 0.02, 0.05, 0.1];
    let step = candidates[candidates.length - 1];
    for (const s of candidates) {
      if (s * this.scale >= 50) { step = s; break; }
    }
    const [lonLeft, latTop] = this.unproject(0, 0);
    const [lonRight, latBottom] = this.unproject(w, h);
    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(120, 128, 110, 0.18)";
    ctx.beginPath();
    const startLon = Math.floor(lonLeft / step) * step;
    for (let lon = startLon; lon <= lonRight; lon += step) {
      const [x] = this.project(lon, 0);
      ctx.moveTo(Math.round(x) + 0.5, 0);
      ctx.lineTo(Math.round(x) + 0.5, h);
    }
    const startLat = Math.floor(latBottom / step) * step;
    for (let lat = startLat; lat <= latTop; lat += step) {
      const [, y] = this.project(0, lat);
      ctx.moveTo(0, Math.round(y) + 0.5);
      ctx.lineTo(w, Math.round(y) + 0.5);
    }
    ctx.stroke();
  }

  _drawBoundary(ctx) {
    ctx.beginPath();
    const ring = this.boundary;
    for (let i = 0; i < ring.length; i += 1) {
      const [x, y] = this.project(ring[i][0], ring[i][1]);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fillStyle = "rgba(252, 251, 246, 0.82)";
    ctx.fill();
    ctx.lineWidth = 1.8;
    ctx.strokeStyle = "#5c6470";
    ctx.setLineDash([]);
    ctx.stroke();
  }

  _drawEnvGrid(ctx) {
    // bbox 顺序为 (west, south, east, north)，见 environment/grid.py 的 Cell 构造。
    for (const cell of this.envCells) {
      const [west, south, east, north] = cell.bbox;
      const [x0, y0] = this.project(west, north);
      const [x1, y1] = this.project(east, south);
      const cw = x1 - x0;
      const ch = y1 - y0;
      if (x1 < 0 || y1 < 0 || x0 > this.canvas.clientWidth || y0 > this.canvas.clientHeight) {
        continue;
      }
      const values = cell.values || {};
      const pm25 = values.pm25_ug_m3 ? values.pm25_ug_m3.value : null;
      ctx.lineWidth = 1;
      if (!cell.inside_district || pm25 === null || pm25 === undefined) {
        // 区外格与缺测格只留边框：涂色会让人把“没有数据”读成一个浓度值。
        ctx.strokeStyle = "rgba(120, 128, 110, 0.28)";
        ctx.setLineDash(cell.inside_district ? [3, 3] : []);
        ctx.strokeRect(x0 + 0.5, y0 + 0.5, cw - 1, ch - 1);
        ctx.setLineDash([]);
        continue;
      }
      const stop = pm25Stop(pm25);
      ctx.fillStyle = stop.fill;
      ctx.fillRect(x0, y0, cw, ch);
      ctx.strokeStyle = "rgba(253, 252, 248, 0.7)";
      ctx.strokeRect(x0 + 0.5, y0 + 0.5, cw - 1, ch - 1);
      if (cw >= 34 && ch >= 20) {
        ctx.font = "600 11px system-ui, -apple-system, 'Segoe UI', sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillStyle = stop.ink;
        ctx.fillText(String(Math.round(pm25)), x0 + cw / 2, y0 + ch / 2);
      }
    }
  }

  _drawEntries(ctx) {
    const showLabel = this.scale >= 150000;
    if (showLabel) {
      ctx.font = "500 10px system-ui, -apple-system, 'Segoe UI', sans-serif";
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
    }
    for (const entry of this.entries) {
      const [x, y] = this.project(entry.coord[0], entry.coord[1]);
      if (x < -20 || y < -20 || x > this.canvas.clientWidth + 20 || y > this.canvas.clientHeight + 20) {
        continue;
      }
      // 菱形，与出发点的圆形区分开：菱形是可去的运动入口，圆形是用户所在位置。
      ctx.beginPath();
      ctx.moveTo(x, y - 4);
      ctx.lineTo(x + 4, y);
      ctx.lineTo(x, y + 4);
      ctx.lineTo(x - 4, y);
      ctx.closePath();
      ctx.fillStyle = "#3d7a4f";
      ctx.fill();
      ctx.lineWidth = 1.4;
      ctx.strokeStyle = "#fdfcf8";
      ctx.stroke();
      if (showLabel && entry.name_zh) {
        ctx.fillStyle = "rgba(32, 38, 46, 0.82)";
        ctx.fillText(entry.name_zh, x + 7, y);
      }
    }
  }

  _drawRoute(ctx, route, isSelected, isHovered = false) {
    const pts = this._screenPoints(route);
    if (pts.length < 4) return;
    const inFilter = !this.filteredIds || this.filteredIds.has(route.route_id);
    const color = MODE_COLORS[route.mode] || "#5a626d";
    ctx.beginPath();
    ctx.moveTo(pts[0], pts[1]);
    for (let i = 2; i < pts.length; i += 2) ctx.lineTo(pts[i], pts[i + 1]);
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.setLineDash([]);
    if (isSelected) {
      ctx.strokeStyle = "rgba(253,252,248,0.95)";
      ctx.lineWidth = 7.5;
      ctx.stroke();
      ctx.strokeStyle = color;
      ctx.lineWidth = 4;
      ctx.stroke();
    } else if (isHovered) {
      ctx.strokeStyle = "rgba(253,252,248,0.8)";
      ctx.lineWidth = 5.5;
      ctx.stroke();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.8;
      ctx.globalAlpha = 0.95;
      ctx.stroke();
      ctx.globalAlpha = 1;
    } else {
      ctx.strokeStyle = color;
      ctx.globalAlpha = inFilter ? 0.55 : 0.1;
      ctx.lineWidth = inFilter ? 2 : 1;
      ctx.stroke();
      ctx.globalAlpha = 1;
    }
  }

  _drawEndpoints(ctx) {
    const eps = this.routeEndpoints;
    const draw = (coord, fill) => {
      const [x, y] = this.project(coord[0], coord[1]);
      ctx.beginPath();
      ctx.arc(x, y, 4.5, 0, Math.PI * 2);
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = "#fdfcf8";
      ctx.stroke();
    };
    if (eps.start) draw(eps.start, "#20262e");
    if (eps.end) draw(eps.end, "#0e6e8c");
  }

  _drawOrigin(ctx) {
    const [x, y] = this.project(this.originMarker.coord[0], this.originMarker.coord[1]);
    ctx.beginPath();
    ctx.arc(x, y, 7, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(14, 110, 140, 0.25)";
    ctx.fill();
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fillStyle = "#0e6e8c";
    ctx.fill();
    ctx.lineWidth = 1.5;
    ctx.strokeStyle = "#fdfcf8";
    ctx.stroke();
  }
}

function distToSegment(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const lenSq = dx * dx + dy * dy;
  let t = lenSq === 0 ? 0 : ((px - x1) * dx + (py - y1) * dy) / lenSq;
  t = clamp(t, 0, 1);
  const cx = x1 + t * dx;
  const cy = y1 + t * dy;
  return Math.hypot(px - cx, py - cy);
}

export { MODE_COLORS, HIT_TOLERANCE_PX };
