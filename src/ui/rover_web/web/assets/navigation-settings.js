(() => {
  'use strict';
  const keys = ['resolution', 'allow_reverse', 'allow_lateral', 'forward_speed', 'reverse_speed',
    'lateral_speed', 'angular_speed', 'linear_acceleration', 'linear_deceleration',
    'angular_acceleration', 'angular_deceleration', 'position_tolerance', 'yaw_tolerance'];
  const flags = new Set(['allow_reverse', 'allow_lateral']);
  let loaded = false, busy = false, dirty = false, snapshot = null;
  const factor = key => key === 'yaw_tolerance' ? 180 / Math.PI
    : ['resolution', 'position_tolerance'].includes(key) ? 100 : 1;
  function lock() {
    const runtime = state.status?.navigation;
    const locked = snapshot?.locked || runtime?.running || runtime?.external?.slam || runtime?.external?.navigation;
    $('#navigation-settings-fields').disabled = busy || !loaded || Boolean(locked);
    $('#navigation-settings-refresh').disabled = busy;
    $('#nav-setting-allow_lateral').disabled = snapshot?.drive_type === 'differential';
    $('#nav-setting-reverse_speed').disabled = !$('#nav-setting-allow_reverse').checked;
    $('#nav-setting-lateral_speed').disabled = !$('#nav-setting-allow_lateral').checked || snapshot?.drive_type === 'differential';
    if (locked) $('#navigation-settings-status').textContent = 'Остановите SLAM и Nav2, чтобы изменить настройки.';
  }
  async function refresh(overwrite = false) {
    if (busy) return;
    busy = true; lock();
    try {
      const data = await api('/api/navigation/settings', {signal: AbortSignal.timeout(8000)});
      snapshot = data;
      if (!loaded || overwrite || !dirty) {
        for (const key of keys) {
          const input = $(`#nav-setting-${key}`);
          if (flags.has(key)) input.checked = data.settings[key];
          else input.value = String(Number((data.settings[key] * factor(key)).toFixed(3)));
        }
        dirty = false;
      }
      loaded = true;
      $('#nav-setting-drive-note').textContent = data.drive_type === 'differential'
        ? 'Установлены обычные колёса: движение вбок всегда запрещено, независимо от сохранённого флага.'
        : 'Mecanum: боковое движение можно разрешить или запретить.';
      $('#navigation-settings-status').textContent = dirty ? 'Есть несохранённые изменения.' : `Настройки: ${data.file}. Применяются при следующем запуске.`;
      $('#navigation-settings-error').textContent = '';
    } catch (error) { $('#navigation-settings-error').textContent = error.message; }
    finally { busy = false; lock(); }
  }
  $('#navigation-settings-form').addEventListener('input', () => {
    dirty = true;
    $('#navigation-settings-status').textContent = 'Есть несохранённые изменения.';
    lock();
  });
  $('#navigation-settings-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !loaded || $('#navigation-settings-fields').disabled) return;
    const values = {};
    for (const key of keys) {
      const input = $(`#nav-setting-${key}`);
      values[key] = flags.has(key) ? input.checked : Number(input.value) / factor(key);
    }
    busy = true; lock();
    try {
      snapshot = await api('/api/navigation/settings', {method:'POST', body:JSON.stringify(values), signal:AbortSignal.timeout(8000)});
      dirty = false;
      $('#navigation-settings-error').textContent = '';
      $('#navigation-settings-status').textContent = 'Сохранено. Новые параметры применятся при следующем запуске SLAM / Nav2.';
    } catch (error) { $('#navigation-settings-error').textContent = error.message; }
    finally { busy = false; lock(); }
  });
  $('#navigation-settings-refresh').addEventListener('click', () => {
    if (!dirty || confirm('Заменить несохранённые изменения сохранёнными настройками?')) refresh(true);
  });
  new MutationObserver(() => { if (state.page === 'settings') refresh(); })
    .observe($('#page-settings'), {attributes:true, attributeFilter:['class']});
  setInterval(() => { if (state.page === 'settings' && !document.hidden) refresh(); }, 5000);
  if (state.page === 'settings') refresh();
})();
