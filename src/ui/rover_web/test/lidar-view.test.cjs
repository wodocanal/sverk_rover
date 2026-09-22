const assert = require('node:assert/strict');
const test = require('node:test');
const { LidarViewport, bindLidarViewport } = require('../web/assets/lidar-view.js');

test('scan cloud is rotated 180 degrees around the rover marker', () => {
  const view = new LidarViewport();
  view.fit([[2, 0]]);
  assert.equal(view.project([1, 0], 800, 600).x, 400);
  assert.ok(view.project([1, 0], 800, 600).y > 300);
  assert.ok(view.project([0, 1], 800, 600).x > 400);
  assert.ok(view.project([-1, 0], 800, 600).y < 300);
  assert.ok(view.project([0, -1], 800, 600).x < 400);
  view.move(90, -30);
  assert.deepEqual(view.project([0, 0], 800, 600), { x: 490, y: 270 });
  assert.deepEqual(view.project([-1, 1], 800, 600), { x: 610, y: 150 });
});

test('zoom keeps cursor world point anchored and is bounded', () => {
  const view = new LidarViewport();
  view.fit([[2, 0]]);
  const point = [1, 0.5];
  const before = view.project(point, 800, 600);
  view.zoomAt(3, before.x, before.y, 800, 600);
  assert.deepEqual(view.project(point, 800, 600), before);
  view.zoomAt(1e6, 400, 300, 800, 600);
  assert.equal(view.zoom, 32);
  view.zoomAt(1e-6, 400, 300, 800, 600);
  assert.equal(view.zoom, 0.25);
});

test('new frames preserve fit, pan and zoom until reset', () => {
  const view = new LidarViewport();
  view.fit([[2, 0]]);
  view.move(100, -50);
  view.zoomAt(2, 400, 300, 800, 600);
  const before = view.project([1, 0], 800, 600);
  view.fit([[10, 0]]);
  assert.deepEqual(view.project([1, 0], 800, 600), before);
  view.reset();
  assert.deepEqual([view.panX, view.panY, view.zoom, view.radius], [0, 0, 1, null]);
});

test('mouse drag, wheel, pinch, cancellation and keyboard controls', () => {
  const handlers = {};
  const captured = new Set();
  const canvas = {
    clientWidth: 800, clientHeight: 600,
    addEventListener: (name, callback) => { handlers[name] = callback; },
    getBoundingClientRect: () => ({ left: 0, top: 0 }),
    focus() {},
    setPointerCapture: (id) => captured.add(id),
    hasPointerCapture: (id) => captured.has(id),
    releasePointerCapture: (id) => captured.delete(id),
    classList: { add() {}, toggle() {} },
  };
  const view = new LidarViewport();
  let redraws = 0;
  bindLidarViewport(canvas, view, () => { redraws += 1; });
  const pointer = (id, x, y) => ({ pointerId: id, clientX: x, clientY: y, pointerType: 'touch', preventDefault() {} });
  handlers.pointerdown(pointer(1, 300, 300));
  handlers.pointermove(pointer(1, 350, 330));
  assert.deepEqual([view.panX, view.panY], [50, 30]);
  handlers.pointercancel(pointer(1, 350, 330));
  handlers.dblclick();
  handlers.pointerdown(pointer(1, 300, 300));
  handlers.pointerdown(pointer(2, 500, 300));
  handlers.pointermove(pointer(2, 700, 300));
  assert.equal(view.zoom, 2);
  handlers.pointerup(pointer(2, 700, 300));
  handlers.lostpointercapture(pointer(1, 300, 300));
  assert.equal(captured.size, 0);
  handlers.wheel({ clientX: 400, clientY: 300, deltaY: -100, deltaMode: 0, preventDefault() {} });
  assert.ok(view.zoom > 2);
  handlers.keydown({ key: 'Home', preventDefault() {} });
  assert.equal(view.zoom, 1);
  assert.ok(redraws >= 5);
});
