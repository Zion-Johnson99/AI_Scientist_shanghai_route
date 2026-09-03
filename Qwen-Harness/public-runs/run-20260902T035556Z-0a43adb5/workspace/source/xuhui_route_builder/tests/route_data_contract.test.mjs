import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const dataDir = join(__dirname, '..', 'data', 'web');

function loadJSON(filename) {
  const filePath = join(dataDir, filename);
  if (!existsSync(filePath)) {
    assert.fail(`Data file not found: ${filePath}`);
  }
  const raw = readFileSync(filePath, 'utf-8');
  return JSON.parse(raw);
}

describe('route_catalog.json contract', () => {
  const catalog = loadJSON('route_catalog.json');

  it('should be an array', () => {
    assert.ok(Array.isArray(catalog), 'route_catalog.json top-level must be an array');
  });

  it('should contain exactly 90 routes', () => {
    assert.equal(catalog.length, 90, `Expected 90 routes, got ${catalog.length}`);
  });

  it('should have 30 walk routes', () => {
    const walkRoutes = catalog.filter(r => r.route_mode === 'walk');
    assert.equal(walkRoutes.length, 30, `Expected 30 walk routes, got ${walkRoutes.length}`);
  });

  it('should have 30 run routes', () => {
    const runRoutes = catalog.filter(r => r.route_mode === 'run');
    assert.equal(runRoutes.length, 30, `Expected 30 run routes, got ${runRoutes.length}`);
  });

  it('should have 30 bike routes', () => {
    const bikeRoutes = catalog.filter(r => r.route_mode === 'bike');
    assert.equal(bikeRoutes.length, 30, `Expected 30 bike routes, got ${bikeRoutes.length}`);
  });

  it('should have no duplicate route_ids', () => {
    const ids = catalog.map(r => r.route_id);
    const uniqueIds = new Set(ids);
    assert.equal(uniqueIds.size, ids.length, `Duplicate route_ids found: ${ids.length - uniqueIds.size} duplicates`);
  });

  it('each route should have required fields', () => {
    const requiredFields = ['route_id', 'route_name', 'route_mode', 'validation_status', 'geometry_status'];
    for (const route of catalog) {
      for (const field of requiredFields) {
        assert.ok(
          route[field] !== undefined && route[field] !== null,
          `Route ${route.route_id || 'unknown'} missing required field: ${field}`
        );
      }
    }
  });

  it('all routes should have validation_status accepted', () => {
    const nonAccepted = catalog.filter(r => r.validation_status !== 'accepted');
    assert.equal(
      nonAccepted.length,
      0,
      `Found ${nonAccepted.length} routes with validation_status !== accepted: ${nonAccepted.map(r => r.route_id).join(', ')}`
    );
  });

  it('route_mode should only be walk, run, or bike', () => {
    const validModes = new Set(['walk', 'run', 'bike']);
    const invalid = catalog.filter(r => !validModes.has(r.route_mode));
    assert.equal(
      invalid.length,
      0,
      `Found ${invalid.length} routes with invalid route_mode: ${invalid.map(r => `${r.route_id}=${r.route_mode}`).join(', ')}`
    );
  });
});

describe('xuhui_routes.geojson contract', () => {
  const geojson = loadJSON('xuhui_routes.geojson');
  const catalog = loadJSON('route_catalog.json');

  it('should be a valid GeoJSON FeatureCollection', () => {
    assert.equal(geojson.type, 'FeatureCollection', 'Top-level type must be FeatureCollection');
  });

  it('should contain exactly 90 features', () => {
    assert.ok(Array.isArray(geojson.features), 'features must be an array');
    assert.equal(geojson.features.length, 90, `Expected 90 features, got ${geojson.features.length}`);
  });

  it('each feature should have properties.route_id', () => {
    for (const feature of geojson.features) {
      assert.ok(feature.properties, 'Feature must have properties');
      assert.ok(
        feature.properties.route_id !== undefined && feature.properties.route_id !== null,
        'Feature missing properties.route_id'
      );
    }
  });

  it('each feature should have LineString geometry with non-empty coordinates', () => {
    for (const feature of geojson.features) {
      assert.ok(feature.geometry, `Feature ${feature.properties?.route_id || 'unknown'} missing geometry`);
      assert.equal(
        feature.geometry.type,
        'LineString',
        `Feature ${feature.properties?.route_id || 'unknown'} geometry type must be LineString, got ${feature.geometry.type}`
      );
      assert.ok(
        Array.isArray(feature.geometry.coordinates),
        `Feature ${feature.properties?.route_id || 'unknown'} coordinates must be an array`
      );
      assert.ok(
        feature.geometry.coordinates.length > 0,
        `Feature ${feature.properties?.route_id || 'unknown'} coordinates must not be empty`
      );
    }
  });

  it('GeoJSON route_ids should match catalog route_ids exactly', () => {
    const catalogIds = new Set(catalog.map(r => r.route_id));
    const geojsonIds = new Set(geojson.features.map(f => f.properties.route_id));

    const missingInGeojson = [...catalogIds].filter(id => !geojsonIds.has(id));
    const extraInGeojson = [...geojsonIds].filter(id => !catalogIds.has(id));

    assert.equal(
      missingInGeojson.length,
      0,
      `Route IDs in catalog but missing from GeoJSON: ${missingInGeojson.join(', ')}`
    );
    assert.equal(
      extraInGeojson.length,
      0,
      `Route IDs in GeoJSON but not in catalog: ${extraInGeojson.join(', ')}`
    );
  });

  it('GeoJSON should have no duplicate route_ids', () => {
    const ids = geojson.features.map(f => f.properties.route_id);
    const uniqueIds = new Set(ids);
    assert.equal(uniqueIds.size, ids.length, `Duplicate route_ids in GeoJSON: ${ids.length - uniqueIds.size} duplicates`);
  });

  it('coordinates should be within reasonable longitude/latitude range for Shanghai Xuhui', () => {
    // Xuhui district approximate bounds: lon 121.3-121.5, lat 31.1-31.25
    const lonMin = 121.0;
    const lonMax = 121.8;
    const latMin = 30.9;
    const latMax = 31.5;

    for (const feature of geojson.features) {
      const routeId = feature.properties?.route_id || 'unknown';
      for (const coord of feature.geometry.coordinates) {
        const [lon, lat] = coord;
        assert.ok(
          lon >= lonMin && lon <= lonMax,
          `Route ${routeId}: longitude ${lon} out of range [${lonMin}, ${lonMax}]`
        );
        assert.ok(
          lat >= latMin && lat <= latMax,
          `Route ${routeId}: latitude ${lat} out of range [${latMin}, ${latMax}]`
        );
      }
    }
  });
});

describe('cross-file consistency', () => {
  const catalog = loadJSON('route_catalog.json');
  const geojson = loadJSON('xuhui_routes.geojson');

  it('catalog and GeoJSON should have the same number of entries', () => {
    assert.equal(
      catalog.length,
      geojson.features.length,
      `Catalog has ${catalog.length} entries but GeoJSON has ${geojson.features.length} features`
    );
  });

  it('every catalog route_id should appear exactly once in GeoJSON', () => {
    const geojsonIdCounts = new Map();
    for (const feature of geojson.features) {
      const id = feature.properties.route_id;
      geojsonIdCounts.set(id, (geojsonIdCounts.get(id) || 0) + 1);
    }

    for (const route of catalog) {
      const count = geojsonIdCounts.get(route.route_id) || 0;
      assert.equal(
        count,
        1,
        `Route ${route.route_id} appears ${count} times in GeoJSON (expected exactly 1)`
      );
    }
  });
});
