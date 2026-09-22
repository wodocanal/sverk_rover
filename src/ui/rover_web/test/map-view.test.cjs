const assert = require('node:assert/strict');
const test = require('node:test');
const { MapViewport, bindMapViewport } = require('../web/assets/map-view.js');

const near = (actual, expected) => assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} != ${expected}`);
const bounds = { minX: -4, maxX: 4, minY: -3, maxY: 3 };

function harness() {
  const handlers = {};
  const captured = new Set();
  const canvas = {
    clientWidth: 800, clientHeight: 600,
    addEventListener: (name, callback) => { handlers[name] = callback; },
    getBoundingClientRect: () => ({ left: 0, top: 0 }),
    focus() {},
    setPointerCapture: id => captured.add(id),
    hasPointerCapture: id => captured.has(id),
    releasePointerCapture: id => captured.delete(id),
    classList: { add() {}, remove() {}, toggle() {} },
  };
  const view = new MapViewport();
  const state = { mode: null, preview: null, commits: [], yaw: 0.7 };
  bindMapViewport(canvas, view, () => {}, {
    mode: () => state.mode,
    yaw: () => state.yaw,
    preview: value => { state.preview = value; },
    commit: (mode, pose) => { state.commits.push({ mode, pose }); },
    cancel: () => { state.mode = null; },
  });
  const pointer = (type, x, y, id = 1) => handlers[type]({
    type, pointerId: id, clientX: x, clientY: y, pointerType: 'touch', preventDefault() {},
  });
  return { view, state, handlers, pointer, captured };
}

test('map zoom anchors world point, clamps scale, and preserves view across map updates', () => {
  const view = new MapViewport();
  view.fit('map', bounds, 800, 600);
  view.move(50, -30);
  const point = { x: 180, y: 420 };
  const before = view.world(point, 800, 600);
  view.zoomAt(3, point.x, point.y, 800, 600);
  const after = view.world(point, 800, 600);
  near(after.x, before.x);
  near(after.y, before.y);
  const snapshot = { ...view };
  view.fit('map', { ...bounds, maxX: 50 }, 390, 340);
  assert.deepEqual({ ...view }, snapshot);
  view.zoomAt(1e9, 400, 300, 800, 600);
  assert.equal(view.scale, 2000);
  view.zoomAt(1e-9, 400, 300, 800, 600);
  assert.equal(view.scale, 5);
  view.reset();
  view.fit('map', bounds, 800, 600);
  near(view.centerX, 0);
  near(view.centerY, 0);
});

test('dragging pans the map and pinch changes scale without selecting a pose', () => {
  const { view, pointer, state } = harness();
  pointer('pointerdown', 300, 300);
  pointer('pointermove', 420, 360);
  near(view.centerX, -1);
  near(view.centerY, 0.5);
  pointer('pointerup', 420, 360);
  pointer('pointerdown', 300, 300);
  pointer('pointerdown', 500, 300, 2);
  pointer('pointermove', 700, 300, 2);
  near(view.scale, 240);
  assert.equal(state.commits.length, 0);
});

for (const mode of ['initial', 'goal']) {
  test(`${mode}: press-drag-release commits anchor and heading in map coordinates`, () => {
    const { view, pointer, state } = harness();
    view.move(120, 60);
    view.zoomAt(2, 400, 300, 800, 600);
    state.mode = mode;
    const anchor = view.world({ x: 300, y: 400 }, 800, 600);
    pointer('pointerdown', 300, 400);
    pointer('pointermove', 420, 280);
    near(state.preview.pose.yaw, Math.PI / 4);
    assert.equal(state.commits.length, 0);
    pointer('pointerup', 420, 280);
    assert.equal(state.commits[0].mode, mode);
    near(state.commits[0].pose.x, anchor.x);
    near(state.commits[0].pose.y, anchor.y);
    near(state.commits[0].pose.yaw, Math.PI / 4);
    assert.equal(state.preview, null);
  });
}

test('simple click preserves existing heading; canceled gestures never commit', () => {
  const { pointer, state, handlers, captured } = harness();
  state.mode = 'goal';
  pointer('pointerdown', 300, 300);
  pointer('pointerup', 300, 300);
  near(state.commits[0].pose.yaw, state.yaw);
  for (const cancel of ['pointercancel', 'lostpointercapture']) {
    pointer('pointerdown', 300, 300);
    pointer('pointermove', 300, 100);
    pointer(cancel, 300, 100);
    assert.equal(state.preview, null);
  }
  pointer('pointerdown', 300, 300);
  handlers.keydown({ key: 'Escape', preventDefault() {} });
  pointer('pointerup', 300, 100);
  assert.equal(state.commits.length, 1);
  assert.equal(state.mode, null);
  assert.equal(captured.size, 0);
});

test('second finger cancels pose preview and switches to pinch without committing', () => {
  const { pointer, state, view } = harness();
  state.mode = 'initial';
  pointer('pointerdown', 300, 300);
  pointer('pointerdown', 500, 300, 2);
  assert.equal(state.preview, null);
  pointer('pointermove', 700, 300, 2);
  pointer('pointerup', 700, 300, 2);
  pointer('pointerup', 300, 300);
  near(view.scale, 240);
  assert.equal(state.commits.length, 0);
});
