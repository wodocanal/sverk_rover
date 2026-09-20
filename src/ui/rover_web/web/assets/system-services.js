(() => {
  'use strict';
  let snapshot = null, busy = false, polling = false;
  const labels = { active: 'Работает', inactive: 'Остановлен', failed: 'Ошибка запуска',
    activating: 'Запускается…', deactivating: 'Останавливается…', reloading: 'Обновляется…',
    refreshing: 'Обновляется…', unknown: 'Состояние неизвестно' };
  const stable = value => ['active', 'inactive', 'failed'].includes(value);
  const running = value => ['active', 'activating', 'reloading', 'refreshing'].includes(value);
  async function fetchState() {
    return api('/api/system/services', { signal: AbortSignal.timeout(8000) });
  }
  function render() {
    const bringup = snapshot?.services?.bringup;
    const web = snapshot?.services?.web;
    for (const [id, service] of [['bringup', bringup], ['web', web]]) {
      $(`#${id}-service-status`).textContent = !service ? 'Состояние недоступно'
        : service.error || `${labels[service.active_state] || service.active_state}${service.sub_state ? ` · ${service.sub_state}` : ''}`;
    }
    if (web?.available && !web.managed_current_process) {
      $('#web-service-status').textContent += ' · Текущий веб запущен не через rover-web.service';
    }
    const stop = running(bringup?.active_state);
    $('#bringup-service-toggle').textContent = stop ? 'Остановить' : 'Запустить';
    $('#bringup-service-toggle').classList.toggle('danger-secondary', stop);
    $('#bringup-service-toggle').disabled = busy || !bringup?.available || !stable(bringup.active_state);
    $('#bringup-service-restart').disabled = busy || !bringup?.available || !stable(bringup.active_state);
    $('#web-service-restart').disabled = busy || !web?.available || !web.managed_current_process
      || !stable(web.active_state);
    $('#services-refresh').disabled = busy;
    const permissions = snapshot?.permissions;
    $('#services-permissions-status').textContent = !permissions ? 'Данные о правах недоступны.'
      : !permissions.supported ? 'В этой среде systemd недоступен.'
      : `Пользователь веба: ${permissions.user}. ${permissions.root ? 'Процесс работает от root.'
        : permissions.sudo_ready ? 'Разрешение sudo на нужные команды подтверждено.'
        : 'Разрешение sudo не подтверждено. Прямой доступ через Polkit может работать; при ошибке авторизации выполните команду ниже.'}`;
  }
  async function refresh() {
    if (polling || busy) return;
    polling = true;
    try { snapshot = await fetchState(); }
    catch (error) { snapshot = null; $('#services-error').textContent = error.message; }
    finally { polling = false; render(); }
  }
  async function waitForWeb(previousId) {
    const deadline = Date.now() + 90000;
    while (Date.now() < deadline) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      let current;
      try { current = await fetchState(); } catch (_) { continue; }
      if (current.instance_id && current.instance_id !== previousId) {
        snapshot = current;
        window.location.reload();
        return;
      }
      if (current.web_restart?.state === 'error') {
        throw new Error(current.web_restart.error || 'Не удалось перезапустить веб');
      }
    }
    throw new Error('Новый процесс веба не появился за 90 секунд. Проверьте rover-web через systemctl и обновите страницу.');
  }
  async function execute(target, action) {
    if (busy) return;
    const description = target === 'web' ? 'Перезапустить rover-web? Соединение временно пропадет, веб-навигация остановится.'
      : `${action === 'start' ? 'Запустить' : action === 'stop' ? 'Остановить' : 'Перезапустить'} rover-bringup? Остановите движение и отключите внешние команды.`;
    if (!window.confirm(description)) return;
    busy = true;
    $('#services-error').textContent = '';
    $('#services-operation-status').textContent = target === 'web'
      ? 'Перезапуск веба: ожидаем восстановления соединения…' : 'Выполняется команда сервиса…';
    render();
    try {
      if (target === 'web') {
        const previous = snapshot?.instance_id;
        try {
          await api('/api/system/web/restart', { method: 'POST',
            body: JSON.stringify({ confirmed: true }), signal: AbortSignal.timeout(15000) });
        } catch (error) {
          // A self-restart may interrupt its own response. Poll, but never resend it.
          if (!(error instanceof TypeError) && !['TimeoutError', 'AbortError'].includes(error.name)) throw error;
        }
        await waitForWeb(previous);
      } else {
        await api('/api/maintenance/hardware', { method: 'POST',
          body: JSON.stringify({ action, confirmed: true }), signal: AbortSignal.timeout(100000) });
        snapshot = await fetchState();
        const desired = action === 'stop' ? 'inactive' : 'active';
        if (snapshot.services.bringup.active_state !== desired) {
          throw new Error(`Команда отправлена, текущее состояние: ${snapshot.services.bringup.active_state}. Проверьте журнал сервиса.`);
        }
        $('#services-operation-status').textContent = action === 'stop' ? 'Bringup остановлен.'
          : action === 'start' ? 'Bringup запущен.' : 'Bringup перезапущен.';
      }
    } catch (error) {
      $('#services-operation-status').textContent = '';
      $('#services-error').textContent = error.message;
    } finally { busy = false; render(); }
  }
  $('#services-refresh').addEventListener('click', refresh);
  $('#bringup-service-toggle').addEventListener('click', () => execute('bringup',
    running(snapshot?.services?.bringup?.active_state) ? 'stop' : 'start'));
  $('#bringup-service-restart').addEventListener('click', () => execute('bringup', 'restart'));
  $('#web-service-restart').addEventListener('click', () => execute('web', 'restart'));
  setInterval(() => { if (state.page === 'overview' && !document.hidden) refresh(); }, 2000);
  refresh();
})();
