const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
  const source = fs.readFileSync(`${__dirname}/../web/assets/app.js`, 'utf8');
  const storage = new Map();
  const elements = new Map();
  const element = (key) => {
    if (!elements.has(key)) elements.set(key, {
      classList: { toggle() {} }, addEventListener(type, fn) { this[type] = fn; },
    });
    return elements.get(key);
  };
  const state = { page: 'settings', servoEnabled: true, audioEnabled: false, octolinerEnabled: false };
  let refreshes = 0;
  const context = vm.createContext({
    state, $: element, $$: (key) => [element(key)],
    STORAGE_KEYS: { servoEnabled: 'servo', audioEnabled: 'audio', octolinerEnabled: 'octoliner', peripheralsPage: 'page' },
    localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) },
    setPage: page => { state.page = page; },
    refreshIdentityAndConfig: () => { refreshes++; },
  });
  vm.runInContext(source.slice(source.indexOf('const PERIPHERAL_FEATURES'), source.indexOf('function closeSidebar()')), context);
  return { context, state, storage, element, refreshes: () => refreshes };
}

test('automatic defaults follow components without persisting them', () => {
  const h = harness();
  h.context.applyFeatureDefaultsFromConfig({ web: { audio_enabled: true, octoliner_enabled: false } });
  assert.equal(h.context.isPageAvailable('audio'), true);
  assert.equal(h.context.isPageAvailable('octoliner'), false);
  assert.equal(h.storage.size, 0);
  h.state.page = 'audio';
  h.context.applyFeatureDefaultsFromConfig({ web: { audio_enabled: false, octoliner_enabled: true } });
  assert.equal(h.state.page, 'camera');
  assert.equal(h.context.isPageAvailable('octoliner'), true);
});

test('manual preferences survive refresh and reset restores automatic mode', () => {
  const h = harness();
  h.context.bindServoUsage();
  h.element('#audio-enabled').change({ target: { checked: true } });
  h.context.applyFeatureDefaultsFromConfig({ web: { audio_enabled: false } });
  assert.equal(h.state.audioEnabled, true);
  h.element('#peripheral-defaults').click();
  assert.equal(h.storage.has('audio'), false);
  assert.equal(h.refreshes(), 1);
  h.context.applyFeatureDefaultsFromConfig({ web: { audio_enabled: false } });
  assert.equal(h.state.audioEnabled, false);
});

test('disabled remembered page falls back to camera and unknown defaults preserve state', () => {
  const h = harness();
  h.storage.set('page', 'octoliner');
  h.context.updatePeripheralUsage('octoliner', false);
  assert.equal(h.storage.get('page'), 'camera');
  h.context.applyFeatureDefaultsFromConfig({});
  assert.equal(h.state.servoEnabled, true);
  assert.equal(h.context.isPageAvailable('camera'), true);
});
