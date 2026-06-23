'use strict';

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const STORAGE_KEYS = {
  page: 'rover_web.page',
  compact: 'rover_web.compact',
  vizScale: 'rover_web.viz_scale',
  vizFollow: 'rover_web.viz_follow',
  sessionId: 'rover_web.session_id',
};

const ROUTE_STEP_LABELS = {
  move: 'Перемещение',
  move_polar: 'По направлению',
  turn: 'Поворот',
  pause: 'Пауза',
  return_to_start: 'Вернуться в начало',
};

const ROUTE_STEP_FIELDS = {
  move: [
    { key: 'forward', label: 'Вперёд, м', type: 'number', required: true, step: '0.01', defaultValue: 0.50 },
    { key: 'left', label: 'Влево, м', type: 'number', required: true, step: '0.01', defaultValue: 0.00 },
    { key: 'linear_speed', label: 'Скорость, м/с', type: 'number', step: '0.01', placeholder: 'по умолчанию' },
    { key: 'approach_speed', label: 'Скорость подхода, м/с', type: 'number', step: '0.01', placeholder: 'по умолчанию' },
    { key: 'position_tolerance', label: 'Допуск, м', type: 'number', step: '0.01', placeholder: 'по умолчанию' },
    { key: 'maximum_time', label: 'Лимит, с', type: 'number', step: '1', placeholder: 'по умолчанию' },
  ],
  move_polar: [
    { key: 'distance', label: 'Дистанция, м', type: 'number', required: true, step: '0.01', defaultValue: 0.50 },
    { key: 'direction_deg', label: 'Направление, °', type: 'number', required: true, step: '1', defaultValue: 0 },
    { key: 'linear_speed', label: 'Скорость, м/с', type: 'number', step: '0.01', placeholder: 'по умолчанию' },
    { key: 'approach_speed', label: 'Скорость подхода, м/с', type: 'number', step: '0.01', placeholder: 'по умолчанию' },
    { key: 'position_tolerance', label: 'Допуск, м', type: 'number', step: '0.01', placeholder: 'по умолчанию' },
    { key: 'maximum_time', label: 'Лимит, с', type: 'number', step: '1', placeholder: 'по умолчанию' },
  ],
  turn: [
    { key: 'degrees', label: 'Угол, °', type: 'number', required: true, step: '1', defaultValue: 90 },
    { key: 'angular_speed', label: 'Угловая скорость, рад/с', type: 'number', step: '0.01', placeholder: 'по умолчанию' },
    { key: 'minimum_angular_speed', label: 'Мин. скорость, рад/с', type: 'number', step: '0.01', placeholder: 'по умолчанию' },
    { key: 'angle_tolerance_deg', label: 'Допуск, °', type: 'number', step: '1', placeholder: 'по умолчанию' },
    { key: 'maximum_time', label: 'Лимит, с', type: 'number', step: '1', placeholder: 'по умолчанию' },
  ],
  pause: [
    { key: 'seconds', label: 'Пауза, с', type: 'number', required: true, step: '0.1', defaultValue: 1.0 },
  ],
  return_to_start: [
    { key: 'restore_heading', label: 'Восстановить курс', type: 'checkbox', defaultValue: true },
    { key: 'linear_speed', label: 'Скорость, м/с', type: 'number', step: '0.01', placeholder: 'по умолчанию' },
    { key: 'approach_speed', label: 'Скорость подхода, м/с', type: 'number', step: '0.01', placeholder: 'по умолчанию' },
    { key: 'position_tolerance', label: 'Допуск, м', type: 'number', step: '0.01', placeholder: 'по умолчанию' },
    { key: 'maximum_time', label: 'Лимит, с', type: 'number', step: '1', placeholder: 'по умолчанию' },
  ],
};

const state = {
  sessionId: ensureSessionId(),
  page: localStorage.getItem(STORAGE_KEYS.page) || 'overview',
  system: null,
  status: null,
  identity: null,
  config: null,
  activity: [],
  rosGraph: null,
  selectedTopic: null,
  selectedTopicType: null,
  selectedTopicInfo: null,
  selectedService: null,
  selectedServiceType: null,
  selectedServiceInfo: null,
  selectedCameraTopic: null,
  selectedCameraType: null,
  cameraTimer: null,
  cameraUrl: null,
  driveKeys: new Set(),
  driveTimer: null,
  route: {
    plans: [],
    selectedName: '',
    draft: null,
  },
  viz: {
    trail: [],
    scale: Number(localStorage.getItem(STORAGE_KEYS.vizScale) || '120'),
    follow: localStorage.getItem(STORAGE_KEYS.vizFollow) !== 'false',
  },
  apiHealthy: false,
  rosHealthy: false,
};

function ensureSessionId() {
  const existing = localStorage.getItem(STORAGE_KEYS.sessionId);
  if (existing) return existing;
  const generated = typeof crypto?.randomUUID === 'function'
    ? crypto.randomUUID()
    : `session-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  localStorage.setItem(STORAGE_KEYS.sessionId, generated);
  return generated;
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = Number(bytes);
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(value >= 10 || index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatGigabytes(bytes) {
  if (!Number.isFinite(bytes)) return '—';
  return (Number(bytes) / (1024 ** 3)).toFixed(1);
}

function formatPercent(value, digits = 0) {
  return Number.isFinite(Number(value)) ? `${Number(value).toFixed(digits)}%` : '—';
}

function formatSeconds(total) {
  if (!Number.isFinite(total)) return '—';
  const seconds = Math.max(0, Math.round(Number(total)));
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

function formatAngleRad(rad) {
  return Number.isFinite(Number(rad)) ? `${(Number(rad) * 180 / Math.PI).toFixed(1)}°` : '—';
}

function formatAge(seconds) {
  if (!Number.isFinite(Number(seconds))) return 'нет данных';
  const value = Number(seconds);
  if (value < 1) return `${value.toFixed(2)} с`;
  if (value < 10) return `${value.toFixed(1)} с`;
  return `${Math.round(value)} с`;
}

function pretty(value) {
  return JSON.stringify(value ?? {}, null, 2);
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function levelTone(level) {
  if (level >= 2) return 'error';
  if (level === 1) return 'warn';
  return 'ok';
}

function levelLabel(level) {
  if (level >= 2) return 'Ошибка';
  if (level === 1) return 'Предупреждение';
  return 'Норма';
}

function topicAgeTone(seconds, warn = 1.5, error = 4.0) {
  if (!Number.isFinite(Number(seconds))) return 'error';
  const value = Number(seconds);
  if (value >= error) return 'error';
  if (value >= warn) return 'warn';
  return 'ok';
}

function setToneClass(element, tone, text) {
  if (!element) return;
  element.classList.remove('ok', 'warn', 'error', 'unknown');
  element.classList.add(tone || 'unknown');
  if (typeof text === 'string') {
    element.textContent = text;
  }
}

function showToast(message, tone = 'ok') {
  const container = $('#toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${tone}`;
  toast.textContent = message;
  container.append(toast);
  window.setTimeout(() => {
    toast.remove();
  }, 3400);
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function currentPageTitle(page) {
  return {
    overview: 'Обзор',
    ros: 'ROS State',
    camera: 'Камера',
    drive: 'Управление',
    routes: 'Маршруты',
    visualization: 'Визуализация',
    terminal: 'Терминал',
    diagnostics: 'Диагностика',
    settings: 'Настройки',
  }[page] || 'Rover';
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  });
  const contentType = response.headers.get('content-type') || '';
  const payload = contentType.includes('application/json')
    ? await response.json().catch(() => ({}))
    : await response.text();
  if (!response.ok) {
    const message = typeof payload === 'string'
      ? payload
      : (payload.error || payload.message || response.statusText);
    throw new Error(message || `HTTP ${response.status}`);
  }
  return payload;
}

