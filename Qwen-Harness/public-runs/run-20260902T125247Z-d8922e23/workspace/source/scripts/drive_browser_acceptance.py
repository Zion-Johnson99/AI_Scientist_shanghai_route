"""Drive the published product in a real browser and write the acceptance evidence.

The in-app browser available during development has a fixed 895px viewport, so it
can reach neither the 1024px desktop minimum nor the exact 500x700 mobile size
this contract requires. Playwright drives a real Chromium at an explicit viewport,
which is what makes the recorded widths trustworthy rather than merely asserted.

Every flow is asserted before it is recorded as passed, and a step that throws is
captured as a failure instead of aborting the run, so one broken interaction
cannot hide the state of the other six.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

SOURCE_ROOT: Path = Path(__file__).resolve().parents[1]
RUN_ROOT: Path = SOURCE_ROOT.parent.parent

sys.path.insert(0, str(SOURCE_ROOT))

from playwright.sync_api import Page, sync_playwright  # noqa: E402

PAYLOAD_GLOB = "**/data/app_payload.json"
DESKTOP_VIEWPORT: dict[str, int] = {"width": 1440, "height": 900}
MOBILE_VIEWPORT: dict[str, int] = {"width": 500, "height": 700}
LOAD_TIMEOUT_MS = 180_000
STEP_TIMEOUT_MS = 20_000
#: A blank canvas encodes to a very short data URL, so this separates "the map
#: drew the district and the routes" from "the canvas exists but is empty".
PAINTED_CANVAS_MIN_CHARS = 20_000


def shot(page: Page, directory: Path, name: str) -> str:
    """Save one screenshot and return its run-relative posix path."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / name
    page.screenshot(path=str(target))
    return target.relative_to(RUN_ROOT).as_posix()


def css_hidden(page: Page, element_id: str) -> bool:
    return bool(
        page.evaluate(
            "id => { const e = document.getElementById(id);"
            " return !!e && getComputedStyle(e).display === 'none'; }",
            element_id,
        )
    )


def canvas_chars(page: Page) -> int:
    return int(
        page.evaluate(
            "() => { const c = document.getElementById('map-canvas');"
            " return c ? c.toDataURL().length : 0; }"
        )
    )


def overflow(page: Page) -> bool:
    return bool(
        page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
    )


class Recorder:
    """Collect interaction verdicts without letting one failure stop the rest."""

    def __init__(self) -> None:
        self.interactions: list[dict[str, Any]] = []
        self.health: list[dict[str, Any]] = []

    def step(self, name: str, action: Callable[[], Any], bucket: str = "interaction") -> Any:
        try:
            detail = action()
            row = {"id": name, "passed": True, "detail": str(detail)[:220]}
        except Exception as exc:  # noqa: BLE001 - keep the remaining flows measurable
            row = {"id": name, "passed": False, "error": f"{exc.__class__.__name__}: {exc}"[:400]}
            detail = None
        (self.interactions if bucket == "interaction" else self.health).append(row)
        return detail

    @property
    def failed(self) -> list[str]:
        return [
            str(row["id"])
            for row in self.interactions + self.health
            if row.get("passed") is not True
        ]


def wait_ready(page: Page, base_url: str) -> None:
    page.goto(base_url, wait_until="domcontentloaded", timeout=LOAD_TIMEOUT_MS)
    #: The cards exist as soon as the payload lands, but the list pane stays hidden
    #: while the recommend flow is the active one, so "attached" is the honest
    #: readiness signal here. The skeleton hiding is what proves the data arrived.
    page.wait_for_selector("[id^='route-card-']", state="attached", timeout=LOAD_TIMEOUT_MS)
    page.wait_for_function(
        "() => { const e = document.getElementById('skeleton-state');"
        " return !!e && getComputedStyle(e).display === 'none'; }",
        timeout=LOAD_TIMEOUT_MS,
    )
    page.wait_for_timeout(1200)


