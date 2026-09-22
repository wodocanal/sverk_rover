(() => {
  'use strict';
  const keys = ['mqtt_host', 'mqtt_port', 'mqtt_topic_prefix', 'mqtt_username'];
  let loaded = false, busy = false, refreshing = false, dirty = false, snapshot = null, generation = 0;
  function lock() {
    $('#server-settings-fields').disabled = busy || !loaded;
    $('#server-settings-refresh').disabled = busy || refreshing;
    $('#server-settings-reconnect').disabled = !snapshot?.can_reconnect;
    $('#server-mqtt_password').disabled = $('#server-clear-password').checked;
  }
  function render(data, overwrite = false) {
    snapshot = data;
    if (!loaded || overwrite || !dirty) {
      for (const key of keys) $(`#server-${key}`).value = data.settings[key];
      $('#server-mqtt_password').value = '';
      $('#server-clear-password').checked = false;
      dirty = false;
    }
    loaded = true;
    $('#server-password-status').textContent = {
      saved: 'Пароль сохранён. Для замены введите новый; пустое поле оставит прежний.',
      empty: 'Пароль отключён в сохранённых настройках.',
      environment: 'Отдельный пароль не сохранён: используется переменная окружения MQTT-моста, если она задана.',
    }[data.password_source];
    $('#server-settings-file').textContent = `Файл: ${data.file}. Значения имеют приоритет над конфигом пакета.`;
    const connection = data.connection;
    const stateLabel = connection?.ready ? 'подключён' : connection?.state === 'connecting' ? 'подключается' : 'связь не подтверждена';
    $('#server-settings-connection').textContent = data.bridge_available
      ? `Сейчас: ${connection?.host || '—'}:${connection?.port || '—'} · ${stateLabel} · Robot ID: ${data.robot_id || '—'}`
      : 'MQTT-мост не запущен или требует обновления. Можно сохранить настройки для следующего запуска.';
    if (data.notice) $('#server-settings-error').textContent = data.notice;
    lock();
  }
  async function refresh(overwrite = false) {
    if (busy || refreshing) return;
    refreshing = true; lock();
    const requestGeneration = generation;
    try {
      const data = await api('/api/server/settings', {signal: AbortSignal.timeout(8000)});
      if (requestGeneration !== generation) return;
      const first = !loaded;
      render(data, overwrite);
      if (first || overwrite) {
        $('#server-settings-status').textContent = 'Настройки загружены. Сохраните изменения или сохраните и переподключите MQTT.';
        $('#server-settings-error').textContent = data.notice || '';
      }
    } catch (error) {
      if (requestGeneration === generation) $('#server-settings-error').textContent = error.message;
    } finally { refreshing = false; lock(); }
  }
  $('#server-settings-form').addEventListener('input', () => {
    dirty = true;
    if ($('#server-clear-password').checked) $('#server-mqtt_password').value = '';
    $('#server-settings-status').textContent = 'Есть несохранённые изменения. Действующее подключение не изменено.';
    lock();
  });
  $('#server-settings-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !loaded) return;
    const reconnect = event.submitter?.id === 'server-settings-reconnect';
    const settings = Object.fromEntries(keys.map(key => [key, key === 'mqtt_port'
      ? Number($(`#server-${key}`).value) : $(`#server-${key}`).value]));
    settings.mqtt_password = $('#server-mqtt_password').value;
    const payload = {settings, reconnect, clear_password: $('#server-clear-password').checked};
    generation++;
    busy = true; lock();
    $('#server-settings-error').textContent = '';
    try {
      const data = await api('/api/server/settings', {method:'POST', body:JSON.stringify(payload), signal:AbortSignal.timeout(15000)});
      render(data, true);
      $('#server-settings-status').textContent = data.reconnect.started
        ? 'Сохранено. Переподключение начато; ожидайте подтверждения связи с сервером.'
        : 'Сохранено. Параметры применятся при следующем запуске моста или переподключении.';
      if (reconnect && !data.reconnect.started) $('#server-settings-error').textContent = data.reconnect.message;
    } catch (error) {
      $('#server-settings-error').textContent = `Не удалось подтвердить сохранение: ${error.message}. Поля не сброшены; проверьте состояние перед повтором.`;
    } finally { busy = false; lock(); }
  });
  $('#server-settings-refresh').addEventListener('click', () => {
    if (!dirty || confirm('Перечитать настройки и заменить несохранённые изменения?')) refresh(true);
  });
  new MutationObserver(() => { if (state.page === 'settings') refresh(); })
    .observe($('#page-settings'), {attributes:true, attributeFilter:['class']});
  setInterval(() => { if (state.page === 'settings' && !document.hidden) refresh(); }, 5000);
  if (state.page === 'settings') refresh();
})();