async function recordActivity(message, details = {}, source = 'web') {
  try {
    await api('/api/activity', {
      method: 'POST',
      body: JSON.stringify({ source, message, details }),
    });
  } catch (error) {
    // Best effort only.
  }
}

function updateCompactMode(enabled) {
  document.body.classList.toggle('compact', enabled);
  $('#compact-mode').checked = enabled;
  localStorage.setItem(STORAGE_KEYS.compact, enabled ? 'true' : 'false');
}

function bindCompactMode() {
  const enabled = localStorage.getItem(STORAGE_KEYS.compact) === 'true';
  updateCompactMode(enabled);
  $('#compact-mode').addEventListener('change', (event) => {
    updateCompactMode(event.target.checked);
  });
}

function closeSidebar() {
  $('#sidebar').classList.remove('open');
}

function setPage(page) {
  state.page = page;
  localStorage.setItem(STORAGE_KEYS.page, page);
  document.title = `${currentPageTitle(page)} · СВЕРХ Rover`;

  $$('.nav-item').forEach((button) => {
    button.classList.toggle('active', button.dataset.page === page);
  });
  $$('.page').forEach((section) => {
    section.classList.toggle('active', section.id === `page-${page}`);
  });

  if (page !== 'camera') {
    stopCameraLoop();
  } else if (state.selectedCameraTopic && state.selectedCameraType) {
    connectCamera();
  }

  if (page === 'terminal') {
    refreshTerminalFrame();
  }

  closeSidebar();
  sendHeartbeat();
}

function updateHealthIndicators() {
  const graphCounts = state.rosGraph || state.system?.ros || {};
  const rosSummary = Number.isFinite(graphCounts.topics)
    ? `ROS ${graphCounts.topics}`
    : 'ROS';
  setToneClass($('#api-status'), state.apiHealthy ? 'ok' : 'error', state.apiHealthy ? 'API OK' : 'API DOWN');
  setToneClass($('#api-dot'), state.apiHealthy ? 'ok' : 'error');
  setToneClass($('#ros-status'), state.rosHealthy ? 'ok' : 'warn', state.rosHealthy ? rosSummary : 'ROS WAIT');
  setToneClass($('#ros-dot'), state.rosHealthy ? 'ok' : 'warn');
  const clients = state.status?.connected_clients ?? 0;
  $('#client-count').textContent = `CLIENTS ${clients}`;
}

function applyIdentity() {
  const identity = state.identity || state.status?.identity || {};
  const system = state.system || state.status?.system || {};
  $('#robot-name').textContent = identity.robot_id || identity.hostname || system.hostname || 'rover';
  const addresses = safeArray(identity.ip_addresses || system.ip_addresses);
  const addressText = addresses.length ? addresses.join(', ') : `${location.hostname}:${location.port || '80'}`;
  $('#robot-address').textContent = addressText;
}

function renderDetailList(element, rows) {
  element.innerHTML = '';
  rows.forEach((row) => {
    const dt = document.createElement('dt');
    dt.textContent = row.label;
    const dd = document.createElement('dd');
    dd.textContent = row.value;
    element.append(dt, dd);
  });
}

function createStatusRow(title, subtitle, tone, valueText) {
  const row = document.createElement('div');
  row.className = 'status-row';

  const info = document.createElement('div');
  const strong = document.createElement('strong');
  strong.textContent = title;
  const small = document.createElement('small');
  small.textContent = subtitle;
  info.append(strong, small);

  const value = document.createElement('span');
  value.className = `status-value ${tone}`;
  value.textContent = valueText;
  row.append(info, value);
  return row;
}

function renderOverview() {
  const status = state.status;
  const system = state.system || status?.system;
  if (!system) return;

  const pose = status?.odom;
  const speed = pose ? Math.hypot(Number(pose.vx || 0), Number(pose.vy || 0)) : null;
  const memoryTotal = Number(system.memory_total_bytes);
  const memoryAvailable = Number(system.memory_available_bytes);
  const memoryUsedPercent = Number.isFinite(memoryTotal) && memoryTotal > 0 && Number.isFinite(memoryAvailable)
    ? (100 * (memoryTotal - memoryAvailable) / memoryTotal)
    : null;

  $('#metric-x').textContent = pose ? formatFloat(pose.x, 2) : '—';
  $('#metric-y').textContent = pose ? formatFloat(pose.y, 2) : '—';
  $('#metric-yaw').textContent = pose ? formatFloat(pose.yaw * 180 / Math.PI, 1) : '—';
  $('#metric-speed').textContent = Number.isFinite(speed) ? formatFloat(speed, 2) : '—';
  $('#metric-cpu').textContent = Number.isFinite(system.cpu_percent) ? formatFloat(system.cpu_percent, 0) : '—';
  $('#metric-temp').textContent = Number.isFinite(system.temperature_c) ? formatFloat(system.temperature_c, 1) : '—';
  $('#metric-ram').textContent = Number.isFinite(memoryUsedPercent) ? formatFloat(memoryUsedPercent, 0) : '—';
  $('#metric-disk').textContent = formatGigabytes(system.disk_free_bytes);

  const topicContainer = $('#topic-health');
  topicContainer.innerHTML = '';
  const topicState = status?.topics || {};
  [
    ['odom', 'Фильтрованная одометрия', topicState.odom],
    ['wheel_odometry', 'Колёсная одометрия', topicState.wheel_odometry],
    ['imu', 'IMU', topicState.imu],
    ['diagnostics', 'Диагностика', topicState.diagnostics],
  ].forEach(([key, label, item]) => {
    const age = item?.age_sec;
    const count = item?.message_count ?? 0;
    const tone = topicAgeTone(age);
    topicContainer.append(
      createStatusRow(
        label,
        `${key} · сообщений: ${count}`,
        tone,
        Number.isFinite(age) ? formatAge(age) : 'нет',
      ),
    );
  });

  const diagnosticSummary = $('#diagnostic-summary');
  diagnosticSummary.innerHTML = '';
  const diagnostics = safeArray(status?.diagnostics?.items);
  if (!diagnostics.length) {
    diagnosticSummary.append(createStatusRow('Диагностика', 'Сообщений пока нет', 'warn', 'ожидание'));
  } else {
    diagnostics.slice(0, 6).forEach((item) => {
      diagnosticSummary.append(
        createStatusRow(
          item.name || 'diagnostic',
          item.message || '—',
          levelTone(item.level),
          levelLabel(item.level),
        ),
      );
    });
  }

  renderDetailList($('#overview-system-details'), [
    { label: 'Hostname', value: system.hostname || '—' },
    { label: 'IP', value: safeArray(system.ip_addresses).join(', ') || '—' },
    { label: 'Uptime', value: formatSeconds(system.uptime_sec) },
    { label: 'Load 1m', value: formatFloat(system.load_average?.one_min, 2) },
    { label: 'Throttling', value: system.throttled || '—' },
    { label: 'Командный топик', value: system.command_topic || state.config?.command_topic || '—' },
    { label: 'Подключённых клиентов', value: String(status?.connected_clients ?? 0) },
    { label: 'Маршрут', value: status?.motion?.running ? 'выполняется' : 'не активен' },
  ]);

  $('#overview-devices').textContent = pretty(system.devices || status?.device_discovery || {});
}

function setSystemError(message) {
  $('#overview-system-details').innerHTML = '';
  $('#overview-devices').textContent = message;
}

async function refreshSystem() {
  try {
    const payload = await api('/api/system');
    state.system = payload;
    state.apiHealthy = true;
    applyIdentity();
    renderOverview();
    updateHealthIndicators();
  } catch (error) {
    state.apiHealthy = false;
    setSystemError(String(error.message || error));
    updateHealthIndicators();
  }
}

