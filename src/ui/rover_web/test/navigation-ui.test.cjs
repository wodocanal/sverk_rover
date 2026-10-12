const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');

const html = fs.readFileSync(`${__dirname}/../web/index.html`, 'utf8');
const source = fs.readFileSync(`${__dirname}/../web/assets/app.js`, 'utf8');
const zones = fs.readFileSync(`${__dirname}/../web/assets/named-zones.js`, 'utf8');
const gateway = fs.readFileSync(`${__dirname}/../rover_web/web_gateway_node.py`, 'utf8');
const nav2 = fs.readFileSync(`${__dirname}/../../../motion/rover_navigation/config/nav2.yaml`, 'utf8');

test('map uses gestures instead of scale and follow controls', () => {
  assert.doesNotMatch(html, /id="viz-(scale|follow|fit|clear|map-info)"/);
  assert.match(html, /assets\/map-view.js/);
  assert.match(source, /RoverMapView.bindMapViewport/);
});

test('map picker and accessible icon refresh share the telemetry row', () => {
  const row = html.slice(html.indexOf('<div class="visualization-readout">'), html.indexOf('<div class="visualization-workspace">'));
  for (const id of ['viz-map-select', 'viz-map-refresh', 'viz-position', 'viz-yaw', 'viz-navigation-state']) {
    assert.ok(row.includes(`id="${id}"`));
  }
  assert.match(row, /id="viz-map-refresh" aria-label="Обновить карты"/);
  assert.match(row, /<svg /);
  assert.doesNotMatch(source, /\$\('#viz-(fit|clear|map-info)'\)/);
});

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

test('named zones are available from the visualization page', () => {
  for (const id of ['grid-pick', 'grid-save', 'grid-clear', 'zone-select', 'zone-name', 'zone-can-drive', 'zone-pick', 'zone-save', 'zone-delete']) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /assets\/named-zones\.js/);
  assert.match(source, /RoverNamedZones\.draw/);
  assert.match(zones, /save_zone/);
  assert.match(zones, /save_grid/);
  assert.match(zones, /toggleCell/);
  assert.match(zones, /delete_zone/);
});

test('manual zone inspection controls and asset are available', () => {
  assert.match(html, /zone-inspection-start/);
  assert.match(html, /assets\/zone-inspection\.js/);
  const inspection = fs.readFileSync(`${__dirname}/../web/assets/zone-inspection.js`, 'utf8');
  assert.match(inspection, /zone_inspection\/start/);
  assert.match(inspection, /target_obstacle: target\(\)\.value/);
  assert.match(inspection, /vlm_analyzing/);
  assert.match(inspection, /alternate_qr_moving/);
  assert.match(inspection, /VLM: \$\{item\.classification\}/);
  assert.match(html, /id="zone-inspection-target"/);
  assert.match(inspection, /RoverZoneInspection/);
});

test('zone inspection sends each Nav2 goal only after its previous scan', () => {
  const namedPlaces = fs.readFileSync(`${__dirname}/../rover_web/named_places.py`, 'utf8');
  assert.match(namedPlaces, /self\.send_navigation_goal\(\{'goal': route\[0\]\}\)/);
  assert.match(namedPlaces, /self\.send_navigation_goal\(\{'goal': status\['route'\]\[next_index\]\}\)/);
  assert.match(namedPlaces, /goal_state == 'succeeded'/);
  assert.match(namedPlaces, /Holding the heading toward the next point/);
  assert.match(namedPlaces, /road = self\.road_state\(\)/);
  assert.match(namedPlaces, /road\['fresh'\] and road\['state'\] == 'blocked'/);
  assert.match(namedPlaces, /state='blocked'/);
  assert.match(nav2, /nav2_waypoint_follower::WaitAtWaypoint/);
});
