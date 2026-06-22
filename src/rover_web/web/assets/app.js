'use strict';

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const state = {
  page: 'system',
  system: null,
  rosGraph: null,
  selectedTopic: null,
  selectedTopicType: null,
  selectedTopicInfo: null,
  selectedService: null,
  selectedServiceType: null,
  selectedServiceInfo: null,
  selectedCameraTopic: null,
  selectedCameraType: null,
  driveKeys: new Set(),
  driveTimer: null,
  cameraTimer: null,
  cameraUrl: null,
};

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatSeconds(total) {
  if (!Number.isFinite(total)) return '—';
  const seconds = Math.max(0, Math.round(total));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remain = seconds % 60;
  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h ${minutes}m ${remain}s`;
  if (minutes > 0) return `${minutes}m ${remain}s`;
  return `${remain}s`;
}

function formatFloat(value, digits = 2) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';
}

function pretty(value) {
  return JSON.stringify(value ?? {}, null, 2);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    cache: 'no-store',
    ...options,
  });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json')
    ? await response.json().catch(() => ({}))
    : await response.text();
  if (!response.ok) {
    const message = typeof payload === 'string' ? payload : (payload.error || response.statusText);
    throw new Error(message);
  }
  return payload;
}

function setPage(page) {
  state.page = page;
  $$('.nav-tab').forEach((button) => {
    button.classList.toggle('active', button.dataset.page === page);
  });
  $$('.page').forEach((section) => {
    section.classList.toggle('active', section.id === `page-${page}`);
  });
  const titleMap = {
    system: 'Система',
    ros: 'ROS State',
    camera: 'Камера',
    drive: 'Движение',
  };
  $('#page-title').textContent = titleMap[page] || 'Console';
}

function setApiStatus(ok, rosCount) {
  $('#api-pill').textContent = ok ? 'API OK' : 'API DOWN';
  $('#api-pill').classList.toggle('neutral', !ok);
  $('#ros-pill').textContent = Number.isFinite(rosCount) ? `ROS ${rosCount}` : 'ROS';
}

function renderDetailList(element, rows) {
  element.innerHTML = '';
  for (const row of rows) {
    const dt = document.createElement('dt');
    dt.textContent = row.label;
    const dd = document.createElement('dd');
    dd.textContent = row.value;
    element.append(dt, dd);
  }
}

function renderList(element, items, renderer, selectedKey) {
  element.innerHTML = '';
  if (!items.length) {
    const empty = document.createElement('div');
    empty.className = 'status-note';
    empty.textContent = 'Ничего не найдено.';
    element.append(empty);
    return;
  }
  items.forEach((item) => {
    const button = renderer(item);
    if (button.dataset.key === selectedKey) {
      button.classList.add('active');
    }
    element.append(button);
  });
}

async function refreshSystem() {
  try {
    const payload = await api('/api/system');
    state.system = payload;
    setApiStatus(true, payload.ros?.topics);
    $('#sidebar-hostname').textContent = payload.hostname || '—';
    $('#sidebar-endpoint').textContent = `${location.hostname}:${payload.port}`;
    $('#metric-hostname').textContent = payload.hostname || '—';
    $('#metric-ip').textContent = (payload.ip_addresses || []).join(', ') || '—';
    $('#metric-uptime').textContent = formatSeconds(payload.uptime_sec);
    $('#metric-temp').textContent = Number.isFinite(payload.temperature_c)
      ? `${payload.temperature_c.toFixed(1)} °C`
      : '—';
    $('#metric-mem').textContent = formatBytes(payload.memory_available_bytes);
    $('#metric-disk').textContent = formatBytes(payload.disk_free_bytes);
    $('#metric-topics').textContent = payload.ros?.topics ?? '—';
    $('#metric-services').textContent = payload.ros?.services ?? '—';

    renderDetailList($('#system-summary'), [
      { label: 'Bind', value: `${payload.bind_address}:${payload.port}` },
      { label: 'Command topic', value: payload.command_topic || '—' },
      { label: 'Drive timeout', value: `${formatFloat(payload.drive_command_timeout_sec, 2)} s` },
      { label: 'Load 1m', value: formatFloat(payload.load_average?.one_min, 2) },
      { label: 'Load 5m', value: formatFloat(payload.load_average?.five_min, 2) },
      { label: 'Memory total', value: formatBytes(payload.memory_total_bytes) },
      { label: 'Disk total', value: formatBytes(payload.disk_total_bytes) },
      { label: 'Image topics', value: String(payload.ros?.image_topics ?? '—') },
    ]);
    $('#devices-box').textContent = pretty(payload.devices || {});
  } catch (error) {
    setApiStatus(false);
    $('#system-summary').innerHTML = '';
    $('#devices-box').textContent = String(error.message || error);
  }
}

function filterByText(items, text, fieldFn) {
  const needle = text.trim().toLowerCase();
  if (!needle) return items;
  return items.filter((item) => fieldFn(item).toLowerCase().includes(needle));
}

async function refreshRosGraph() {
  try {
    const payload = await api('/api/ros/graph');
    state.rosGraph = payload;
    $('#ros-nodes-count').textContent = payload.nodes.length;
    $('#ros-topics-count').textContent = payload.topics.length;
    $('#ros-services-count').textContent = payload.services.length;
    $('#ros-image-count').textContent = payload.image_topics.length;
    setApiStatus(true, payload.topics.length);
    renderNodes();
    renderTopics();
    renderServices();
    renderCameraTopics();
  } catch (error) {
    setApiStatus(false);
    $('#ros-nodes-count').textContent = '—';
    $('#ros-topics-count').textContent = '—';
    $('#ros-services-count').textContent = '—';
    $('#ros-image-count').textContent = '—';
  }
}

function renderNodes() {
  const items = filterByText(
    state.rosGraph?.nodes || [],
    $('#nodes-filter').value,
    (item) => `${item.full_name} ${item.namespace}`,
  );
  renderList($('#nodes-list'), items, (item) => {
    const button = document.createElement('button');
    button.className = 'list-item';
    button.type = 'button';
    button.dataset.key = item.full_name;
    button.innerHTML = `<strong>${item.full_name}</strong><small>${item.namespace}</small>`;
    return button;
  });
}

function renderTopics() {
  const items = filterByText(
    state.rosGraph?.topics || [],
    $('#topics-filter').value,
    (item) => `${item.name} ${item.types.join(' ')}`,
  );
  renderList($('#topics-list'), items, (item) => {
    const button = document.createElement('button');
    button.className = 'list-item';
    button.type = 'button';
    button.dataset.key = item.name;
    const type = item.types[0] || 'unknown';
    button.innerHTML = `
      <strong>${item.name}</strong>
      <small>${type}</small>
      <small>pub ${item.publishers} · sub ${item.subscribers}${item.is_image ? ' · image' : ''}</small>
    `;
    button.addEventListener('click', () => selectTopic(item.name, type));
    return button;
  }, state.selectedTopic);
}

function renderServices() {
  const items = filterByText(
    state.rosGraph?.services || [],
    $('#services-filter').value,
    (item) => `${item.name} ${item.types.join(' ')}`,
  );
  renderList($('#services-list'), items, (item) => {
    const button = document.createElement('button');
    button.className = 'list-item';
    button.type = 'button';
    button.dataset.key = item.name;
    const type = item.types[0] || 'unknown';
    button.innerHTML = `<strong>${item.name}</strong><small>${type}</small>`;
    button.addEventListener('click', () => selectService(item.name, type));
    return button;
  }, state.selectedService);
}

async function selectTopic(name, type) {
  state.selectedTopic = name;
  state.selectedTopicType = type;
  $('#topic-detail-title').textContent = name;
  $('#topic-action-status').textContent = 'Загрузка топика…';
  renderTopics();
  try {
    const info = await api(`/api/ros/topic?name=${encodeURIComponent(name)}&type=${encodeURIComponent(type)}`);
    state.selectedTopicInfo = info;
    renderDetailList($('#topic-meta'), [
      { label: 'Type', value: info.type || '—' },
      { label: 'Kind', value: info.kind || '—' },
      { label: 'Publishers', value: String(info.publishers ?? '—') },
      { label: 'Subscribers', value: String(info.subscribers ?? '—') },
      { label: 'Messages', value: String(info.message_count ?? '—') },
      { label: 'Age', value: info.age_sec == null ? '—' : `${formatFloat(info.age_sec, 2)} s` },
    ]);
    if (info.kind === 'image') {
      $('#topic-payload').value = '';
      $('#topic-latest-message').textContent = pretty({
        note: 'Это image topic. Для просмотра кадра открой страницу "Камера".',
        frame_url: info.frame_url,
        width: info.width,
        height: info.height,
        encoding: info.encoding,
        last_error: info.last_error,
      });
      $('#topic-action-status').textContent = 'Image topic найден.';
      return;
    }
    $('#topic-latest-message').textContent = pretty(info.latest_message || {});
    $('#topic-payload').value = pretty(info.template || {});
    $('#topic-action-status').textContent = 'Можно публиковать JSON в этот топик.';
  } catch (error) {
    $('#topic-action-status').textContent = String(error.message || error);
    $('#topic-latest-message').textContent = 'Ошибка чтения топика.';
  }
}

async function refreshSelectedTopic() {
  if (!state.selectedTopic || !state.selectedTopicType) return;
  await selectTopic(state.selectedTopic, state.selectedTopicType);
}

async function publishSelectedTopic() {
  if (!state.selectedTopic || !state.selectedTopicType) return;
  try {
    const message = JSON.parse($('#topic-payload').value || '{}');
    await api('/api/ros/topic/publish', {
      method: 'POST',
      body: JSON.stringify({
        topic: state.selectedTopic,
        type: state.selectedTopicType,
        message,
      }),
    });
    $('#topic-action-status').textContent = 'Сообщение опубликовано.';
    await refreshSelectedTopic();
  } catch (error) {
    $('#topic-action-status').textContent = String(error.message || error);
  }
}

function restoreTopicTemplate() {
  if (state.selectedTopicInfo?.template) {
    $('#topic-payload').value = pretty(state.selectedTopicInfo.template);
  }
}

async function selectService(name, type) {
  state.selectedService = name;
  state.selectedServiceType = type;
  $('#service-detail-title').textContent = name;
  $('#service-action-status').textContent = 'Загрузка сервиса…';
  renderServices();
  try {
    const info = await api(`/api/ros/service?name=${encodeURIComponent(name)}&type=${encodeURIComponent(type)}`);
    state.selectedServiceInfo = info;
    renderDetailList($('#service-meta'), [
      { label: 'Type', value: info.type || '—' },
      { label: 'Ready', value: info.ready ? 'yes' : 'no' },
      { label: 'Available types', value: (info.available_types || []).join(', ') || '—' },
    ]);
    $('#service-request').value = pretty(info.request_template || {});
    $('#service-response').textContent = 'Ожидание вызова.';
    $('#service-action-status').textContent = 'Можно вызвать сервис.';
  } catch (error) {
    $('#service-action-status').textContent = String(error.message || error);
    $('#service-response').textContent = 'Ошибка чтения сервиса.';
  }
}

async function refreshSelectedService() {
  if (!state.selectedService || !state.selectedServiceType) return;
  await selectService(state.selectedService, state.selectedServiceType);
}

async function callSelectedService() {
  if (!state.selectedService || !state.selectedServiceType) return;
  try {
    const request = JSON.parse($('#service-request').value || '{}');
    const response = await api('/api/ros/service/call', {
      method: 'POST',
      body: JSON.stringify({
        service: state.selectedService,
        type: state.selectedServiceType,
        request,
      }),
    });
    $('#service-response').textContent = pretty(response.response || response);
    $('#service-action-status').textContent = `Сервис вызван за ${formatFloat(response.duration_sec, 3)} s`;
  } catch (error) {
    $('#service-action-status').textContent = String(error.message || error);
  }
}

function restoreServiceTemplate() {
  if (state.selectedServiceInfo?.request_template) {
    $('#service-request').value = pretty(state.selectedServiceInfo.request_template);
  }
}

function renderCameraTopics() {
  const select = $('#camera-topic-select');
  const topics = state.rosGraph?.image_topics || [];
  select.innerHTML = '';
  if (!topics.length) {
    state.selectedCameraTopic = null;
    state.selectedCameraType = null;
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'Нет image topics';
    select.append(option);
    return;
  }
  topics.forEach((item, index) => {
    const option = document.createElement('option');
    option.value = item.name;
    option.dataset.type = item.types[0] || '';
    option.textContent = `${item.name} (${item.types[0] || 'unknown'})`;
    if (!state.selectedCameraTopic && index === 0) {
      state.selectedCameraTopic = item.name;
      state.selectedCameraType = item.types[0] || '';
    }
    if (item.name === state.selectedCameraTopic) {
      option.selected = true;
    }
    select.append(option);
  });
}

async function connectCamera() {
  const select = $('#camera-topic-select');
  state.selectedCameraTopic = select.value || null;
  state.selectedCameraType = select.selectedOptions[0]?.dataset.type || null;
  stopCameraLoop();
  if (!state.selectedCameraTopic || !state.selectedCameraType) {
    $('#camera-status').textContent = 'Нет выбранного источника.';
    return;
  }
  await refreshCameraStatus();
  startCameraLoop();
}

async function refreshCameraStatus() {
  if (!state.selectedCameraTopic || !state.selectedCameraType) return;
  try {
    const info = await api(
      `/api/camera/status?topic=${encodeURIComponent(state.selectedCameraTopic)}&type=${encodeURIComponent(state.selectedCameraType)}`,
    );
    renderDetailList($('#camera-meta'), [
      { label: 'Topic', value: info.topic || '—' },
      { label: 'Type', value: info.type || '—' },
      { label: 'Encoding', value: info.encoding || '—' },
      { label: 'Resolution', value: info.width && info.height ? `${info.width}×${info.height}` : '—' },
      { label: 'Frames', value: String(info.message_count ?? '—') },
      { label: 'Age', value: info.age_sec == null ? '—' : `${formatFloat(info.age_sec, 2)} s` },
    ]);
    $('#camera-status').textContent = info.last_error
      ? `Ошибка: ${info.last_error}`
      : (info.frame_ready ? 'Кадры поступают.' : 'Ожидание первого кадра.');
  } catch (error) {
    $('#camera-status').textContent = String(error.message || error);
  }
}

async function fetchCameraFrame() {
  if (state.page !== 'camera' || !state.selectedCameraTopic || !state.selectedCameraType) return;
  try {
    const response = await fetch(
      `/api/camera/frame?topic=${encodeURIComponent(state.selectedCameraTopic)}&type=${encodeURIComponent(state.selectedCameraType)}&t=${Date.now()}`,
      { cache: 'no-store' },
    );
    if (!response.ok) {
      throw new Error(`Frame ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    if (state.cameraUrl) {
      URL.revokeObjectURL(state.cameraUrl);
    }
    state.cameraUrl = url;
    $('#camera-frame').src = url;
    $('#camera-empty').classList.add('hidden');
  } catch (error) {
    $('#camera-empty').classList.remove('hidden');
  }
}