function appendUniqueTrailPoint(pose) {
  if (!pose) return;
  const trail = state.viz.trail;
  const last = trail[trail.length - 1];
  if (!last) {
    trail.push({ x: pose.x, y: pose.y, yaw: pose.yaw });
    return;
  }
  const distance = Math.hypot(pose.x - last.x, pose.y - last.y);
  const yawDelta = Math.abs(pose.yaw - last.yaw);
  if (distance > 0.01 || yawDelta > 0.04) {
    trail.push({ x: pose.x, y: pose.y, yaw: pose.yaw });
    if (trail.length > 1500) {
      trail.splice(0, trail.length - 1500);
    }
  }
}

function renderDiagnostics() {
  const status = state.status;
  if (!status) return;

  const diagnostics = safeArray(status.diagnostics?.items);
  const topicState = status.topics || {};
  const motorTone = topicAgeTone(topicState.wheel_odometry?.age_sec, 1.2, 3.0);
  const imuTone = topicAgeTone(topicState.imu?.age_sec, 1.2, 3.0);
  const odomTone = topicAgeTone(topicState.odom?.age_sec, 1.2, 3.0);
  const diagTopicTone = diagnostics.length
    ? levelTone(status.diagnostics?.highest_level ?? 0)
    : topicAgeTone(topicState.diagnostics?.age_sec, 2.0, 5.0);

  setToneClass($('#diagnostic-motor-status'), motorTone, motorTone === 'ok' ? 'OK' : motorTone === 'warn' ? 'STALE' : 'ERROR');
  $('#diagnostic-motor-detail').textContent = `wheel/odometry: ${formatAge(topicState.wheel_odometry?.age_sec)}`;

  setToneClass($('#diagnostic-imu-status'), imuTone, imuTone === 'ok' ? 'OK' : imuTone === 'warn' ? 'STALE' : 'ERROR');
  $('#diagnostic-imu-detail').textContent = `imu/data: ${formatAge(topicState.imu?.age_sec)}`;

  setToneClass($('#diagnostic-odom-status'), odomTone, odomTone === 'ok' ? 'OK' : odomTone === 'warn' ? 'STALE' : 'ERROR');
  $('#diagnostic-odom-detail').textContent = `odom: ${formatAge(topicState.odom?.age_sec)}`;

  setToneClass($('#diagnostic-topic-status'), diagTopicTone, diagnostics.length ? levelLabel(status.diagnostics?.highest_level ?? 0) : 'WAIT');
  $('#diagnostic-topic-detail').textContent = diagnostics.length
    ? `${diagnostics.length} сообщений`
    : `/diagnostics: ${formatAge(topicState.diagnostics?.age_sec)}`;

  const detailList = $('#diagnostic-details');
  detailList.innerHTML = '';
  if (!diagnostics.length) {
    const empty = document.createElement('div');
    empty.className = 'status-note';
    empty.textContent = 'Сообщения /diagnostics пока не поступали.';
    detailList.append(empty);
  } else {
    diagnostics.forEach((item) => {
      const card = document.createElement('article');
      card.className = 'diagnostic-item';
      const header = document.createElement('header');
      const title = document.createElement('strong');
      title.textContent = item.name || 'diagnostic';
      const badge = document.createElement('span');
      badge.className = `status-value ${levelTone(item.level)}`;
      badge.textContent = levelLabel(item.level);
      header.append(title, badge);

      const text = document.createElement('p');
      text.textContent = item.message || '—';

      const values = document.createElement('dl');
      Object.entries(item.values || {}).slice(0, 12).forEach(([key, value]) => {
        const dt = document.createElement('dt');
        dt.textContent = key;
        const dd = document.createElement('dd');
        dd.textContent = String(value);
        values.append(dt, dd);
      });

      card.append(header, text);
      if (values.children.length) {
        card.append(values);
      }
      detailList.append(card);
    });
  }
}

function renderActivity() {
  const container = $('#activity-list');
  container.innerHTML = '';
  if (!state.activity.length) {
    const empty = document.createElement('div');
    empty.className = 'status-note';
    empty.textContent = 'Журнал пока пуст.';
    container.append(empty);
    return;
  }

  state.activity.forEach((item) => {
    const card = document.createElement('article');
    card.className = 'activity-item';
    const header = document.createElement('header');
    const title = document.createElement('strong');
    title.textContent = `${item.source || 'web'} · ${new Date((item.timestamp || 0) * 1000).toLocaleTimeString()}`;
    const message = document.createElement('span');
    message.className = 'status-value';
    message.textContent = item.message || 'Activity';
    header.append(title, message);

    const body = document.createElement('p');
    body.textContent = item.message || '—';
    card.append(header, body);

    if (item.details && Object.keys(item.details).length) {
      const details = document.createElement('pre');
      details.className = 'message-box';
      details.textContent = pretty(item.details);
      card.append(details);
    }
    container.append(card);
  });
}

async function refreshActivity() {
  try {
    const payload = await api('/api/activity?limit=120');
    state.activity = safeArray(payload.items);
    renderActivity();
  } catch (error) {
    // Keep previous activity in place.
  }
}

function renderMotionStatus(motion) {
  const lines = [];
  if (!motion || !motion.running) {
    lines.push('Исполнитель не запущен.');
  } else {
    lines.push(`PID: ${motion.pid}`);
    lines.push(`Старт: ${motion.started_at ? new Date(motion.started_at * 1000).toLocaleString() : '—'}`);
    lines.push(`Команда: ${(motion.command || []).join(' ') || '—'}`);
    lines.push('');
  }
  if (motion?.return_code != null) {
    lines.push(`Последний код завершения: ${motion.return_code}`);
    lines.push('');
  }
  const logLines = safeArray(motion?.log);
  if (logLines.length) {
    lines.push(...logLines);
  }
  $('#motion-log').textContent = lines.join('\n');
  $('#route-stop').disabled = !motion?.running;
  $('#plan-run').disabled = Boolean(motion?.running);

  const warning = $('#drive-warning');
  if (motion?.running) {
    warning.textContent = 'Маршрут сейчас выполняется. Ручное управление может конфликтовать с исполнителем.';
    warning.classList.remove('hidden');
  } else {
    warning.classList.add('hidden');
    warning.textContent = '';
  }
}

function renderSettings() {
  if (state.identity) {
    $('#identity-json').textContent = pretty(state.identity);
  }
  if (state.config) {
    $('#config-json').textContent = pretty(state.config);
    $('#drive-topic-label').textContent = state.config.command_topic || '/cmd_vel';
  }
}

function configureTerminal() {
  const terminalButton = $('#nav-terminal');
  const web = state.config?.web || {};
  const enabled = Boolean(web.terminal_enabled);
  terminalButton.disabled = !enabled;

  const frame = $('#terminal-frame');
  const notice = $('#terminal-unavailable');
  if (!enabled) {
    notice.classList.remove('hidden');
    frame.src = 'about:blank';
    frame.classList.add('hidden');
    return;
  }

  notice.classList.add('hidden');
  frame.classList.remove('hidden');
}

function terminalUrl() {
  const web = state.config?.web || {};
  if (!web.terminal_enabled) return '';
  if (web.terminal_url) return web.terminal_url;
  const port = web.terminal_port || 7681;
  const path = web.terminal_path || '/terminal/';
  return `${location.protocol}//${location.hostname}:${port}${path}`;
}

function refreshTerminalFrame(force = false) {
  configureTerminal();
  const url = terminalUrl();
  if (!url) return;
  const frame = $('#terminal-frame');
  if (force || frame.src === 'about:blank') {
    frame.src = url;
  }
  $('#terminal-title').textContent = `Терминал: ${url}`;
}

async function refreshIdentityAndConfig() {
  try {
    const [identity, config] = await Promise.all([
      api('/api/identity'),
      api('/api/config'),
    ]);
    state.identity = identity;
    state.config = config;
    applyIdentity();
    renderSettings();
    configureTerminal();
    applyRouteDefaults(config);
    refreshDriveConfigFromConfig(config);
  } catch (error) {
    state.apiHealthy = false;
    updateHealthIndicators();
  }
}

