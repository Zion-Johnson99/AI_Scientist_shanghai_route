async (page) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.waitForFunction(() => window.AMap && window.XUHUI_AMAP_READY);
  await page.evaluate(async () => {
    const response = await fetch("/data/interim/pilot_candidates.json");
    const routes = (await response.json()).filter((route) => route.route_mode === "walk");
    document.body.innerHTML =
      '<div id="auditTitle" style="position:fixed;z-index:9999;top:16px;left:16px;padding:12px 18px;background:rgba(255,255,255,.94);border-radius:10px;font:700 18px sans-serif;box-shadow:0 4px 18px #0002"></div><div id="auditMap" style="position:fixed;inset:0"></div>';
    const AMapApi = await window.XUHUI_AMAP_READY;
    const auditMap = new AMapApi.Map("auditMap", { zoom: 13, viewMode: "2D" });
    window.__walkAudit = { routes, auditMap, AMapApi };
  });
  const colors = ["#e53935", "#00a884", "#7c3aed", "#f59e0b", "#1677ff"];
  await page.evaluate((palette) => {
    window.__showAuditBatch = (batchIndex) => {
      const { routes, auditMap, AMapApi } = window.__walkAudit;
      auditMap.clearMap();
      const selected = routes.slice(batchIndex * 5, batchIndex * 5 + 5);
      const overlays = [];
      selected.forEach((route, index) => {
        const path = route.polyline_gcj02.map((point) => [point.lng_gcj02, point.lat_gcj02]);
        const halo = new AMapApi.Polyline({
          path,
          strokeColor: "#ffffff",
          strokeWeight: 10,
          strokeOpacity: 0.9,
          lineJoin: "round",
        });
        const line = new AMapApi.Polyline({
          path,
          strokeColor: palette[index],
          strokeWeight: 5,
          strokeOpacity: 1,
          lineJoin: "round",
        });
        const label = new AMapApi.Text({
          text: `${route.route_id.slice(-4)} · ${(route.actual_distance_m / 1000).toFixed(2)}km`,
          position: path[Math.floor(path.length / 2)],
          anchor: "center",
          style: {
            padding: "5px 8px",
            border: `2px solid ${palette[index]}`,
            borderRadius: "7px",
            background: "#fff",
            fontWeight: "700",
            color: "#172033",
          },
        });
        auditMap.add([halo, line, label]);
        overlays.push(halo, line, label);
      });
      auditMap.setFitView(overlays, false, [90, 90, 90, 90]);
      document.getElementById("auditTitle").textContent =
        `步行路线视觉复核 · 第 ${batchIndex + 1}/6 批 · ${selected.map((route) => route.route_id.slice(-4)).join(" / ")}`;
    };
  }, colors);
  for (let batch = 0; batch < 6; batch += 1) {
    await page.evaluate((index) => window.__showAuditBatch(index), batch);
    await page.waitForTimeout(1800);
    await page.screenshot({
      path: `output/playwright/walk-audit-batch-${batch + 1}.png`,
      fullPage: true,
    });
  }
  await page.evaluate((palette) => {
    window.__showAuditRoute = (routeIndex) => {
      const { routes, auditMap, AMapApi } = window.__walkAudit;
      auditMap.clearMap();
      const route = routes[routeIndex];
      const path = route.polyline_gcj02.map((point) => [point.lng_gcj02, point.lat_gcj02]);
      const halo = new AMapApi.Polyline({
        path,
        strokeColor: "#ffffff",
        strokeWeight: 12,
        strokeOpacity: 0.95,
        lineJoin: "round",
      });
      const line = new AMapApi.Polyline({
        path,
        strokeColor: palette[routeIndex % palette.length],
        strokeWeight: 6,
        strokeOpacity: 1,
        lineJoin: "round",
      });
      auditMap.add([halo, line]);
      auditMap.setFitView([halo, line], false, [130, 130, 130, 130]);
      document.getElementById("auditTitle").textContent =
        `步行路线视觉复核 · ${route.route_id} · ${(route.actual_distance_m / 1000).toFixed(2)} km · ${route.route_shape}`;
    };
  }, colors);
  for (let routeIndex = 0; routeIndex < 30; routeIndex += 1) {
    await page.evaluate((index) => window.__showAuditRoute(index), routeIndex);
    await page.waitForTimeout(650);
    await page.screenshot({
      path: `output/playwright/walk-audit-${String(routeIndex + 1).padStart(4, "0")}.png`,
      fullPage: true,
    });
  }
}