function startCameraLoop() {
  stopCameraLoop();
  state.cameraTimer = window.setInterval(() => {
    refreshCameraStatus();
    fetchCameraFrame();
  }, 350);
  fetchCameraFrame();
}

function stopCameraLoop() {
  if (state.cameraTimer) {
    window.clearInterval(state.cameraTimer);
    state.cameraTimer = null;
  }
  if (state.cameraUrl) {
    URL.revokeObjectURL(state.cameraUrl);
    state.cameraUrl = null;
  }
}

async function refreshDriveConfig() {
  try {
    const payload = await api('/api/drive');
    $('#linear-speed').max = payload.limits.linear_x;
    $('#linear-speed').value = payload.defaults.linear_x;
    $('#lateral-speed').max = payload.limits.linear_y;
    $('#lateral-speed').value = payload.defaults.linear_y;
    $('#angular-speed').max = payload.limits.angular_z;
    $('#angular-speed').value = payload.defaults.angular_z;
    updateDriveOutputs();
    renderDetailList($('#drive-meta'), [
      { label: 'Command topic', value: payload.command_topic || '—' },
      { label: 'Timeout', value: `${formatFloat(payload.timeout_sec, 2)} s` },
      { label: 'Linear max', value: formatFloat(payload.limits.linear_x, 2) },
      { label: 'Lateral max', value: formatFloat(payload.limits.linear_y, 2) },
      { label: 'Angular max', value: formatFloat(payload.limits.angular_z, 2) },
    ]);
  } catch (error) {
    $('#drive-meta').innerHTML = '';
  }
}

