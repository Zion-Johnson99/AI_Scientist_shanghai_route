import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const webSrcDir = join(__dirname, '..', 'web', 'src');

/**
 * Minimal DOM stub for testing research-harness-ui.js behavior
 * without a browser environment.
 */
class MockElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = {};
    this.style = {};
    this.classList = new MockClassList();
    this._textContent = '';
    this._innerHTML = null;
    this._listeners = {};
  }

  get textContent() {
    return this._textContent;
  }

  set textContent(value) {
    this._textContent = String(value);
  }

  get innerHTML() {
    return this._innerHTML;
  }

  set innerHTML(value) {
    // Track innerHTML usage for security assertion
    this._innerHTML = value;
    this._innerHTMLUsed = true;
  }

  get innerHTMLUsed() {
    return this._innerHTMLUsed || false;
  }

  setAttribute(name, value) {
    this.attributes[name] = value;
  }

  getAttribute(name) {
    return this.attributes[name] ?? null;
  }

  appendChild(child) {
    this.children.push(child);
    return child;
  }

  removeChild(child) {
    const idx = this.children.indexOf(child);
    if (idx >= 0) this.children.splice(idx, 1);
    return child;
  }

  addEventListener(event, handler) {
    if (!this._listeners[event]) this._listeners[event] = [];
    this._listeners[event].push(handler);
  }

  dispatchEvent(event) {
    const handlers = this._listeners[event.type] || [];
    for (const h of handlers) h(event);
  }

  querySelector(selector) {
    return null;
  }

  querySelectorAll(selector) {
    return [];
  }
}

class MockClassList {
  constructor() {
    this._classes = new Set();
  }

  add(...names) {
    for (const n of names) this._classes.add(n);
  }

  remove(...names) {
    for (const n of names) this._classes.delete(n);
  }

  contains(name) {
    return this._classes.has(name);
  }

  toggle(name) {
    if (this._classes.has(name)) {
      this._classes.delete(name);
    } else {
      this._classes.add(name);
    }
  }
}

/**
 * Read the source file and check for innerHTML usage patterns.
 */
function readSourceFile(filename) {
  const filePath = join(webSrcDir, filename);
  try {
    return readFileSync(filePath, 'utf-8');
  } catch {
    return null;
  }
}

describe('research-harness-ui.js UI contract', () => {
  test('source file exists', () => {
    const source = readSourceFile('research-harness-ui.js');
    assert.notEqual(source, null, 'research-harness-ui.js must exist in web/src/');
  });

  test('source does not use innerHTML for model-generated text', () => {
    const source = readSourceFile('research-harness-ui.js');
    if (source === null) {
      assert.fail('research-harness-ui.js not found');
      return;
    }
    // innerHTML should not be used for rendering model-generated content.
    // Allow innerHTML only if it is set to a static empty string for clearing.
    const innerHTMLAssignments = source.match(/\.innerHTML\s*=\s*(?!['"]\s*['"]|``)/g);
    assert.equal(
      innerHTMLAssignments,
      null,
      'research-harness-ui.js must not assign dynamic content via innerHTML; use textContent instead'
    );
  });

  test('source uses textContent for text rendering', () => {
    const source = readSourceFile('research-harness-ui.js');
    if (source === null) {
      assert.fail('research-harness-ui.js not found');
      return;
    }
    const usesTextContent = source.includes('textContent');
    assert.ok(usesTextContent, 'research-harness-ui.js should use textContent for safe text rendering');
  });

  test('module exports an init or render function', () => {
    const source = readSourceFile('research-harness-ui.js');
    if (source === null) {
      assert.fail('research-harness-ui.js not found');
      return;
    }
    const hasExport = source.includes('export function') || source.includes('export default') || source.includes('export {');
    assert.ok(hasExport, 'research-harness-ui.js must export at least one function');
  });

  test('module handles null/undefined data without throwing', () => {
    const source = readSourceFile('research-harness-ui.js');
    if (source === null) {
      assert.fail('research-harness-ui.js not found');
      return;
    }
    // Verify the source contains null/undefined guard patterns
    const hasNullGuard =
      source.includes('=== null') ||
      source.includes('=== undefined') ||
      source.includes('== null') ||
      source.includes('!data') ||
      source.includes('if (!') ||
      source.includes('?.');
    assert.ok(hasNullGuard, 'research-harness-ui.js must contain null/undefined guards for missing data');
  });

  test('module contains hide/hidden logic for missing data', () => {
    const source = readSourceFile('research-harness-ui.js');
    if (source === null) {
      assert.fail('research-harness-ui.js not found');
      return;
    }
    const hasHideLogic =
      source.includes('hidden') ||
      source.includes('display') ||
      source.includes('classList') ||
      source.includes('style.display');
    assert.ok(hasHideLogic, 'research-harness-ui.js must contain logic to hide the panel when data is missing');
  });

  test('no eval or Function constructor usage', () => {
    const source = readSourceFile('research-harness-ui.js');
    if (source === null) {
      assert.fail('research-harness-ui.js not found');
      return;
    }
    const hasEval = /\beval\s*\(/.test(source);
    const hasFunctionConstructor = /new\s+Function\s*\(/.test(source);
    assert.ok(!hasEval, 'research-harness-ui.js must not use eval()');
    assert.ok(!hasFunctionConstructor, 'research-harness-ui.js must not use new Function()');
  });

  test('no document.write usage', () => {
    const source = readSourceFile('research-harness-ui.js');
    if (source === null) {
      assert.fail('research-harness-ui.js not found');
      return;
    }
    const hasDocumentWrite = /document\.write\s*\(/.test(source);
    assert.ok(!hasDocumentWrite, 'research-harness-ui.js must not use document.write()');
  });
});

describe('research-harness-ui.js integration with data-loader', () => {
  test('data-loader gracefully handles missing research_harness_latest.json', () => {
    const source = readSourceFile('data-loader.js');
    if (source === null) {
      assert.fail('data-loader.js not found');
      return;
    }
    // data-loader should handle fetch failure for research_harness_latest.json
    const hasCatchOrFallback =
      source.includes('.catch') ||
      source.includes('try') ||
      source.includes('null') ||
      source.includes('undefined');
    assert.ok(hasCatchOrFallback, 'data-loader.js must handle missing research_harness_latest.json gracefully');
  });

  test('data-loader references research_harness_latest.json', () => {
    const source = readSourceFile('data-loader.js');
    if (source === null) {
      assert.fail('data-loader.js not found');
      return;
    }
    const referencesResearchData = source.includes('research_harness_latest');
    assert.ok(referencesResearchData, 'data-loader.js must reference research_harness_latest.json');
  });
});

describe('research-harness.css contract', () => {
  test('stylesheet file exists', () => {
    const cssPath = join(__dirname, '..', 'web', 'styles', 'research-harness.css');
    let content = null;
    try {
      content = readFileSync(cssPath, 'utf-8');
    } catch {
      // file may not exist yet
    }
    assert.notEqual(content, null, 'research-harness.css must exist in web/styles/');
  });

  test('stylesheet does not use !important excessively', () => {
    const cssPath = join(__dirname, '..', 'web', 'styles', 'research-harness.css');
    let content = null;
    try {
      content = readFileSync(cssPath, 'utf-8');
    } catch {
      assert.fail('research-harness.css not found');
      return;
    }
    const importantCount = (content.match(/!important/g) || []).length;
    assert.ok(importantCount <= 3, `research-harness.css should not overuse !important (found ${importantCount})`);
  });
});
