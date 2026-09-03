import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const mainSource = readFileSync(join(__dirname, '..', 'web', 'src', 'main.js'), 'utf8');

test('recommendation button calls the local API and renders its response', () => {
  assert.match(mainSource, /recommend-btn/);
  assert.match(mainSource, /http:\/\/127\.0\.0\.1:8124\/api\/v1\/recommendations/);
  assert.match(mainSource, /addEventListener\(['"]click['"]/);
  assert.match(mainSource, /renderLoading\(\)/);
  assert.match(mainSource, /renderResult\(/);
});