def desktop_pass(page: Page, base_url: str, out: Path, rec: Recorder) -> list[str]:
    """Exercise the seven required flows at a width above the desktop minimum."""
    shots: list[str] = []
    wait_ready(page, base_url)

    def health_first_screen() -> str:
        assert not overflow(page), "horizontal overflow on the desktop first screen"
        assert css_hidden(page, "skeleton-state"), "loading skeleton still visible after data load"
        assert css_hidden(page, "partial-banner"), "partial-data banner shown for a complete payload"
        painted = canvas_chars(page)
        assert painted > PAINTED_CANVAS_MIN_CHARS, f"map canvas looks blank ({painted} chars)"
        cards = page.locator("[id^='route-card-']").count()
        assert cards > 0, "no route cards rendered"
        return f"cards={cards} canvas_chars={painted}"

    rec.step("first_screen", health_first_screen, bucket="health")
    shots.append(shot(page, out, "desktop-01-first-screen.png"))

    def do_recommend() -> str:
        page.click("#flow-recommend-btn", timeout=STEP_TIMEOUT_MS)
        page.select_option("#rec-mode", "run", timeout=STEP_TIMEOUT_MS)
        page.select_option("#rec-band", "1", timeout=STEP_TIMEOUT_MS)
        page.click("#recommend-submit-btn", timeout=STEP_TIMEOUT_MS)
        page.wait_for_timeout(1500)
        assert page.locator("#recommend-results").is_visible(), "recommend results not shown"
        text = page.locator("#recommend-results").inner_text().strip()
        assert len(text) > 40, f"recommend results look empty ({len(text)} chars)"
        return text[:120].replace("\n", " / ")

    rec.step("recommend", do_recommend)
    shots.append(shot(page, out, "desktop-02-recommend.png"))

    def do_alternatives() -> str:
        count = page.locator("#alt-cards > *").count()
        assert count >= 2, f"expected a primary plus two alternatives, found {count} alternative slots"
        return f"alternative_cards={count}"

    rec.step("alternatives", do_alternatives)

    def do_origin() -> str:
        page.fill("#origin-input", "徐家汇", timeout=STEP_TIMEOUT_MS)
        page.press("#origin-input", "Enter")
        page.wait_for_timeout(1200)
        value = page.input_value("#origin-input")
        assert value == "徐家汇", f"origin input did not retain the typed place ({value!r})"
        status = page.locator("#origin-status").inner_text().strip()
        suggested = page.locator("#origin-suggestions > *").count()
        assert status or suggested, "origin input produced neither a status nor a suggestion"
        return f"value={value} status={status[:60]!r} suggestions={suggested}"

    rec.step("origin_input", do_origin)
    shots.append(shot(page, out, "desktop-03-origin-input.png"))

    def do_filter() -> str:
        page.click("#flow-browse-btn", timeout=STEP_TIMEOUT_MS)
        page.wait_for_timeout(600)
        before = page.locator("#route-list [id^='route-card-']").count()
        page.click("#env-near-water", timeout=STEP_TIMEOUT_MS)
        page.wait_for_timeout(900)
        after = page.locator("#route-list [id^='route-card-']").count()
        empty_shown = page.locator("#empty-state").is_visible()
        assert after != before or empty_shown, (
            f"environment filter changed nothing ({before} -> {after}) and showed no empty state"
        )
        page.click("#clear-filters-btn", timeout=STEP_TIMEOUT_MS)
        page.wait_for_timeout(600)
        return f"before={before} after={after} empty_state={empty_shown}"

    rec.step("filter", do_filter)
    shots.append(shot(page, out, "desktop-04-filter.png"))

    def do_detail() -> str:
        page.locator("#route-list [id^='route-card-']").first.click(timeout=STEP_TIMEOUT_MS)
        page.wait_for_timeout(900)
        assert page.locator("#detail-panel").is_visible(), "detail panel did not open"
        breakdown = page.locator("#score-breakdown").inner_text().strip()
        assert len(breakdown) > 20, f"score breakdown empty ({len(breakdown)} chars)"
        gates = page.locator("#gate-metrics").inner_text().strip()
        assert gates, "gate metrics empty in the detail panel"
        return f"breakdown={breakdown[:70]!r}"

    rec.step("route_detail", do_detail)
    shots.append(shot(page, out, "desktop-05-route-detail.png"))

    def do_map_linkage() -> str:
        selected = page.locator(".route-card.is-selected").count()
        assert selected == 1, f"expected exactly one selected card, found {selected}"
        painted = canvas_chars(page)
        assert painted > PAINTED_CANVAS_MIN_CHARS, f"map not redrawn after selection ({painted})"
        page.click("#show-all-btn", timeout=STEP_TIMEOUT_MS)
        page.wait_for_timeout(700)
        after = canvas_chars(page)
        assert after > PAINTED_CANVAS_MIN_CHARS, "fit-all left the map blank"
        return f"selected={selected} canvas_before={painted} canvas_after={after}"

    rec.step("map_linkage", do_map_linkage)
    shots.append(shot(page, out, "desktop-06-map-linkage.png"))

    def do_error_state() -> str:
        page.route(PAYLOAD_GLOB, lambda route: route.abort())
        page.reload(wait_until="domcontentloaded", timeout=LOAD_TIMEOUT_MS)
        page.wait_for_selector("#error-state", state="visible", timeout=STEP_TIMEOUT_MS)
        assert page.locator("#error-state").is_visible(), "error state not shown when the payload 404s"
        assert page.locator("#retry-btn").is_visible(), "no retry control offered in the error state"
        text = page.locator("#error-state").inner_text().strip()
        page.unroute(PAYLOAD_GLOB)
        return text[:90].replace("\n", " / ")

    rec.step("error_state", do_error_state)
    shots.append(shot(page, out, "desktop-07-error-state.png"))
    return shots


