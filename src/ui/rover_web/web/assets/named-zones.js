/* Map-bound semantic quadrilaterals. Coordinates stay in the map frame. */
const RoverNamedZones = (() => {
  let data = null;
  let mapKey = '';
  let corners = [];
  let busy = false;

  function selected() { return data?.zones?.find(zone => zone.id === $('#zone-select').value); }
  function reset() {
    $('#zone-select').value = '';
    $('#zone-name').value = '';
    $('#zone-aliases').value = '';
    $('#zone-can-drive').checked = false;
    corners = [];
  }
  function options(id = '') {
    const select = $('#zone-select');
    select.replaceChildren(new Option('Новая зона', ''));
    for (const zone of data?.zones || []) select.add(new Option(zone.name, zone.id));
    select.value = id;
  }
  async function refresh(clear = false) {
    const map = state.viz.selectedMap;
    if (clear) { data = null; options(); reset(); }
    if (!map) return;
    try {
      data = await api(`/api/navigation/places?map=${encodeURIComponent(map)}`);
      options($('#zone-select').value);
      $('#zones-status').textContent = `Сохранено зон: ${data.zones.length}.`;
    } catch (error) { $('#zones-status').textContent = error.message; }
    update(); renderVisualization();
  }
  function update() {
    const available = Boolean(data?.map === state.viz.selectedMap);
    $('#zone-pick').disabled = busy || !available;
    $('#zone-save').disabled = busy || !available || corners.length !== 4;
    $('#zone-delete').disabled = busy || !selected();
  }
  async function post(action, extra = {}) {
    busy = true; update();
    try {
      const result = await api('/api/navigation/places', {method: 'POST', body: JSON.stringify({
        action, map: state.viz.selectedMap, map_id: data.map_id, revision: data.revision, ...extra,
      })});
      data = result;
      if (action === 'save_zone') {
        const saved = data.zones.find(zone => zone.name === extra.zone.name);
        options(saved?.id || '');
        $('#zones-status').textContent = saved?.can_drive
          ? 'Проезжаемая зона сохранена.' : 'Непроезжаемая зона сохранена: перезапустите Nav2, чтобы применить её.';
      } else { reset(); options(); $('#zones-status').textContent = 'Зона удалена: перезапустите Nav2, чтобы применить изменение.'; }
    } catch (error) { $('#zones-status').textContent = error.message; showToast(error.message, 'error'); }
    finally { busy = false; update(); renderVisualization(); }
  }
  function addCorner(pose) {
    if (corners.length >= 4) corners = [];
    corners.push({x: pose.x, y: pose.y});
    $('#zones-status').textContent = `Выбрано углов: ${corners.length}/4.`;
    if (corners.length === 4) { setVisualizationPickMode(null); $('#zones-status').textContent = 'Четыре угла выбраны. Укажите название и сохраните зону.'; }
    renderVisualization(); update();
  }
  function bind() {
    $('#zone-refresh').addEventListener('click', () => refresh());
    $('#zone-pick').addEventListener('click', () => { corners = []; setVisualizationPickMode('zone'); update(); });
    $('#zone-select').addEventListener('change', () => {
      const zone = selected();
      if (!zone) reset();
      else { $('#zone-name').value = zone.name; $('#zone-aliases').value = zone.aliases.join(', '); $('#zone-can-drive').checked = zone.can_drive; corners = zone.corners.map(point => ({...point})); }
      update(); renderVisualization();
    });
    $('#zone-save').addEventListener('click', () => {
      const name = $('#zone-name').value.trim();
      if (!name || corners.length !== 4) return showToast('Укажите имя и четыре угла зоны.', 'error');
      const aliases = $('#zone-aliases').value.split(',').map(item => item.trim()).filter(Boolean);
      post('save_zone', {zone: {id: $('#zone-select').value, name, aliases, can_drive: $('#zone-can-drive').checked, corners}});
    });
    $('#zone-delete').addEventListener('click', () => { const zone = selected(); if (zone && confirm(`Удалить зону «${zone.name}»?`)) post('delete_zone', {id: zone.id}); });
  }
  function sync() {
    const map = currentVisualizationMap(); const key = `${state.viz.selectedMap}:${map?.revision || ''}`;
    if (key !== mapKey) { mapKey = key; refresh(true); }
    update();
  }
  function draw(ctx, toScreen) {
    if (data?.map !== state.viz.selectedMap) return;
    const zones = [...(data.zones || [])];
    if (corners.length) zones.push({name: 'Новая зона', can_drive: $('#zone-can-drive').checked, corners});
    for (const zone of zones) {
      if (zone.corners.length < 2) continue;
      ctx.save(); ctx.beginPath();
      zone.corners.forEach((corner, index) => { const point = toScreen(corner); index ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y); });
      if (zone.corners.length === 4) ctx.closePath();
      ctx.fillStyle = zone.can_drive ? 'rgba(22, 184, 243, 0.18)' : 'rgba(201, 54, 68, 0.25)';
      ctx.strokeStyle = zone.can_drive ? '#008fc7' : '#c93644'; ctx.lineWidth = 3;
      if (zone.corners.length === 4) ctx.fill(); ctx.stroke();
      const label = toScreen(zone.corners[0]); ctx.fillStyle = '#173245'; ctx.font = '700 13px Manrope, sans-serif'; ctx.fillText(zone.name, label.x + 8, label.y - 8); ctx.restore();
    }
  }
  return {bind, sync, draw, addCorner};
})();