async function refreshStatus() {
  try {
    const payload = await api('/api/status');
    state.status = payload;
    state.apiHealthy = true;
    state.rosHealthy = Boolean(payload.ok);
    if (!state.system) {
      state.system = payload.system;
    }
    if (!state.identity) {
      state.identity = payload.identity;
    }
    applyIdentity();
    appendUniqueTrailPoint(payload.odom);
    renderOverview();
    renderDiagnostics();
    renderVisualization();
    renderMotionStatus(payload.motion);
    updateHealthIndicators();
  } catch (error) {
    state.apiHealthy = false;
    state.rosHealthy = false;
    updateHealthIndicators();
  }
}

function renderList(element, items, selectedKey, factory) {
  element.innerHTML = '';
  if (!items.length) {
    const empty = document.createElement('div');
    empty.className = 'status-note';
    empty.textContent = 'Ничего не найдено.';
    element.append(empty);
    return;
  }
  items.forEach((item) => {
    const node = factory(item);
    if (selectedKey && node.dataset.key === selectedKey) {
      node.classList.add('active');
    }
    element.append(node);
  });
}

function filterByText(items, text, mapper) {
  const needle = text.trim().toLowerCase();
  if (!needle) return items;
  return items.filter((item) => mapper(item).toLowerCase().includes(needle));
}

async function refreshRosGraph() {
  try {
    const payload = await api('/api/ros/graph');
    state.rosGraph = payload;
    state.apiHealthy = true;
    state.rosHealthy = true;
    $('#ros-nodes-count').textContent = payload.nodes.length;
    $('#ros-topics-count').textContent = payload.topics.length;
    $('#ros-services-count').textContent = payload.services.length;
    $('#ros-image-count').textContent = payload.image_topics.length;
    renderNodes();
    renderTopics();
    renderServices();
    renderCameraTopics();
    updateHealthIndicators();
  } catch (error) {
    state.rosHealthy = false;
    updateHealthIndicators();
  }
}

function renderNodes() {
  const items = filterByText(
    safeArray(state.rosGraph?.nodes),
    $('#nodes-filter').value,
    (item) => `${item.full_name || ''} ${item.namespace || ''}`,
  );
  renderList($('#nodes-list'), items, null, (item) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'list-item';
    button.dataset.key = item.full_name || '';
    button.innerHTML = `<strong>${item.full_name || item.name || 'node'}</strong><small>${item.namespace || '/'}</small>`;
    return button;
  });
}

function renderTopics() {
  const items = filterByText(
    safeArray(state.rosGraph?.topics),
    $('#topics-filter').value,
    (item) => `${item.name || ''} ${(item.types || []).join(' ')}`,
  );
  renderList($('#topics-list'), items, state.selectedTopic, (item) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'list-item';
    button.dataset.key = item.name || '';
    const type = safeArray(item.types)[0] || 'unknown';
    const tags = [`pub ${item.publishers ?? 0}`, `sub ${item.subscribers ?? 0}`];
    if (item.is_image) tags.push('image');
    button.innerHTML = `<strong>${item.name || 'topic'}</strong><small>${type}</small><small>${tags.join(' · ')}</small>`;
    button.addEventListener('click', () => selectTopic(item.name, type));
    return button;
  });
}

function renderServices() {
  const items = filterByText(
    safeArray(state.rosGraph?.services),
    $('#services-filter').value,
    (item) => `${item.name || ''} ${(item.types || []).join(' ')}`,
  );
  renderList($('#services-list'), items, state.selectedService, (item) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'list-item';
    button.dataset.key = item.name || '';
    const type = safeArray(item.types)[0] || 'unknown';
    button.innerHTML = `<strong>${item.name || 'service'}</strong><small>${type}</small>`;
    button.addEventListener('click', () => selectService(item.name, type));
    return button;
  });
}

async function selectTopic(name, type) {
  state.selectedTopic = name;
  state.selectedTopicType = type;
  $('#topic-detail-title').textContent = name || 'Выбери топик';
  $('#topic-action-status').textContent = 'Загрузка топика...';
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
      { label: 'Age', value: info.age_sec == null ? '—' : formatAge(info.age_sec) },
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
    } else {
      $('#topic-payload').value = pretty(info.template || {});
      $('#topic-latest-message').textContent = pretty(info.latest_message || {});
      $('#topic-action-status').textContent = 'Можно публиковать JSON в этот топик.';
    }
  } catch (error) {
    $('#topic-action-status').textContent = String(error.message || error);
    $('#topic-latest-message').textContent = 'Ошибка чтения топика.';
  }
}

async function refreshSelectedTopic() {
  if (state.selectedTopic && state.selectedTopicType) {
    await selectTopic(state.selectedTopic, state.selectedTopicType);
  }
}

function restoreTopicTemplate() {
  if (state.selectedTopicInfo?.template) {
    $('#topic-payload').value = pretty(state.selectedTopicInfo.template);
  }
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
    showToast(`Опубликовано в ${state.selectedTopic}`);
    await recordActivity('Опубликовано сообщение в ROS topic', { topic: state.selectedTopic, type: state.selectedTopicType }, 'ros');
    await refreshSelectedTopic();
  } catch (error) {
    $('#topic-action-status').textContent = String(error.message || error);
    showToast(String(error.message || error), 'error');
  }
}

