/* Saved map destinations; editor values are never replaced by status polling. */
const RoverNamedPlaces = (() => {
  let data = null;
  let mapKey = '';
  let requestId = 0;
  let busy = false;

  function resetEditor() {
    $('#place-select').value = '';
    $('#place-name').value = '';
    $('#nav-place-x').value = '';
    $('#nav-place-y').value = '';
    $('#nav-place-yaw').value = '0';
  }

  function options(selected = '') {
    const select = $('#place-select');
    select.replaceChildren(new Option('Новая точка', ''));
    for (const point of data?.places || []) select.add(new Option(point.name, point.id));
    select.value = selected;
  }

  async function refresh(reset = false) {
    const map = state.viz.selectedMap;
    const id = ++requestId;
    if (reset) { data = null; options(); resetEditor(); }
    if (!map) { data = null; options(); updateControls(); return; }
    try {
      const payload = await api(`/api/navigation/places?map=${encodeURIComponent(map)}`);
      if (id !== requestId || map !== state.viz.selectedMap) return;
      const selected = $('#place-select').value;
      data = payload;
      options(selected);
      $('#places-status').textContent = `Сохранено точек: ${data.places.length}. Выберите точку или создайте новую.`;
    } catch (error) {
      if (id !== requestId) return;
      data = null;
      $('#places-status').textContent = error.message;
    }
    updateControls();
    renderVisualization();
  }

  function updateControls() {
    const runtime = state.viz.navigation;
    const available = Boolean(data && data.map === state.viz.selectedMap);
    const selected = available && data.places.some(p => p.id === $('#place-select').value);
    $('#place-save').disabled = busy || !available;
    $('#place-delete').disabled = busy || !selected;
    $('#place-go').disabled = busy || !selected || (runtime?.running && runtime.mode !== 'navigation')
      || ['queued', 'sending', 'active', 'canceling'].includes(runtime?.goal_state);
    $('#place-pick').disabled = busy || !available;
    $('#place-refresh').disabled = busy;
    $('#places-prepare').disabled = busy || !state.viz.selectedMap || !readNavigationPose('nav-initial')
      || Boolean(runtime?.running || runtime?.external?.navigation || runtime?.external?.slam);
  }

  function sync() {
    const map = currentVisualizationMap();
    const key = `${state.viz.selectedMap}:${map?.revision || ''}`;
    if (key !== mapKey) { mapKey = key; refresh(true); }
    updateControls();
  }

  async function post(action, extra = {}) {
    if (busy) return;
    const map = state.viz.selectedMap;
    busy = true;
    updateControls();
    try {
      const result = await api('/api/navigation/places', { method: 'POST', body: JSON.stringify({
        action, map, map_id: data?.map_id, revision: data?.revision, ...extra,
      }) });
      if (map !== state.viz.selectedMap) return;
      if (action === 'save' || action === 'delete') {
        data = result;
        const selected = action === 'save' ? data.places.find(p => p.name === extra.point.name)?.id : '';
        options(selected);
        if (action === 'delete') resetEditor();
        $('#places-status').textContent = action === 'save' ? 'Точка сохранена и доступна агенту.' : 'Точка удалена.';
      } else if (action === 'prepare') {
        $('#places-status').textContent = 'Старт подтверждён на 5 минут. Не двигайте ровер до команды агенту. Nav2 ещё не запущен.';
      } else if (action === 'navigate') {
        renderNavigationRuntime(result.navigation);
        $('#places-status').textContent = `Цель «${result.name}» отправлена. Результат смотрите в SLAM / Nav2.`;
      }
      renderVisualization();
    } catch (error) {
      $('#places-status').textContent = error.message;
      showToast(error.message, 'error');
    } finally { busy = false; updateControls(); }
  }

  function bind() {
    $('#place-select').addEventListener('change', () => {
      const point = data?.places.find(p => p.id === $('#place-select').value);
      if (point) { $('#place-name').value = point.name; writeNavigationPose('nav-place', point); }
      else resetEditor();
      updateControls(); renderVisualization();
    });
    $('#place-pick').addEventListener('click', () => setVisualizationPickMode('place'));
    $('#place-refresh').addEventListener('click', () => refresh());
    $('#place-save').addEventListener('click', () => {
      const pose = readNavigationPose('nav-place');
      const name = $('#place-name').value.normalize('NFC').trim();
      if (!pose || !name) { showToast('Укажите название, координаты и направление точки.', 'error'); return; }
      post('save', {point: {id: $('#place-select').value, name, ...pose}});
    });
    $('#place-delete').addEventListener('click', () => {
      const point = data?.places.find(p => p.id === $('#place-select').value);
      if (point && window.confirm(`Удалить точку «${point.name}»?`)) post('delete', {id: point.id});
    });
    $('#place-go').addEventListener('click', () => {
      const point = data?.places.find(p => p.id === $('#place-select').value);
      if (point) post('navigate', {name: point.name});
    });
    $('#places-prepare').addEventListener('click', () => post('prepare', {initial_pose: readNavigationPose('nav-initial')}));
    ['nav-place-x', 'nav-place-y', 'nav-place-yaw'].forEach(id => $(`#${id}`).addEventListener('input', renderVisualization));
  }

  function draw(ctx, toScreen) {
    if (data?.map !== state.viz.selectedMap || state.viz.navigation?.mode === 'mapping' && state.viz.navigation?.running) return;
    ctx.save();
    ctx.font = '600 13px Manrope, sans-serif';
    for (const point of data?.places || []) {
      const screen = toScreen(point);
      drawRoverArrow(ctx, screen, point.yaw, '#0099cf', 20);
      ctx.lineWidth = 4;
      ctx.strokeStyle = '#ffffff';
      ctx.fillStyle = '#075f89';
      ctx.strokeText(point.name, screen.x + 16, screen.y - 10);
      ctx.fillText(point.name, screen.x + 16, screen.y - 10);
    }
    const preview = state.viz.posePreview;
    const pose = preview?.mode === 'place' ? preview.pose : readNavigationPose('nav-place');
    if (pose) drawRoverArrow(ctx, toScreen(pose), pose.yaw, '#0099cf', 28);
    ctx.restore();
  }
  return {bind, sync, draw};
})();