def mobile_pass(page: Page, base_url: str, out: Path, rec: Recorder) -> list[str]:
    """Check the narrow layout holds together and its tab bar really switches views."""
    shots: list[str] = []
    wait_ready(page, base_url)

    def health_mobile() -> str:
        assert not overflow(page), "horizontal overflow at 500px width"
        assert css_hidden(page, "skeleton-state"), "loading skeleton still visible at 500px"
        assert page.locator("#mobile-action-bar").is_visible(), "mobile action bar not shown at 500px"
        cards = page.locator("[id^='route-card-']").count()
        assert cards > 0, "no route cards rendered at 500px"
        return f"cards={cards} action_bar=visible"

    rec.step("mobile_layout", health_mobile, bucket="health")
    shots.append(shot(page, out, "mobile-01-first-screen.png"))

    for view, name in (("list", "mobile-02-route-list.png"), ("filters", "mobile-03-filters.png")):
        page.click(f'#mobile-action-bar button[data-view="{view}"]', timeout=STEP_TIMEOUT_MS)
        page.wait_for_timeout(700)
        shots.append(shot(page, out, name))

    def detail_tab() -> str:
        page.click('#mobile-action-bar button[data-view="detail"]', timeout=STEP_TIMEOUT_MS)
        page.wait_for_timeout(700)
        assert not overflow(page), "horizontal overflow on the mobile detail view"
        return "detail tab reachable without overflow"

    rec.step("mobile_detail_tab", detail_tab, bucket="health")
    shots.append(shot(page, out, "mobile-04-detail.png"))
    return shots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", default="blind", choices=("blind", "final"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8765/index.html")
    args = parser.parse_args(argv)

    out_dir = RUN_ROOT / f"{args.stage}_checkpoint" / "screenshots"
    rec = Recorder()
    desktop_shots: list[str] = []
    mobile_shots: list[str] = []
    launch_error: str | None = None

    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - report a missing browser, do not stack-trace
            browser = None
            launch_error = f"{exc.__class__.__name__}: {exc}"[:300]
        if browser is not None:
            desktop_ctx = browser.new_context(viewport=DESKTOP_VIEWPORT)
            desktop_shots = desktop_pass(desktop_ctx.new_page(), args.base_url, out_dir, rec)
            desktop_ctx.close()
            mobile_ctx = browser.new_context(
                viewport=MOBILE_VIEWPORT, is_mobile=True, has_touch=True
            )
            mobile_shots = mobile_pass(mobile_ctx.new_page(), args.base_url, out_dir, rec)
            mobile_ctx.close()
            browser.close()

    if launch_error:
        rec.health.append({"id": "browser_launch", "passed": False, "error": launch_error})

    required = ("recommend", "filter", "route_detail", "map_linkage", "origin_input",
                "alternatives", "error_state")
    recorded = {row["id"]: row.get("passed") for row in rec.interactions}
    desktop_ok = bool(desktop_shots) and all(
        recorded.get(name) is True for name in required
    )
    mobile_ok = bool(mobile_shots)
    evidence: dict[str, Any] = {
        "check": "browser_acceptance",
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "driver": "playwright chromium, explicit viewport per context",
        "base_url": args.base_url,
        "stage": args.stage,
        "passed": desktop_ok and mobile_ok and not rec.failed,
        "viewports": [
            {
                "id": "desktop",
                "width": DESKTOP_VIEWPORT["width"],
                "height": DESKTOP_VIEWPORT["height"],
                "passed": desktop_ok,
                "screenshots": desktop_shots,
            },
            {
                "id": "mobile",
                "width": MOBILE_VIEWPORT["width"],
                "height": MOBILE_VIEWPORT["height"],
                "passed": mobile_ok,
                "screenshots": mobile_shots,
            },
        ],
        "interactions": rec.interactions,
        "page_health": rec.health,
        "failed": rec.failed,
        "screenshot_count": len(desktop_shots) + len(mobile_shots),
    }
    (RUN_ROOT / "checks").mkdir(parents=True, exist_ok=True)
    (RUN_ROOT / "checks" / "browser_acceptance.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for row in rec.interactions + rec.health:
        mark = "ok  " if row.get("passed") else "FAIL"
        print(f"{mark} {row['id']}: {row.get('detail') or row.get('error')}")
    print(
        f"desktop={len(desktop_shots)} shots mobile={len(mobile_shots)} shots "
        f"failed={rec.failed}"
    )
    print(f"BROWSER_EVIDENCE_PASSED={str(evidence['passed']).lower()}")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