async function selectService(name, type) {
  state.selectedService = name;
  state.selectedServiceType = type;
  $('#service-detail-title').textContent = name || 'Выбери сервис';
  $('#service-action-status').textContent = 'Загрузка сервиса...';
  renderServices();
  try {
    const info = await api(`/api/ros/service?name=${encodeURIComponent(name)}&type=${encodeURIComponent(type)}`);
    state.selectedServiceInfo = info;
    renderDetailList($('#service-meta'), [
      { label: 'Type', value: info.type || '—' },
      { label: 'Ready', value: info.ready ? 'yes' : 'no' },
      { label: 'Available types', value: safeArray(info.available_types).join(', ') || '—' },
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
  if (state.selectedService && state.selectedServiceType) {
    await selectService(state.selectedService, state.selectedServiceType);
  }
}

function restoreServiceTemplate() {
  if (state.selectedServiceInfo?.request_template) {
    $('#service-request').value = pretty(state.selectedServiceInfo.request_template);
  }
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
    showToast(`Сервис ${state.selectedService} вызван`);
    await recordActivity('Вызван ROS service', { service: state.selectedService, type: state.selectedServiceType }, 'ros');
  } catch (error) {
    $('#service-action-status').textContent = String(error.message || error);
    showToast(String(error.message || error), 'error');
  }
}

function renderCameraTopics() {
  const select = $('#camera-topic-select');
  const topics = safeArray(state.rosGraph?.image_topics);
  select.innerHTML = '';
  if (!topics.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'Нет image topics';
    select.append(option);
    state.selectedCameraTopic = null;
    state.selectedCameraType = null;
    $('#camera-status').textContent = 'Камера не найдена.';
    return;
  }

  if (!topics.some((item) => item.name === state.selectedCameraTopic)) {
    state.selectedCameraTopic = topics[0].name;
    state.selectedCameraType = safeArray(topics[0].types)[0] || '';
  }

  topics.forEach((item) => {
    const option = document.createElement('option');
    option.value = item.name;
    option.dataset.type = safeArray(item.types)[0] || '';
    option.textContent = `${item.name} (${safeArray(item.types)[0] || 'unknown'})`;
    option.selected = item.name === state.selectedCameraTopic;
    select.append(option);
  });
}

async function refreshCameraStatus() {
  if (!state.selectedCameraTopic || !state.selectedCameraType) return;
  try {
    const info = await api(`/api/camera/status?topic=${encodeURIComponent(state.selectedCameraTopic)}&type=${encodeURIComponent(state.selectedCameraType)}`);
    renderDetailList($('#camera-meta'), [
      { label: 'Topic', value: info.topic || '—' },
      { label: 'Type', value: info.type || '—' },
      { label: 'Encoding', value: info.encoding || '—' },
      { label: 'Resolution', value: info.width && info.height ? `${info.width}×${info.height}` : '—' },
      { label: 'Frames', value: String(info.message_count ?? '—') },
      { label: 'Age', value: info.age_sec == null ? '—' : formatAge(info.age_sec) },
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
  fetchCameraFrame();
  state.cameraTimer = window.setInterval(() => {
    refreshCameraStatus();
    fetchCameraFrame();
  }, 350);
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

async function connectCamera() {
  const select = $('#camera-topic-select');
  state.selectedCameraTopic = select.value || null;
  state.selectedCameraType = select.selectedOptions[0]?.dataset.type || null;
  stopCameraLoop();
  if (!state.selectedCameraTopic || !state.selectedCameraType) {
    $('#camera-status').textContent = 'Нет выбранного источника.';
    return;
  }
  $('#camera-status').textContent = 'Подключение...';
  await recordActivity('Выбран источник камеры', { topic: state.selectedCameraTopic, type: state.selectedCameraType }, 'camera');
  await refreshCameraStatus();
  startCameraLoop();
}

function refreshDriveConfigFromConfig(config) {
  if (!config) return;
  const defaults = config.drive_defaults || {};
  const limits = config.drive_limits || {};

  $('#linear-speed').max = String(limits.linear_x ?? 0.35);
  $('#lateral-speed').max = String(limits.linear_y ?? 0.35);
  $('#angular-speed').max = String(limits.angular_z ?? 1.5);

  $('#linear-speed').value = String(defaults.linear_x ?? 0.18);
  $('#lateral-speed').value = String(defaults.linear_y ?? 0.16);
  $('#angular-speed').value = String(defaults.angular_z ?? 0.70);

  updateDriveOutputs();
  renderDetailList($('#drive-meta'), [
    { label: 'Command topic', value: config.command_topic || '/cmd_vel' },
    { label: 'Timeout', value: `${formatFloat(config.drive_command_timeout_sec, 2)} s` },
    { label: 'Linear max', value: formatFloat(limits.linear_x, 2) },
    { label: 'Lateral max', value: formatFloat(limits.linear_y, 2) },
    { label: 'Angular max', value: formatFloat(limits.angular_z, 2) },
  ]);
  $('#drive-topic-label').textContent = config.command_topic || '/cmd_vel';
}

async function refreshDriveConfig() {
  try {
    const payload = await api('/api/drive');
    $('#linear-speed').max = String(payload.limits.linear_x);
    $('#linear-speed').value = String(payload.defaults.linear_x);
    $('#lateral-speed').max = String(payload.limits.linear_y);
    $('#lateral-speed').value = String(payload.defaults.linear_y);
    $('#angular-speed').max = String(payload.limits.angular_z);
    $('#angular-speed').value = String(payload.defaults.angular_z);
    updateDriveOutputs();
    renderDetailList($('#drive-meta'), [
      { label: 'Command topic', value: payload.command_topic || '—' },
      { label: 'Timeout', value: `${formatFloat(payload.timeout_sec, 2)} s` },
      { label: 'Linear max', value: formatFloat(payload.limits.linear_x, 2) },
      { label: 'Lateral max', value: formatFloat(payload.limits.linear_y, 2) },
      { label: 'Angular max', value: formatFloat(payload.limits.angular_z, 2) },
    ]);
    $('#drive-topic-label').textContent = payload.command_topic || '/cmd_vel';
  } catch (error) {
    $('#drive-meta').innerHTML = '';
  }
}

function updateDriveOutputs() {
  $('#linear-speed-output').textContent = `${formatFloat($('#linear-speed').value, 2)} м/с`;
  $('#lateral-speed-output').textContent = `${formatFloat($('#lateral-speed').value, 2)} м/с`;
  $('#angular-speed-output').textContent = `${formatFloat($('#angular-speed').value, 2)} рад/с`;
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

  return {
    linearX: (forward - backward) * linear,
    linearY: (left - right) * lateral,
    angularZ: (rotateLeft - rotateRight) * angular,
  };
}

function updateDrivePreview(command) {
  $('#drive-preview').textContent = `linear.x: ${formatFloat(command.linearX, 2)}\nlinear.y: ${formatFloat(command.linearY, 2)}\nangular.z: ${formatFloat(command.angularZ, 2)}`;
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
    // Keep controls responsive even if the rover is temporarily unavailable.
  }
}

function syncDriveKeyHighlights() {
  $$('#keypad button[data-key]').forEach((button) => {
    button.classList.toggle('active', state.driveKeys.has(button.dataset.key));
  });
}

function startDriveLoop() {
  if (state.driveTimer) return;
  state.driveTimer = window.setInterval(() => {
    if (state.driveKeys.size > 0) {
      sendDriveCommand();
    }
  }, 120);
}

function stopDriveLoop() {
  if (state.driveTimer) {
    window.clearInterval(state.driveTimer);
    state.driveTimer = null;
  }
}

async function stopDrive() {
  stopDriveLoop();
  state.driveKeys.clear();
  syncDriveKeyHighlights();
  updateDrivePreview({ linearX: 0, linearY: 0, angularZ: 0 });
  try {
    await api('/api/drive/stop', { method: 'POST', body: '{}' });
  } catch (error) {
    // no-op
  }
}

async function issueGlobalStop() {
  await Promise.allSettled([
    api('/api/stop', {
      method: 'POST',
      body: JSON.stringify({
        source: 'web',
        details: { session_id: state.sessionId, page: state.page },
      }),
    }),
    api('/api/drive/stop', { method: 'POST', body: '{}' }),
    api('/api/motion/stop', { method: 'POST', body: '{}' }),
  ]);
  await stopDrive();
  showToast('STOP отправлен', 'error');
  await refreshStatus();
}

function applyRouteDefaults(config) {
  if (!config) return;
  const recommended = config.recommended || {};
  const limits = config.drive_limits || {};
  const angular = recommended.manual_angular_speed_radps ?? config.drive_defaults?.angular_z ?? 0.32;
  const shouldApply = !state.route.draft || !safeArray(state.route.draft.steps).length;
  if (!shouldApply) return;

  $('#route-default-linear').value = String(recommended.manual_linear_speed_mps ?? config.drive_defaults?.linear_x ?? 0.18);
  $('#route-default-approach').value = String(Math.min(recommended.manual_linear_speed_mps ?? 0.18, 0.10));
  $('#route-default-position-tolerance').value = '0.07';
  $('#route-default-angular').value = String(Math.min(angular, limits.angular_z ?? angular));
  $('#route-default-angle-tolerance').value = '3';
  $('#route-default-time').value = '45';

  if (!state.route.draft) {
    state.route.draft = createBlankPlan();
  } else {
    updateDraftDefaults();
  }
}

function currentRouteDefaults() {
  return {
    linear_speed: Number($('#route-default-linear').value || '0.18'),
    approach_speed: Number($('#route-default-approach').value || '0.10'),
    position_tolerance: Number($('#route-default-position-tolerance').value || '0.07'),
    angular_speed: Number($('#route-default-angular').value || '0.32'),
    minimum_angular_speed: 0.10,
    angle_tolerance_deg: Number($('#route-default-angle-tolerance').value || '3'),
    maximum_step_time: Number($('#route-default-time').value || '45'),
  };
}

function applyDefaultsToInputs(defaults = {}) {
  $('#route-default-linear').value = String(defaults.linear_speed ?? 0.18);
  $('#route-default-approach').value = String(defaults.approach_speed ?? 0.10);
  $('#route-default-position-tolerance').value = String(defaults.position_tolerance ?? 0.07);
  $('#route-default-angular').value = String(defaults.angular_speed ?? 0.32);
  $('#route-default-angle-tolerance').value = String(defaults.angle_tolerance_deg ?? 3);
  $('#route-default-time').value = String(defaults.maximum_step_time ?? 45);
}

function normalizePlanName(name) {
  const trimmed = String(name || '').trim();
  if (!trimmed) return 'web_route.yaml';
  return trimmed.endsWith('.yaml') || trimmed.endsWith('.yml') ? trimmed : `${trimmed}.yaml`;
}

function createBlankPlan() {
  return {
    defaults: currentRouteDefaults(),
    steps: [],
  };
}

function createStep(type) {
  const step = { type };
  safeArray(ROUTE_STEP_FIELDS[type]).forEach((field) => {
    if (field.required) {
      step[field.key] = field.defaultValue;
    } else if (field.type === 'checkbox') {
      step[field.key] = field.defaultValue;
    }
  });
  return step;
}

function currentDraftPlan() {
  return state.route.draft || createBlankPlan();
}

function updateRouteStepCount() {
  const count = safeArray(currentDraftPlan().steps).length;
  $('#route-step-count').textContent = `${count} ${count === 1 ? 'шаг' : count < 5 ? 'шага' : 'шагов'}`;
  $('#route-empty').classList.toggle('hidden', count > 0);
}

function updateDraftDefaults() {
  const plan = currentDraftPlan();
  plan.defaults = currentRouteDefaults();
  state.route.draft = plan;
}

function renderRouteSteps() {
  const container = $('#route-step-list');
  container.innerHTML = '';
  const steps = safeArray(currentDraftPlan().steps);

  steps.forEach((step, index) => {
    const card = document.createElement('article');
    card.className = 'route-step';
    card.dataset.index = String(index);

    const header = document.createElement('div');
    header.className = 'route-step-header';

    const title = document.createElement('div');
    title.className = 'route-step-title';
    const number = document.createElement('span');
    number.className = 'route-step-number';
    number.textContent = String(index + 1);
    const label = document.createElement('span');
    label.textContent = ROUTE_STEP_LABELS[step.type] || step.type;
    title.append(number, label);

    const actions = document.createElement('div');
    actions.className = 'route-step-actions';
    actions.innerHTML = `
      <button class="secondary" type="button" data-action="up" ${index === 0 ? 'disabled' : ''}>↑</button>
      <button class="secondary" type="button" data-action="down" ${index === steps.length - 1 ? 'disabled' : ''}>↓</button>
      <button class="danger-secondary" type="button" data-action="delete">✕</button>
    `;

    header.append(title, actions);
    card.append(header);

    const fieldsWrap = document.createElement('div');
    fieldsWrap.className = 'route-step-fields';
    safeArray(ROUTE_STEP_FIELDS[step.type]).forEach((field) => {
      const labelEl = document.createElement('label');
      labelEl.textContent = field.label;
      const input = document.createElement('input');
      input.dataset.field = field.key;
      input.dataset.index = String(index);
      input.type = field.type === 'checkbox' ? 'checkbox' : 'number';
      if (field.type === 'checkbox') {
        input.checked = step[field.key] !== undefined ? Boolean(step[field.key]) : Boolean(field.defaultValue);
      } else {
        if (field.step) input.step = field.step;
        if (field.required) input.required = true;
        if (field.placeholder) input.placeholder = field.placeholder;
        input.value = step[field.key] !== undefined && step[field.key] !== null
          ? String(step[field.key])
          : '';
      }
      labelEl.append(input);
      fieldsWrap.append(labelEl);
    });
    card.append(fieldsWrap);
    container.append(card);
  });

  updateRouteStepCount();
  renderRoutePreview();
}

function renderPlanList() {
  const select = $('#plan-select');
  select.innerHTML = '';
  if (!state.route.plans.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = 'Сохранённых маршрутов нет';
    select.append(option);
    return;
  }
  state.route.plans.forEach((item) => {
    const option = document.createElement('option');
    option.value = item.name;
    option.textContent = `${item.name} · ${item.steps} шагов`;
    option.selected = item.name === state.route.selectedName;
    select.append(option);
  });
}

async function refreshPlanList() {
  try {
    const payload = await api('/api/plans');
    state.route.plans = safeArray(payload.plans);
    if (!state.route.selectedName && state.route.plans.length) {
      state.route.selectedName = state.route.plans[0].name;
    }
    renderPlanList();
  } catch (error) {
    showToast(String(error.message || error), 'error');
  }
}

async function loadPlan(name) {
  const normalized = normalizePlanName(name);
  try {
    const payload = await api(`/api/plans/${encodeURIComponent(normalized)}`);
    state.route.selectedName = payload.name || normalized;
    state.route.draft = payload.plan || createBlankPlan();
    $('#plan-name').value = state.route.selectedName;
    applyDefaultsToInputs(state.route.draft.defaults || {});
    renderPlanList();
    renderRouteSteps();
    showToast(`Маршрут ${state.route.selectedName} загружен`);
    await recordActivity('Загружен маршрут', { name: state.route.selectedName }, 'routes');
  } catch (error) {
    showToast(String(error.message || error), 'error');
  }
}

function newPlan() {
  state.route.selectedName = '';
  state.route.draft = createBlankPlan();
  $('#plan-name').value = 'web_route.yaml';
  renderPlanList();
  renderRouteSteps();
  showToast('Создан новый маршрут');
}

async function savePlan({ silent = false } = {}) {
  const name = normalizePlanName($('#plan-name').value);
  const plan = deepClone(currentDraftPlan());
  plan.defaults = currentRouteDefaults();
  if (!safeArray(plan.steps).length) {
    throw new Error('Маршрут должен содержать хотя бы один шаг');
  }
  await api('/api/plans/save', {
    method: 'POST',
    body: JSON.stringify({ name, plan }),
  });
  state.route.selectedName = name;
  state.route.draft = plan;
  $('#plan-name').value = name;
  await refreshPlanList();
  renderPlanList();
  if (!silent) {
    showToast(`Маршрут ${name} сохранён`);
    await recordActivity('Сохранён маршрут', { name, steps: plan.steps.length }, 'routes');
  }
  return name;
}

async function runSelectedPlan() {
  try {
    const name = await savePlan({ silent: true });
    const payload = await api('/api/motion/start', {
      method: 'POST',
      body: JSON.stringify({ kind: 'plan', name }),
    });
    renderMotionStatus(payload.motion);
    showToast(`Маршрут ${name} запущен`);
    await recordActivity('Запущен маршрут', { name }, 'routes');
  } catch (error) {
    showToast(String(error.message || error), 'error');
  }
}

async function stopMotion() {
  try {
    const payload = await api('/api/motion/stop', { method: 'POST', body: '{}' });
    renderMotionStatus(payload.motion);
    showToast('Маршрут остановлен', 'warn');
  } catch (error) {
    showToast(String(error.message || error), 'error');
  }
}

function renderRoutePreview() {
  const canvas = $('#route-preview-canvas');
  const ctx = setupCanvas(canvas);
  if (!ctx) return;

  const plan = currentDraftPlan();
  const points = simulatePlan(plan);
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = '#f9fdff';
  ctx.fillRect(0, 0, width, height);

  const bounds = pathBounds(points);
  const margin = 24;
  const usableWidth = Math.max(1, width - margin * 2);
  const usableHeight = Math.max(1, height - margin * 2);
  const rangeX = Math.max(0.5, bounds.maxX - bounds.minX);
  const rangeY = Math.max(0.5, bounds.maxY - bounds.minY);
  const scale = Math.min(usableWidth / rangeX, usableHeight / rangeY);
  const centerX = (bounds.minX + bounds.maxX) / 2;
  const centerY = (bounds.minY + bounds.maxY) / 2;

  const toScreen = (point) => ({
    x: width / 2 + (point.x - centerX) * scale,
    y: height / 2 - (point.y - centerY) * scale,
  });

  drawGrid(ctx, width, height, scale, centerX, centerY);

  const origin = toScreen({ x: 0, y: 0 });
  ctx.strokeStyle = '#c93644';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.arc(origin.x, origin.y, 6, 0, Math.PI * 2);
  ctx.stroke();

  if (points.length > 1) {
    ctx.strokeStyle = '#16b8f3';
    ctx.lineWidth = 3;
    ctx.beginPath();
    points.forEach((point, index) => {
      const screen = toScreen(point);
      if (index === 0) {
        ctx.moveTo(screen.x, screen.y);
      } else {
        ctx.lineTo(screen.x, screen.y);
      }
    });
    ctx.stroke();
  }

  points.forEach((point, index) => {
    const screen = toScreen(point);
    ctx.fillStyle = index === points.length - 1 ? '#075f89' : '#16b8f3';
    ctx.beginPath();
    ctx.arc(screen.x, screen.y, index === points.length - 1 ? 5 : 3, 0, Math.PI * 2);
    ctx.fill();
  });

  const finalPose = points[points.length - 1] || { x: 0, y: 0, yaw: 0 };
  drawRoverArrow(ctx, toScreen(finalPose), finalPose.yaw, '#075f89', 18);
}

function simulatePlan(plan) {
  const pose = { x: 0, y: 0, yaw: 0 };
  const points = [{ ...pose }];
  safeArray(plan.steps).forEach((step) => {
    const type = step.type;
    if (type === 'move') {
      applyRelativeMove(pose, Number(step.forward || 0), Number(step.left || 0));
      points.push({ ...pose });
    } else if (type === 'move_polar') {
      const distance = Number(step.distance || 0);
      const directionRad = Number(step.direction_deg || 0) * Math.PI / 180;
      applyRelativeMove(pose, distance * Math.cos(directionRad), distance * Math.sin(directionRad));
      points.push({ ...pose });
    } else if (type === 'turn') {
      pose.yaw += Number(step.degrees || 0) * Math.PI / 180;
      points.push({ ...pose });
    } else if (type === 'return_to_start') {
      pose.x = 0;
      pose.y = 0;
      if (step.restore_heading !== false) {
        pose.yaw = 0;
      }
      points.push({ ...pose });
    }
  });
  return points;
}

function applyRelativeMove(pose, forward, left) {
  const cosine = Math.cos(pose.yaw);
  const sine = Math.sin(pose.yaw);
  pose.x += cosine * forward - sine * left;
  pose.y += sine * forward + cosine * left;
}

function pathBounds(points) {
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  return {
    minX: Math.min(...xs, -0.25),
    maxX: Math.max(...xs, 0.25),
    minY: Math.min(...ys, -0.25),
    maxY: Math.max(...ys, 0.25),
  };
}

function setupCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const dpr = window.devicePixelRatio || 1;
  const width = Math.round(rect.width * dpr);
  const height = Math.round(rect.height * dpr);
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return ctx;
}

function drawGrid(ctx, width, height, scale, centerX, centerY) {
  const spacingMeters = scale >= 180 ? 0.25 : scale >= 100 ? 0.5 : 1.0;
  const left = centerX - width / (2 * scale);
  const right = centerX + width / (2 * scale);
  const bottom = centerY - height / (2 * scale);
  const top = centerY + height / (2 * scale);

  ctx.strokeStyle = '#e3edf2';
  ctx.lineWidth = 1;
  for (let x = Math.floor(left / spacingMeters) * spacingMeters; x <= right; x += spacingMeters) {
    const sx = width / 2 + (x - centerX) * scale;
    ctx.beginPath();
    ctx.moveTo(sx, 0);
    ctx.lineTo(sx, height);
    ctx.stroke();
  }
  for (let y = Math.floor(bottom / spacingMeters) * spacingMeters; y <= top; y += spacingMeters) {
    const sy = height / 2 - (y - centerY) * scale;
    ctx.beginPath();
    ctx.moveTo(0, sy);
    ctx.lineTo(width, sy);
    ctx.stroke();
  }

  ctx.strokeStyle = '#91cfe7';
  ctx.lineWidth = 1.2;
  const axisX = width / 2 + (0 - centerX) * scale;
  const axisY = height / 2 - (0 - centerY) * scale;
  ctx.beginPath();
  ctx.moveTo(axisX, 0);
  ctx.lineTo(axisX, height);
  ctx.stroke();
  ctx.beginPath();
  ctx.moveTo(0, axisY);
  ctx.lineTo(width, axisY);
  ctx.stroke();
}

function drawRoverArrow(ctx, point, yaw, color, size) {
  ctx.save();
  ctx.translate(point.x, point.y);
  ctx.rotate(-yaw);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(size, 0);
  ctx.lineTo(-size * 0.6, size * 0.55);
  ctx.lineTo(-size * 0.25, 0);
  ctx.lineTo(-size * 0.6, -size * 0.55);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function renderVisualization() {
  const canvas = $('#odom-canvas');
  const ctx = setupCanvas(canvas);
  if (!ctx) return;

  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = '#f9fdff';
  ctx.fillRect(0, 0, width, height);

  const pose = state.status?.odom;
  const trail = state.viz.trail;
  $('#viz-empty').classList.toggle('hidden', Boolean(pose));
  $('#viz-position').textContent = pose
    ? `Позиция: x=${formatFloat(pose.x, 2)} м, y=${formatFloat(pose.y, 2)} м`
    : 'Позиция: —';
  $('#viz-yaw').textContent = `Курс: ${pose ? formatAngleRad(pose.yaw) : '—'}`;
  $('#viz-points').textContent = `Точек: ${trail.length}`;

  if (!pose) return;

  const scale = Number($('#viz-scale').value || state.viz.scale);
  state.viz.scale = scale;
  localStorage.setItem(STORAGE_KEYS.vizScale, String(scale));
  const follow = $('#viz-follow').checked;
  state.viz.follow = follow;
  localStorage.setItem(STORAGE_KEYS.vizFollow, follow ? 'true' : 'false');

  let centerX = pose.x;
  let centerY = pose.y;
  if (!follow && trail.length) {
    const bounds = pathBounds(trail);
    centerX = (bounds.minX + bounds.maxX) / 2;
    centerY = (bounds.minY + bounds.maxY) / 2;
  }

  drawGrid(ctx, width, height, scale, centerX, centerY);
  const toScreen = (point) => ({
    x: width / 2 + (point.x - centerX) * scale,
    y: height / 2 - (point.y - centerY) * scale,
  });

  if (trail.length > 1) {
    ctx.strokeStyle = '#16b8f3';
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    trail.forEach((point, index) => {
      const screen = toScreen(point);
      if (index === 0) ctx.moveTo(screen.x, screen.y);
      else ctx.lineTo(screen.x, screen.y);
    });
    ctx.stroke();
  }

  drawRoverArrow(ctx, toScreen(pose), pose.yaw, '#075f89', 18);
}

async function sendHeartbeat() {
  try {
    await api('/api/heartbeat', {
      method: 'POST',
      body: JSON.stringify({
        session_id: state.sessionId,
        page: state.page,
      }),
    });
  } catch (error) {
    // Best effort only.
  }
}

function bindNavigation() {
  $$('.nav-item[data-page]').forEach((button) => {
    button.addEventListener('click', () => {
      if (button.disabled) return;
      setPage(button.dataset.page);
    });
  });
  $('#menu-toggle').addEventListener('click', () => {
    $('#sidebar').classList.toggle('open');
  });
}

function bindOverviewPage() {
  $('#overview-refresh').addEventListener('click', async () => {
    await Promise.all([refreshSystem(), refreshStatus()]);
  });
}

function bindRosPage() {
  $('#nodes-filter').addEventListener('input', renderNodes);
  $('#topics-filter').addEventListener('input', renderTopics);
  $('#services-filter').addEventListener('input', renderServices);
  $('#ros-refresh').addEventListener('click', refreshRosGraph);
  $('#topic-refresh').addEventListener('click', refreshSelectedTopic);
  $('#topic-template').addEventListener('click', restoreTopicTemplate);
  $('#topic-publish').addEventListener('click', publishSelectedTopic);
  $('#service-refresh').addEventListener('click', refreshSelectedService);
  $('#service-template').addEventListener('click', restoreServiceTemplate);
  $('#service-call').addEventListener('click', callSelectedService);
}

function bindCameraPage() {
  $('#camera-refresh-topics').addEventListener('click', refreshRosGraph);
  $('#camera-connect').addEventListener('click', connectCamera);
  $('#camera-topic-select').addEventListener('change', () => {
    state.selectedCameraTopic = $('#camera-topic-select').value || null;
    state.selectedCameraType = $('#camera-topic-select').selectedOptions[0]?.dataset.type || null;
  });
}

function shouldIgnoreDriveKeyEvent(target) {
  const tag = target?.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target?.isContentEditable;
}

function bindDrivePage() {
  ['linear-speed', 'lateral-speed', 'angular-speed'].forEach((id) => {
    $(`#${id}`).addEventListener('input', () => {
      updateDriveOutputs();
      updateDrivePreview(computeDriveCommand());
    });
  });

  $('#drive-stop').addEventListener('click', stopDrive);
  $('#global-stop').addEventListener('click', issueGlobalStop);

  $$('#keypad button[data-key]').forEach((button) => {
    const activate = async () => {
      state.driveKeys.add(button.dataset.key);
      syncDriveKeyHighlights();
      startDriveLoop();
      await sendDriveCommand();
    };
    const release = async () => {
      state.driveKeys.delete(button.dataset.key);
      syncDriveKeyHighlights();
      if (state.driveKeys.size === 0) {
        stopDriveLoop();
      }
      await sendDriveCommand();
    };
    button.addEventListener('pointerdown', activate);
    button.addEventListener('pointerup', release);
    button.addEventListener('pointerleave', release);
    button.addEventListener('pointercancel', release);
  });

  window.addEventListener('keydown', (event) => {
    if (shouldIgnoreDriveKeyEvent(event.target)) return;
    if (event.code === 'Space') {
      event.preventDefault();
      stopDrive();
      return;
    }
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
  window.addEventListener('beforeunload', stopDrive);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopDrive();
    }
  });
}

function bindRoutesPage() {
  ['route-default-linear', 'route-default-approach', 'route-default-position-tolerance', 'route-default-angular', 'route-default-angle-tolerance', 'route-default-time']
    .forEach((id) => {
      $(`#${id}`).addEventListener('input', () => {
        updateDraftDefaults();
        renderRoutePreview();
      });
    });

  $$('[data-add-step]').forEach((button) => {
    button.addEventListener('click', () => {
      currentDraftPlan().steps.push(createStep(button.dataset.addStep));
      renderRouteSteps();
    });
  });

  $('#route-step-list').addEventListener('click', (event) => {
    const action = event.target.dataset.action;
    if (!action) return;
    const card = event.target.closest('.route-step');
    const index = Number(card?.dataset.index);
    if (!Number.isFinite(index)) return;
    const steps = currentDraftPlan().steps;

    if (action === 'delete') {
      steps.splice(index, 1);
    } else if (action === 'up' && index > 0) {
      [steps[index - 1], steps[index]] = [steps[index], steps[index - 1]];
    } else if (action === 'down' && index < steps.length - 1) {
      [steps[index + 1], steps[index]] = [steps[index], steps[index + 1]];
    }
    renderRouteSteps();
  });

  $('#route-step-list').addEventListener('input', (event) => {
    const index = Number(event.target.dataset.index);
    const field = event.target.dataset.field;
    if (!Number.isFinite(index) || !field) return;
    const step = currentDraftPlan().steps[index];
    const fieldSpec = safeArray(ROUTE_STEP_FIELDS[step.type]).find((item) => item.key === field);
    if (!fieldSpec) return;

    if (fieldSpec.type === 'checkbox') {
      step[field] = event.target.checked;
    } else {
      const valueText = event.target.value;
      if (valueText === '') {
        if (fieldSpec.required) {
          step[field] = fieldSpec.defaultValue ?? 0;
        } else {
          delete step[field];
        }
      } else {
        step[field] = Number(valueText);
      }
    }
    renderRoutePreview();
  });

  $('#plan-refresh').addEventListener('click', refreshPlanList);
  $('#plan-select').addEventListener('change', (event) => {
    const name = event.target.value;
    if (name) loadPlan(name);
  });
  $('#plan-new').addEventListener('click', newPlan);
  $('#plan-save').addEventListener('click', async () => {
    try {
      await savePlan();
    } catch (error) {
      showToast(String(error.message || error), 'error');
    }
  });
  $('#plan-run').addEventListener('click', runSelectedPlan);
  $('#route-stop').addEventListener('click', stopMotion);
}

function bindVisualizationPage() {
  $('#viz-scale').value = String(state.viz.scale);
  $('#viz-follow').checked = state.viz.follow;
  $('#viz-scale').addEventListener('input', renderVisualization);
  $('#viz-follow').addEventListener('change', renderVisualization);
  $('#viz-clear').addEventListener('click', () => {
    state.viz.trail = [];
    renderVisualization();
  });
}

function bindTerminalPage() {
  $('#terminal-reload').addEventListener('click', () => {
    refreshTerminalFrame(true);
  });
}

function bindDiagnosticsPage() {
  $('#diagnostics-refresh').addEventListener('click', async () => {
    await Promise.all([refreshStatus(), refreshActivity()]);
  });
}

function bindSettingsPage() {
  bindCompactMode();
}

function refreshPeriodicData() {
  refreshStatus();
  if (state.page === 'overview' || !state.system) {
    refreshSystem();
  }
  if (state.page === 'ros' || !state.rosGraph) {
    refreshRosGraph();
    refreshSelectedTopic();
    refreshSelectedService();
  }
  if (state.page === 'diagnostics') {
    refreshActivity();
  }
  if (state.page === 'camera' && state.selectedCameraTopic && state.selectedCameraType && !state.cameraTimer) {
    connectCamera();
  }
}

async function initialize() {
  bindNavigation();
  bindOverviewPage();
  bindRosPage();
  bindCameraPage();
  bindDrivePage();
  bindRoutesPage();
  bindVisualizationPage();
  bindTerminalPage();
  bindDiagnosticsPage();
  bindSettingsPage();

  state.route.draft = createBlankPlan();
  updateDrivePreview({ linearX: 0, linearY: 0, angularZ: 0 });
  renderRouteSteps();

  await Promise.all([
    refreshIdentityAndConfig(),
    refreshSystem(),
    refreshStatus(),
    refreshRosGraph(),
    refreshDriveConfig(),
    refreshPlanList(),
    refreshActivity(),
  ]);

  if (!state.route.plans.length) {
    newPlan();
  } else if (state.route.selectedName) {
    await loadPlan(state.route.selectedName);
  }

  setPage(['overview', 'ros', 'camera', 'drive', 'routes', 'visualization', 'terminal', 'diagnostics', 'settings'].includes(state.page)
    ? state.page
    : 'overview');
  renderSettings();
  renderVisualization();
  renderRoutePreview();

  await recordActivity('Web session started', {
    session_id: state.sessionId,
    user_agent: navigator.userAgent,
  }, 'web');

  await sendHeartbeat();

  window.setInterval(sendHeartbeat, 5000);
  window.setInterval(refreshPeriodicData, 1500);
  window.setInterval(() => {
    if (state.page === 'overview' || state.page === 'settings') {
      refreshIdentityAndConfig();
    }
  }, 12000);
  window.addEventListener('resize', () => {
    renderVisualization();
    renderRoutePreview();
  });
}

initialize().catch((error) => {
  state.apiHealthy = false;
  state.rosHealthy = false;
  updateHealthIndicators();
  showToast(`Ошибка инициализации: ${error.message || error}`, 'error');
  console.error(error);
});
