/* Fixed 5x5 field, each competition cell is split into a 2x2 selection grid. */
const RoverNamedZones = (() => {
  const ROWS = 10;
  const COLUMNS = 10;
  let data = null;
  let mapKey = '';
  let cells = [];
  let draftGrid = null;
  let busy = false;

  function selected() { return data?.zones?.find(zone => zone.id === $('#zone-select').value); }
  function cellKey(cell) { return `${cell.row}:${cell.column}`; }
  function cellSet() { return new Set(cells.map(cellKey)); }
  function reset() {
    $('#zone-select').value = '';
    $('#zone-name').value = '';
    $('#zone-aliases').value = '';
    $('#zone-can-drive').checked = false;
    cells = [];
  }
  function options(id = '') {
    const select = $('#zone-select');
    select.replaceChildren(new Option('Новая зона', ''));
    for (const zone of data?.zones || []) select.add(new Option(zone.name, zone.id));
    select.value = id;
  }
  function activeGrid() { return draftGrid || data?.grid || null; }
  function interpolation(grid, row, column) {
    const [topLeft, topRight, bottomRight, bottomLeft] = grid.corners;
    const u = column / COLUMNS;
    const v = row / ROWS;
    return {
      x: topLeft.x * (1 - u) * (1 - v) + topRight.x * u * (1 - v)
        + bottomRight.x * u * v + bottomLeft.x * (1 - u) * v,
      y: topLeft.y * (1 - u) * (1 - v) + topRight.y * u * (1 - v)
        + bottomRight.y * u * v + bottomLeft.y * (1 - u) * v,
    };
  }
  function cellCorners(grid, cell) {
    return [
      interpolation(grid, cell.row, cell.column),
      interpolation(grid, cell.row, cell.column + 1),
      interpolation(grid, cell.row + 1, cell.column + 1),
      interpolation(grid, cell.row + 1, cell.column),
    ];
  }
  function pointInCell(point, corners) {
    let sign = 0;
    for (let index = 0; index < 4; index += 1) {
      const first = corners[index];
      const second = corners[(index + 1) % 4];
      const cross = (second.x - first.x) * (point.y - first.y)
        - (second.y - first.y) * (point.x - first.x);
      if (Math.abs(cross) < 1e-7) continue;
      const next = Math.sign(cross);
      if (sign && next !== sign) return false;
      sign = next;
    }
    return true;
  }
  function findCell(point) {
    const grid = data?.grid;
    if (!grid) return null;
    for (let row = 0; row < ROWS; row += 1) {
      for (let column = 0; column < COLUMNS; column += 1) {
        const cell = {row, column};
        if (pointInCell(point, cellCorners(grid, cell))) return cell;
      }
    }
    return null;
  }
  async function refresh(clear = false) {
    const map = state.viz.selectedMap;
    if (clear) { data = null; options(); reset(); draftGrid = null; }
    if (!map) return;
    try {
      data = await api(`/api/navigation/places?map=${encodeURIComponent(map)}`);
      options($('#zone-select').value);
      const gridText = data.grid ? 'Сетка 5×5 готова.' : 'Сначала натяните сетку поля.';
      $('#zones-status').textContent = `${gridText} Сохранено зон: ${data.zones.length}.`;
    } catch (error) { $('#zones-status').textContent = error.message; }
    update(); renderVisualization();
  }
  function update() {
    const available = Boolean(data?.map === state.viz.selectedMap);
    const legacy = selected()?.cells == null && Boolean(selected()?.corners);
    $('#grid-pick').disabled = busy || !available;
    $('#grid-save').disabled = busy || !available || !draftGrid;
    const gridZoneExists = data?.zones?.some(zone => Array.isArray(zone.cells));
    $('#grid-clear').disabled = busy || !available || !data?.grid || gridZoneExists;
    $('#zone-pick').disabled = busy || !available || !data?.grid;
    $('#zone-save').disabled = busy || !available || !data?.grid || !cells.length || legacy;
    $('#zone-delete').disabled = busy || !selected();
  }
  async function post(action, extra = {}) {
    busy = true; update();
    try {
      const result = await api('/api/navigation/places', {method: 'POST', body: JSON.stringify({
        action, map: state.viz.selectedMap, map_id: data.map_id, revision: data.revision, ...extra,
      })});
      data = result;
      draftGrid = null;
      if (action === 'save_grid') {
        $('#zones-status').textContent = 'Сетка 5×5 сохранена. Выбирайте малые клетки для зоны.';
      } else if (action === 'clear_grid') {
        reset(); options(); $('#zones-status').textContent = 'Сетка удалена.';
      } else if (action === 'save_zone') {
        const saved = data.zones.find(zone => zone.name === extra.zone.name);
        options(saved?.id || '');
        cells = (saved?.cells || []).map(cell => ({...cell}));
        $('#zones-status').textContent = saved?.can_drive
          ? 'Проезжаемая зона сохранена.'
          : 'Непроезжаемая зона сохранена: перезапустите Nav2, чтобы применить её.';
      } else {
        reset(); options(); $('#zones-status').textContent = 'Зона удалена: перезапустите Nav2, чтобы применить изменение.';
      }
    } catch (error) { $('#zones-status').textContent = error.message; showToast(error.message, 'error'); }
    finally { busy = false; update(); renderVisualization(); }
  }
  function addGridCorner(pose) {
    const oldCorners = draftGrid?.corners || [];
    if (oldCorners.length >= 4) draftGrid = null;
    const corners = draftGrid?.corners || [];
    corners.push({x: pose.x, y: pose.y});
    draftGrid = {corners};
    $('#zones-status').textContent = `Углы поля: ${corners.length}/4. Порядок: левый верхний, правый верхний, правый нижний, левый нижний.`;
    if (corners.length === 4) {
      setVisualizationPickMode(null);
      $('#zones-status').textContent = 'Сетка построена предварительно. Проверьте её и сохраните.';
    }
    update(); renderVisualization();
  }
  function toggleCell(pose) {
    const cell = findCell(pose);
    if (!cell) {
      $('#zones-status').textContent = 'Нажмите внутри натянутой сетки поля.';
      return;
    }
    const key = cellKey(cell);
    const chosen = cellSet();
    cells = chosen.has(key)
      ? cells.filter(item => cellKey(item) !== key)
      : [...cells, cell].sort((left, right) => left.row - right.row || left.column - right.column);
    $('#zones-status').textContent = `Выбрано малых клеток: ${cells.length}. Нажмите ещё раз, чтобы снять выбор.`;
    update(); renderVisualization();
  }
  function bind() {
    $('#zone-refresh').addEventListener('click', () => refresh());
    $('#grid-pick').addEventListener('click', () => {
      draftGrid = null;
      setVisualizationPickMode('grid');
      $('#zones-status').textContent = 'Укажите 4 угла поля: левый верхний, правый верхний, правый нижний, левый нижний.';
      update();
    });
    $('#grid-save').addEventListener('click', () => post('save_grid', {grid: draftGrid}));
    $('#grid-clear').addEventListener('click', () => {
      if (confirm('Удалить сетку поля? Сначала нужно удалить зоны, созданные по сетке.')) post('clear_grid');
    });
    $('#zone-pick').addEventListener('click', () => {
      setVisualizationPickMode('zone');
      $('#zones-status').textContent = 'Нажимайте малые клетки сетки, чтобы добавить или убрать их из зоны.';
    });
    $('#zone-select').addEventListener('change', () => {
      const zone = selected();
      if (!zone) {
        reset();
      } else {
        $('#zone-name').value = zone.name;
        $('#zone-aliases').value = zone.aliases.join(', ');
        $('#zone-can-drive').checked = zone.can_drive;
        cells = (zone.cells || []).map(cell => ({...cell}));
        if (!zone.cells) $('#zones-status').textContent = 'Это старая зона с углами. Она сохранена, но для редактирования создайте новую по сетке.';
      }
      update(); renderVisualization();
    });
    $('#zone-save').addEventListener('click', () => {
      const name = $('#zone-name').value.trim();
      if (!name || !cells.length) return showToast('Укажите имя и хотя бы одну малую клетку зоны.', 'error');
      const aliases = $('#zone-aliases').value.split(',').map(item => item.trim()).filter(Boolean);
      post('save_zone', {zone: {id: $('#zone-select').value, name, aliases,
        can_drive: $('#zone-can-drive').checked, cells}});
    });
    $('#zone-delete').addEventListener('click', () => {
      const zone = selected();
      if (zone && confirm(`Удалить зону «${zone.name}»?`)) post('delete_zone', {id: zone.id});
    });
  }
  function sync() {
    const map = currentVisualizationMap();
    const key = `${state.viz.selectedMap}:${map?.revision || ''}`;
    if (key !== mapKey) { mapKey = key; refresh(true); }
    update();
  }
  function polygon(ctx, points, toScreen) {
    points.forEach((point, index) => {
      const screen = toScreen(point);
      index ? ctx.lineTo(screen.x, screen.y) : ctx.moveTo(screen.x, screen.y);
    });
    ctx.closePath();
  }
  function drawGrid(ctx, grid, toScreen) {
    ctx.save();
    for (let row = 0; row <= ROWS; row += 1) {
      ctx.beginPath();
      for (let column = 0; column <= COLUMNS; column += 1) {
        const point = toScreen(interpolation(grid, row, column));
        column ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y);
      }
      ctx.strokeStyle = row % 2 ? 'rgba(0, 143, 199, 0.38)' : 'rgba(0, 95, 145, 0.78)';
      ctx.lineWidth = row % 2 ? 1 : 2.5;
      ctx.stroke();
    }
    for (let column = 0; column <= COLUMNS; column += 1) {
      ctx.beginPath();
      for (let row = 0; row <= ROWS; row += 1) {
        const point = toScreen(interpolation(grid, row, column));
        row ? ctx.lineTo(point.x, point.y) : ctx.moveTo(point.x, point.y);
      }
      ctx.strokeStyle = column % 2 ? 'rgba(0, 143, 199, 0.38)' : 'rgba(0, 95, 145, 0.78)';
      ctx.lineWidth = column % 2 ? 1 : 2.5;
      ctx.stroke();
    }
    ctx.restore();
  }
  function drawCells(ctx, grid, zone, label, toScreen) {
    const color = zone.can_drive ? '#008fc7' : '#c93644';
    for (const cell of zone.cells || []) {
      ctx.beginPath(); polygon(ctx, cellCorners(grid, cell), toScreen);
      ctx.fillStyle = zone.can_drive ? 'rgba(22, 184, 243, 0.18)' : 'rgba(201, 54, 68, 0.30)';
      ctx.fill(); ctx.strokeStyle = color; ctx.lineWidth = 1.5; ctx.stroke();
    }
    if (label && zone.cells?.length) {
      const first = toScreen(interpolation(grid, zone.cells[0].row + 0.5, zone.cells[0].column + 0.5));
      ctx.fillStyle = '#173245'; ctx.font = '700 13px Manrope, sans-serif'; ctx.fillText(zone.name, first.x + 7, first.y - 7);
    }
  }
  function drawLegacyZone(ctx, zone, toScreen) {
    if (!zone.corners?.length) return;
    ctx.beginPath(); polygon(ctx, zone.corners, toScreen);
    ctx.fillStyle = zone.can_drive ? 'rgba(22, 184, 243, 0.12)' : 'rgba(201, 54, 68, 0.20)';
    ctx.strokeStyle = '#6f7780'; ctx.setLineDash([7, 5]); ctx.lineWidth = 2;
    ctx.fill(); ctx.stroke(); ctx.setLineDash([]);
  }
  function draw(ctx, toScreen) {
    if (data?.map !== state.viz.selectedMap) return;
    const grid = activeGrid();
    if (grid) drawGrid(ctx, grid, toScreen);
    for (const zone of data.zones || []) {
      ctx.save();
      if (zone.cells && grid) drawCells(ctx, grid, zone, true, toScreen);
      else drawLegacyZone(ctx, zone, toScreen);
      ctx.restore();
    }
    if (grid && cells.length) {
      ctx.save();
      drawCells(ctx, grid, {name: 'Новая зона', can_drive: $('#zone-can-drive').checked, cells}, true, toScreen);
      ctx.restore();
    }
  }
  return {bind, sync, draw, addGridCorner, toggleCell};
})();
