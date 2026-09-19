const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');

const html = fs.readFileSync(`${__dirname}/../web/index.html`, 'utf8');
const source = fs.readFileSync(`${__dirname}/../web/assets/app.js`, 'utf8');

test('visualization page exposes mapping lifecycle controls', () => {
  for (const id of ['mapping-start', 'mapping-save', 'mapping-stop', 'mapping-label']) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
});

test('navigation requires map, initial pose and goal inputs', () => {
  for (const id of [
    'viz-map-select',
    'nav-initial-x', 'nav-initial-y', 'nav-initial-yaw',
    'nav-goal-x', 'nav-goal-y', 'nav-goal-yaw',
    'navigation-start', 'navigation-stop',
  ]) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(source, /!map \|\| !initialPose \|\| !goal/);
  assert.match(source, /\/api\/navigation\/start/);
});

test('planned Nav2 path and selected goal are rendered on the movement canvas', () => {
  assert.match(source, /runtime\?\.planned_path/);
  assert.match(source, /ctx\.strokeStyle = '#f28b21'/);
  assert.match(source, /ctx\.fillStyle = '#c93644'/);
});
