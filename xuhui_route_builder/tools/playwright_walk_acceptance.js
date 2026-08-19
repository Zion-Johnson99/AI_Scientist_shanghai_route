async (page) => {
  const load = async (width, height) => {
    await page.setViewportSize({ width, height });
    await page.goto("http://127.0.0.1:8123/web/");
    await page.waitForFunction(() => document.querySelectorAll("#routeSelect option").length === 31);
  };
  const catalog = await (await page.request.get("http://127.0.0.1:8123/data/web/route_catalog.json")).json();
  const walks = catalog.filter((route) => route.route_mode === "walk");
  if (walks.length !== 30 || walks.some((route) => route.validation_status !== "accepted")) {
    throw new Error("walk catalog is not 30/30 accepted");
  }
  const expectedCount = (type) => walks.filter((route) =>
    (route.nearby_pois || []).some((poi) => poi.poi_type === type)
  ).length;
  const markerText = () => [...document.querySelectorAll("#map .amap-route-marker")]
    .map((element) => element.textContent || "").join("\n");

  await load(1600, 1000);
  await page.check("#preferToilet");
  await page.click("#planButton");
  if (await page.locator("#routeSelect option").count() !== expectedCount("toilet") + 1) {
    throw new Error("toilet filter count differs from real POI associations");
  }
  if (!(await page.locator("#map").evaluate(markerText)).includes("厕所")) {
    throw new Error("toilet route lacks a real toilet marker");
  }

  await page.click("#resetButton");
  await page.check("#preferPark");
  await page.click("#planButton");
  if (await page.locator("#routeSelect option").count() !== expectedCount("park_gate") + 1) {
    throw new Error("park filter count differs from real POI associations");
  }
  await page.selectOption("#routeSelect", "XH_WALK_0018");
  const nearbyText = await page.locator("#map").evaluate(markerText);
  if (!nearbyText.includes("邻近公园·约143米") || !nearbyText.includes("徐家汇公园衡山路入口")) {
    throw new Error("nearby park marker is missing its real entrance and distance");
  }
  const nearbyOverlaps = await page.evaluate(() => {
    const markers = [...document.querySelectorAll("#map .amap-route-marker")];
    const preferred = markers.find((element) => element.textContent?.includes("邻近公园"));
    if (!preferred) return true;
    const first = preferred.getBoundingClientRect();
    return markers.some((element) => {
      if (element === preferred) return false;
      const second = element.getBoundingClientRect();
      return Math.min(first.right, second.right) - Math.max(first.left, second.left) > 2
        && Math.min(first.bottom, second.bottom) - Math.max(first.top, second.top) > 2;
    });
  });
  if (nearbyOverlaps) throw new Error("nearby park marker overlaps another route marker");
  await page.screenshot({ path: "output/playwright/walk-desktop-final.png", fullPage: true });

  await page.selectOption("#routeSelect", "XH_WALK_0009");
  const directText = await page.locator("#map").evaluate(markerText);
  if (!directText.includes("公园入口") || directText.includes("邻近公园")) {
    throw new Error("direct park route relation is displayed incorrectly");
  }

  await page.click("#resetButton");
  const emptyRoute = walks.find((route) => !(route.nearby_pois || []).length);
  if (!emptyRoute) throw new Error("no empty-POI walk route available for verification");
  await page.selectOption("#routeSelect", emptyRoute.route_id);
  const emptyText = await page.locator("#map").evaluate(markerText);
  if (["咖啡", "厕所", "补给", "公园入口", "邻近公园"].some((label) => emptyText.includes(label))) {
    throw new Error(`empty-POI route ${emptyRoute.route_id} displays a facility marker`);
  }

  await load(500, 700);
  await page.check("#preferPark");
  await page.click("#planButton");
  await page.selectOption("#routeSelect", "XH_WALK_0018");
  if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1)) {
    throw new Error("500x700 viewport has horizontal overflow");
  }
  if (!(await page.locator("#map").evaluate(markerText)).includes("邻近公园·约143米")) {
    throw new Error("nearby park marker is unreadable at 500x700");
  }
  const narrowOverlaps = await page.evaluate(() => {
    const markers = [...document.querySelectorAll("#map .amap-route-marker")];
    const preferred = markers.find((element) => element.textContent?.includes("邻近公园"));
    if (!preferred) return true;
    const first = preferred.getBoundingClientRect();
    return markers.some((element) => {
      if (element === preferred) return false;
      const second = element.getBoundingClientRect();
      return Math.min(first.right, second.right) - Math.max(first.left, second.left) > 2
        && Math.min(first.bottom, second.bottom) - Math.max(first.top, second.top) > 2;
    });
  });
  if (narrowOverlaps) throw new Error("nearby park marker overlaps at 500x700");
  await page.screenshot({ path: "output/playwright/walk-narrow-final.png", fullPage: true });

  return {
    walkAccepted: walks.length,
    toiletRoutes: expectedCount("toilet"),
    parkRoutes: expectedCount("park_gate"),
    emptyPoiRoute: emptyRoute.route_id,
  };
}