function updateDriveOutputs() {
  $('#linear-speed-output').textContent = `${formatFloat($('#linear-speed').value, 2)} m/s`;
  $('#lateral-speed-output').textContent = `${formatFloat($('#lateral-speed').value, 2)} m/s`;
  $('#angular-speed-output').textContent = `${formatFloat($('#angular-speed').value, 2)} rad/s`;
}

function computeDriveCommand() {
  const linear = Number($('#linear-speed').value);
  const lateral = Number($('#lateral-speed').value);
  const angular = Number($('#angular-speed').value);

  const forward = state.driveKeys.has('KeyW') ? 1 : 0;
  const backward = state.driveKeys.has('KeyS') ? 1 : 0;
  const left = state.driveKeys.has('KeyA') ? 1 : 0;
  const right = state.driveKeys.has('KeyD') ? 1 : 0;
  const rotateLeft = state.driveKeys.has('KeyQ') ? 1 : 0;
  const rotateRight = state.driveKeys.has('KeyE') ? 1 : 0;

  const linearX = (forward - backward) * linear;
  const linearY = (left - right) * lateral;
  const angularZ = (rotateLeft - rotateRight) * angular;
  return { linearX, linearY, angularZ };
}

function updateDrivePreview(command) {
  $('#drive-preview').textContent = `linear.x: ${formatFloat(command.linearX, 2)}
linear.y: ${formatFloat(command.linearY, 2)}
angular.z: ${formatFloat(command.angularZ, 2)}`;
}

