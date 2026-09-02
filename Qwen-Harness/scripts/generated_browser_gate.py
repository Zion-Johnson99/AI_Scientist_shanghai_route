"""对当前 run 生成的地图产品执行最小真实浏览器验收。"""

# pyright: reportMissingImports=false

from __future__ import annotations

import argparse
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _capture_reference(
    browser: Browser, reference_url: str, output_dir: Path, evidence: dict[str, Any]
) -> None:
    captures: dict[str, str] = {}
    try:
        for name, viewport in VIEWPORTS.items():
            page = browser.new_page(viewport=viewport)
            page.goto(reference_url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(1_000)
            target = output_dir / f"online-{name}.png"
            page.screenshot(path=str(target), full_page=False)
            captures[name] = str(target)
            page.close()
    except Exception as exc:  # noqa: BLE001 - 在线基准不可用不掩盖本地功能结论
        evidence["reference_error"] = f"{type(exc).__name__}: {exc}"
    evidence["reference_screenshots"] = captures


def _exercise_viewport(
    browser: Browser,
    base_url: str,
    name: str,
    viewport: dict[str, int],
    output_dir: Path,
) -> dict[str, Any]:
    page: Page = browser.new_page(viewport=viewport)
    console_errors: list[str] = []
    local_http_errors: list[str] = []
    page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
    page.on("pageerror", lambda error: console_errors.append(str(error)))
    page.on(
        "response",
        lambda response: local_http_errors.append(f"{response.status} {response.url}")
        if response.url.startswith(base_url) and response.status >= 400
        else None,
    )
    page.goto(f"{base_url}/web/", wait_until="domcontentloaded", timeout=20_000)
    route_cards = page.locator('[data-testid="route-card"]')
    try:
        route_cards.first.wait_for(state="visible", timeout=5_000)
    except PlaywrightTimeoutError as exc:
        failure = output_dir / f"local-{name}-failure.png"
        page.screenshot(path=str(failure), full_page=False)
        raise AssertionError(f"{name}: data-testid=route-card 未在 5 秒内出现") from exc

    map_element = page.locator('[data-testid="map"]')
    workbench = page.locator('[data-testid="route-workbench"]')
    _assert(map_element.is_visible(), f"{name}: 地图不可见")
    _assert(workbench.is_visible(), f"{name}: 路线工作台不可见")
    map_box = map_element.bounding_box()
    _assert(map_box is not None, f"{name}: 无法读取地图尺寸")
    minimum_width = 320 if name == "desktop" else 260
    minimum_height = 300 if name == "desktop" else 220
    _assert(map_box["width"] >= minimum_width, f"{name}: 地图宽度不足")
    _assert(map_box["height"] >= minimum_height, f"{name}: 地图高度不足")
    _assert(route_cards.count() == 90, f"{name}: 初始路线数量不是 90")

    overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    _assert(int(overflow) <= 1, f"{name}: 页面存在横向溢出 {overflow}px")

    mode_filter = page.locator('[data-testid="mode-filter"]')
    mode_filter.select_option("walk")
    page.wait_for_timeout(200)
    _assert(route_cards.count() == 30, f"{name}: walk 筛选后路线数量不是 30")
    route_cards.first.click()

    details = page.locator('[data-testid="environment-details"]')
    try:
        details.wait_for(state="visible", timeout=5_000)
    except PlaywrightTimeoutError as exc:
        failure = output_dir / f"local-{name}-failure.png"
        page.screenshot(path=str(failure), full_page=False)
        raise AssertionError(f"{name}: 环境详情点击后不可见") from exc
    detail_text = details.inner_text()
    for marker in ("PM2.5", "噪声", "花粉"):
        _assert(marker in detail_text, f"{name}: 环境详情缺少 {marker}")
    selected_route_id = map_element.get_attribute("data-selected-route-id")
    _assert(bool(selected_route_id), f"{name}: 路线选择未同步到地图")
    _assert(not local_http_errors, f"{name}: 本地资源请求失败: {local_http_errors}")
    _assert(not console_errors, f"{name}: 控制台错误: {console_errors}")

    screenshot = output_dir / f"local-{name}.png"
    page.screenshot(path=str(screenshot), full_page=False)
    page.close()
    return {
        "viewport": viewport,
        "route_count": 90,
        "walk_route_count": 30,
        "map_box": map_box,
        "selected_route_id": selected_route_id,
        "environment_markers": ["PM2.5", "噪声", "花粉"],
        "horizontal_overflow_px": overflow,
        "screenshot": str(screenshot),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reference-url", required=True)
    args = parser.parse_args()

    source_root = args.source_root.resolve()
    route_root = source_root / "xuhui_route_builder"
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, Any] = {
        "passed": False,
        "reference_url": args.reference_url,
        "viewports": {},
    }
    evidence_path = output_dir / "browser_acceptance.json"
    handler = partial(_QuietHandler, directory=str(route_root))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            _capture_reference(browser, args.reference_url, output_dir, evidence)
            for name, viewport in VIEWPORTS.items():
                evidence["viewports"][name] = _exercise_viewport(
                    browser, base_url, name, viewport, output_dir
                )
            browser.close()
    except Exception as exc:
        evidence["error"] = f"{type(exc).__name__}: {exc}"
        raise
    else:
        evidence["passed"] = True
        return 0
    finally:
        server.shutdown()
        server.server_close()
        evidence_path.write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    raise SystemExit(main())
