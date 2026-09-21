// Run only against an isolated preview, never an operating physical rover.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  const page = await browser.newPage({viewport: {width: 1470, height: 1000}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.accept());
  const url = process.env.ROVER_WEB_URL || 'http://127.0.0.1:8876';
  const name = `Тест-диван-${Date.now()}`;
  let map;
  try {
    await page.addInitScript(() => localStorage.setItem('rover_web.page', 'visualization'));
    await page.goto(url);
    await page.locator('#page-visualization.active').waitFor();
    await page.waitForFunction(() => !document.querySelector('#place-save').disabled);
    map = await page.locator('#viz-map-select').inputValue();
    const status = await (await page.request.get(`${url}/api/navigation/status`)).json();
    assert.equal(status.running, false, 'Browser test requires an idle preview');
    assert.equal(status.prerequisites.ready, false, 'Browser test must not have live hardware');
    await page.locator('#place-pick').click();
    const canvas = page.locator('#odom-canvas');
    await canvas.scrollIntoViewIfNeeded();
    const box = await canvas.boundingBox();
    await page.mouse.move(box.x + box.width * 0.4, box.y + box.height * 0.4);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.25, {steps: 8});
    await page.mouse.up();
    assert.notEqual(await page.locator('#nav-place-x').inputValue(), '');
    assert.notEqual(await page.locator('#nav-place-yaw').inputValue(), '0.0');
    await page.locator('#place-name').fill(name);
    const pose = await Promise.all(['x', 'y', 'yaw'].map(k => page.locator(`#nav-place-${k}`).inputValue()));
    await page.locator('#place-save').click();
    await page.waitForFunction(() => document.querySelector('#places-status').textContent.includes('Точка сохранена'));
    const id = await page.locator('#place-select').inputValue();
    assert.ok(id);
    await page.reload();
    await page.locator(`#place-select option[value="${id}"]`).waitFor({state: 'attached'});
    await page.locator('#place-select').selectOption(id);
    assert.equal(await page.locator('#place-name').inputValue(), name);
    assert.deepEqual(await Promise.all(['x', 'y', 'yaw'].map(k => page.locator(`#nav-place-${k}`).inputValue())), pose);
    await page.locator('#place-name').fill(`${name}-правка`);
    // Cover several regular status polls while unsaved input is being edited.
    await page.waitForTimeout(3400);
    assert.equal(await page.locator('#place-name').inputValue(), `${name}-правка`);
    await page.locator('#place-save').click();
    await page.waitForFunction(name => document.querySelector('#place-select').selectedOptions[0].textContent === name, `${name}-правка`);
    await page.locator('#place-go').click();
    await page.waitForFunction(() => document.querySelector('#places-status').textContent.includes('confirm'));
    assert.equal(await page.locator('#place-save').isEnabled(), true);
    const maps = await page.locator('#viz-map-select option').evaluateAll(options => options.map(o => o.value).filter(Boolean));
    if (maps.length > 1) {
      await page.locator('#viz-map-select').selectOption(maps.find(value => value !== map));
      await page.waitForFunction(() => !document.querySelector('#place-save').disabled);
      assert.equal(await page.locator(`#place-select option[value="${id}"]`).count(), 0);
      await page.locator('#viz-map-select').selectOption(map);
      await page.locator(`#place-select option[value="${id}"]`).waitFor({state: 'attached'});
      await page.locator('#place-select').selectOption(id);
    }
    for (const width of [1470, 825, 390]) {
      await page.setViewportSize({width, height: 1000});
      assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    }
    await page.setViewportSize({width: 1470, height: 1000});
    await page.locator('.named-places-card').scrollIntoViewIfNeeded();
    await page.screenshot({path: '/tmp/rover-named-points.png'});
    await page.locator('#place-delete').click();
    await page.waitForFunction(() => document.querySelector('#places-status').textContent === 'Точка удалена.');
    assert.deepEqual(errors, []);
    console.log('PASS: drag position+yaw, persistence, polling-safe editor, rename, map isolation, unprepared error, delete, 3 viewport widths');
  } finally {
    if (map) {
      const data = await (await page.request.get(`${url}/api/navigation/places?map=${encodeURIComponent(map)}`)).json();
      for (const point of data.places || []) {
        if (point.name.startsWith(name)) await page.request.post(`${url}/api/navigation/places`, {data: {
          action: 'delete', map, map_id: data.map_id, revision: data.revision++, id: point.id,
        }});
      }
    }
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
