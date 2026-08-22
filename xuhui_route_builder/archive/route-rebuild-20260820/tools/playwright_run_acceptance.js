async (page) => {
  const load = async (width, height) => {
    await page.setViewportSize({ width, height });
    await page.goto("http://127.0.0.1:8123/web/");
    await page.click('[data-route-mode="run"]');
    await page.waitForFunction(() => document.querySelectorAll("#routeSelect option").length === 31);
  };
  const catalog = await (await page.request.get("http://127.0.0.1:8123/data/web/route_catalog.json")).json();
  const runs = catalog.filter((route) => route.route_mode === "run");
  if (runs.length !== 30 || runs.some((route) => route.validation_status !== "accepted")) {
    throw new Error("run catalog is not 30/30 accepted");
  }
  const expectedRoutes = (type) => runs.filter((route) =>
    (route.nearby_pois || []).some((poi) => poi.poi_type === type)
  );
  const markerText = () => [...document.querySelectorAll("#map .amap-route-marker")]
    .map((element) => element.textContent || "").join("\n");

  await load(1600, 1000);
  const toiletRoutes = expectedRoutes("toilet");
  await page.check("#preferToilet");
  await page.click("#planButton");
  if (await page.locator("#routeSelect option").count() !== toiletRoutes.length + 1) {
    throw new Error("run toilet filter count differs from real POI associations");
  }
  if (toiletRoutes.length) {
    await page.selectOption("#routeSelect", toiletRoutes[0].route_id);
    if (!(await page.locator("#map").evaluate(markerText)).includes("厕所")) {
      throw new Error("run toilet route lacks a real toilet marker");
    }
  }

  await page.click("#resetButton");
  await page.click('[data-route-mode="run"]');
  const parkRoutes = expectedRoutes("park_gate");
  await page.check("#preferPark");
  await page.click("#planButton");
  if (await page.locator("#routeSelect option").count() !== parkRoutes.length + 1) {
    throw new Error("run park filter count differs from real POI associations");
  }
  if (parkRoutes.length) {
    await page.selectOption("#routeSelect", parkRoutes[0].route_id);
    const parkText = await page.locator("#map").evaluate(markerText);
    if (!parkText.includes("公园入口") && !parkText.includes("邻近公园")) {
      throw new Error("run park route lacks a real entrance marker");
    }
  }
  await page.screenshot({ path: "output/playwright/run-desktop-final.png", fullPage: true });

  await page.click("#resetButton");
  await page.click('[data-route-mode="run"]');
  const emptyRoute = runs.find((route) => !(route.nearby_pois || []).length);
  if (emptyRoute) {
    await page.selectOption("#routeSelect", emptyRoute.route_id);
    const emptyText = await page.locator("#map").evaluate(markerText);
    if (["咖啡", "厕所", "补给", "公园入口", "邻近公园"].some((label) => emptyText.includes(label))) {
      throw new Error(`empty-POI run ${emptyRoute.route_id} displays a facility marker`);
    }
  }

  await load(500, 700);
  const narrowRoute = parkRoutes[0] || toiletRoutes[0] || runs[0];
  await page.selectOption("#routeSelect", narrowRoute.route_id);
  if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)) {
    throw new Error("500x700 run viewport has horizontal overflow");
  }
  await page.screenshot({ path: "output/playwright/run-narrow-final.png", fullPage: true });

  return {
    runAccepted: runs.length,
    toiletRoutes: toiletRoutes.length,
    parkRoutes: parkRoutes.length,
    emptyPoiRoute: emptyRoute?.route_id || null,
  };
}
