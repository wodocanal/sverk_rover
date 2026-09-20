(() => {
  'use strict';
  let snapshot = null, polling = false, sending = false, rendered = '', attempt = null;
  const labels = { sent: 'Отправлено', running: 'Выполняется', completed: 'Ответ получен', error: 'Ошибка' };
  function messageId() {
    // getRandomValues also works over HTTP on the rover's LAN address.
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    const hex = [...bytes].map(value => value.toString(16).padStart(2, '0')).join('');
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }
  function updateSendButton() {
    $('#agent-send').disabled = sending || !snapshot?.input_subscribers || !$('#agent-input').value.trim();
    $('#agent-send').textContent = sending ? 'Отправка…' : 'Отправить';
  }
  function render(data) {
    snapshot = data;
    renderServerConnection(data.server_connection);
    $('#agent-connection').textContent = data.input_subscribers
      ? 'Входной топик имеет подписчика. Можно отправить сообщение.'
      : 'Агент не подключен: у входного топика нет подписчиков.';
    if (data.input_subscribers && !data.answer_publishers) {
      $('#agent-connection').textContent += ' Издатель ответов пока не обнаружен.';
    }
    const topics = $('#agent-topics');
    topics.replaceChildren();
    for (const [key, label] of [['input', 'Вход'], ['answer', 'Ответы'], ['status', 'Статусы']]) {
      const term = document.createElement('dt'), value = document.createElement('dd');
      term.textContent = label; value.textContent = data.topics[key]; topics.append(term, value);
    }
    const version = `${data.instance_id}:${data.revision}`;
    if (version !== rendered) {
      const log = $('#agent-messages');
      const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 60;
      const oldScroll = log.scrollTop;
      log.replaceChildren();
      for (const item of data.messages) {
        const thread = document.createElement('section');
        thread.className = 'agent-exchange';
        const bubble = (role, text, kind) => {
          const block = document.createElement('div'), heading = document.createElement('strong');
          const content = document.createElement('p');
          block.className = `agent-bubble ${kind}`;
          heading.textContent = role; content.textContent = text;
          block.append(heading, content); thread.append(block);
        };
        if (item.text !== null) bubble('Вы', item.text, 'agent-user');
        if (item.answer !== null) bubble(item.robot_id ? `Агент · ${item.robot_id}` : 'Агент', item.answer, 'agent-answer');
        const status = document.createElement('p');
        status.className = `status-note${item.status === 'error' ? ' maintenance-error' : ''}`;
        const detail = item.answer === null ? ` · ${item.status_text || ''}` : '';
        status.textContent = `${labels[item.status] || item.status}${detail}`;
        if (item.text === null) status.textContent = `Внешний запрос · ${status.textContent}`;
        thread.append(status); log.append(thread);
      }
      if (!data.messages.length) {
        const empty = document.createElement('p');
        empty.className = 'muted'; empty.textContent = 'Сообщений пока нет.'; log.append(empty);
      }
      if (atBottom || !rendered) log.scrollTop = log.scrollHeight;
      else log.scrollTop = oldScroll;
      rendered = version;
    }
    updateSendButton();
  }
  async function refresh() {
    if (polling) return;
    polling = true;
    try {
      render(await api('/api/agent', { signal: AbortSignal.timeout(8000) }));
      $('#agent-connection').classList.remove('maintenance-error');
    } catch (error) {
      snapshot = null;
      renderServerConnection(null);
      $('#agent-connection').textContent = `Не удалось получить состояние: ${error.message}`;
      $('#agent-connection').classList.add('maintenance-error');
      updateSendButton();
    } finally { polling = false; }
  }
  function renderServerConnection(connection) {
    const stateName = connection?.state || 'unavailable';
    const ready = connection?.ready === true;
    const descriptions = {
      connected: 'MQTT-соединение установлено, подписка на команды и публикация online подтверждены брокером.',
      connecting: 'Подключение к MQTT-серверу; ожидаем подтверждения соединения, подписки и online.',
      disconnected: 'Связь с MQTT-сервером потеряна или сервер недоступен. Мост повторяет подключение.',
      error: 'MQTT-сервер отклонил подключение или подписку; проверьте настройки и права доступа.',
      unavailable: 'Нет данных от MQTT-моста. Он не запущен, ещё не обнаружен или требует обновления.',
      waiting: 'Издатель статуса найден; ожидаем первое сообщение.',
      stale: 'Статус не обновлялся более 5 секунд. Подключение больше не подтверждено.',
      ambiguous: 'Найдено несколько издателей статуса MQTT. Проверьте, что запущен только один мост.',
    };
    const tone = ready ? 'ok' : ['error','disconnected'].includes(stateName) ? 'error' : 'unknown';
    const label = ready ? 'ПОДКЛЮЧЕН' : stateName === 'connecting' ? 'ПОДКЛЮЧЕНИЕ'
      : ['error','disconnected'].includes(stateName) ? 'НЕТ СВЯЗИ' : 'НЕТ ПОДТВЕРЖДЕНИЯ';
    setToneClass($('#agent-server-state'), tone, label);
    $('#agent-server-detail').textContent = connection
      ? `${descriptions[stateName] || 'Состояние неизвестно.'}${connection.error ? ` ${connection.error}` : ''}`
      : 'Состояние связи с сервером недоступно. Обновите страницу или проверьте веб-сервис.';
    const meta = $('#agent-server-meta');
    meta.replaceChildren();
    for (const [label, value] of [
      ['MQTT-сервер', connection?.host ? `${connection.host}:${connection.port || '—'}` : '—'],
      ['Robot ID моста', connection?.robot_id || '—'],
      ['Обновление статуса', Number.isFinite(connection?.age_sec) ? `${Math.floor(connection.age_sec)} с назад` : 'Нет данных'],
    ]) {
      const term = document.createElement('dt'), description = document.createElement('dd');
      term.textContent = label; description.textContent = value; meta.append(term, description);
    }
  }
  $('#agent-form').addEventListener('submit', async event => {
    event.preventDefault();
    const input = $('#agent-input'), text = input.value.trim();
    if (!text || sending || !snapshot?.input_subscribers) return;
    if (!attempt || attempt.text !== text) attempt = { text, message_id: messageId() };
    sending = true; updateSendButton(); $('#agent-error').textContent = '';
    try {
      await api('/api/agent/send', { method: 'POST', body: JSON.stringify(attempt), signal: AbortSignal.timeout(8000) });
      if (input.value.trim() === text) input.value = '';
      attempt = null;
      await refresh();
      $('#agent-messages').scrollTop = $('#agent-messages').scrollHeight;
    } catch (error) {
      $('#agent-error').textContent = `Не удалось подтвердить отправку: ${error.message}. Текст сохранен; проверьте переписку перед повторной отправкой.`;
    } finally { sending = false; updateSendButton(); }
  });
  $('#agent-input').addEventListener('input', updateSendButton);
  $('#agent-input').addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault(); $('#agent-form').requestSubmit();
    }
  });
  $('#agent-refresh').addEventListener('click', refresh);
  new MutationObserver(() => { if (state.page === 'agent') refresh(); })
    .observe($('#page-agent'), { attributes: true, attributeFilter: ['class'] });
  setInterval(() => { if (state.page === 'agent' && !document.hidden) refresh(); }, 1500);
  if (state.page === 'agent') refresh();
})();
