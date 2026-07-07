export function renderRoutes(catalog, onSelect) {
  const list = document.querySelector("#routeList");
  const modeFilter = document.querySelector("#modeFilter");

  function paint() {
    const selectedMode = modeFilter.value;
    const routes = catalog.filter((route) => selectedMode === "all" || route.route_mode === selectedMode);
    list.innerHTML = "";
    for (const route of routes) {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "route-item";
      item.dataset.routeId = route.route_id;
      item.innerHTML = `
        <strong>${route.route_name}</strong>
        <span class="meta">${route.region_zone} · ${route.distance_level} · ${route.duration_min} 分钟</span>
        <span class="meta">${route.tags.map((tag) => `<span class="tag">${tag}</span>`).join("")}</span>
      `;
      item.addEventListener("click", () => {
        setActive(route.route_id);
        renderDetail(route);
        onSelect(route.route_id);
      });
      list.appendChild(item);
    }
  }

  modeFilter.addEventListener("change", paint);
  paint();
  if (catalog[0]) {
    renderDetail(catalog[0]);
    onSelect(catalog[0].route_id);
    setActive(catalog[0].route_id);
  }
}

function renderDetail(route) {
  const detail = document.querySelector("#routeDetail");
  detail.innerHTML = `
    <h2>${route.route_name}</h2>
    <p>区域：${route.region_zone}</p>
    <p>距离：${route.distance_m} 米；预计 ${route.duration_min} 分钟。</p>
    <p>${route.score_note}</p>
  `;
}

function setActive(routeId) {
  document.querySelectorAll(".route-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.routeId === routeId);
  });
}
