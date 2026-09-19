const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');

const source = fs.readFileSync(`${__dirname}/../web/assets/app.js`, 'utf8');
const html = fs.readFileSync(`${__dirname}/../web/index.html`, 'utf8');

function commandFor(driveType, keys) {
  const elements = {
    '#linear-speed': { value: '0.2' },
    '#lateral-speed': { value: '0.15' },
    '#angular-speed': { value: '0.8' },
  };
  const context = vm.createContext({
    state: { driveType, driveKeys: new Set(keys) },
    $: (selector) => elements[selector],
  });
  const start = source.indexOf('function computeDriveCommand()');
  const end = source.indexOf('function updateDrivePreview', start);
  vm.runInContext(source.slice(start, end), context);
  return JSON.parse(JSON.stringify(context.computeDriveCommand()));
}

test('settings expose mecanum and ordinary wheel modes', () => {
  assert.match(html, /id="drive-type-setting"/);
  assert.match(html, /option value="mecanum"/);
  assert.match(html, /option value="differential"/);
});

test('ordinary wheel mode ignores A and D lateral input', () => {
  assert.deepEqual(commandFor('differential', ['KeyW', 'KeyA']), {
    linearX: 0.2,
    linearY: 0,
    angularZ: 0,
  });
});

test('ordinary wheel mode retains Q W E S controls', () => {
  assert.deepEqual(commandFor('differential', ['KeyS', 'KeyE']), {
    linearX: -0.2,
    linearY: 0,
    angularZ: -0.8,
  });
  for (const key of ['KeyQ', 'KeyW', 'KeyE', 'KeyS']) {
    assert.match(html, new RegExp(`data-key="${key}"`));
  }
});

test('mecanum mode keeps lateral input', () => {
  assert.deepEqual(commandFor('mecanum', ['KeyD']), {
    linearX: 0,
    linearY: -0.15,
    angularZ: 0,
  });
});
