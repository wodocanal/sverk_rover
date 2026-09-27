/* Manual clockwise perimeter test for a saved no-drive zone. */
const RoverZoneInspection = (() => {
  let places = null;
  let route = [];
  let active = false;

  function select() { return $('#zone-inspection-select'); }
  function selectedZone() { return places?.zones?.find(zone => zone.id === select().value); }
  function renderOptions() {
    const current = select().value;
    select().replaceChildren(new Option('Выберите непроезжаемую зону', ''));
    for (const zone of places?.zones || []) if (!zone.can_drive) select().add(new Option(zone.name, zone.id));
    select().value = current;
  }
  async function refresh() {
    if (!state.viz.selectedMap) return;
    try {
      places = await api(`/api/navigation/places?map=${encodeURIComponent(state.viz.selectedMap)}`);
      renderOptions();
    } catch (error) { $('#zone-inspection-status').textContent = error.message; }
  }
  async function poll() {
    try {
      const inspection = await api('/api/navigation/zone_inspection');
      route = inspection.route || [];
      active = ['starting', 'active', 'approaching'].includes(inspection.state);
      $('#zone-inspection-start').disabled = active || !selectedZone();
      $('#zone-inspection-stop').disabled = !active;
      const position = Number.isInteger(inspection.current_index) ? ` Точка ${inspection.current_index + 1}/${route.length}.` : '';
      $('#zone-inspection-status').textContent = `${inspection.message || 'Ожидание.'}${position}`;
      $('#zone-inspection-qr').textContent = inspection.qr_codes?.length ? `QR: ${inspection.qr_codes.join(', ')}` : '';
      renderVisualization();
    } catch (_) { /* The static UI can be opened before its backend has been rebuilt. */ }
  }
  async function start() {
    if (!selectedZone()) return showToast('Выберите непроезжаемую зону.', 'error');
    try {
      const response = await api('/api/navigation/zone_inspection/start', {method: 'POST', body: JSON.stringify({
        map: state.viz.selectedMap, zone_id: selectedZone().id,
        clearance_m: Number($('#zone-inspection-clearance').value), step_m: Number($('#zone-inspection-step').value),
      })});
      route = response.inspection.route || []; active = true;
      showToast('Тест объезда зоны запущен.'); await poll();
    } catch (error) { showToast(error.message, 'error'); }
  }
  async function stop() {
    try { await api('/api/navigation/zone_inspection/stop', {method: 'POST', body: '{}'}); await poll(); }
    catch (error) { showToast(error.message, 'error'); }
  }
  function bind() {
    $('#zone-inspection-start').addEventListener('click', start);
    $('#zone-inspection-stop').addEventListener('click', stop);
    select().addEventListener('change', poll);
    setInterval(poll, 1000);
  }
  function sync() { refresh(); }
  function draw(ctx, toScreen) {
    if (route.length < 2) return;
    ctx.save(); ctx.strokeStyle = '#704cc9'; ctx.lineWidth = 3; ctx.setLineDash([7, 6]); ctx.beginPath();
    route.forEach((point, index) => { const screen = toScreen(point); index ? ctx.lineTo(screen.x, screen.y) : ctx.moveTo(screen.x, screen.y); });
    ctx.closePath(); ctx.stroke(); ctx.setLineDash([]);
    route.forEach(point => { const screen = toScreen(point); ctx.fillStyle = '#704cc9'; ctx.beginPath(); ctx.arc(screen.x, screen.y, 3, 0, Math.PI * 2); ctx.fill(); }); ctx.restore();
  }
  return {bind, sync, draw};
})();