async function sendDriveCommand() {
  const command = computeDriveCommand();
  updateDrivePreview(command);
  try {
    await api('/api/drive/command', {
      method: 'POST',
      body: JSON.stringify({
        linear_x: command.linearX,
        linear_y: command.linearY,
        angular_z: command.angularZ,
      }),
    });
  } catch (error) {
    // Keep UI responsive even if the rover is temporarily unavailable.
  }
}

async function stopDrive() {
  stopDriveLoop();
  state.driveKeys.clear();
  $$('.drive-key').forEach((button) => button.classList.remove('active'));
  updateDrivePreview({ linearX: 0, linearY: 0, angularZ: 0 });
  try {
    await api('/api/drive/stop', { method: 'POST', body: '{}' });
  } catch (error) {
    // no-op
  }
}

function syncDriveKeyHighlights() {
  $$('.drive-key').forEach((button) => {
    button.classList.toggle('active', state.driveKeys.has(button.dataset.key));
  });
}

function startDriveLoop() {
  if (state.driveTimer) return;
  state.driveTimer = window.setInterval(() => {
    if (state.driveKeys.size === 0) return;
    sendDriveCommand();
  }, 120);
}

function stopDriveLoop() {
  if (state.driveTimer) {
    window.clearInterval(state.driveTimer);
    state.driveTimer = null;
  }
}

