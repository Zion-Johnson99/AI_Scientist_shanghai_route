---
name: optimize-xuhui-routes
description: Audit, redesign, generate, and visually verify the 90 Xuhui walking, running, and cycling routes in xuhui_route_builder. Use for false or formal closures, dumbbell and multi-lobe loops, distorted route shapes, detours, retraced edges, forks, dead-end POI excursions, incorrect start or end semantics, missing direction arrows, inaccurate waypoints, unverified amenities, excessive API work, or for producing smooth one-way routes and clean single-cycle loops from real public roads and paths.
---

# Optimize Xuhui Routes

## Goal

Produce a fixed portfolio of 90 accurate, useful, visually clear routes: 30 walking, 30 running, and 30 cycling. Accept only a smooth `one_way` route or a clean single-cycle `strict_loop`. Keep route geometry, road evidence, preference POIs, portfolio balance, and frontend display as separate checks.

## Full-portfolio contract

For a 90-route release, apply all of these gates:

| Mode | Short, 10 routes | Medium, 10 routes | Long, 10 routes |
| --- | --- | --- | --- |
| `walk` | 0.5–2 km | 2–3.5 km | 3.5–5 km |
| `run` | 1–5 km | 5–10 km | 10–15 km |
| `bike` | 5–10 km | 10–20 km | 20–30 km |

- Keep 30 routes per mode and 10 routes in every distance band. A boundary value belongs to the band that starts at that value; the last band includes its upper boundary.
- Target 15 `strict_loop` and 15 `one_way` routes per mode. Final release allows 14–16 `strict_loop` routes per mode when real roads do not support the exact target.
- Never convert a false closure into a quota-compliant loop. Replace its backbone, transfer the loop slot to a more suitable route, or use a useful `one_way` route.
- Search `coffee`, `park_gate`, `toilet`, and `convenience` for every route. Associate at least two verified types with every route and prefer three or four where the real corridor supports them.
- Cover all major route areas across the portfolio: Xuhui West Bund, Longhua, Xujiahui, Hengfu Historic Area, Shanghai Botanical Garden, Kangjian Park, Caohejing, and Huajing. Metadata coverage is a screening signal; the full-route map view confirms actual spatial coverage.

Run the portfolio gate after each mode handoff and before final web export:

```powershell
python .agents/skills/optimize-xuhui-routes/scripts/route_portfolio_gate.py `
  xuhui_route_builder/data/interim/pilot_candidates.json `
  --web-catalog xuhui_route_builder/data/web/route_catalog.json `
  --report xuhui_route_builder/data/processed/route_portfolio_gate.json
```

The report includes route and mode counts, distance-band counts, shape balance, checked loop geometries, two/three/four-type preference coverage, popular-area coverage, and web eligibility totals.

During repair, the gate accepts `needs_review` as a viewable intermediate state. For the final release, rerun the same command with `--require-all-accepted`; final acceptance requires 90 `accepted` routes and zero `needs_review` routes.

## Use the quick path by default

For one requested route:

1. Read only that route from `route_seeds.json` and `pilot_candidates.json`.
2. Decide its shape and continuous movement backbone.
3. Run the local quality gate before any network request.
4. If it fails, revise the seed nodes or target distance locally.
5. Generate the changed route once with a cached Amap response, then rerun the local gate.
6. Inspect one full-route map view. Add one street-scale view only around a suspicious segment.
7. Match POIs after geometry passes.

The normal diagnosis path uses zero network calls. The normal repair path uses one cached or fresh route-generation call. Avoid full-90 processing during single-route work.

## Coordinate a full 90-route repair

Use one worker per mode after the skill and gates are frozen. Each worker owns only its mode-specific research result and candidate patch. A single integrator validates and writes shared seeds, reports, GeoJSON, and web catalogs. This prevents concurrent edits to shared files.

Process routes in corridor-aware batches of at most five. Finish geometry first, then POI evidence, then display. At every batch boundary, classify work as:

- `geometry_changed`: regenerate once and rerun local geometry gates;
- `amenity_changed`: rematch and reverify preference POIs without regenerating geometry;
- `display_changed`: rebuild the web catalog and run focused frontend checks;
- unchanged: skip all three pipelines.

Work batches propagate downstream: every geometry change also enters amenity and display batches, and every amenity change also enters the display batch. This keeps corridor POIs and frontend artifacts aligned with the latest geometry.

## Load files only when needed

| Task | Read |
| --- | --- |
| Shape diagnosis or seed repair | Target slices from `route_seeds.json` and `pilot_candidates.json` |
| Route evidence or access uncertainty | Relevant section of `0815_90条线路优化工作计划.md` and [references/evidence-and-poi-rules.md](references/evidence-and-poi-rules.md) |
| POI matching | Target corridor and relevant entries from `poi_catalog.json` |
| Arrow or marker defect | Relevant functions from `web/src/map.js` |
| Status audit | Target record from `route_validation_report.json` |

Follow the repository `AGENTS.md` already present in context. Avoid reopening unrelated large files.

## Route-shape contract

Choose exactly one shape:

- `one_way`: distinct, recognizable endpoints; one continuous direction; no local return leg.
- `strict_loop`: start and end together; the snapped route graph forms one connected simple cycle; every graph node has degree two; the route covers one coherent spatial area.

Reject a `strict_loop` that contains two joined loops, a dumbbell or gourd shape, a long entrance stem, repeated connectors, internal spurs, or a figure-eight crossing. Endpoint proximity alone establishes coordinate closure, not route validity.

When a real return corridor is absent, use a useful one-way route or reduce the target distance. Avoid adding blocks, POIs, or a second loop to reach a nominal distance.

## Design the movement backbone

1. Select one continuous public-road or public-path backbone appropriate for the mode.
2. Use navigation nodes only at entrances, junctions, bridges, and meaningful directional turns.
3. Keep 2–6 nodes for most routes and at most 8 for long cycling routes.
4. Order nodes along the travel direction.
5. Remove dead ends, courtyards, closed compounds, mode-restricted paths, and destinations requiring the same-way exit.

POIs beside the route remain services or landmarks. They do not become navigation nodes.

## Apply three bounded gates

### Gate A: local shape check

Run:

```powershell
python .agents/skills/optimize-xuhui-routes/scripts/route_quality_gate.py `
  xuhui_route_builder/data/interim/pilot_candidates.json `
  --route-id XH_WALK_0002
