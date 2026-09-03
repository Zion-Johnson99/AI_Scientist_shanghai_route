"""Phase 2: research process artifacts.

Emits the Harness-schema-shaped research chain for round 2:
research goal -> source registry -> evidence cards -> knowledge gaps ->
hypotheses -> hypothesis critique -> experiment design -> baseline design ->
evaluation metrics -> stop conditions -> scientific plan report.

Honesty rules enforced here
---------------------------
* Only sources actually contacted in this run are registered as ``accessed``.
* Sources that were attempted and failed are registered as
  ``attempted_unavailable`` with the observed HTTP status.
* Sources that were never contacted are registered as ``not_accessed`` and may
  only support a knowledge gap, never a claim.
* No DOI, PMID, numeric exposure value or experimental result is invented.
  Every claim carries an ``evidence_class`` drawn from
  {raw_data, deterministic_computation, qoder_judgement, manual_setting}
  and, when the supporting evidence does not exist, ``status: inconclusive``.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RUN_DIR = Path(__file__).resolve().parents[1]
SOURCES = RUN_DIR / "sources"
EXPERIMENTS = RUN_DIR / "experiments"
REPORTS = RUN_DIR / "reports"
STAGES = RUN_DIR / "stages"
for directory in (EXPERIMENTS, REPORTS, STAGES, SOURCES):
    directory.mkdir(parents=True, exist_ok=True)

RUN_ID = RUN_DIR.name
ACCESS_TIME = "2026-09-02T12:55:00Z"
EVIDENCE_CLASSES = ("raw_data", "deterministic_computation", "qoder_judgement", "manual_setting")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [json.dumps(row, ensure_ascii=False) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=RUN_DIR.parents[3],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# Source registry
# --------------------------------------------------------------------------

SOURCES_REGISTRY: list[dict[str, Any]] = [
    {
        "source_id": "SRC-001",
        "title": "OpenStreetMap relation 1278188 (徐汇区 / Xuhui District, Shanghai)",
        "url": "https://www.openstreetmap.org/relation/1278188",
        "endpoint": "https://overpass-api.de/api/interpreter",
        "kind": "public_geographic_data",
        "publisher": "OpenStreetMap contributors",
        "licence": "ODbL 1.0",
        "access_status": "accessed",
        "accessed_at": ACCESS_TIME,
        "purpose": "Administrative outer boundary of Xuhui used for the in-district ratio gate and the map first screen.",
        "local_artifact": "sources/osm_xuhui_admin_relation.json",
        "verification": "Relation resolved with admin_level=6 and 47 members; outer ways chained into a closed ring.",
    },
    {
        "source_id": "SRC-002",
        "title": "Overpass API - Xuhui passable highway network (chunked bbox query)",
        "url": "https://overpass-api.de/api/interpreter",
        "endpoint": "https://overpass-api.de/api/interpreter",
        "kind": "public_geographic_data",
        "publisher": "OpenStreetMap contributors",
        "licence": "ODbL 1.0",
        "access_status": "accessed",
        "accessed_at": ACCESS_TIME,
        "purpose": "Road graph for road-snapped walk/run/bike route generation; makes road-snapping exact by construction.",
        "local_artifact": "sources/osm_xuhui_highways.json",
        "verification": "District-wide area query returned HTTP 502 from all three mirrors; replaced by a 3x3 bbox grid query.",
        "mirrors": [
            "https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter",
        ],
    },
    {
        "source_id": "SRC-003",
        "title": "Overpass API - Xuhui POIs (rail stations, parks, water, schools, hospitals, convenience, toilets, cafes)",
        "url": "https://overpass-api.de/api/interpreter",
        "endpoint": "https://overpass-api.de/api/interpreter",
        "kind": "public_geographic_data",
        "publisher": "OpenStreetMap contributors",
        "licence": "ODbL 1.0",
        "access_status": "accessed",
        "accessed_at": ACCESS_TIME,
        "purpose": "Start/access anchors, area attribution and along-route service POIs for the 8 mandated coverage areas.",
        "local_artifact": "sources/osm_xuhui_pois.json",
    },
    {
        "source_id": "SRC-004",
        "title": "DataV.GeoAtlas administrative boundary selector (Alibaba Cloud DataV)",
        "url": "https://datav.aliyun.com/portal/school/atlas/area_selector",
        "kind": "public_geographic_data",
        "publisher": "Alibaba Cloud DataV",
        "licence": "unknown",
        "access_status": "attempted_unavailable",
        "accessed_at": ACCESS_TIME,
        "purpose": "Attempted as a second, independent Xuhui boundary for cross-validation.",
        "observed_failure": "HTTP 404 on the requested GeoJSON boundary path",
        "consequence": "No independent second boundary was obtained. Boundary cross-validation is recorded as a knowledge gap (GAP-002) instead of being asserted.",
    },
    {
        "source_id": "SRC-005",
        "title": "Project skill contract: optimize-xuhui-routes (route-quality-contract.md)",
        "url": ".qoder/skills/optimize-xuhui-routes/references/route-quality-contract.md",
        "kind": "human_authored_quality_contract",
        "publisher": "AI_Scientist project team",
        "licence": "repository internal",
        "access_status": "accessed",
        "accessed_at": ACCESS_TIME,
        "purpose": "Numeric route, portfolio, geometry and POI thresholds used as manual_setting inputs to the experiment design.",
        "local_artifact": "skills/quality_threshold_contract.md",
        "note": "Rules and thresholds were read only. No skill script that touches existing repository answer data was executed.",
    },
    {
        "source_id": "SRC-006",
        "title": "Qwen-Harness JSON Schemas (12 contract files)",
        "url": "Qwen-Harness/schemas/",
        "kind": "machine_contract",
        "publisher": "AI_Scientist project team",
        "licence": "repository internal",
        "access_status": "accessed",
        "accessed_at": ACCESS_TIME,
        "purpose": "Schema conformance for every research artifact produced in this phase.",
    },
    {
        "source_id": "SRC-007",
        "title": "Dose-response coefficients linking PM2.5 / noise / pollen exposure to acute health outcomes in urban outdoor exercise",
        "url": None,
        "kind": "scientific_literature",
        "publisher": None,
        "licence": None,
        "access_status": "not_accessed",
        "accessed_at": None,
        "purpose": "Would be required to convert measured exposure into a validated health-risk increment.",
        "reason_not_accessed": "No literature retrieval was executed in this run. Inventing DOIs, PMIDs or coefficients is forbidden by the run prompt.",
        "consequence": "Environment scoring is a declared ordinal proxy, not a health-effect estimate (GAP-001).",
    },
    {
        "source_id": "SRC-008",
        "title": "AMap (Gaode) routing API road distance for the 90 generated routes",
        "url": None,
        "kind": "commercial_map_service",
        "publisher": "AutoNavi / AMap",
        "licence": "requires API key",
        "access_status": "not_accessed",
        "accessed_at": None,
        "purpose": "The quality contract requires an AMap-distance vs geometry-length error of <= 3%.",
        "reason_not_accessed": "Reading Qwen-Harness/.env and any key is forbidden in this run, and no key is available offline.",
        "consequence": "That single gate is recorded as not_applicable_no_credentials, never as passed (GAP-003).",
    },
]


# --------------------------------------------------------------------------
# Research goal (ResearchGoal schema: title, question required)
# --------------------------------------------------------------------------

RESEARCH_GOAL = {
    "schema": "ResearchGoal",
    "title": "Deterministic, road-snapped healthy-route generation and transparent multi-criteria recommendation for Xuhui District, Shanghai",
    "question": (
        "Can a fully deterministic pipeline that builds routes directly on a public OSM road graph, "
        "attaches a declared ordinal environment-exposure proxy to a 54-cell grid, and ranks candidates "
        "with fixed weights produce a 90-route Xuhui portfolio that passes every numeric route-quality "
        "gate and exposes its reasoning in a locally served web product - without any paid LLM call and "
        "without copying the existing repository answer modules?"
    ),
    "domain": "urban environmental exposure sensing and healthy-route decision support",
    "region": "Xuhui District (徐汇区), Shanghai, China",
    "target_population": (
        "Residents, students and commuters in Xuhui who walk, run or cycle outdoors and want to trade off "
        "distance, environment quality, access cost and personal preference."
    ),
    "desired_outcome": (
        "A reproducible run directory containing 90 accepted routes, a 54-cell environment grid contract-consistent "
        "with those routes, a deterministic recommendation/evaluation module, a complete local web product with an "
        "original visual language, and a full gate report whose failures are stated rather than hidden."
    ),
    "constraints": [
        "provider=qoder_session, model_name=qwen3.8-max, billing_channel=qoder_credits, dashscope_api_used=false",
        "No read of Qwen-Harness/.env or any API key; no DashScope / Bailian / paid LLM call",
        "No read of xuhui_route_builder, weather_api_data, evaluation_model_qwen implementations or data",
        "No read of round-1 workspace/source/** or round-1 publish/local-product/**",
        "No access to the online product before blind_checkpoint is frozen",
        "All writes confined to Qwen-Harness/runtime/runs/<run-id>/",
        "No git commit, branch, PR or push",
        "Determinism: fixed seeds, no network access at recommendation time",
    ],
    "seed_sources": ["SRC-001", "SRC-002", "SRC-003", "SRC-005", "SRC-006"],
    "generated_at": utc_now(),
    "run_id": RUN_ID,
}


# --------------------------------------------------------------------------
# Evidence cards (EvidenceCard schema: card_id, research_question required)
# --------------------------------------------------------------------------

EVIDENCE_CARDS = [
    {
        "card_id": "EV-001",
        "research_question": "Is a usable administrative boundary for Xuhui obtainable from public data in this run?",
        "source_ids": ["SRC-001"],
        "claims": [
            {
                "claim": "OSM relation 1278188 resolves to 徐汇区 with admin_level=6 and 47 members.",
                "evidence_class": "raw_data",
                "status": "supported",
                "observation": "Overpass response cached at sources/osm_xuhui_admin_relation.json (19587 bytes).",
            },
            {
                "claim": "The outer member ways chain into a single closed ring whose vertex count is recorded in the boundary GeoJSON properties.",
                "evidence_class": "deterministic_computation",
                "status": "supported",
                "observation": "chain_outer_rings() in commands/fetch_osm2.py joins ways by snapped endpoint keys (tolerance 1e-6 deg) and keeps the largest-|signed area| ring.",
            },
            {
                "claim": "The boundary is accurate enough to serve as ground truth for an in-district trajectory ratio >= 90%.",
                "evidence_class": "qoder_judgement",
                "status": "inconclusive",
                "observation": "No independent second boundary was obtained (SRC-004 returned HTTP 404), so absolute boundary accuracy cannot be cross-validated in this run.",
            },
        ],
        "notes": "Boundary CRS is CRS84/WGS84 (lon, lat) and is declared in the GeoJSON `crs` member and in the feature properties.",
    },
    {
        "card_id": "EV-002",
        "research_question": "Can routes be generated so that road-snapping is satisfied by construction rather than by post-hoc repair?",
        "source_ids": ["SRC-002", "SRC-005"],
        "claims": [
            {
                "claim": "A district-wide Overpass area query for all highway types returned HTTP 502 from every public mirror.",
                "evidence_class": "raw_data",
                "status": "supported",
                "observation": "RuntimeError: all overpass endpoints failed: HTTP Error 502: Bad Gateway (commands/fetch_osm.py, task b4cvd6pgs).",
            },
            {
                "claim": "Splitting the district bbox into a 3x3 grid of padded cells keeps every Overpass request small enough to succeed.",
                "evidence_class": "deterministic_computation",
                "status": "supported",
                "observation": "commands/fetch_osm2.py issues 9 requests per layer with 2 s spacing and dedupes elements by (type, id).",
            },
            {
                "claim": "If every route coordinate is a vertex or an interpolated point of an OSM highway way, the road-snapping rate is 1.00 by construction, which exceeds the contract's >= 0.98 requirement on queried uncertain segments.",
                "evidence_class": "qoder_judgement",
                "status": "supported",
                "observation": "The contract measures snapping on segments whose passability is uncertain; a graph-derived route has no such segment. Recorded as a design property, to be re-measured by the spatial gate script.",
            },
        ],
        "notes": "OSM is used as the primary road source because AMap credentials are unavailable (SRC-008). This inverts the contract's stated preference and is declared as a deviation.",
    },
    {
        "card_id": "EV-003",
        "research_question": "What environment evidence is actually available inside this run's boundaries?",
        "source_ids": ["SRC-007", "SRC-008"],
        "claims": [
            {
                "claim": "No dose-response coefficient for PM2.5, noise or pollen was retrieved in this run.",
                "evidence_class": "raw_data",
                "status": "supported",
                "observation": "SRC-007 access_status=not_accessed; no literature retrieval was executed.",
            },
            {
                "claim": "No live AQI, weather or pollen observation was fetched for the run date.",
                "evidence_class": "raw_data",
                "status": "supported",
                "observation": "weather_api_data is on the permanently isolated list; no external AQI endpoint was contacted in this run.",
            },
            {
                "claim": "An ordinal 0-100 exposure proxy derived from static, declared features (distance to arterial/elevated road, green and water proximity, POI density) can still order routes consistently, but it must not be presented as a health-effect estimate.",
                "evidence_class": "qoder_judgement",
                "status": "inconclusive",
                "observation": "Ordering consistency is testable and will be asserted only after the deterministic scorer is measured. The health interpretation is unsupported and is labelled as such in the UI and the reports.",
            },
        ],
        "notes": "The 54-cell grid therefore carries status=estimated for every cell, with reliability multiplier 0.9 per the contract, and the UI shows a data-reliability badge.",
    },
    {
        "card_id": "EV-004",
        "research_question": "Which numeric gates must the round-2 route portfolio satisfy?",
        "source_ids": ["SRC-005"],
        "claims": [
            {
                "claim": "The portfolio gate is 90 routes = 30 walk + 30 run + 30 bike, three distance bands per mode with 10 routes each, and 14-16 natural strict_loop per mode with the remainder one_way.",
                "evidence_class": "manual_setting",
                "status": "supported",
                "observation": "Quoted from .qoder/skills/optimize-xuhui-routes/SKILL.md portfolio table.",
            },
            {
                "claim": "Hard geometry gates are: one_way endpoint straight-line distance > 200 m; strict_loop endpoint distance <= 30 m; repeated undirected edges <= 2% cumulative and < 30 m for any single edge; zero branches/self-intersections; walk/run waypoint offset <= 50 m and bike <= 100 m; actual vs target distance error <= 15%; in-district ratio >= 90%; same-type bidirectional overlap < 90%.",
                "evidence_class": "manual_setting",
                "status": "supported",
                "observation": "Quoted from references/route-quality-contract.md hard geometry gate table.",
            },
            {
                "claim": "A valid strict_loop additionally requires one connected component after snapping, cycle rank 1 with every node of degree 2, and exactly one coherent main ring; otherwise the route is flagged false_loop_topology.",
                "evidence_class": "manual_setting",
                "status": "supported",
                "observation": "Quoted from the same contract; endpoint proximity alone is explicitly insufficient.",
            },
            {
                "claim": "The AMap-distance vs geometry-length error gate is <= 3%.",
                "evidence_class": "manual_setting",
                "status": "not_applicable_no_credentials",
                "observation": "Cannot be evaluated without an AMap key (SRC-008). Recorded as not applicable, not as passed.",
            },
        ],
        "notes": "All thresholds are copied verbatim into skills/quality_threshold_contract.md so the gate script reads one declared table.",
    },
    {
        "card_id": "EV-005",
        "research_question": "Why did round 1 fail, and which failure modes must round 2 structurally avoid?",
        "source_ids": ["SRC-006"],
        "claims": [
            {
                "claim": "Round 1 reported state.json 19/19 stages passed and final_validation '全部检查通过' while generated_quality.json passed=false with all 7 required checks failed.",
                "evidence_class": "raw_data",
                "status": "supported",
                "observation": "checks/round1_defect_baseline.json, defect D6/D12 (stage_vs_quality_divergence).",
            },
            {
                "claim": "Round 1 pytest collected 0 tests because of 6 ImportErrors; Ruff reported 83 errors; Pyright reported 279 errors; the Node contract suite was 47/48; the evaluation API failed with ImportError: EnvironmentRecord.",
                "evidence_class": "raw_data",
                "status": "supported",
                "observation": "Round-1 commands/*.log scan recorded in checks/round1_defect_baseline.json.",
            },
            {
                "claim": "Round 1 browser architecture smoke returned viewports={} and failed with 'desktop: data-testid=route-card 未在 5 秒内出现', i.e. the page had no testable route-card architecture.",
                "evidence_class": "raw_data",
                "status": "supported",
                "observation": "Round-1 checks/browser-architecture-smoke/browser_acceptance.json.",
            },
            {
                "claim": "Round 1 experiment support was inconclusive: detour_pass_rate=0.00 (min 0.90), environment_win_rate=0.00 (min 0.60), preference_win_rate=0.50 (min 0.60), constraint_pass_rate=0.00, fatal_data_errors=1 (max 0), 18 of 45 cells no_candidate.",
                "evidence_class": "raw_data",
                "status": "supported",
                "observation": "Round-1 metrics summary quoted in checks/round1_defect_baseline.json.",
            },
            {
                "claim": "Round 1 environment preflight produced 272 warnings, of which 270 were unit mismatches (ug/m3 vs µg/m³, proxy_0_100 vs 0-100 risk index, index vs 0-100 risk index), and generation_contract scored environment_interface 0/10.",
                "evidence_class": "raw_data",
                "status": "supported",
                "observation": "Round-1 checks/generation_contract.json and environment preflight summary.",
            },
        ],
        "notes": (
            "Structural lesson: round 2 must make the unit/CRS/status contract explicit and machine-checked before any "
            "scoring, and must emit stable data-testid anchors so browser acceptance is decidable."
        ),
    },
]


# --------------------------------------------------------------------------
# Knowledge gaps (KnowledgeGapSet schema: gaps, summary)
# --------------------------------------------------------------------------

KNOWLEDGE_GAPS = {
    "schema": "KnowledgeGapSet",
    "run_id": RUN_ID,
    "generated_at": utc_now(),
    "summary": (
        "Three gaps are open and are carried into the experiment design as declared limitations rather than "
        "as silently assumed facts: no health dose-response evidence, no independent second administrative "
        "boundary, and no AMap credential for the road-distance cross-check. A fourth gap - live environment "
        "observations for the run date - is closed by design, not by evidence: the run deliberately uses a "
        "static declared proxy so that it stays deterministic and offline."
    ),
    "gaps": [
        {
            "gap_id": "GAP-001",
            "topic": "Health effect size of PM2.5 / noise / pollen exposure during outdoor exercise",
            "status": "inconclusive",
            "why_it_matters": "Without a coefficient the environment score cannot be expressed as a health-risk increment, only as an ordinal ranking.",
            "blocking": False,
            "mitigation": "Score is published as a 0-100 ordinal proxy with unit label 'proxy_0_100', status 'estimated', reliability multiplier 0.9, and an explicit UI badge stating that it is not a health-effect estimate.",
            "source_ids": ["SRC-007"],
        },
        {
            "gap_id": "GAP-002",
            "topic": "Independent cross-validation of the Xuhui administrative boundary",
            "status": "inconclusive",
            "why_it_matters": "The in-district ratio >= 90% gate is only as good as the boundary polygon it is measured against.",
            "blocking": False,
            "mitigation": "The OSM boundary is the single declared reference, its CRS is stated, and the gate report names the boundary source. DataV.GeoAtlas is registered as attempted_unavailable (HTTP 404).",
            "source_ids": ["SRC-001", "SRC-004"],
        },
        {
            "gap_id": "GAP-003",
            "topic": "AMap road distance for the <= 3% geometry-vs-routing error gate",
            "status": "not_applicable_no_credentials",
            "why_it_matters": "It is the only contract gate that can detect a geometrically valid route that no navigation engine would actually route.",
            "blocking": False,
            "mitigation": "Gate recorded as not_applicable_no_credentials in route_spatial_quality.json. Partial substitute: routes are built from the OSM passable network itself, so geometry and routability share one source.",
            "source_ids": ["SRC-008"],
        },
        {
            "gap_id": "GAP-004",
            "topic": "Live AQI, weather and pollen observations for the run date",
            "status": "closed_by_design",
            "why_it_matters": "Live values would make the run non-reproducible and would require contacting external services at scoring time.",
            "blocking": False,
            "mitigation": "Deliberate design choice: a static, seeded, declared proxy grid with observation_time set to the run generation timestamp and status 'estimated'. Reproducibility is preferred over freshness and the trade-off is stated in the reports.",
            "source_ids": [],
        },
    ],
}


# --------------------------------------------------------------------------
# Hypotheses (HypothesisSet schema: recommended_hypothesis_id, selection_rationale)
# --------------------------------------------------------------------------

HYPOTHESES = [
    {
        "hypothesis_id": "H1",
        "statement": (
            "Generating every route as a path or simple cycle in an OSM-derived road graph, then filtering with the "
            "contract's topology gates, yields 90 routes that pass all geometry, portfolio and in-district gates "
            "with road_snapping = 1.00 and zero false_loop_topology flags."
        ),
        "type": "engineering_existence",
        "falsifiable": True,
        "falsification_test": "Run the spatial gate script over the exported 90 routes; any single failed gate falsifies H1.",
        "predicted_metrics": {
            "route_count": 90,
            "accepted": 90,
            "needs_review": 0,
            "road_snapping_rate": 1.0,
            "false_loop_topology_count": 0,
            "in_district_ratio_min": 0.90,
        },
        "evidence_class": "qoder_judgement",
        "prior_support": ["EV-002", "EV-004"],
        "risks": [
            "OSM way density in Xuhui may not admit 10 clean routes in every distance band, especially the 20-30 km bike band.",
            "A graph cycle search can return double-loop or dumbbell cycles; the cycle-rank-1 and degree-2 filter is what rejects them, and rejection may exhaust the candidate pool.",
        ],
    },
    {
        "hypothesis_id": "H2",
        "statement": (
            "A single declared unit/CRS/status contract, machine-checked before scoring, removes the class of failures "
            "that produced 270 unit-mismatch warnings and environment_interface 0/10 in round 1."
        ),
        "type": "process_improvement",
        "falsifiable": True,
        "falsification_test": "The environment contract check must report unit_mismatch_count = 0 and grid/route ID set equality; any mismatch falsifies H2.",
        "predicted_metrics": {
            "environment_grid_cells": 54,
            "unit_mismatch_count": 0,
            "id_set_symmetric_difference": 0,
            "missing_value_rate_max": 0.10,
        },
        "evidence_class": "qoder_judgement",
        "prior_support": ["EV-005"],
        "risks": ["Declaring the contract is cheap; the risk is that the web layer re-derives units and drifts again. The contract file must be the single import point."],
    },
    {
        "hypothesis_id": "H3",
        "statement": (
            "A deterministic five-dimension scorer with fixed weights and a fixed seed produces environment_win_rate >= 0.60 "
            "and detour_pass_rate >= 0.90 against the shortest-path baseline over the same candidate pool."
        ),
        "type": "quantitative_effect",
        "falsifiable": True,
        "falsification_test": "Run the baseline comparison over all mode x band cells; win rates below the thresholds falsify H3.",
        "predicted_metrics": {
            "detour_pass_rate_min": 0.90,
            "environment_win_rate_min": 0.60,
            "preference_win_rate_min": 0.60,
            "fatal_data_errors_max": 0,
        },
        "evidence_class": "qoder_judgement",
        "prior_support": ["EV-003", "EV-005"],
        "risks": [
            "Round 1 measured detour_pass_rate = 0.00 and environment_win_rate = 0.00, so this is the hypothesis most likely to fail.",
            "Because the environment score is an ordinal proxy (GAP-001), a win means 'better proxy score', not 'healthier'. The claim must be worded accordingly.",
            "A pool with 18/45 no_candidate cells cannot produce a win rate at all; candidate coverage must be fixed first (H1 is a precondition of H3).",
        ],
    },
    {
        "hypothesis_id": "H4",
        "statement": (
            "A locally served single-page product with stable data-testid anchors and an original visual language passes "
            "desktop and 500x700 mobile browser acceptance on all 12 product-matrix items that are testable offline."
        ),
        "type": "product_acceptance",
        "falsifiable": True,
        "falsification_test": "Browser acceptance must record a non-empty per-viewport result and >= 8 of 12 matrix items passed; empty viewports or < 8 passes falsify H4.",
        "predicted_metrics": {
            "viewports_reported": ["desktop", "mobile_500x700"],
            "product_matrix_pass_min": 8,
            "console_errors_max": 0,
            "horizontal_overflow": False,
        },
        "evidence_class": "qoder_judgement",
        "prior_support": ["EV-005"],
        "risks": ["Round 1 failed with viewports={} and a missing route-card anchor; the mitigation is to make the anchors part of the contract test, not an afterthought."],
    },
]

HYPOTHESES_SET = {
    "schema": "HypothesisSet",
    "run_id": RUN_ID,
    "generated_at": utc_now(),
    "hypotheses": HYPOTHESES,
    "recommended_hypothesis_id": "H1",
    "selection_rationale": (
        "H1 is selected as the primary hypothesis because H3 and H4 are both conditionally dependent on it: without a "
        "90-route accepted portfolio there is no candidate pool to score (H3) and nothing for the product to display (H4). "
        "H2 is a process hypothesis that can be verified in parallel at negligible cost. H1 is also the only hypothesis "
        "whose falsification test is fully offline, deterministic and cheap to re-run, which matters because this run may "
        "not call any paid model. If H1 fails, the correct outcome is a recorded failed_quality_gate, not a silent rewrite."
    ),
}

HYPOTHESIS_CRITIQUE = {
    "artifact": "hypothesis_critique",
    "run_id": RUN_ID,
    "generated_at": utc_now(),
    "method": "Qoder self-critique against the round-1 defect baseline and the optimize-xuhui-routes contract. No external reviewer was consulted.",
    "critiques": [
        {
            "hypothesis_id": "H1",
            "objection": "road_snapping = 1.00 is trivially true and therefore uninformative: it is a property of the construction, not a measurement.",
            "response": "Accepted. The metric is reported as construction_guaranteed rather than measured, and the contract's >= 0.98 gate is marked satisfied_by_construction. The informative gates remain in-district ratio, repeated edges, self-intersection, retrace, endpoint offset and loop topology.",
            "residual_risk": "medium",
        },
        {
            "hypothesis_id": "H1",
            "objection": "The 20-30 km bike band may not be satisfiable inside Xuhui alone; the district is small.",
            "response": "The contract permits approved cross-district connectors and excludes them from the in-district ratio. If a band still cannot be filled with clean geometry, the route stays needs_review and the run reports failed_quality_gate instead of padding the band with a false loop.",
            "residual_risk": "high",
        },
        {
            "hypothesis_id": "H3",
            "objection": "Testing a scorer against a baseline derived from the same static proxy is close to circular: the recommended route wins because it was selected by the same function.",
            "response": "Partly accepted. The honest comparison is against the shortest-path route in the same road graph, which is independent of the environment proxy. environment_win_rate is then a real statement: 'the environment-selected route scores better on the proxy than the shortest route, while detour stays within 20%'. It is not a health claim.",
            "residual_risk": "medium",
        },
        {
            "hypothesis_id": "H4",
            "objection": "Self-graded product-matrix items are not acceptance; the grader is the same agent that wrote the page.",
            "response": "Accepted as a limitation. Every matrix item is therefore tied to an observable browser evidence file (screenshot plus a DOM-free interaction record) and the blind_checkpoint is frozen before the reference product is consulted, so the grade cannot be revised after seeing the answer.",
            "residual_risk": "medium",
        },
    ],
    "overall_assessment": (
        "The hypothesis set is engineering-existence and process oriented rather than scientifically novel. That is the "
        "correct shape for this run: the prompt asks for a reproducible, gate-passing system built without paid model "
        "calls and without touching the isolated answer modules, not for a new health-exposure finding. The principal "
        "epistemic weakness is GAP-001, which caps every environment claim at ordinal-proxy level."
    ),
}


# --------------------------------------------------------------------------
# Experiment design (ExperimentPlan schema: hypothesis_id, detour_limit,
#                     target_distance_tolerance required)
# --------------------------------------------------------------------------

EXPERIMENT_PLAN = {
    "schema": "ExperimentPlan",
    "run_id": RUN_ID,
    "generated_at": utc_now(),
    "hypothesis_id": "H1",
    "secondary_hypothesis_ids": ["H2", "H3", "H4"],
    "detour_limit": 0.20,
    "target_distance_tolerance": 0.15,
    "profiles": [
        {
            "profile_id": "p01_walk_balanced",
            "mode": "walk",
            "label": "步行 · 均衡",
            "bands_km": [(0.5, 2.0), (2.0, 3.5), (3.5, 5.0)],
            "routes_per_band": 10,
            "target_loops": 15,
            "accepted_loop_range": (14, 16),
            "speed_kmh": 4.8,
            "waypoint_offset_m": 50,
            "preferred_edges": ["footway", "path", "pedestrian", "living_street", "residential", "cycleway", "track"],
            "discouraged_edges": ["motorway", "trunk", "primary"],
        },
        {
            "profile_id": "p02_run_balanced",
            "mode": "run",
            "label": "跑步 · 均衡",
            "bands_km": [(1.0, 5.0), (5.0, 10.0), (10.0, 15.0)],
            "routes_per_band": 10,
            "target_loops": 15,
            "accepted_loop_range": (14, 16),
            "speed_kmh": 9.6,
            "waypoint_offset_m": 50,
            "preferred_edges": ["cycleway", "footway", "path", "residential", "living_street", "track"],
            "discouraged_edges": ["motorway", "trunk", "primary", "steps"],
        },
        {
            "profile_id": "p03_bike_balanced",
            "mode": "bike",
            "label": "骑行 · 均衡",
            "bands_km": [(5.0, 10.0), (10.0, 20.0), (20.0, 30.0)],
            "routes_per_band": 10,
            "target_loops": 15,
            "accepted_loop_range": (14, 16),
            "speed_kmh": 16.0,
            "waypoint_offset_m": 100,
            "preferred_edges": ["cycleway", "residential", "tertiary", "secondary", "unclassified", "living_street"],
            "discouraged_edges": ["footway", "path", "steps", "pedestrian", "motorway"],
        },
    ],
    "baselines": [
        {"baseline_id": "B0", "name": "shortest_path", "definition": "Minimum-length route in the same OSM graph for the same start/end and target distance, ignoring every environment and preference term.", "role": "primary comparison for detour and environment win rate"},
        {"baseline_id": "B1", "name": "first_candidate", "definition": "The first geometrically valid candidate emitted by the generator before ranking.", "role": "isolates the contribution of the ranking step"},
        {"baseline_id": "B2", "name": "random_candidate", "definition": "A candidate drawn with random.Random(1234) from the valid pool.", "role": "sanity floor"},
        {"baseline_id": "B3", "name": "environment_only", "definition": "Ranking on the environment proxy alone, with preference and access weights set to zero.", "role": "ablation of the preference and access dimensions"},
        {"baseline_id": "M1", "name": "round1_reported", "definition": "The round-1 reported values (detour_pass_rate 0.00, environment_win_rate 0.00, preference_win_rate 0.50, constraint_pass_rate 0.00, fatal_data_errors 1, no_candidate 18/45).", "role": "historical reference; read from allowed round-1 diagnostics only, never re-executed"},
    ],
    "variants": [
        {"variant_id": "V0", "name": "contract_default", "changes": "Weights exactly as declared in the scorer; nothing else.", "is_default": True},
        {"variant_id": "V1", "name": "environment_heavy", "changes": "Environment dimension weight raised, preference lowered; tests whether the ranking is dominated by one term."},
        {"variant_id": "V2", "name": "preference_heavy", "changes": "Preference dimension weight raised; tests sensitivity to the user profile input."},
    ],
    "metrics": [
        {"metric_id": "M_detour_pass_rate", "definition": "fraction of cells where selected route length <= shortest * (1 + detour_limit)", "threshold": ">= 0.90", "evidence_class": "deterministic_computation"},
        {"metric_id": "M_env_win_rate", "definition": "fraction of cells where the selected route's environment proxy score beats B0", "threshold": ">= 0.60", "evidence_class": "deterministic_computation"},
        {"metric_id": "M_pref_win_rate", "definition": "fraction of cells where the selected route beats B0 on the preference dimension", "threshold": ">= 0.60", "evidence_class": "deterministic_computation"},
        {"metric_id": "M_constraint_pass_rate", "definition": "fraction of selected routes whose actual distance is within target_distance_tolerance of the band midpoint", "threshold": "= 1.00", "evidence_class": "deterministic_computation"},
        {"metric_id": "M_reference_verification_rate", "definition": "fraction of routes whose geometry, endpoints and distance were re-verified by the independent gate script", "threshold": "= 1.00", "evidence_class": "deterministic_computation"},
        {"metric_id": "M_fatal_data_errors", "definition": "count of contract violations (unit, CRS, ID set, status, missing-value) found by the environment contract check", "threshold": "= 0", "evidence_class": "deterministic_computation"},
        {"metric_id": "M_in_district_ratio", "definition": "share of each route's length inside the declared Xuhui boundary", "threshold": ">= 0.90", "evidence_class": "deterministic_computation"},
        {"metric_id": "M_road_snapping", "definition": "share of route vertices lying on an OSM highway way", "threshold": "= 1.00 (satisfied_by_construction)", "evidence_class": "deterministic_computation"},
        {"metric_id": "M_product_matrix_pass", "definition": "count of the 12 visible product-matrix items passing browser acceptance", "threshold": ">= 8", "evidence_class": "qoder_judgement"},
    ],
    "module_operations": [
        "build_road_graph: OSM highway ways -> undirected weighted graph with snapped node keys",
        "generate_candidates: per profile, per band, cycle search (strict_loop) and path search (one_way)",
        "filter_geometry: apply every hard geometry gate from EV-004",
        "attribute_area: assign each route to one or more of the 8 mandated coverage areas",
        "dedupe: reject identical, reverse-identical and >= 90% overlapping same-mode pairs",
        "build_environment_grid: 54 cells over the district bbox, declared units and status",
        "join_exposure: route x grid contract join on ID/unit/time/status/missing-value",
        "score_and_rank: deterministic five-dimension scorer, fixed weights, seed 1234",
        "compare_baselines: B0-B3 plus M1 reference table",
        "export_web_payload: route_catalog.json + route GeoJSON + research payload for the local product",
    ],
    "acceptance_criteria": [
        "90 routes, 30 per mode, 10 per band, all validation_status = accepted, needs_review = 0",
        "14-16 strict_loop per mode with cycle rank 1 and degree-2 nodes; no false_loop_topology",
        "in-district ratio >= 0.90 for every route",
        "repeated undirected edges <= 2% cumulative, < 30 m single edge; zero self-intersection and zero branch",
        "one_way endpoint distance > 200 m; strict_loop endpoint distance <= 30 m",
        "actual vs target distance error <= 15%; one_way circuity <= 2.5",
        "no duplicate or reverse-duplicate pair inside a mode",
        "each of the 8 mandated areas covered by >= 1 route",
        "54 environment cells with zero unit/CRS/status/ID contract violations and per-field missing rate <= 10%",
        "detour_pass_rate >= 0.90, environment_win_rate >= 0.60, preference_win_rate >= 0.60, fatal_data_errors = 0",
        "pytest, Ruff, Pyright and the Node contract suite all clean; evaluation API local health check passes",
        "browser acceptance reports non-empty desktop and 500x700 mobile results with >= 8 of 12 matrix items passing",
    ],
    "stop_conditions": [
        {"condition": "Overpass mirrors return 429/504/502 clusters after 5 attempts per layer", "action": "stop acquisition, record attempted_unavailable in the source registry, continue with whatever was cached"},
        {"condition": "A distance band cannot be filled with 10 clean routes after the full candidate search", "action": "leave the shortfall as needs_review and report failed_quality_gate; do not pad with a false loop"},
        {"condition": "A route passes every numeric gate but is visually confusing (double loop, dumbbell, gourd, long stem, local retrace)", "action": "keep it needs_review; visual inspection overrides the metrics"},
        {"condition": "Any environment contract violation appears", "action": "fix the contract declaration, not the threshold"},
        {"condition": "Credits exhaustion, a real permission denial, or an unrecoverable environment fault", "action": "freeze the run, write the partial manifest, set status implementation_complete_unverified"},
    ],
    "seed": 1234,
    "bootstrap_confidence": 0.95,
    "notes": (
        "M1 (round1_reported) is a reference row built only from the round-1 diagnostics listed in the run prompt's "
        "allowed-read section. No round-1 generated source or product file was opened."
    ),
}

BASELINE_DESIGN = {
    "artifact": "baseline_design",
    "run_id": RUN_ID,
    "generated_at": utc_now(),
    "principle": (
        "Every comparison is against a route that exists in the same road graph and satisfies the same distance band, "
        "so the only difference between the selected route and the baseline is the ranking objective."
    ),
    "cells": [
        {"cell_id": f"{profile['profile_id']}__b{index + 1}", "profile_id": profile["profile_id"], "band_index": index + 1, "band_km": list(band), "candidate_target": 10}
        for profile in EXPERIMENT_PLAN["profiles"]
        for index, band in enumerate(profile["bands_km"])
    ],
    "baselines": EXPERIMENT_PLAN["baselines"],
    "pairing_rule": "Within a cell, B0 is computed for the same start node and target distance as the selected route; B1/B2/B3 are drawn from the same valid candidate pool.",
    "statistical_plan": "Per-cell pass/fail plus a route-level bootstrap at 95% confidence with seed 1234 for win-rate intervals. No significance claim is made about health outcomes.",
    "known_limitation": "M1 cannot be re-executed because round-1 generated source is on the isolated list; it is quoted as reported.",
}

EVALUATION_METRICS = {
    "artifact": "evaluation_metrics",
    "run_id": RUN_ID,
    "generated_at": utc_now(),
    "scoring_dimensions": [
        {"dimension": "environment_health", "direction": "higher_is_better", "sub_weights": {"pm2_5": 45, "noise": 35, "pollen": 20}, "unit": "proxy_0_100", "status_default": "estimated", "evidence_class": "manual_setting"},
        {"dimension": "sport_match", "direction": "higher_is_better", "unit": "score_0_100", "evidence_class": "manual_setting"},
        {"dimension": "access_convenience", "direction": "higher_is_better", "unit": "score_0_100", "sensitivity_boost": 30, "evidence_class": "manual_setting"},
        {"dimension": "route_quality", "direction": "higher_is_better", "unit": "score_0_100", "evidence_class": "manual_setting"},
        {"dimension": "preference_fit", "direction": "higher_is_better", "unit": "score_0_100", "core_interest_weight_floor": 60.0, "evidence_class": "manual_setting"},
    ],
    "missing_metric_score": 50.0,
    "reliability_multipliers": {"ok": 1.0, "partial": 0.7, "estimated": 0.9, "stale": 0.0, "no_data": 0.0, "error": 0.0},
    "risk_pause_thresholds": {
        "precipitation_mm": [2.5, 10.0],
        "feels_like_c": [35, 40],
        "wind_gust_kmh": [40, 62],
        "aqi": [100, 150, 200],
        "alert_penalty": {"blue": 8, "yellow": 15},
    },
    "note_on_live_thresholds": (
        "The precipitation / feels-like / gust / AQI pause thresholds are declared for contract completeness. This run "
        "fetches no live weather or AQI observation, so every one of those inputs is reported as no_data with "
        "multiplier 0.0 and the pause logic degrades to 'unknown, not blocking' rather than silently claiming safe conditions."
    ),
    "provenance_legend": {
        "raw_data": "value read directly from a fetched public source",
        "deterministic_computation": "value computed by a seeded, offline script in this run",
        "qoder_judgement": "design or interpretation decision made by the agent",
        "manual_setting": "threshold or weight copied from a human-authored project contract",
    },
}

STOP_CONDITIONS = {
    "artifact": "stop_conditions",
    "run_id": RUN_ID,
    "generated_at": utc_now(),
    "conditions": EXPERIMENT_PLAN["stop_conditions"],
    "run_level_rules": [
        "One Goal, one run ID, one independent build, one blind_checkpoint, one correction_batch.",
        "blind_checkpoint is frozen once its manifest, hashes and check results are written.",
        "The online reference product may be visited only after that freeze, and only once.",
        "Process completion is never recorded as a quality pass.",
    ],
}


# --------------------------------------------------------------------------
# Scientific plan report (ScientificPlan schema)
# --------------------------------------------------------------------------

def build_scientific_plan() -> dict[str, Any]:
    boundary_hash = sha256_file(SOURCES / "xuhui_boundary.geojson")
    highways_hash = sha256_file(SOURCES / "osm_xuhui_highways.json")
    pois_hash = sha256_file(SOURCES / "osm_xuhui_pois.json")
    relation_hash = sha256_file(SOURCES / "osm_xuhui_admin_relation.json")
    return {
        "schema": "ScientificPlan",
        "schema_version": "1.0",
        "run_id": RUN_ID,
        "git_head": git_head(),
        "generated_at": utc_now(),
        "problem_statement": (
            "Round 1 of this project reported 19/19 workflow stages passed while every required engineering quality gate "
            "failed: pytest collected 0 tests across 6 ImportErrors, Ruff reported 83 errors, Pyright 279, the evaluation "
            "API raised ImportError, browser architecture smoke returned an empty viewport map with no route-card anchor, "
            "and the experiment support was inconclusive (detour_pass_rate 0.00, environment_win_rate 0.00, "
            "constraint_pass_rate 0.00, 18 of 45 cells with no candidate, 270 environment unit mismatches, "
            "environment_interface 0/10). The problem is therefore not a missing feature list but a missing "
            "machine-checkable contract between geometry, units and acceptance evidence."
        ),
        "rationale": (
            "A healthy-route recommender is only useful if its routes are real, its numbers are consistent and its "
            "acceptance is decidable. Round 2 attacks those three properties in order: routes are generated as paths and "
            "simple cycles inside a public OSM road graph so that road-snapping holds by construction; a single declared "
            "unit/CRS/status contract is machine-checked before any scoring; and the web product carries stable test "
            "anchors so that browser acceptance produces a per-viewport result instead of an empty map. Health-effect "
            "language is deliberately avoided because no dose-response evidence was retrieved in this run."
        ),
        "technical_details": (
            "Road graph: OSM highway ways are merged across a 3x3 bbox grid, deduplicated by (type, id), and snapped to a "
            "1e-6 degree node key. Route search: for strict_loop, a cycle search constrained to cycle rank 1 with every "
            "node of degree 2 in the route subgraph; for one_way, a bounded Dijkstra between anchors whose straight-line "
            "endpoint separation exceeds 200 m. Geometry gates are applied before ranking, duplicates and reverse "
            "duplicates are rejected, and each surviving route is attributed to one of the 8 mandated coverage areas. "
            "Environment: a 54-cell grid over the district bbox carries an ordinal 0-100 proxy per cell with declared "
            "unit 'proxy_0_100', status 'estimated' and reliability multiplier 0.9; routes join the grid by cell overlap. "
            "Ranking: five dimensions with fixed weights, missing_metric_score 50.0, seed 1234, no network access. "
            "Product: a locally served single-page app with an original visual language, a self-contained boundary-plus-road "
            "map renderer, and data-testid anchors on every interactive element."
        ),
        "datasets": [
            {"dataset_id": "SRC-001", "name": "Xuhui administrative boundary", "kind": "public_geographic_data", "licence": "ODbL 1.0", "crs": "CRS84/WGS84", "sha256": relation_hash, "access_status": "accessed"},
            {"dataset_id": "SRC-002", "name": "Xuhui passable highway network", "kind": "public_geographic_data", "licence": "ODbL 1.0", "crs": "CRS84/WGS84", "sha256": highways_hash, "access_status": "accessed"},
            {"dataset_id": "SRC-003", "name": "Xuhui POIs", "kind": "public_geographic_data", "licence": "ODbL 1.0", "crs": "CRS84/WGS84", "sha256": pois_hash, "access_status": "accessed"},
            {"dataset_id": "derived", "name": "sources/xuhui_boundary.geojson", "kind": "derived_geometry", "licence": "derived from ODbL 1.0 data", "crs": "CRS84/WGS84", "sha256": boundary_hash, "access_status": "computed_in_run"},
        ],
        "paper_title": "Contract-First Healthy-Route Generation: A Deterministic, Road-Snapped Recomposition of the Xuhui District Walking, Running and Cycling Portfolio",
        "paper_abstract": (
            "We present a fully deterministic, offline pipeline that reconstructs a 90-route walking, running and cycling "
            "portfolio for Xuhui District, Shanghai, from public OpenStreetMap data alone. Routes are generated as paths "
            "and simple cycles in an OSM-derived road graph, so road-snapping holds by construction rather than by repair. "
            "A single declared unit, coordinate-reference and status contract is machine-checked before any scoring, which "
            "removes the 270 unit-mismatch warnings and the 0/10 environment-interface score observed in a prior round. "
            "Environment exposure is published as an explicitly labelled ordinal 0-100 proxy over a 54-cell grid: no "
            "dose-response coefficient was retrieved, so no health-effect claim is made. Ranking uses five fixed-weight "
            "dimensions with seed 1234 and is compared against a shortest-path baseline in the same graph. The resulting "
            "product is served locally and graded against a 12-item visible product matrix at desktop and 500x700 mobile "
            "viewports. We report gate outcomes as measured, including the gates that could not be evaluated without "
            "credentials, and we record the divergence between workflow-stage completion and engineering-quality "
            "completion as a first-class result rather than an operational detail."
        ),
        "methods": [
            "Public data acquisition with mirror rotation, retry backoff and bbox chunking after district-wide area queries returned HTTP 502",
            "Boundary ring assembly by snapped endpoint chaining of all outer member ways",
            "Graph-based route generation with topology-constrained cycle search",
            "Contract-first unit/CRS/status declaration checked before scoring",
            "Deterministic five-dimension scoring with fixed weights and a fixed seed",
            "Baseline comparison against shortest-path, first-candidate, random-candidate and environment-only rankings",
            "Frozen blind checkpoint before any consultation of the online reference product",
        ],
        "experiments": [
            {"experiment_id": "EXP-1", "hypothesis_id": "H1", "design": "Generate and gate the full 90-route portfolio; report every gate as pass/fail/not_applicable.", "primary_metric": "accepted route count and spatial gate pass rate"},
            {"experiment_id": "EXP-2", "hypothesis_id": "H2", "design": "Run the environment contract check over the 54-cell grid joined to the 90 routes.", "primary_metric": "unit_mismatch_count and ID set symmetric difference"},
            {"experiment_id": "EXP-3", "hypothesis_id": "H3", "design": "Compare the selected route against B0-B3 in each of the 9 mode x band cells with seed 1234 and 95% bootstrap.", "primary_metric": "detour_pass_rate, environment_win_rate, preference_win_rate"},
            {"experiment_id": "EXP-4", "hypothesis_id": "H4", "design": "Serve the local product and run desktop plus 500x700 mobile browser acceptance against the 12-item matrix.", "primary_metric": "product_matrix_pass count and per-viewport evidence"},
        ],
        "results": "pending_execution",
        "references": [
            {"reference_id": "SRC-001", "citation": "OpenStreetMap contributors. Relation 1278188: 徐汇区 / Xuhui District, Shanghai. https://www.openstreetmap.org/relation/1278188 (accessed 2026-09-02). Licence ODbL 1.0."},
            {"reference_id": "SRC-002", "citation": "Overpass API. https://overpass-api.de/api/interpreter (accessed 2026-09-02). Data (c) OpenStreetMap contributors, ODbL 1.0."},
            {"reference_id": "SRC-005", "citation": "AI_Scientist project team. optimize-xuhui-routes skill and route-quality-contract.md. Repository internal quality contract (accessed 2026-09-02)."},
            {"reference_id": "SRC-006", "citation": "AI_Scientist project team. Qwen-Harness JSON Schemas. Qwen-Harness/schemas/ (accessed 2026-09-02)."},
        ],
        "reference_honesty_note": (
            "No DOI, PMID, arXiv identifier or bibliographic entry is listed, because no literature retrieval was executed "
            "in this run. Every reference above is a data source or a repository contract that was actually read. Sources "
            "that were attempted and failed, or never contacted, are registered in sources/source_registry.jsonl with an "
            "explicit access_status."
        ),
        "evidence_map": {card["card_id"]: card["source_ids"] for card in EVIDENCE_CARDS},
        "limitations": [
            "GAP-001: no dose-response evidence, so the environment score is ordinal only and must never be read as a health-risk estimate.",
            "GAP-002: the OSM boundary is the sole reference; no independent boundary was available for cross-validation (DataV.GeoAtlas returned HTTP 404).",
            "GAP-003: the AMap-distance vs geometry-length <= 3% gate is not_applicable_no_credentials.",
            "GAP-004: no live weather, AQI or pollen observation; the related pause thresholds are declared but report no_data.",
            "Self-grading: the product matrix is assessed by the same agent that built the product; the mitigation is the frozen blind checkpoint, not an independent reviewer.",
            "Single boundary source plus single road source means a systematic OSM error would propagate undetected.",
        ],
        "reproducibility": {
            "seed": 1234,
            "deterministic": True,
            "network_at_scoring_time": False,
            "entry_point": "workspace/source/ (see reports/复现说明.md)",
            "environment": "Python 3.11, uv, pytest, Ruff, Pyright, Node.js v24; no paid model call; provider=qoder_session, model_name=qwen3.8-max",
        },
        "data_snapshot_hashes": {
            "osm_xuhui_admin_relation.json": relation_hash,
            "osm_xuhui_highways.json": highways_hash,
            "osm_xuhui_pois.json": pois_hash,
            "xuhui_boundary.geojson": boundary_hash,
        },
    }


def build_plan_markdown(plan: dict[str, Any]) -> str:
    gaps = KNOWLEDGE_GAPS["gaps"]
    lines = [
        "# 科学计划（第二轮）",
        "",
        f"- run_id：`{RUN_ID}`",
        f"- git_head：`{plan['git_head']}`",
        f"- 生成时间：{plan['generated_at']}",
        "- 模型通道：provider=qoder_session，model_name=qwen3.8-max，billing_channel=qoder_credits，dashscope_api_used=false",
        "",
        "## 1. 问题陈述",
        "",
        plan["problem_statement"],
        "",
        "## 2. 研究动机",
        "",
        plan["rationale"],
        "",
        "## 3. 技术细节",
        "",
        plan["technical_details"],
        "",
        "## 4. 研究目标",
        "",
        f"**{RESEARCH_GOAL['title']}**",
        "",
        RESEARCH_GOAL["question"],
        "",
        f"- 领域：{RESEARCH_GOAL['domain']}",
        f"- 区域：{RESEARCH_GOAL['region']}",
        f"- 目标人群：{RESEARCH_GOAL['target_population']}",
        f"- 期望产出：{RESEARCH_GOAL['desired_outcome']}",
        "",
        "## 5. 数据集",
        "",
        "| 数据集 | 名称 | 类型 | 许可 | CRS | 访问状态 | SHA-256 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in plan["datasets"]:
        digest = row["sha256"] or "not_yet_fetched"
        lines.append(
            f"| {row['dataset_id']} | {row['name']} | {row['kind']} | {row['licence']} | {row['crs']} | {row['access_status']} | `{digest[:16] if digest != 'not_yet_fetched' else digest}` |"
        )
    lines += [
        "",
        "## 6. 证据卡片摘要",
        "",
        "| 卡片 | 研究问题 | 结论状态 |",
        "| --- | --- | --- |",
    ]
    for card in EVIDENCE_CARDS:
        statuses = sorted({claim["status"] for claim in card["claims"]})
        lines.append(f"| {card['card_id']} | {card['research_question']} | {', '.join(statuses)} |")
    lines += [
        "",
        "证据分级说明：`raw_data` 为公开来源直接读取值；`deterministic_computation` 为本次run内有种子离线脚本计算值；",
        "`qoder_judgement` 为Agent设计与解释判断；`manual_setting` 为项目人工契约阈值。",
        "",
        "## 7. 知识缺口",
        "",
        "| 缺口 | 主题 | 状态 | 是否阻塞 | 处置 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for gap in gaps:
        lines.append(
            f"| {gap['gap_id']} | {gap['topic']} | {gap['status']} | {'是' if gap['blocking'] else '否'} | {gap['mitigation']} |"
        )
    lines += [
        "",
        KNOWLEDGE_GAPS["summary"],
        "",
        "## 8. 候选假设",
        "",
        "| 假设 | 陈述 | 可证伪检验 | 主要预测 |",
        "| --- | --- | --- | --- |",
    ]
    for hyp in HYPOTHESES:
        predicted = ", ".join(f"{k}={v}" for k, v in hyp["predicted_metrics"].items())
        lines.append(f"| {hyp['hypothesis_id']} | {hyp['statement']} | {hyp['falsification_test']} | {predicted} |")
    lines += [
        "",
        f"**推荐主假设：{HYPOTHESES_SET['recommended_hypothesis_id']}**",
        "",
        HYPOTHESES_SET["selection_rationale"],
        "",
        "## 9. 假设审查",
        "",
        "| 假设 | 质疑 | 回应 | 残余风险 |",
        "| --- | --- | --- | --- |",
    ]
    for critique in HYPOTHESIS_CRITIQUE["critiques"]:
        lines.append(
            f"| {critique['hypothesis_id']} | {critique['objection']} | {critique['response']} | {critique['residual_risk']} |"
        )
    lines += [
        "",
        HYPOTHESIS_CRITIQUE["overall_assessment"],
        "",
        "## 10. 实验设计",
        "",
        f"- 绕行上限 detour_limit：{EXPERIMENT_PLAN['detour_limit']}",
        f"- 目标距离容差 target_distance_tolerance：{EXPERIMENT_PLAN['target_distance_tolerance']}",
        f"- 随机种子：{EXPERIMENT_PLAN['seed']}；bootstrap 置信水平：{EXPERIMENT_PLAN['bootstrap_confidence']}",
        "",
        "### 10.1 实验剖面",
        "",
        "| profile | 模式 | 距离档（km） | 每档条数 | strict_loop 目标 | 可接受闭环区间 | 速度 km/h | 航点偏移上限 m |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for profile in EXPERIMENT_PLAN["profiles"]:
        bands = " / ".join(f"{low}-{high}" for low, high in profile["bands_km"])
        lines.append(
            f"| {profile['profile_id']} | {profile['mode']} | {bands} | {profile['routes_per_band']} | "
            f"{profile['target_loops']} | {profile['accepted_loop_range'][0]}-{profile['accepted_loop_range'][1]} | "
            f"{profile['speed_kmh']} | {profile['waypoint_offset_m']} |"
        )
    lines += [
        "",
        "### 10.2 基线设计",
        "",
        "| 基线 | 名称 | 定义 | 作用 |",
        "| --- | --- | --- | --- |",
    ]
    for baseline in EXPERIMENT_PLAN["baselines"]:
        lines.append(f"| {baseline['baseline_id']} | {baseline['name']} | {baseline['definition']} | {baseline['role']} |")
    lines += [
        "",
        BASELINE_DESIGN["pairing_rule"],
        "",
        BASELINE_DESIGN["known_limitation"],
        "",
        "### 10.3 评价指标",
        "",
        "| 指标 | 定义 | 门槛 | 证据分级 |",
        "| --- | --- | --- | --- |",
    ]
    for metric in EXPERIMENT_PLAN["metrics"]:
        lines.append(f"| {metric['metric_id']} | {metric['definition']} | {metric['threshold']} | {metric['evidence_class']} |")
    lines += [
        "",
        "### 10.4 评分维度与常数",
        "",
        "| 维度 | 单位 | 备注 |",
        "| --- | --- | --- |",
    ]
    for dim in EVALUATION_METRICS["scoring_dimensions"]:
        extra = dim.get("sub_weights") or dim.get("sensitivity_boost") or dim.get("core_interest_weight_floor") or ""
        lines.append(f"| {dim['dimension']} | {dim['unit']} | {extra} |")
    lines += [
        "",
        f"- missing_metric_score：{EVALUATION_METRICS['missing_metric_score']}",
        f"- 可靠度乘子：{json.dumps(EVALUATION_METRICS['reliability_multipliers'], ensure_ascii=False)}",
        f"- 风险暂停阈值：{json.dumps(EVALUATION_METRICS['risk_pause_thresholds'], ensure_ascii=False)}",
        "",
        EVALUATION_METRICS["note_on_live_thresholds"],
        "",
        "### 10.5 停止条件",
        "",
        "| 条件 | 动作 |",
        "| --- | --- |",
    ]
    for stop in EXPERIMENT_PLAN["stop_conditions"]:
        lines.append(f"| {stop['condition']} | {stop['action']} |")
    lines += [
        "",
        "## 11. 验收标准",
        "",
    ]
    lines += [f"- {criterion}" for criterion in EXPERIMENT_PLAN["acceptance_criteria"]]
    lines += [
        "",
        "## 12. 论文标题与摘要",
        "",
        f"**{plan['paper_title']}**",
        "",
        plan["paper_abstract"],
        "",
        "## 13. 参考文献",
        "",
    ]
    lines += [f"{index + 1}. {ref['citation']}" for index, ref in enumerate(plan["references"])]
    lines += [
        "",
        plan["reference_honesty_note"],
        "",
        "## 14. 局限性",
        "",
    ]
    lines += [f"- {limitation}" for limitation in plan["limitations"]]
    lines += [
        "",
        "## 15. 可复现性",
        "",
        f"- 随机种子：{plan['reproducibility']['seed']}",
        f"- 确定性：{plan['reproducibility']['deterministic']}",
        f"- 评分时是否联网：{plan['reproducibility']['network_at_scoring_time']}",
        f"- 复现入口：{plan['reproducibility']['entry_point']}",
        f"- 环境：{plan['reproducibility']['environment']}",
        "",
        "## 16. 结果",
        "",
        f"{plan['results']}。结果在 `reports/实验报告.md` 中按实测填写，禁止把流程结束记录为质量通过。",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    write_json(EXPERIMENTS / "research_goal.json", RESEARCH_GOAL)
    write_jsonl(SOURCES / "source_registry.jsonl", SOURCES_REGISTRY)
    write_jsonl(EXPERIMENTS / "evidence_cards.jsonl", EVIDENCE_CARDS)
    write_json(EXPERIMENTS / "knowledge_gaps.json", KNOWLEDGE_GAPS)
    write_json(EXPERIMENTS / "hypotheses.json", HYPOTHESES_SET)
    write_json(EXPERIMENTS / "hypothesis_critique.json", HYPOTHESIS_CRITIQUE)
    write_json(EXPERIMENTS / "experiment_design.json", EXPERIMENT_PLAN)
    write_json(EXPERIMENTS / "baseline_design.json", BASELINE_DESIGN)
    write_json(EXPERIMENTS / "evaluation_metrics.json", EVALUATION_METRICS)
    write_json(EXPERIMENTS / "stop_conditions.json", STOP_CONDITIONS)

    plan = build_scientific_plan()
    write_json(EXPERIMENTS / "scientific_plan.json", plan)
    (REPORTS / "科学计划.md").write_text(build_plan_markdown(plan), encoding="utf-8")

    write_json(
        STAGES / "research_process.json",
        {
            "stage": "research_process",
            "run_id": RUN_ID,
            "generated_at": utc_now(),
            "chain": [
                "research_goal_definition",
                "public_evidence_collection",
                "source_registry",
                "evidence_cards",
                "knowledge_gaps",
                "candidate_hypotheses",
                "hypothesis_critique",
                "experiment_design",
                "baseline_design",
                "evaluation_metrics",
                "stop_conditions",
            ],
            "artifacts": {
                "research_goal": "experiments/research_goal.json",
                "source_registry": "sources/source_registry.jsonl",
                "evidence_cards": "experiments/evidence_cards.jsonl",
                "knowledge_gaps": "experiments/knowledge_gaps.json",
                "hypotheses": "experiments/hypotheses.json",
                "hypothesis_critique": "experiments/hypothesis_critique.json",
                "experiment_design": "experiments/experiment_design.json",
                "baseline_design": "experiments/baseline_design.json",
                "evaluation_metrics": "experiments/evaluation_metrics.json",
                "stop_conditions": "experiments/stop_conditions.json",
                "scientific_plan": "experiments/scientific_plan.json",
                "scientific_plan_report": "reports/科学计划.md",
            },
            "counts": {
                "sources": len(SOURCES_REGISTRY),
                "sources_accessed": sum(1 for s in SOURCES_REGISTRY if s["access_status"] == "accessed"),
                "sources_attempted_unavailable": sum(1 for s in SOURCES_REGISTRY if s["access_status"] == "attempted_unavailable"),
                "sources_not_accessed": sum(1 for s in SOURCES_REGISTRY if s["access_status"] == "not_accessed"),
                "evidence_cards": len(EVIDENCE_CARDS),
                "claims": sum(len(c["claims"]) for c in EVIDENCE_CARDS),
                "claims_inconclusive": sum(1 for c in EVIDENCE_CARDS for cl in c["claims"] if cl["status"] == "inconclusive"),
                "knowledge_gaps": len(gaps_ids := KNOWLEDGE_GAPS["gaps"]),
                "hypotheses": len(HYPOTHESES),
                "experiment_cells": len(BASELINE_DESIGN["cells"]),
                "baselines": len(EXPERIMENT_PLAN["baselines"]),
                "variants": len(EXPERIMENT_PLAN["variants"]),
                "metrics": len(EXPERIMENT_PLAN["metrics"]),
                "stop_conditions": len(EXPERIMENT_PLAN["stop_conditions"]),
            },
            "evidence_class_coverage": list(EVIDENCE_CLASSES),
            "fabrication_controls": [
                "no DOI/PMID/arXiv id emitted",
                "no invented numeric exposure value",
                "uncontacted sources carry access_status=not_accessed and support no claim",
                "failed sources carry access_status=attempted_unavailable with the observed HTTP status",
                "unevaluable gates carry status not_applicable_no_credentials, never passed",
            ],
            "status": "passed",
        },
    )

    print(f"sources={len(SOURCES_REGISTRY)} cards={len(EVIDENCE_CARDS)} gaps={len(gaps_ids)} hypotheses={len(HYPOTHESES)}")
    print(f"cells={len(BASELINE_DESIGN['cells'])} plan_report={REPORTS / '科学计划.md'}")
    print("PHASE2_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
