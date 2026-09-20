(() => {
  'use strict';
  const wheels = ['Переднее левое', 'Переднее правое', 'Заднее левое', 'Заднее правое'];
  const roles = { motor_controller: 'Quad-MD', imu: 'IMU', lidar: 'Лидар' };
  let latest = {}, busy = false, polling = false;
  const visible = () => ['motor-calibration', 'device-manager'].includes(state.page);
  const fillList = (id, items) => {
    const list = document.getElementById(id);
    list.replaceChildren();
    for (const text of items.length ? items : ['Нет данных']) {
      const item = document.createElement('li');
      item.textContent = text;
      list.append(item);
    }
  };
  function render() {
    const m = latest.motors || {};
    $('#motor-status').textContent = !m.available ? (m.message || 'Драйвер недоступен')
      : `${m.active ? 'Калибровка активна' : 'Обычный режим'} · ${m.message || ''}${m.pulsing ? ` · ${Number(m.seconds_remaining).toFixed(1)} с` : ''}`;
    $('#motor-step').textContent = m.complete ? 'Все четыре канала проверены' : `Канал ${Number(m.channel || 0) + 1} из 4`;
    $('#motor-file').textContent = m.file || '';
    $('#motor-begin').disabled = busy || !m.available || m.active || !$('#motor-raised').checked;
    $('#motor-stop').disabled = busy || !m.available || !m.active;
    $('#motor-end').disabled = busy || !m.active;
    $('#motor-pulse').disabled = busy || !m.active || m.pulsing || m.complete;
    $('#motor-record').disabled = busy || !m.can_record || !$('#motor-wheel').value || !$('#motor-direction').value;
    $('#motor-save').disabled = busy || !m.active || !m.complete || m.saved;
    $('#motor-restart').disabled = busy || !m.saved;
    const assigned = new Set((m.observations || []).map(o => String(o.wheel)));
    for (const option of $('#motor-wheel').options) option.disabled = assigned.has(option.value);
    fillList('motor-observations', (m.observations || []).map((o, i) =>
      `Канал ${i+1}: ${wheels[o.wheel]}, ${o.direction === 1 ? 'вперед' : 'назад'}; энкодер ${o.encoder_channel+1}`));

    const d = latest.devices || {};
    const phases = { idle: 'Мастер не запущен', waiting: 'Подключите следующий компонент',
      probing: 'Проверка протокола, подождите…', verified: 'Устройство проверено, подтвердите выбор',
      error: 'Проверка не пройдена: можно повторить', complete: 'Все устройства приняты, можно сохранить',
      saved: 'Конфигурация сохранена', canceling: 'Отмена: ожидание завершения текущей проверки' };
    $('#devices-status').textContent = phases[d.phase] || 'Ожидание…';
    $('#devices-verification').textContent = d.error || d.pending?.entry?.setup_verification || '';
    $('#devices-config').textContent = d.config_path || '';
    fillList('devices-inventory', (d.inventory || []).map(p => `${p.device} → ${p.resolved}${p.candidate ? ' (новый)' : ''}`));
    for (const key of ['accepted', 'saved']) fillList(`devices-${key}`,
      Object.entries(d[key] || {}).map(([role, entry]) => `${roles[role] || role}: ${entry.device} @ ${entry.baudrate}`));
    const options = (d.inventory || []).filter(p => p.candidate);
    const select = $('#devices-port');
    const selected = select.value;
    const signature = JSON.stringify(options.map(p => [p.device, p.resolved]));
    if (select.dataset.signature !== signature) {
      select.replaceChildren();
      if (!options.length) select.add(new Option('Новых устройств нет', ''));
      for (const port of options) select.add(new Option(`${port.device} → ${port.resolved}`, port.device));
      if (options.some(p => p.device === selected)) select.value = selected;
      select.dataset.signature = signature;
    }
    for (const option of $('#devices-role').options) option.disabled = Boolean(d.accepted?.[option.value]);
    if (d.accepted?.[$('#devices-role').value]) {
      $('#devices-role').value = [...$('#devices-role').options].find(o => !o.disabled)?.value || '';
    }
    $('#devices-begin').disabled = busy || d.busy || !$('#devices-confirmed').checked;
    $('#devices-cancel').disabled = busy || !d.phase || d.phase === 'idle';
    $('#devices-probe').disabled = busy || d.busy || !['waiting', 'error', 'verified'].includes(d.phase)
      || !select.value || !$('#devices-role').value;
    $('#devices-accept').disabled = busy || d.busy || d.phase !== 'verified';
    $('#devices-save').disabled = busy || d.busy || d.phase !== 'complete';
    $('#devices-hardware-start').disabled = busy || d.busy || !['idle', 'saved'].includes(d.phase);
    $('#devices-hardware-stop').disabled = busy || d.busy;
    $('#devices-role').disabled = busy || d.busy;
    $('#devices-port').disabled = busy || d.busy;
  }
  async function refresh() {
    if (polling || busy) return;
    polling = true;
    try {
      latest = await api('/api/maintenance');
      render();
    } catch (error) {
      $(`#${state.page === 'motor-calibration' ? 'motor' : 'devices'}-error`).textContent = error.message;
    } finally { polling = false; }
  }
  async function request(kind, payload) {
    if (busy) return;
    busy = true;
    const errorId = state.page === 'motor-calibration' ? '#motor-error' : '#devices-error';
    $(errorId).textContent = '';
    render();
    try {
      const result = await api(`/api/maintenance/${kind}`, { method: 'POST', body: JSON.stringify(payload) });
      if (kind === 'motors') latest.motors = result;
      if (kind === 'devices') latest.devices = result;
      if (payload.command === 'record' || payload.command === 'begin') {
        $('#motor-wheel').value = '';
        $('#motor-direction').value = '';
      }
      if (kind === 'hardware' || payload.command === 'save') showToast('Выполнено');
    } catch (error) {
      $(errorId).textContent = error.message;
    } finally {
      busy = false;
      render();
      await refresh();
    }
  }
  for (const command of ['begin', 'pulse', 'record', 'save', 'stop', 'end']) {
    $(`#motor-${command}`).addEventListener('click', () => request('motors', {
      command, wheels_raised: $('#motor-raised').checked,
      wheel: Number($('#motor-wheel').value), direction: Number($('#motor-direction').value),
    }));
  }
  for (const command of ['begin', 'probe', 'accept', 'save', 'cancel']) {
    $(`#devices-${command}`).addEventListener('click', () => request('devices', {
      command, confirmed: $('#devices-confirmed').checked,
      role: $('#devices-role').value, device: $('#devices-port').value,
    }));
  }
  for (const [id, action] of [['motor-restart', 'restart'], ['devices-hardware-stop', 'stop'], ['devices-hardware-start', 'start']]) {
    $(`#${id}`).addEventListener('click', () => {
      if (window.confirm(`${action === 'stop' ? 'Остановить' : action === 'restart' ? 'Перезапустить' : 'Запустить'} rover-bringup? Убедитесь, что ровер неподвижен и зона безопасна. Внешние команды движения должны быть отключены.`)) {
        request('hardware', { action, confirmed: true });
      }
    });
  }
  for (const id of ['motor-raised', 'motor-wheel', 'motor-direction', 'devices-confirmed', 'devices-role', 'devices-port']) {
    $(`#${id}`).addEventListener('change', render);
  }
  $('#devices-refresh').addEventListener('click', refresh);
  setInterval(() => { if (visible() && !document.hidden) refresh(); }, 1000);
  if (visible()) refresh();
})();
