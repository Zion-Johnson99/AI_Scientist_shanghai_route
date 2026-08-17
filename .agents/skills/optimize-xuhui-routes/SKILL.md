---
name: optimize-xuhui-routes
description: Audit, redesign, generate, and visually verify the 90 Xuhui walking, running, and cycling routes in xuhui_route_builder. Use for false or formal closures, dumbbell and multi-lobe loops, distorted route shapes, detours, retraced edges, forks, dead-end POI excursions, incorrect start or end semantics, missing direction arrows, inaccurate waypoints, unverified amenities, excessive API work, or for producing smooth one-way routes and clean single-cycle loops from real public roads and paths.
---

# Optimize Xuhui Routes

## Goal

Produce routes that are accurate, useful, visually clear, and easy to follow. Accept only a smooth `one_way` route or a clean single-cycle `strict_loop`. Keep route geometry, road evidence, service POIs, and frontend display as separate checks.

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

After geometry acceptance, match coffee shops, toilets, convenience stores, drinking water, sport stations, and bike services within the corridor. Record source, access time, status, coordinates, route distance, and related route IDs. Keep uncertain facilities as `needs_review`. See [references/evidence-and-poi-rules.md](references/evidence-and-poi-rules.md).

## Stop conditions

- Local shape failure: stop network work and redesign the seed.
- Same defect after two distinct seed designs: stop the route, reconsider its shape or target distance, and report the blocker.
- API `429`, `504`, or repeated source failure: stop that source for the batch and retain the exact error context.
- Uncertain current access: keep `needs_review` and move to the next route.
- Unchanged route: skip generation, POI matching, screenshot capture, and focused tests.

Process one route first. Expand to a batch of at most five routes sharing a verified backbone, entrance set, or corridor. Avoid routine hashes; use them only for geometry explicitly protected by the user.

## Select changed work

Use:

```powershell
python .agents/skills/optimize-xuhui-routes/scripts/select_changed_routes.py `
  --baseline <baseline-route-seeds.json> `
  --current xuhui_route_builder/data/seeds/route_seeds.json
```

Regenerate `geometry_changed` routes, rematch `amenity_changed` routes, and skip unchanged routes.

## Handoff

Report changed route IDs, shape decisions, local and conditional checks, verified POIs, exact remaining blockers, edge cases, and focused tests. Keep any visually confusing route outside the accepted catalog.