function bindNavigation() {
  $$('.nav-tab').forEach((button) => {
    button.addEventListener('click', () => {
      const page = button.dataset.page;
      setPage(page);
      if (page === 'camera' && state.selectedCameraTopic) {
        connectCamera();
      } else if (page !== 'camera') {
        stopCameraLoop();
      }
    });
  });
}

function bindRosPage() {
  $('#nodes-filter').addEventListener('input', renderNodes);
  $('#topics-filter').addEventListener('input', renderTopics);
  $('#services-filter').addEventListener('input', renderServices);
  $('#ros-refresh').addEventListener('click', refreshRosGraph);
  $('#topic-refresh').addEventListener('click', refreshSelectedTopic);
  $('#topic-publish').addEventListener('click', publishSelectedTopic);
  $('#topic-template').addEventListener('click', restoreTopicTemplate);
  $('#service-refresh').addEventListener('click', refreshSelectedService);
  $('#service-call').addEventListener('click', callSelectedService);
  $('#service-template').addEventListener('click', restoreServiceTemplate);
}

function bindCameraPage() {
  $('#camera-refresh-topics').addEventListener('click', refreshRosGraph);
  $('#camera-connect').addEventListener('click', connectCamera);
  $('#camera-topic-select').addEventListener('change', () => {
    state.selectedCameraTopic = $('#camera-topic-select').value || null;
    state.selectedCameraType = $('#camera-topic-select').selectedOptions[0]?.dataset.type || null;
  });
}

