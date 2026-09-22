const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');

for (const kind of ['Nodes', 'Services']) {
  test(`${kind} list shows plain names and preserves selection`, () => {
    const source = fs.readFileSync(`${__dirname}/../web/assets/app.js`, 'utf8');
    const rows = [];
    const selected = [];
    const context = {
      state: { selectedNode: '/camera', selectedService: '/camera/set_parameters', rosGraph: {
        nodes: [{ full_name: '/camera', namespace: '/' }],
        services: [{ name: '/camera/set_parameters', types: ['rcl_interfaces/srv/SetParameters'] }],
      } },
      $: () => ({ value: '' }), safeArray: value => value || [], filterByText: items => items,
      renderList: (_element, items, _selected, factory) => items.forEach(item => rows.push(factory(item))),
      document: { createElement: () => ({ dataset: {}, attributes: {},
        setAttribute(name, value) { this.attributes[name] = value; },
        addEventListener(_name, callback) { this.click = callback; },
      }) },
      selectNode: (...args) => selected.push(args), selectService: (...args) => selected.push(args),
    };
    const end = kind === 'Nodes' ? 'function renderNodeDetails' : 'async function selectTopic';
    vm.runInNewContext(source.slice(source.indexOf(`function render${kind}()`), source.indexOf(end)), context);
    context[`render${kind}`]();
    const expected = kind === 'Nodes' ? '/camera' : '/camera/set_parameters';
    assert.equal(rows[0].textContent, expected);
    assert.equal(rows[0].innerHTML, undefined);
    assert.equal(rows[0].className, 'ros-list-row');
    assert.equal(rows[0].attributes['aria-pressed'], 'true');
    rows[0].click();
    assert.deepEqual(selected, [kind === 'Nodes' ? [expected] : [expected, 'rcl_interfaces/srv/SetParameters']]);
  });
}

test('topic list shows only names and preserves selection with message type', () => {
  const source = fs.readFileSync(`${__dirname}/../web/assets/app.js`, 'utf8');
  const rows = [];
  const selected = [];
  const context = {
    state: { selectedTopic: '/scan', rosGraph: { topics: [
      { name: '/scan', types: ['sensor_msgs/msg/LaserScan'], publishers: 2, subscribers: 3 },
      { name: '/image_raw', types: ['sensor_msgs/msg/Image'], is_image: true },
    ] } },
    $: () => ({ value: '' }),
    safeArray: value => value || [],
    filterByText: items => items,
    renderList: (_element, items, _selected, factory) => items.forEach(item => rows.push(factory(item))),
    document: { createElement: () => ({ dataset: {}, attributes: {},
      setAttribute(name, value) { this.attributes[name] = value; },
      addEventListener(_name, handler) { this.click = handler; },
    }) },
    selectTopic: (...args) => selected.push(args),
  };
  vm.runInNewContext(source.slice(source.indexOf('function renderTopics()'), source.indexOf('function renderServices()')), context);
  context.renderTopics();
  assert.deepEqual(rows.map(row => row.textContent), ['/scan', '/image_raw']);
  assert.ok(rows.every(row => row.className === 'ros-list-row' && row.innerHTML === undefined));
  assert.equal(rows[0].attributes['aria-pressed'], 'true');
  assert.equal(rows[1].attributes['aria-pressed'], 'false');
  rows[0].click();
  assert.deepEqual(selected, [['/scan', 'sensor_msgs/msg/LaserScan']]);
});
