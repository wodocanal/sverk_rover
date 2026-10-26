(() => {
  'use strict';
  let loaded = false;
  let busy = false;

  function lock() {
    $('#agent-settings-fields').disabled = busy || !loaded;
    $('#agent-settings-refresh').disabled = busy;
    $('#agent-provider-key').disabled = $('#agent-provider-clear-key').checked;
  }

  function currentSettings() {
    return {
      base_url: $('#agent-provider-url').value.trim(),
      model: $('#agent-provider-model').value.trim(),
      api_key: $('#agent-provider-key').value,
    };
  }

  function render(data) {
    $('#agent-provider-url').value = data.settings?.base_url || '';
    $('#agent-provider-model').value = data.settings?.model || '';
    $('#agent-provider-key').value = '';
    $('#agent-provider-clear-key').checked = false;
    $('#agent-provider-key-status').textContent = data.api_key_configured
      ? `API-ключ настроен (${data.api_key_source === 'saved' ? 'сохранённый файл' : 'окружение'}). Пустое поле оставит его без изменений.`
      : 'API-ключ не настроен.';
    $('#agent-settings-file').textContent = `Файл: ${data.file}`;
    loaded = true;
    lock();
  }

  async function refresh() {
    if (busy) return;
    busy = true; lock();
    $('#agent-settings-error').textContent = '';
    try {
      const data = await api('/api/agent/settings', {signal: AbortSignal.timeout(8000)});
      render(data);
      $('#agent-settings-status').textContent = data.notice;
    } catch (error) {
      $('#agent-settings-error').textContent = error.message;
    } finally { busy = false; lock(); }
  }

  async function providerAction(path) {
    if (busy || !loaded) return;
    busy = true; lock();
    $('#agent-settings-error').textContent = '';
    $('#agent-settings-status').textContent = path.endsWith('/models')
      ? 'Получаю список моделей…' : 'Проверяю подключение и ответ выбранной модели…';
    try {
      const data = await api(path, {
        method: 'POST', body: JSON.stringify({settings: currentSettings()}),
        signal: AbortSignal.timeout(path.endsWith('/models') ? 15000 : 35000),
      });
      if (path.endsWith('/models')) {
        const options = data.models.map(id => Object.assign(document.createElement('option'), {value:id}));
        $('#agent-provider-models').replaceChildren(...options);
        $('#agent-settings-status').textContent = `Получено моделей: ${data.count}. Выберите название в поле модели.`;
      } else {
        $('#agent-settings-status').textContent = `Подключение работает. Модель ${data.model} ответила: ${data.reply || 'OK'}`;
      }
    } catch (error) {
      $('#agent-settings-error').textContent = error.message;
      $('#agent-settings-status').textContent = 'Проверка не выполнена.';
    } finally { busy = false; lock(); }
  }

  $('#agent-settings-form').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !loaded) return;
    busy = true; lock();
    $('#agent-settings-error').textContent = '';
    try {
      const data = await api('/api/agent/settings', {
        method: 'POST', body: JSON.stringify({
          settings: currentSettings(), clear_api_key: $('#agent-provider-clear-key').checked,
        }), signal: AbortSignal.timeout(10000),
      });
      render(data);
      $('#agent-settings-status').textContent = 'Сохранено. Перезапустите rover-bringup, чтобы агент применил настройки.';
      showToast('Настройки ИИ-агента сохранены');
    } catch (error) {
      $('#agent-settings-error').textContent = error.message;
    } finally { busy = false; lock(); }
  });
  $('#agent-provider-clear-key').addEventListener('change', lock);
  $('#agent-settings-refresh').addEventListener('click', refresh);
  $('#agent-provider-load-models').addEventListener('click', () => providerAction('/api/agent/models'));
  $('#agent-provider-check').addEventListener('click', () => providerAction('/api/agent/check'));
  new MutationObserver(() => { if (state.page === 'settings' && !loaded) refresh(); })
    .observe($('#page-settings'), {attributes:true, attributeFilter:['class']});
  if (state.page === 'settings') refresh();
})();
