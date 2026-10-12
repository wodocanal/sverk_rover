const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');

function harness() {
  const source = fs.readFileSync(`${__dirname}/../web/assets/app.js`, 'utf8');
  const timers = new Map();
  let id = 0;
  const requests = [];
  const revoked = [];
  const frame = { draws: 0, getContext: () => ({ canvas: frame, drawImage: () => frame.draws++, clearRect: () => {}, setLineDash() {} }) };
  const state = { selectedCameraTopic: 'live', selectedCameraType: 'direct', cameraGeneration: 0 };
  const metadata = Buffer.from(JSON.stringify({ sequence: 1, result: { detections: [] } }));
  const packet = new Uint8Array(4 + metadata.length + 4);
  new DataView(packet.buffer).setUint32(0, metadata.length);
  packet.set(metadata, 4);
  const context = vm.createContext({
    state, AbortController, DataView, Uint8Array, TextDecoder, Blob,
    safeArray: value => value || [], document: { hidden: false },
    window: {
      setTimeout: (callback, delay) => { timers.set(++id, { callback, delay }); return id; },
      clearTimeout: (key) => timers.delete(key),
    },
    $: (selector) => selector === '#camera-frame' ? frame : { classList: { add() {}, remove() {} } },
    URL: { createObjectURL: () => `blob:${++id}`, revokeObjectURL: (url) => revoked.push(url) },
    Image: class { async decode() {} },
    fetch: (_url, options) => new Promise((resolve, reject) => {
      requests.push({ resolve: () => resolve({ ok: true, arrayBuffer: async () => packet.buffer }), options });
      options.signal.addEventListener('abort', () => reject(new Error('aborted')));
    }),
  });
  vm.runInContext(source.slice(source.indexOf('function startCameraLoop()'), source.indexOf('async function connectCamera()')), context);
  const run = (delay) => {
    const [key, timer] = [...timers].find(([, timer]) => timer.delay === delay);
    timers.delete(key);
    return timer.callback();
  };
  return { context, state, frame, timers, requests, revoked, run };
}

test('only one frame request is in flight and next frame waits for decode', async () => {
  const h = harness();
  h.context.startCameraLoop();
  const pending = h.run(0);
  assert.equal(h.requests.length, 1);
  assert.equal([...h.timers.values()].filter(t => t.delay === 10).length, 0);
  h.requests[0].resolve();
  await pending;
  assert.equal(h.frame.draws, 1);
  const first = h.state.cameraUrl;
  const next = h.run(10);
  h.requests[1].resolve();
  await next;
  assert.ok(h.revoked.includes(first));
  h.context.stopCameraLoop();
  assert.equal(h.timers.size, 0);
});

test('stop aborts pending frame and prevents stale source from updating image', async () => {
  const h = harness();
  h.context.startCameraLoop();
  const pending = h.run(0);
  h.context.stopCameraLoop();
  await pending;
  assert.equal(h.requests[0].options.signal.aborted, true);
  assert.equal(h.frame.draws, 0);
  assert.equal(h.timers.size, 0);
});

test('slow frame is aborted and retried without a queue', async () => {
  const h = harness();
  h.context.startCameraLoop();
  const pending = h.run(0);
  h.run(1500);
  await pending;
  assert.equal(h.frame.draws, 0);
  assert.equal(h.requests.length, 1);
  assert.ok([...h.timers.values()].some(t => t.delay === 10));
});

test('hidden tab pauses frame requests', () => {
  const h = harness();
  h.context.document.hidden = true;
  h.context.startCameraLoop();
  h.run(0);
  assert.equal(h.requests.length, 0);
  assert.ok([...h.timers.values()].some(t => t.delay === 250));
});
