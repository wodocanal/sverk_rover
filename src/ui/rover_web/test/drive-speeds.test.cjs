const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(`${__dirname}/../web/assets/app.js`, 'utf8');

function harness(saved = null) {
  const inputs = Object.fromEntries(['linear-speed', 'lateral-speed', 'angular-speed'].map(id => [id, {value:''}]));
  const storage = {value:saved};
  const context = {
    STORAGE_KEYS: {manualDriveSpeeds:'speeds'}, state: {},
    localStorage: {getItem:()=>storage.value, setItem:(_, value)=>{storage.value=value;}},
    $: selector=>inputs[selector.slice(1)],
    updateDriveOutputs() {}, updateDrivePreview() {}, computeDriveCommand() {},
  };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('function readManualDriveSpeeds()'), source.indexOf('function refreshDriveConfigFromConfig')), context);
  context.state.manualDriveSpeeds = context.readManualDriveSpeeds();
  return {context, inputs, storage};
}

test('periodic config refresh preserves all user-selected speeds', () => {
  const {context:c, inputs} = harness();
  c.syncManualDriveSpeeds();
  assert.equal(inputs['linear-speed'].value,'0.18');
  for (const [id, speed] of [['linear-speed',0.27],['lateral-speed',0.23],['angular-speed',0.95]]) {
    inputs[id].value = String(speed); c.rememberManualDriveSpeed(id);
  }
  for(let i=0;i<5;i++) c.syncManualDriveSpeeds({linear_x:0.18,linear_y:0.16,angular_z:0.7});
  assert.equal(inputs['linear-speed'].value,'0.27');
  assert.equal(inputs['lateral-speed'].value,'0.23');
  assert.equal(inputs['angular-speed'].value,'0.95');
});

test('selection survives reload and clamps to reduced server limits', () => {
  const {context:c, inputs,storage} = harness('{"linear_x":0.3,"angular_z":1.2}');
  c.syncManualDriveSpeeds({}, {linear_x:0.2,angular_z:0.8});
  assert.equal(inputs['linear-speed'].value,'0.2');
  assert.equal(inputs['angular-speed'].value,'0.8');
  const reload = harness(storage.value);
  reload.context.syncManualDriveSpeeds();
  assert.equal(reload.inputs['linear-speed'].value,'0.2');
});

test('corrupt storage and unavailable storage do not break driving', () => {
  for(const saved of ['oops', 'null', '[]', '{"linear_x":"fast","linear_y":-1}']) {
    const {context:c, inputs} = harness(saved);
    c.syncManualDriveSpeeds();
    assert.equal(inputs['linear-speed'].value,'0.18');
  }
  const {context:c, inputs} = harness();
  c.localStorage.setItem = ()=>{throw Error('disabled');};
  inputs['linear-speed'].value='0.24'; c.rememberManualDriveSpeed('linear-speed');
  c.syncManualDriveSpeeds();
  assert.equal(inputs['linear-speed'].value,'0.24');
});

test('both config paths use the shared synchronization and input persists selection', () => {
  assert.match(source.slice(source.indexOf('function refreshDriveConfigFromConfig'),source.indexOf('function normalizeDriveType')),/syncManualDriveSpeeds\(defaults, limits\)/);
  assert.match(source.slice(source.indexOf('async function refreshDriveConfig()'),source.indexOf('function updateDriveOutputs')),/syncManualDriveSpeeds\(payload.defaults, payload.limits\)/);
  assert.match(source.slice(source.indexOf('function bindDrivePage()'),source.indexOf('function bindRoutesPage()')),/rememberManualDriveSpeed\(id\)/);
});