function bindDrivePage() {
  ['linear-speed', 'lateral-speed', 'angular-speed'].forEach((id) => {
    $(`#${id}`).addEventListener('input', () => {
      updateDriveOutputs();
      updateDrivePreview(computeDriveCommand());
    });
  });
  $('#drive-stop').addEventListener('click', stopDrive);
  $$('.drive-key').forEach((button) => {
    button.addEventListener('pointerdown', () => {
      state.driveKeys.add(button.dataset.key);
      syncDriveKeyHighlights();
      startDriveLoop();
      sendDriveCommand();
    });
    button.addEventListener('pointerup', () => {
      state.driveKeys.delete(button.dataset.key);
      syncDriveKeyHighlights();
      if (state.driveKeys.size === 0) {
        stopDriveLoop();
      }
      sendDriveCommand();
    });
    button.addEventListener('pointerleave', () => {
      state.driveKeys.delete(button.dataset.key);
      syncDriveKeyHighlights();
    });
  });

  window.addEventListener('keydown', (event) => {
    if (!['KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE'].includes(event.code)) return;
    event.preventDefault();
    state.driveKeys.add(event.code);
    syncDriveKeyHighlights();
    startDriveLoop();
    sendDriveCommand();
  });
  window.addEventListener('keyup', (event) => {
    if (!state.driveKeys.has(event.code)) return;
    state.driveKeys.delete(event.code);
    syncDriveKeyHighlights();
    if (state.driveKeys.size === 0) {
      stopDriveLoop();
    }
    sendDriveCommand();
  });
  window.addEventListener('blur', stopDrive);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) stopDrive();
  });
}

async function initialize() {
  bindNavigation();
  bindRosPage();
  bindCameraPage();
  bindDrivePage();
  $('#system-refresh').addEventListener('click', refreshSystem);

  await Promise.all([
    refreshSystem(),
    refreshRosGraph(),
    refreshDriveConfig(),
  ]);
  setPage('system');
  updateDrivePreview({ linearX: 0, linearY: 0, angularZ: 0 });
  window.setInterval(refreshSystem, 3000);
  window.setInterval(() => {
    if (state.page === 'ros') {
      refreshRosGraph();
      refreshSelectedTopic();
      refreshSelectedService();
    }
  }, 3000);
}

initialize().catch((error) => {
  $('#api-pill').textContent = 'INIT ERR';
  $('#api-pill').classList.add('neutral');
  console.error(error);
});
