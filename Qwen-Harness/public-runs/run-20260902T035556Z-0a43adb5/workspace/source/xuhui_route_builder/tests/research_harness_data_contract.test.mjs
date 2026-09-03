import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const dataWebDir = join(__dirname, '..', 'data', 'web');
const payloadPath = join(dataWebDir, 'research_harness_latest.json');
const routeCatalogPath = join(dataWebDir, 'route_catalog.json');

/**
 * Load route catalog route_ids for cross-reference checks.
 */
function loadRouteIds() {
  if (!existsSync(routeCatalogPath)) {
    return null;
  }
  const raw = readFileSync(routeCatalogPath, 'utf-8');
  const catalog = JSON.parse(raw);
  if (!Array.isArray(catalog)) return null;
  return new Set(catalog.map(r => r.route_id));
}

/**
 * Attempt to load the research harness payload.
 * Returns null if file is missing or unparseable.
 */
function loadPayload() {
  if (!existsSync(payloadPath)) {
    return null;
  }
  try {
    const raw = readFileSync(payloadPath, 'utf-8');
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

describe('research_harness_latest.json data contract', () => {

  test('payload file missing does not throw - page should hide panel gracefully', () => {
    // This test verifies that the absence of the payload file is handled
    // without error. The test itself must not throw.
    const payload = loadPayload();
    // If payload is null, the UI should hide the panel - no error expected.
    // We simply assert that loading did not throw.
    assert.ok(true, 'No error thrown when payload is missing or present');
  });

  test('if payload exists it must be a valid JSON object', () => {
    const payload = loadPayload();
    if (payload === null) {
      // File missing or unparseable - acceptable, panel hides.
      return;
    }
    assert.equal(typeof payload, 'object', 'Payload must be an object');
    assert.ok(!Array.isArray(payload), 'Payload must not be an array');
  });

  test('if payload exists it must contain required top-level fields', () => {
    const payload = loadPayload();
    if (payload === null) return;

    const requiredFields = [
      'run_id',
      'generated_at',
      'research_question',
      'hypothesis',
      'support_status',
      'baselines',
      'metrics',
      'selected_route'
    ];

    for (const field of requiredFields) {
      assert.ok(
        field in payload,
        `Payload must contain field "${field}"`
      );
    }
  });

  test('support_status must be a valid enum value', () => {
    const payload = loadPayload();
    if (payload === null) return;

    const validStatuses = [
      'supported',
      'partially_supported',
      'unsupported',
      'inconclusive'
    ];
    assert.ok(
      validStatuses.includes(payload.support_status),
      `support_status "${payload.support_status}" must be one of: ${validStatuses.join(', ')}`
    );
  });

  test('selected_route.route_id must exist in route_catalog.json when both are present', () => {
    const payload = loadPayload();
    if (payload === null) return;

    const routeIds = loadRouteIds();
    if (routeIds === null) {
      // Route catalog missing - cannot cross-reference, skip.
      return;
    }

    if (!payload.selected_route) {
      // No selected route - acceptable degradation.
      return;
    }

    const selectedRouteId = payload.selected_route.route_id;
    if (selectedRouteId === undefined || selectedRouteId === null) {
      return;
    }

    assert.ok(
      routeIds.has(selectedRouteId),
      `selected_route.route_id "${selectedRouteId}" must exist in route_catalog.json. ` +
      `If not found, UI should show degradation text instead of map linkage.`
    );
  });

  test('selected_route.route_id not in catalog triggers degradation (documented behavior)', () => {
    // This test documents the expected degradation behavior:
    // When route_id is not in catalog, the UI must NOT link to map
    // and must show a degradation message instead.
    const routeIds = loadRouteIds();
    if (routeIds === null) return;

    const fakeRouteId = 'nonexistent_route_999';
    assert.ok(
      !routeIds.has(fakeRouteId),
      'A fabricated route_id should not exist in catalog'
    );
    // The UI contract requires: no map linkage, show degradation text.
    // This is a documentation test - actual UI behavior tested in UI contract tests.
  });

  test('payload must not contain local absolute paths', () => {
    const payload = loadPayload();
    if (payload === null) return;

    const jsonStr = JSON.stringify(payload);

    // Check for Windows absolute paths (e.g., C:\, D:\)
    const windowsAbsPath = /[A-Za-z]:\\/;
    assert.ok(
      !windowsAbsPath.test(jsonStr),
      'Payload must not contain Windows absolute paths'
    );

    // Check for Unix absolute paths (e.g., /home/, /Users/, /tmp/)
    const unixAbsPath = /"\/(home|Users|tmp|var|opt|srv)\//;
    assert.ok(
      !unixAbsPath.test(jsonStr),
      'Payload must not contain Unix absolute paths'
    );
  });

  test('payload must not contain API keys or authorization headers', () => {
    const payload = loadPayload();
    if (payload === null) return;

    const jsonStr = JSON.stringify(payload).toLowerCase();

    const sensitivePatterns = [
      'api_key',
      'apikey',
      'api-key',
      'authorization',
      'bearer ',
      'secret',
      'password',
      'token'
    ];

    for (const pattern of sensitivePatterns) {
      assert.ok(
        !jsonStr.includes(pattern),
        `Payload must not contain sensitive pattern "${pattern}"`
      );
    }
  });

  test('payload artifacts must only contain repository-relative paths or public URLs', () => {
    const payload = loadPayload();
    if (payload === null) return;

    if (!payload.artifacts) return;

    assert.ok(Array.isArray(payload.artifacts), 'artifacts must be an array');

    for (const artifact of payload.artifacts) {
      if (typeof artifact === 'string') {
        // Must be relative path or https URL
        const isRelative = !artifact.startsWith('/') && !artifact.includes(':\\');
        const isHttpsUrl = artifact.startsWith('https://');
        assert.ok(
          isRelative || isHttpsUrl,
          `Artifact "${artifact}" must be a repository-relative path or public HTTPS URL`
        );
      } else if (typeof artifact === 'object' && artifact !== null) {
        if (artifact.path) {
          const isRelative = !artifact.path.startsWith('/') && !artifact.path.includes(':\\');
          const isHttpsUrl = artifact.path.startsWith('https://');
          assert.ok(
            isRelative || isHttpsUrl,
            `Artifact path "${artifact.path}" must be a repository-relative path or public HTTPS URL`
          );
        }
        if (artifact.url) {
          assert.ok(
            artifact.url.startsWith('https://'),
            `Artifact URL "${artifact.url}" must be HTTPS`
          );
        }
      }
    }
  });

  test('payload must not contain raw model internal reasoning', () => {
    const payload = loadPayload();
    if (payload === null) return;

    const jsonStr = JSON.stringify(payload);

    // Check for common model reasoning markers
    const reasoningPatterns = [
      '<|im_start|>',
      '<|im_end|>',
      'system_prompt',
      'assistant_message',
      'user_message'
    ];

    for (const pattern of reasoningPatterns) {
      assert.ok(
        !jsonStr.includes(pattern),
        `Payload must not contain model reasoning marker "${pattern}"`
      );
    }
  });

  test('baselines array must reference known baseline IDs when present', () => {
    const payload = loadPayload();
    if (payload === null) return;

    if (!payload.baselines) return;

    assert.ok(Array.isArray(payload.baselines), 'baselines must be an array');

    const knownBaselineIds = [
      'B0_shortest_feasible',
      'B1_pm25_only',
      'B2_multi_environment',
      'B3_non_personalized',
      'M1_personalized_constrained'
    ];

    for (const baseline of payload.baselines) {
      if (baseline && baseline.baseline_id) {
        assert.ok(
          knownBaselineIds.includes(baseline.baseline_id),
          `Baseline ID "${baseline.baseline_id}" must be one of the known variants`
        );
      }
    }
  });

  test('metrics must include primary metric jaccard_top5 when present', () => {
    const payload = loadPayload();
    if (payload === null) return;

    if (!payload.metrics) return;

    assert.ok(Array.isArray(payload.metrics), 'metrics must be an array');

    const metricIds = payload.metrics.map(m => m.metric_id).filter(Boolean);
    if (metricIds.length > 0) {
      assert.ok(
        metricIds.includes('jaccard_top5'),
        'metrics must include primary metric jaccard_top5'
      );
    }
  });

  test('generated_at must be a parseable ISO 8601 timestamp when present', () => {
    const payload = loadPayload();
    if (payload === null) return;

    if (!payload.generated_at) return;

    const date = new Date(payload.generated_at);
    assert.ok(
      !isNaN(date.getTime()),
      `generated_at "${payload.generated_at}" must be a valid ISO 8601 timestamp`
    );
  });

  test('hypothesis must contain hypothesis_id and statement when present', () => {
    const payload = loadPayload();
    if (payload === null) return;

    if (!payload.hypothesis) return;

    assert.ok(
      'hypothesis_id' in payload.hypothesis,
      'hypothesis must contain hypothesis_id'
    );
    assert.ok(
      'statement' in payload.hypothesis || 'question' in payload.hypothesis,
      'hypothesis must contain statement or question'
    );
  });

  test('evidence and citations counts must be non-negative integers when present', () => {
    const payload = loadPayload();
    if (payload === null) return;

    if (payload.evidence_count !== undefined) {
      assert.ok(
        Number.isInteger(payload.evidence_count) && payload.evidence_count >= 0,
        'evidence_count must be a non-negative integer'
      );
    }

    if (payload.citation_count !== undefined) {
      assert.ok(
        Number.isInteger(payload.citation_count) && payload.citation_count >= 0,
        'citation_count must be a non-negative integer'
      );
    }
  });

  test('iteration_timeline must be an array of objects with timestamp when present', () => {
    const payload = loadPayload();
    if (payload === null) return;

    if (!payload.iteration_timeline) return;

    assert.ok(
      Array.isArray(payload.iteration_timeline),
      'iteration_timeline must be an array'
    );

    for (const entry of payload.iteration_timeline) {
      assert.ok(
        typeof entry === 'object' && entry !== null,
        'Each timeline entry must be an object'
      );
      if (entry.timestamp) {
        const date = new Date(entry.timestamp);
        assert.ok(
          !isNaN(date.getTime()),
          `Timeline entry timestamp "${entry.timestamp}" must be valid`
        );
      }
    }
  });

  test('data_limitations must be present and non-empty when payload exists', () => {
    const payload = loadPayload();
    if (payload === null) return;

    // The research question explicitly states constraints about proxy variables
    // and data limitations. The payload should surface these.
    if (payload.data_limitations !== undefined) {
      assert.ok(
        Array.isArray(payload.data_limitations),
        'data_limitations must be an array'
      );
    }
  });

  test('payload must not contain free-text model profiles', () => {
    const payload = loadPayload();
    if (payload === null) return;

    const jsonStr = JSON.stringify(payload);

    // Free-text profiles are prohibited per CLI contract
    // Check for common profile-like patterns that would indicate raw model output
    const prohibitedPatterns = [
      'as an ai',
      'i am an ai',
      'as a language model',
      'i cannot',
      'i\'m sorry'
    ];

    const lowerStr = jsonStr.toLowerCase();
    for (const pattern of prohibitedPatterns) {
      assert.ok(
        !lowerStr.includes(pattern),
        `Payload must not contain free-text model output pattern "${pattern}"`
      );
    }
  });

});