```

The gate rejects invalid closure, multiple cycles, graph nodes with invalid degree, retraces, self-intersections, local return loops, distant nodes, marker offsets, and distance mismatches. A failure returns to seed design without network work.

### Gate B: one route generation

Generate only a `geometry_changed` route. Reuse the node-pair cache. Run Gate A once on the result. A repeated failure triggers shape or target-distance redesign rather than another identical request.

### Gate C: conditional evidence and display

- Run Overpass only when public-road access, travel mode, or OSM attachment remains uncertain.
- Match POIs only after geometry passes; batch POI lookup by shared corridor.
- Open the frontend only for changed routes. Verify one full view, then inspect flagged areas.
- Run focused tests after each small batch. Run the full project test set once at final release.

## Verify visual usefulness

Accept a changed route only when:

- it reads as one clear path or one clear ring;
- it has no forks, rectangular detours, extra lobes, long stems, or visible retracing;
- start, end, and waypoint markers align with the travel sequence;
- walking, running, and cycling routes show direction arrows;
- a loop shows one `起终点` marker and a one-way route shows separate endpoints;
- nearby POIs do not bend the route;
- cycling uses suitable public roads or cycleways.

Automatic metrics screen defects. The single full-route view decides overall shape quality.

## POI rules

After geometry acceptance, search all four preference types: coffee shops, park gates, toilets, and convenience stores. Record a `preference_search_status` for every type, even when the corridor has no verified match. Record source, access time, status, coordinates, route distance, and related route IDs for matched POIs. Keep uncertain facilities as `needs_review`; only verified types enter `preference_hits`. Optional drinking water, sport stations, and bike services remain additional services and do not count toward the four-type gate. See [references/evidence-and-poi-rules.md](references/evidence-and-poi-rules.md).

Every route needs at least two verified preference types. Running routes over 5 km and cycling routes over 10 km also need a verified `toilet` or `convenience` hit. Report how many routes cover exactly two, exactly three, and all four types.

## Web catalog contract

- Export all 90 routes to the route catalog and GeoJSON, including `needs_review` routes.
- All catalog routes remain viewable on the map.
- Derive recommendation and formal-navigation eligibility from `validation_status == accepted`.
- A `needs_review` route stays out of recommendation results and formal navigation selectors until acceptance.
- Route cards and selectors show mode, distance band, and `strict_loop` or `one_way` shape.
- Frontend tests verify 90 displayed routes and the accepted-only recommendation/navigation filter.

## Stop conditions

- Local shape failure: stop network work and redesign the seed.
- Same defect after two distinct seed designs: stop the route, reconsider its shape or target distance, and report the blocker.
- API `429`, `504`, or repeated source failure: stop that source for the batch and retain the exact error context.
- Uncertain current access: keep `needs_review` and move to the next route.
- Unchanged route: skip generation, POI matching, screenshot capture, and focused tests.
- More than five routes in one work batch: split the batch before network or generation work.
- Missing one of the four preference search records: stop POI acceptance for that route and complete the audit record.
- Fewer than two verified preference types: keep the route outside final acceptance while retaining its geometry result.
- Web catalog count below or above 90: stop release; do not hide `needs_review` routes to make metrics look cleaner.

Process one route first. Expand to a batch of at most five routes sharing a verified backbone, entrance set, or corridor. Avoid routine hashes; use them only for geometry explicitly protected by the user.

## Select changed work

Use:

```powershell
python .agents/skills/optimize-xuhui-routes/scripts/select_changed_routes.py `
  --baseline <baseline-route-seeds.json> `
  --current xuhui_route_builder/data/seeds/route_seeds.json
```

Regenerate `geometry_changed` routes, rematch `amenity_changed` routes, rebuild frontend artifacts for `display_changed` routes, and skip unchanged routes. The command emits work batches with at most five route IDs by default. `--max-batch-size` accepts values from 1 through 5.

## Handoff

Report changed route IDs, shape decisions, local and conditional checks, verified POIs, two/three/four-type coverage, distance and shape balance, popular-area coverage, exact remaining blockers, edge cases, and focused tests. Keep visually confusing routes at `needs_review` while retaining all 90 routes in the viewable web catalog.
