'use strict';

import { RosbridgeClient } from './rosbridge-client.js';

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function createSessionId() {
  if (globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }
  return `sverh-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function storageGet(name, key) {
  try { return globalThis[name]?.getItem(key) ?? null; } catch { return null; }
}

function storageSet(name, key, value) {
  try { globalThis[name]?.setItem(key, value); } catch { /* optional browser storage */ }
}

const sessionId = storageGet('sessionStorage', 'sverhSessionId') || createSessionId();
storageSet('sessionStorage', 'sverhSessionId', sessionId);

const websocketScheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
let ros = null;

const DEFAULT_PLAN_DEFAULTS = {
  linear_speed: 0.18,
  approach_speed: 0.10,
  position_tolerance: 0.07,
  angular_speed: 0.32,
  minimum_angular_speed: 0.10,
  angle_tolerance_deg: 3.0,
  maximum_step_time: 45.0,
};

const state = {
  page: 'overview',
  identity: null,
  config: null,
  status: null,
  graph: { topics: [] },
  selectedTopic: null,
  topicSubscriptionId: null,
  topicMessageCount: 0,
  vizSubscriptionId: null,
  vizPoints: [],
  vizPose: null,
  vizOrigin: null,
  driveKeys: new Set(),
  driveTimer: null,
  routePlan: { defaults: { ...DEFAULT_PLAN_DEFAULTS }, steps: [] },
};

function defaultConfig() {
  return {
    command_topic: '/cmd_vel',
    web_command_topic: '/web/cmd_vel',
    limits: { max_wheel_speed_mps: 0.35 },
    web: {
      rosbridge_url: '',
      rosbridge_port: 9090,
      rosbridge_path: '/rosbridge',
      rosbridge_server_path: '/',
      terminal_enabled: true,
      terminal_url: '',
      terminal_port: 7681,
      terminal_path: '/terminal/',
    },
  };
}

function webConfig() {
  return state.config?.web || defaultConfig().web;
}

function currentHostname() {
  return location.hostname || window.location.hostname || 'localhost';
}

function absoluteUrl(value, scheme) {
  if (!value) return '';
  if (/^[a-z]+:\/\//i.test(value)) return value;
  if (value.startsWith('/')) return `${scheme}//${location.host}${value}`;
  return `${scheme}//${location.host}/${value.replace(/^\.?\//, '')}`;
}

function normalizePath(value, fallback = '/') {
  if (!value) return fallback;
  return value.startsWith('/') ? value : `/${value}`;
}

function normalizePort(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function isLikelyReverseProxyOrigin() {
  const port = location.port;
  return port === '' || port === '80' || port === '443';
}

function resolveRosbridgeUrl() {
  const web = webConfig();
  const explicit = absoluteUrl(web.rosbridge_url, websocketScheme);
  if (explicit) return explicit;
  const proxyPath = normalizePath(web.rosbridge_path, '/rosbridge');
  if (proxyPath !== '/' && isLikelyReverseProxyOrigin()) {
    return `${websocketScheme}//${location.host}${proxyPath}`;
  }
  const port = normalizePort(web.rosbridge_port) ?? 9090;
  return `${websocketScheme}//${currentHostname()}:${port}${normalizePath(web.rosbridge_server_path, '/')}`;
}

function resolveTerminalUrl() {
  const web = webConfig();
  const explicit = absoluteUrl(web.terminal_url, location.protocol);
  if (explicit) return explicit;
  const proxyPath = normalizePath(web.terminal_path, '/terminal/');
  if (isLikelyReverseProxyOrigin()) {
    return `${location.protocol}//${location.host}${proxyPath}`;
  }
  const port = normalizePort(web.terminal_port) ?? 7681;
  return `${location.protocol}//${currentHostname()}:${port}${proxyPath}`;
}

function terminalEnabled() {
  const web = webConfig();
  return Boolean(web.terminal_enabled);
}

function isRosConnected() {
  return Boolean(ros && ros.connected);
}

function configureTerminal() {
  const navButton = $('#nav-terminal');
  const reloadButton = $('#terminal-reload');
  const frame = $('#terminal-frame');
  const notice = $('#terminal-unavailable');
  const enabled = terminalEnabled();

  navButton.disabled = !enabled;
  reloadButton.disabled = !enabled;

  if (enabled) {
    frame.src = resolveTerminalUrl();
    frame.classList.remove('hidden');
    notice.classList.add('hidden');
    return;
  }

  frame.removeAttribute('src');
  frame.classList.add('hidden');
  notice.textContent = 'Веб-терминал не настроен для этого запуска. Для него нужен ttyd и путь /terminal/.';
  notice.classList.remove('hidden');

  if (state.page === 'terminal') {
    showPage('overview');
  }
}

function connectRos() {
  ros = new RosbridgeClient(resolveRosbridgeUrl());
  ros.addEventListener('state', (event) => updateRosState(event.detail));
  ros.addEventListener('status', (event) => {
    const status = event.detail;
    if (status.level === 'error') toast(`rosbridge: ${status.msg}`, 'error');
  });
  ros.connect();
}

function toast(message, kind = '') {
  const item = document.createElement('div');
  item.className = `toast ${kind}`;
  item.textContent = message;
  $('#toast-container').append(item);
  window.setTimeout(() => item.remove(), 4500);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    cache: 'no-store',
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `${response.status} ${response.statusText}`);
  return payload;
}

function postActivity(source, message, details = {}) {
  api('/api/activity', {
    method: 'POST',
    body: JSON.stringify({ source, message, details }),
  }).catch(() => {});
}

function formatNumber(value, digits = 2) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';
}

function bytesToGiB(value) {
  return Number.isFinite(value) ? value / (1024 ** 3) : null;
}

function ageState(age, warn, error) {
  if (age === null || age === undefined) return ['NO DATA', 'error'];
  if (age > error) return [`STALE ${age.toFixed(1)}s`, 'error'];
  if (age > warn) return [`WARN ${age.toFixed(1)}s`, 'warn'];
  return [`OK ${age.toFixed(2)}s`, 'ok'];
}

function setPill(element, text, kind) {
  element.textContent = text;
  element.className = `status-pill ${kind}`;
}

function setDot(element, kind) {
  element.className = `dot ${kind}`;
}

function setStatusValue(element, text, kind) {
  element.textContent = text;
  element.className = `status-value ${kind}`;
}

function renderStatusRows(element, rows) {
  element.replaceChildren();
  for (const row of rows) {
    const container = document.createElement('div');
    container.className = 'status-row';
    const left = document.createElement('div');
    const title = document.createElement('div');
    title.textContent = row.title;
    const detail = document.createElement('small');
    detail.textContent = row.detail || '';
    left.append(title, detail);
    const value = document.createElement('span');
    value.className = `status-value ${row.kind || ''}`;
    value.textContent = row.value;
    container.append(left, value);
    element.append(container);
  }
}

async function initialize() {
  bindNavigation();
  bindGlobalActions();
  bindDrive();
  bindRoutes();
  bindRosExplorer();
  bindVisualization();
  bindSettings();

  const compact = storageGet('localStorage', 'sverhCompact') === 'true';
  $('#compact-mode').checked = compact;
  document.body.classList.toggle('compact', compact);

  const [identityResult, configResult] = await Promise.allSettled([
    api('/api/identity'),
    api('/api/config'),
  ]);

  if (identityResult.status === 'fulfilled') {
    state.identity = identityResult.value;
  } else {
    toast(`Идентичность ровера: ${identityResult.reason?.message || 'ошибка связи'}`, 'error');
  }

  if (configResult.status === 'fulfilled') {
    state.config = configResult.value;
    setDot($('#api-dot'), 'ok');
  } else {
    state.config = defaultConfig();
    setDot($('#api-dot'), 'error');
    toast(`Конфигурация web gateway: ${configResult.reason?.message || 'ошибка связи'}`, 'error');
  }

  renderIdentity();
  configureDriveLimits();
  configureTerminal();
  connectRos();

  newRoutePlan(false);
  refreshPlans();
  statusLoop();
  heartbeatLoop();
}

function bindNavigation() {
  $$('.nav-item').forEach((button) => {
    button.addEventListener('click', () => showPage(button.dataset.page));
  });
  $('#menu-toggle').addEventListener('click', () => $('#sidebar').classList.toggle('open'));
}

function showPage(page) {
  if (page === 'terminal' && !terminalEnabled()) {
    toast('Веб-терминал не включён для этого запуска', 'warn');
    page = 'overview';
  }
  if (state.page === 'drive' && page !== 'drive') stopDrive('left drive page');
  if (state.page === 'visualization' && page !== 'visualization') stopVisualization();
  if (state.page === 'ros-explorer' && page !== 'ros-explorer') unsubscribeSelectedTopic();

  state.page = page;
  $$('.page').forEach((section) => section.classList.toggle('active', section.id === `page-${page}`));
  $$('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.page === page));
  $('#sidebar').classList.remove('open');

  if (page === 'visualization') startVisualization();
  if (page === 'diagnostics') refreshDiagnostics();
  if (page === 'ros-explorer' && isRosConnected()) refreshRosGraph();
  if (page === 'routes') drawRoutePreview();
}

function bindGlobalActions() {
  $('#global-stop').addEventListener('click', () => globalStop('header'));
  $('#overview-refresh').addEventListener('click', refreshStatus);
  $('#diagnostics-refresh').addEventListener('click', refreshDiagnostics);
  $('#terminal-reload').addEventListener('click', () => {
    if (!terminalEnabled()) {
      toast('Веб-терминал не настроен', 'warn');
      return;
    }
    const frame = $('#terminal-frame');
    const url = new URL(resolveTerminalUrl(), window.location.href);
    url.searchParams.set('reload', String(Date.now()));
    frame.src = url.toString();
  });
}

async function globalStop(source) {
  stopDrive(`global stop: ${source}`);
  const results = await Promise.allSettled([
    api('/api/stop', { method: 'POST', body: JSON.stringify({ source, details: { session_id: sessionId } }) }),
    api('/api/motion/stop', { method: 'POST', body: '{}' }),
  ]);
  const failed = results.filter((item) => item.status === 'rejected');
  if (failed.length) {
    toast(`STOP частично не выполнен: ${failed[0].reason?.message || 'ошибка связи'}`, 'error');
  } else {
    toast('Программный STOP отправлен', 'ok');
  }
}

function updateRosState(value) {
  const kinds = { connected: 'ok', connecting: 'warn', disconnected: 'error', error: 'error' };
  setDot($('#ros-dot'), kinds[value] || 'unknown');
  setPill($('#ros-status'), value === 'connected' ? 'ROS ONLINE' : `ROS ${value.toUpperCase()}`, kinds[value] || 'unknown');
  if (value === 'connected') {
    if (state.page === 'visualization') startVisualization();
    if (state.page === 'ros-explorer') refreshRosGraph();
  } else {
    stopDrive(`rosbridge ${value}`);
    state.topicSubscriptionId = null;
    state.vizSubscriptionId = null;
    $('#topic-subscription-state').textContent = 'НЕТ СОЕДИНЕНИЯ';
    $('#topic-subscription-state').className = 'subscription-state';
  }
}

async function refreshStatus() {
  try {
    state.status = await api('/api/status');
    setDot($('#api-dot'), 'ok');
    renderStatus();
  } catch (error) {
    setDot($('#api-dot'), 'error');
  }
}

async function statusLoop() {
  await refreshStatus();
  window.setTimeout(statusLoop, document.hidden ? 5000 : 1000);
}

async function heartbeatLoop() {
  try {
    await api('/api/heartbeat', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, page: state.page }),
    });
  } catch {
    // Status loop displays the gateway failure.
  }
  window.setTimeout(heartbeatLoop, document.hidden ? 8000 : 3000);
}

function renderIdentity() {
  const identity = state.identity || {};
  const address = identity.ip_addresses?.[0] || location.hostname;
  $('#robot-name').textContent = identity.robot_id || 'sverh-rover';
  $('#robot-address').textContent = address;
  $('#terminal-title').textContent = `Shell пользователя pi на ${identity.robot_id || 'ровере'} · ${address}`;
  $('#identity-json').textContent = JSON.stringify(identity, null, 2);
  document.title = `СВЕРХ · ${identity.robot_id || 'Rover'}`;
}

function renderStatus() {
  const status = state.status;
  if (!status) return;
  const odom = status.odom;
  $('#metric-x').textContent = formatNumber(odom?.x, 3);
  $('#metric-y').textContent = formatNumber(odom?.y, 3);
  $('#metric-yaw').textContent = formatNumber(odom ? odom.yaw * 180 / Math.PI : null, 1);
  $('#metric-speed').textContent = formatNumber(odom ? Math.hypot(odom.vx, odom.vy) : null, 3);
  $('#metric-cpu').textContent = formatNumber(status.system.cpu_percent, 1);
  $('#metric-temp').textContent = formatNumber(status.system.temperature_c, 1);
  const ramUsed = status.system.memory_total_bytes && status.system.memory_available_bytes
    ? 100 * (1 - status.system.memory_available_bytes / status.system.memory_total_bytes) : null;
  $('#metric-ram').textContent = formatNumber(ramUsed, 1);
  $('#metric-disk').textContent = formatNumber(bytesToGiB(status.system.disk_free_bytes), 1);
  $('#client-count').textContent = `CLIENTS ${status.connected_clients}`;

  const topicRows = [
    ['EKF /odom', status.topics.odom, 0.25, 1.0],
    ['Колёсная одометрия', status.topics.wheel_odometry, 0.4, 1.2],
    ['Yahboom IMU', status.topics.imu, 0.2, 1.0],
    ['/diagnostics', status.topics.diagnostics, 3.0, 10.0],
  ].map(([title, topic, warn, error]) => {
    const [value, kind] = ageState(topic?.age_sec, warn, error);
    return { title, detail: `${topic?.message_count ?? 0} сообщений с запуска gateway`, value, kind };
  });
  renderStatusRows($('#topic-health'), topicRows);

  const diagnostics = status.diagnostics.items || [];
  if (diagnostics.length === 0) {
    renderStatusRows($('#diagnostic-summary'), [{ title: 'Нет сообщений', detail: 'Топик пока не получен или пуст', value: 'NO DATA', kind: 'warn' }]);
  } else {
    renderStatusRows($('#diagnostic-summary'), diagnostics.slice(0, 8).map((item) => ({
      title: item.name || 'diagnostic',
      detail: item.message,
      value: ['OK', 'WARN', 'ERROR', 'STALE'][item.level] || String(item.level),
      kind: item.level === 0 ? 'ok' : item.level === 1 ? 'warn' : 'error',
    })));
  }

  renderDiagnosticHealth(status);

  const warning = $('#drive-warning');
  if (status.drive_clients > 1) {
    warning.textContent = `Страница Drive открыта у ${status.drive_clients} клиентов. Команды могут конфликтовать.`;
    warning.classList.remove('hidden');
  } else {
    warning.classList.add('hidden');
  }

  const motion = status.motion;
  if (motion) {
    $('#motion-log').textContent = motion.log?.length ? motion.log.join('\n') : (motion.running ? 'Процесс запущен, ожидается вывод…' : 'Исполнитель не запущен.');
    $('#motion-log').scrollTop = $('#motion-log').scrollHeight;
  }

  if (odom && state.page === 'visualization') {
    ingestVisualizationPose({ x: odom.x, y: odom.y, yaw: odom.yaw });
  }
}

function renderDiagnosticHealth(status) {
  const entries = [
    ['diagnostic-motor', status.topics.wheel_odometry, 0.4, 1.2],
    ['diagnostic-imu', status.topics.imu, 0.2, 1.0],
    ['diagnostic-odom', status.topics.odom, 0.25, 1.0],
    ['diagnostic-topic', status.topics.diagnostics, 3.0, 10.0],
  ];
  for (const [prefix, topic, warn, error] of entries) {
    const [text, kind] = ageState(topic?.age_sec, warn, error);
    setStatusValue($(`#${prefix}-status`), text, kind);
    $(`#${prefix}-detail`).textContent = `${topic?.message_count ?? 0} сообщений · возраст ${topic?.age_sec == null ? '—' : `${topic.age_sec.toFixed(3)} с`}`;
  }
}

function configureDriveLimits() {
  const config = state.config || {};
  const max = Number(config.limits?.max_wheel_speed_mps ?? 0.35);
  $('#linear-speed').max = String(Math.min(max, 0.35));
  $('#drive-topic-label').textContent = `${config.web_command_topic || '/web/cmd_vel'} → ${config.command_topic || '/cmd_vel'}`;
  $('#config-json').textContent = JSON.stringify(config, null, 2);
}

function bindDrive() {
  const relevant = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'KeyQ', 'KeyE']);
  window.addEventListener('keydown', (event) => {
    if (state.page !== 'drive') return;
    if (event.code === 'Space') {
      event.preventDefault();
      globalStop('space');
      return;
    }
    if (!relevant.has(event.code) || event.repeat) return;
    event.preventDefault();
    state.driveKeys.add(event.code);
    updateKeypad();
    startDriveTimer();
  });
  window.addEventListener('keyup', (event) => {
    if (!relevant.has(event.code)) return;
    state.driveKeys.delete(event.code);
    updateKeypad();
    if (state.driveKeys.size === 0) stopDrive('keys released');
  });

  $$('#keypad button').forEach((button) => {
    const code = button.dataset.key;
    const press = (event) => {
      event.preventDefault();
      state.driveKeys.add(code);
      updateKeypad();
      startDriveTimer();
    };
    const release = (event) => {
      event.preventDefault();
      state.driveKeys.delete(code);
      updateKeypad();
      if (state.driveKeys.size === 0) stopDrive('touch released');
    };
    button.addEventListener('pointerdown', press);
    button.addEventListener('pointerup', release);
    button.addEventListener('pointercancel', release);
    button.addEventListener('pointerleave', (event) => { if (event.buttons) release(event); });
  });

  $('#drive-stop').addEventListener('click', () => globalStop('drive button'));
  $('#linear-speed').addEventListener('input', updateDriveOutputs);
  $('#angular-speed').addEventListener('input', updateDriveOutputs);
  window.addEventListener('blur', () => stopDrive('window blur'));
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopDrive('tab hidden'); });
  window.addEventListener('pagehide', () => stopDrive('page hidden'));
  updateDriveOutputs();
}

function updateDriveOutputs() {
  $('#linear-speed-output').textContent = `${Number($('#linear-speed').value).toFixed(2)} м/с`;
  $('#angular-speed-output').textContent = `${Number($('#angular-speed').value).toFixed(2)} рад/с`;
}

function driveVector() {
  const linear = Number($('#linear-speed').value);
  const angular = Number($('#angular-speed').value);
  const x = (state.driveKeys.has('KeyW') ? 1 : 0) - (state.driveKeys.has('KeyS') ? 1 : 0);
  const y = (state.driveKeys.has('KeyA') ? 1 : 0) - (state.driveKeys.has('KeyD') ? 1 : 0);
  const z = (state.driveKeys.has('KeyQ') ? 1 : 0) - (state.driveKeys.has('KeyE') ? 1 : 0);
  const norm = Math.hypot(x, y);
  return {
    x: norm > 1 ? linear * x / norm : linear * x,
    y: norm > 1 ? linear * y / norm : linear * y,
    z: angular * z,
  };
}

function publishDrive(vector) {
  const topic = state.config?.web_command_topic || '/web/cmd_vel';
  if (!ros) throw new Error('ROS WebSocket не инициализирован');
  ros.publish(topic, 'geometry_msgs/msg/Twist', {
    linear: { x: vector.x, y: vector.y, z: 0 },
    angular: { x: 0, y: 0, z: vector.z },
  }, { history: 'keep_last', depth: 1, reliability: 'reliable', durability: 'volatile' });
  $('#drive-command').textContent = `linear: x=${vector.x.toFixed(3)} y=${vector.y.toFixed(3)}\nangular: z=${vector.z.toFixed(3)}`;
}

function startDriveTimer() {
  if (state.driveTimer) return;
  if (!isRosConnected()) {
    toast('ROS WebSocket не подключён', 'error');
    state.driveKeys.clear();
    updateKeypad();
    return;
  }
  const tick = () => {
    if (state.page !== 'drive' || state.driveKeys.size === 0 || !isRosConnected()) {
      stopDrive('drive inactive');
      return;
    }
    try { publishDrive(driveVector()); } catch (error) { stopDrive(error.message); }
  };
  tick();
  state.driveTimer = window.setInterval(tick, 50);
  postActivity('drive', 'Manual drive started', { session_id: sessionId });
}

function sendZeroTwist() {
  if (!isRosConnected()) return;
  try { publishDrive({ x: 0, y: 0, z: 0 }); } catch { /* gateway timeout remains */ }
}

function stopDrive(reason = 'stop') {
  if (state.driveTimer) window.clearInterval(state.driveTimer);
  state.driveTimer = null;
  const wasActive = state.driveKeys.size > 0;
  state.driveKeys.clear();
  updateKeypad();
  sendZeroTwist();
  if (wasActive) postActivity('drive', 'Manual drive stopped', { reason, session_id: sessionId });
}

function updateKeypad() {
  $$('#keypad button').forEach((button) => button.classList.toggle('active', state.driveKeys.has(button.dataset.key)));
}

/* Route builder */
function bindRoutes() {
  $('#plan-refresh').addEventListener('click', refreshPlans);
  $('#plan-select').addEventListener('change', loadSelectedPlan);
  $('#plan-run').addEventListener('click', async () => {
    const name = $('#plan-select').value;
    if (!name) return toast('Выберите маршрут', 'error');
    await startMotion({ kind: 'plan', name });
  });
  $('#plan-save').addEventListener('click', savePlan);
  $('#plan-new').addEventListener('click', () => newRoutePlan(true));
  $('#route-stop').addEventListener('click', async () => {
    await api('/api/motion/stop', { method: 'POST', body: '{}' }).catch((error) => toast(error.message, 'error'));
    toast('Остановка маршрута запрошена', 'ok');
  });
  $$('[data-add-step]').forEach((button) => {
    button.addEventListener('click', () => addRouteStep(button.dataset.addStep));
  });
  const defaultsMap = {
    'route-default-linear': 'linear_speed',
    'route-default-approach': 'approach_speed',
    'route-default-position-tolerance': 'position_tolerance',
    'route-default-angular': 'angular_speed',
    'route-default-angle-tolerance': 'angle_tolerance_deg',
    'route-default-time': 'maximum_step_time',
  };
  for (const [id, key] of Object.entries(defaultsMap)) {
    $(`#${id}`).addEventListener('input', (event) => {
      state.routePlan.defaults[key] = Number(event.target.value);
      drawRoutePreview();
    });
  }
  window.addEventListener('resize', () => {
    drawRoutePreview();
    if (state.page === 'visualization') drawVisualization();
  });
}

function newRoutePlan(showToast = false) {
  state.routePlan = { defaults: { ...DEFAULT_PLAN_DEFAULTS }, steps: [] };
  $('#plan-name').value = 'web_route.yaml';
  syncRouteDefaultInputs();
  renderRouteBuilder();
  if (showToast) toast('Создан новый маршрут', 'ok');
}

function normalizePlan(plan) {
  const defaults = { ...DEFAULT_PLAN_DEFAULTS, ...(plan?.defaults || {}) };
  const steps = Array.isArray(plan?.steps) ? plan.steps.map((step) => ({ ...step })) : [];
  return { ...plan, defaults, steps };
}

function syncRouteDefaultInputs() {
  const defaults = state.routePlan.defaults || {};
  $('#route-default-linear').value = defaults.linear_speed ?? DEFAULT_PLAN_DEFAULTS.linear_speed;
  $('#route-default-approach').value = defaults.approach_speed ?? DEFAULT_PLAN_DEFAULTS.approach_speed;
  $('#route-default-position-tolerance').value = defaults.position_tolerance ?? DEFAULT_PLAN_DEFAULTS.position_tolerance;
  $('#route-default-angular').value = defaults.angular_speed ?? DEFAULT_PLAN_DEFAULTS.angular_speed;
  $('#route-default-angle-tolerance').value = defaults.angle_tolerance_deg ?? DEFAULT_PLAN_DEFAULTS.angle_tolerance_deg;
  $('#route-default-time').value = defaults.maximum_step_time ?? DEFAULT_PLAN_DEFAULTS.maximum_step_time;
}

function defaultStep(type) {
  const steps = {
    move: { type: 'move', forward: 0.5, left: 0.0 },
    move_polar: { type: 'move_polar', distance: 0.5, direction_deg: 0.0 },
    turn: { type: 'turn', degrees: 90.0 },
    pause: { type: 'pause', seconds: 1.0 },
    return_to_start: { type: 'return_to_start', restore_heading: true },
  };
  return { ...(steps[type] || steps.move) };
}

function addRouteStep(type) {
  state.routePlan.steps.push(defaultStep(type));
  renderRouteBuilder();
}

function stepTitle(type) {
  return {
    move: 'Перемещение',
    move_polar: 'Движение по направлению',
    turn: 'Поворот',
    pause: 'Пауза',
    return_to_start: 'Возврат в начало',
  }[type] || type;
}

function makeNumberField(labelText, value, options, onChange) {
  const label = document.createElement('label');
  label.textContent = labelText;
  const input = document.createElement('input');
  input.type = 'number';
  input.value = value ?? '';
  for (const [key, optionValue] of Object.entries(options || {})) input[key] = optionValue;
  input.addEventListener('input', () => onChange(input.value === '' ? null : Number(input.value)));
  label.append(input);
  return label;
}

function renderRouteBuilder() {
  const container = $('#route-step-list');
  container.replaceChildren();
  const steps = state.routePlan.steps;
  $('#route-empty').classList.toggle('hidden', steps.length > 0);
  $('#route-step-count').textContent = `${steps.length} ${steps.length === 1 ? 'шаг' : steps.length < 5 ? 'шага' : 'шагов'}`;

  steps.forEach((step, index) => {
    const card = document.createElement('article');
    card.className = 'route-step';
    const header = document.createElement('div');
    header.className = 'route-step-header';
    const title = document.createElement('div');
    title.className = 'route-step-title';
    const number = document.createElement('span');
    number.className = 'route-step-number';
    number.textContent = String(index + 1);
    const name = document.createElement('span');
    name.textContent = stepTitle(step.type);
    title.append(number, name);

    const actions = document.createElement('div');
    actions.className = 'route-step-actions';
    const up = document.createElement('button'); up.className = 'secondary'; up.textContent = '↑'; up.title = 'Выше'; up.disabled = index === 0;
    const down = document.createElement('button'); down.className = 'secondary'; down.textContent = '↓'; down.title = 'Ниже'; down.disabled = index === steps.length - 1;
    const remove = document.createElement('button'); remove.className = 'danger-secondary'; remove.textContent = '×'; remove.title = 'Удалить';
    up.addEventListener('click', () => moveRouteStep(index, -1));
    down.addEventListener('click', () => moveRouteStep(index, 1));
    remove.addEventListener('click', () => { steps.splice(index, 1); renderRouteBuilder(); });
    actions.append(up, down, remove);
    header.append(title, actions);

    const fields = document.createElement('div');
    fields.className = 'route-step-fields';
    const update = (key, value) => {
      if (value === null || value === '') delete step[key]; else step[key] = value;
      drawRoutePreview();
    };

    if (step.type === 'move') {
      fields.append(
        makeNumberField('Вперёд, м', step.forward ?? 0, { step: '0.05' }, (value) => update('forward', value)),
        makeNumberField('Влево, м', step.left ?? 0, { step: '0.05' }, (value) => update('left', value)),
        makeNumberField('Скорость, м/с (необязательно)', step.linear_speed, { step: '0.01', min: '0.10', max: '0.35', placeholder: 'по умолчанию' }, (value) => update('linear_speed', value)),
      );
    } else if (step.type === 'move_polar') {
      fields.append(
        makeNumberField('Расстояние, м', step.distance ?? 0.5, { step: '0.05' }, (value) => update('distance', value)),
        makeNumberField('Направление, °', step.direction_deg ?? 0, { step: '5' }, (value) => update('direction_deg', value)),
        makeNumberField('Скорость, м/с (необязательно)', step.linear_speed, { step: '0.01', min: '0.10', max: '0.35', placeholder: 'по умолчанию' }, (value) => update('linear_speed', value)),
      );
    } else if (step.type === 'turn') {
      fields.append(
        makeNumberField('Угол, °', step.degrees ?? 90, { step: '5' }, (value) => update('degrees', value)),
        makeNumberField('Скорость, рад/с (необязательно)', step.angular_speed, { step: '0.01', min: '0.10', max: '1.00', placeholder: 'по умолчанию' }, (value) => update('angular_speed', value)),
        makeNumberField('Допуск, ° (необязательно)', step.angle_tolerance_deg, { step: '1', min: '1', max: '15', placeholder: 'по умолчанию' }, (value) => update('angle_tolerance_deg', value)),
      );
    } else if (step.type === 'pause') {
      fields.append(makeNumberField('Длительность, с', step.seconds ?? 1, { step: '0.5', min: '0' }, (value) => update('seconds', value)));
    } else if (step.type === 'return_to_start') {
      const label = document.createElement('label');
      label.className = 'check-label';
      const input = document.createElement('input');
      input.type = 'checkbox';
      input.checked = step.restore_heading !== false;
      input.addEventListener('change', () => { step.restore_heading = input.checked; drawRoutePreview(); });
      label.append(input, document.createTextNode(' Восстановить исходный курс'));
      fields.append(
        label,
        makeNumberField('Скорость, м/с (необязательно)', step.linear_speed, { step: '0.01', min: '0.10', max: '0.35', placeholder: 'по умолчанию' }, (value) => update('linear_speed', value)),
      );
    }

    card.append(header, fields);
    container.append(card);
  });
  drawRoutePreview();
}

function moveRouteStep(index, delta) {
  const target = index + delta;
  if (target < 0 || target >= state.routePlan.steps.length) return;
  const [step] = state.routePlan.steps.splice(index, 1);
  state.routePlan.steps.splice(target, 0, step);
  renderRouteBuilder();
}

async function refreshPlans() {
  try {
    const result = await api('/api/plans');
    const select = $('#plan-select');
    const previous = select.value;
    select.replaceChildren();
    const placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = result.plans.length ? 'Выберите маршрут…' : 'Сохранённых маршрутов нет';
    select.append(placeholder);
    for (const plan of result.plans) {
      const option = document.createElement('option');
      option.value = plan.name;
      option.textContent = `${plan.name} · ${plan.steps} шагов`;
      select.append(option);
    }
    if ([...select.options].some((option) => option.value === previous)) select.value = previous;
  } catch (error) {
    toast(`Маршруты: ${error.message}`, 'error');
  }
}

async function loadSelectedPlan() {
  const name = $('#plan-select').value;
  if (!name) return;
  try {
    const result = await api(`/api/plans/${encodeURIComponent(name)}`);
    state.routePlan = normalizePlan(result.plan);
    $('#plan-name').value = name;
    syncRouteDefaultInputs();
    renderRouteBuilder();
  } catch (error) {
    toast(`Маршрут: ${error.message}`, 'error');
  }
}

function normalizedPlanName(value) {
  const trimmed = value.trim().replace(/\s+/g, '_');
  if (!trimmed) return 'web_route.yaml';
  return /\.ya?ml$/i.test(trimmed) ? trimmed : `${trimmed}.yaml`;
}

async function savePlan() {
  try {
    if (!state.routePlan.steps.length) throw new Error('Добавьте хотя бы один шаг');
    const name = normalizedPlanName($('#plan-name').value);
    $('#plan-name').value = name;
    await api('/api/plans/save', {
      method: 'POST',
      body: JSON.stringify({ name, plan: state.routePlan }),
    });
    toast('Маршрут сохранён', 'ok');
    await refreshPlans();
    $('#plan-select').value = name;
  } catch (error) {
    toast(`Сохранение маршрута: ${error.message}`, 'error');
  }
}

async function startMotion(payload) {
  try {
    const result = await api('/api/motion/start', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    toast('Маршрут запущен', 'ok');
    $('#motion-log').textContent = result.motion.log?.join('\n') || 'Процесс запущен…';
  } catch (error) {
    toast(`Маршрут: ${error.message}`, 'error');
  }
}

function routePreviewPoints() {
  const points = [{ x: 0, y: 0, yaw: 0, kind: 'start' }];
  let x = 0;
  let y = 0;
  let yaw = 0;
  for (const step of state.routePlan.steps) {
    if (step.type === 'move') {
      const forward = Number(step.forward || 0);
      const left = Number(step.left || 0);
      x += Math.cos(yaw) * forward - Math.sin(yaw) * left;
      y += Math.sin(yaw) * forward + Math.cos(yaw) * left;
      points.push({ x, y, yaw, kind: 'move' });
    } else if (step.type === 'move_polar') {
      const distance = Number(step.distance || 0);
      const direction = Number(step.direction_deg || 0) * Math.PI / 180;
      const forward = distance * Math.cos(direction);
      const left = distance * Math.sin(direction);
      x += Math.cos(yaw) * forward - Math.sin(yaw) * left;
      y += Math.sin(yaw) * forward + Math.cos(yaw) * left;
      points.push({ x, y, yaw, kind: 'move' });
    } else if (step.type === 'turn') {
      yaw += Number(step.degrees || 0) * Math.PI / 180;
      points.push({ x, y, yaw, kind: 'turn' });
    } else if (step.type === 'return_to_start') {
      x = 0;
      y = 0;
      if (step.restore_heading !== false) yaw = 0;
      points.push({ x, y, yaw, kind: 'return' });
    }
  }
  return points;
}

function prepareCanvas(canvas, minimumHeight = 360) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(320, Math.floor(rect.width || canvas.clientWidth || 800));
  const height = Math.max(minimumHeight, Math.floor(rect.height || canvas.clientHeight || minimumHeight));
  if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
  }
  const context = canvas.getContext('2d');
  context.setTransform(dpr, 0, 0, dpr, 0, 0);
  context.clearRect(0, 0, width, height);
  return { context, width, height };
}

function drawGrid(context, width, height, centerX, centerY, grid) {
  context.strokeStyle = '#d9ebf3';
  context.lineWidth = 1;
  for (let x = ((centerX % grid) + grid) % grid; x < width; x += grid) {
    context.beginPath(); context.moveTo(x, 0); context.lineTo(x, height); context.stroke();
  }
  for (let y = ((centerY % grid) + grid) % grid; y < height; y += grid) {
    context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke();
  }
  context.strokeStyle = '#8dcfe7';
  context.lineWidth = 1.3;
  context.beginPath(); context.moveTo(0, centerY); context.lineTo(width, centerY); context.stroke();
  context.beginPath(); context.moveTo(centerX, 0); context.lineTo(centerX, height); context.stroke();
}

function drawRobot(context, x, y, yaw, scale = 1) {
  context.save();
  context.translate(x, y);
  context.rotate(-yaw);
  context.fillStyle = '#16b8f3';
  context.strokeStyle = '#075f89';
  context.lineWidth = 2;
  context.beginPath();
  context.moveTo(17 * scale, 0);
  context.lineTo(-11 * scale, 10 * scale);
  context.lineTo(-7 * scale, 0);
  context.lineTo(-11 * scale, -10 * scale);
  context.closePath();
  context.fill();
  context.stroke();
  context.restore();
}

function drawRoutePreview() {
  const canvas = $('#route-preview-canvas');
  if (!canvas) return;
  const { context, width, height } = prepareCanvas(canvas, 320);
  const points = routePreviewPoints();
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const minX = Math.min(...xs, -0.5);
  const maxX = Math.max(...xs, 0.5);
  const minY = Math.min(...ys, -0.5);
  const maxY = Math.max(...ys, 0.5);
  const rangeX = Math.max(1, maxX - minX);
  const rangeY = Math.max(1, maxY - minY);
  const scale = Math.min((width - 90) / rangeX, (height - 80) / rangeY, 220);
  const worldCenterX = (minX + maxX) / 2;
  const worldCenterY = (minY + maxY) / 2;
  const centerX = width / 2 - worldCenterX * scale;
  const centerY = height / 2 + worldCenterY * scale;
  drawGrid(context, width, height, centerX, centerY, Math.max(25, scale * 0.25));
  const mapPoint = (point) => ({ x: centerX + point.x * scale, y: centerY - point.y * scale });

  if (points.length > 1) {
    context.strokeStyle = '#078ac4';
    context.lineWidth = 3;
    context.beginPath();
    points.forEach((point, index) => {
      const mapped = mapPoint(point);
      if (index === 0) context.moveTo(mapped.x, mapped.y); else context.lineTo(mapped.x, mapped.y);
    });
    context.stroke();
  }
  points.forEach((point, index) => {
    const mapped = mapPoint(point);
    context.fillStyle = index === 0 ? '#178f59' : '#ffffff';
    context.strokeStyle = '#078ac4';
    context.lineWidth = 2;
    context.beginPath(); context.arc(mapped.x, mapped.y, 5, 0, Math.PI * 2); context.fill(); context.stroke();
    context.fillStyle = '#355462';
    context.font = '12px system-ui';
    context.fillText(String(index), mapped.x + 8, mapped.y - 7);
  });
  const end = points[points.length - 1];
  const endMapped = mapPoint(end);
  drawRobot(context, endMapped.x, endMapped.y, end.yaw, .8);
}

/* Visualization */
function bindVisualization() {
  $('#viz-clear').addEventListener('click', () => {
    state.vizPoints = [];
    state.vizOrigin = state.vizPose ? { ...state.vizPose } : null;
    if (state.vizPose) state.vizPoints.push({ ...state.vizPose });
    drawVisualization();
  });
  $('#viz-scale').addEventListener('input', drawVisualization);
  $('#viz-follow').addEventListener('change', drawVisualization);
}

function startVisualization() {
  if (state.status?.odom) ingestVisualizationPose(state.status.odom);
  if (!isRosConnected() || state.vizSubscriptionId) {
    drawVisualization();
    return;
  }
  if (!ros) return;
  state.vizSubscriptionId = ros.subscribe('/odom', 'nav_msgs/msg/Odometry', (message) => {
    const position = message.pose?.pose?.position;
    const orientation = message.pose?.pose?.orientation;
    if (!position || !orientation) return;
    const yaw = Math.atan2(
      2 * (orientation.w * orientation.z + orientation.x * orientation.y),
      1 - 2 * (orientation.y ** 2 + orientation.z ** 2),
    );
    ingestVisualizationPose({ x: Number(position.x), y: Number(position.y), yaw });
  }, {
    throttleRate: 50,
    queueLength: 1,
    qos: { history: 'keep_last', depth: 1, reliability: 'best_effort', durability: 'volatile' },
  });
  drawVisualization();
}

function ingestVisualizationPose(pose) {
  const normalized = { x: Number(pose.x), y: Number(pose.y), yaw: Number(pose.yaw) };
  if (![normalized.x, normalized.y, normalized.yaw].every(Number.isFinite)) return;
  state.vizPose = normalized;
  if (!state.vizOrigin) state.vizOrigin = { ...normalized };
  const last = state.vizPoints[state.vizPoints.length - 1];
  if (!last || Math.hypot(last.x - normalized.x, last.y - normalized.y) > 0.003) {
    state.vizPoints.push({ ...normalized });
    if (state.vizPoints.length > 1500) state.vizPoints.splice(0, state.vizPoints.length - 1500);
  }
  drawVisualization();
}

function stopVisualization() {
  if (state.vizSubscriptionId && isRosConnected() && ros) ros.unsubscribe(state.vizSubscriptionId);
  state.vizSubscriptionId = null;
}

function drawVisualization() {
  const canvas = $('#odom-canvas');
  const { context, width, height } = prepareCanvas(canvas, 360);
  const scale = Number($('#viz-scale').value);
  const follow = $('#viz-follow').checked;
  const viewCenter = follow && state.vizPose ? state.vizPose : (state.vizOrigin || { x: 0, y: 0 });
  const centerX = width / 2 - viewCenter.x * scale;
  const centerY = height / 2 + viewCenter.y * scale;
  drawGrid(context, width, height, centerX, centerY, Math.max(20, scale * 0.25));
  const mapPoint = (point) => ({ x: centerX + point.x * scale, y: centerY - point.y * scale });

  if (state.vizPoints.length > 1) {
    context.strokeStyle = '#078ac4';
    context.lineWidth = 2.5;
    context.beginPath();
    state.vizPoints.forEach((point, index) => {
      const mapped = mapPoint(point);
      if (index === 0) context.moveTo(mapped.x, mapped.y); else context.lineTo(mapped.x, mapped.y);
    });
    context.stroke();
  }

  if (state.vizOrigin) {
    const origin = mapPoint(state.vizOrigin);
    context.fillStyle = '#178f59';
    context.beginPath(); context.arc(origin.x, origin.y, 5, 0, Math.PI * 2); context.fill();
  }

  if (state.vizPose) {
    const robot = mapPoint(state.vizPose);
    drawRobot(context, robot.x, robot.y, state.vizPose.yaw);
    $('#viz-position').textContent = `Позиция: X ${state.vizPose.x.toFixed(3)} м · Y ${state.vizPose.y.toFixed(3)} м`;
    $('#viz-yaw').textContent = `Курс: ${(state.vizPose.yaw * 180 / Math.PI).toFixed(1)}°`;
  } else {
    $('#viz-position').textContent = 'Позиция: —';
    $('#viz-yaw').textContent = 'Курс: —';
  }
  $('#viz-points').textContent = `Точек: ${state.vizPoints.length}`;
  $('#viz-empty').classList.toggle('hidden', Boolean(state.vizPose));
}

/* Topics-only ROS Explorer */
function bindRosExplorer() {
  $('#ros-refresh').addEventListener('click', refreshRosGraph);
  $('#topic-filter').addEventListener('input', renderTopicList);
  $('#topic-throttle').addEventListener('change', () => {
    if (state.selectedTopic) subscribeSelectedTopic();
  });
}

async function refreshRosGraph() {
  if (!isRosConnected() || !ros) return toast('rosbridge не подключён', 'error');
  try {
    const topics = await ros.callService('/rosapi/topics', {});
    state.graph.topics = (topics.topics || [])
      .map((name, index) => ({ name, type: topics.types?.[index] || '' }))
      .sort((a, b) => a.name.localeCompare(b.name));
    renderTopicList();
    if (state.selectedTopic) {
      const refreshed = state.graph.topics.find((topic) => topic.name === state.selectedTopic.name);
      if (refreshed) {
        state.selectedTopic = refreshed;
        if (state.page === 'ros-explorer') subscribeSelectedTopic();
      }
    }
    toast(`Найдено топиков: ${state.graph.topics.length}`, 'ok');
  } catch (error) {
    toast(`ROS Explorer: ${error.message}`, 'error');
  }
}

function renderTopicList() {
  const filter = $('#topic-filter').value.toLowerCase();
  const container = $('#topic-list');
  container.replaceChildren();
  for (const topic of state.graph.topics.filter((item) => `${item.name} ${item.type}`.toLowerCase().includes(filter))) {
    const button = document.createElement('button');
    button.classList.toggle('selected', state.selectedTopic?.name === topic.name);
    button.textContent = `${topic.name}\n${topic.type}`;
    button.addEventListener('click', () => selectTopic(topic));
    container.append(button);
  }
  if (!container.children.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-state';
    empty.textContent = 'Топики не найдены.';
    container.append(empty);
  }
}

function selectTopic(topic) {
  state.selectedTopic = topic;
  $('#selected-topic-title').textContent = topic.name;
  $('#selected-topic-type').textContent = topic.type || 'Тип не определён';
  $('#topic-message').textContent = 'Ожидание первого сообщения…';
  $('#topic-message-count').textContent = 'Сообщений: 0';
  $('#topic-message-time').textContent = 'Последнее: —';
  state.topicMessageCount = 0;
  renderTopicList();
  subscribeSelectedTopic();
}

function subscribeSelectedTopic() {
  if (!state.selectedTopic) return;
  unsubscribeSelectedTopic();
  if (!isRosConnected() || !ros) {
    $('#topic-subscription-state').textContent = 'НЕТ СОЕДИНЕНИЯ';
    $('#topic-subscription-state').className = 'subscription-state';
    return;
  }
  try {
    state.topicSubscriptionId = ros.subscribe(
      state.selectedTopic.name,
      state.selectedTopic.type,
      (message) => {
        state.topicMessageCount += 1;
        $('#topic-message').textContent = JSON.stringify(message, null, 2);
        $('#topic-message-count').textContent = `Сообщений: ${state.topicMessageCount}`;
        $('#topic-message-time').textContent = `Последнее: ${new Date().toLocaleTimeString()}`;
      },
      {
        throttleRate: Number($('#topic-throttle').value),
        queueLength: 1,
        qos: { history: 'keep_last', depth: 1, reliability: 'best_effort', durability: 'volatile' },
      },
    );
    $('#topic-subscription-state').textContent = 'ПОДПИСАН';
    $('#topic-subscription-state').className = 'subscription-state ok';
    postActivity('ros-explorer', 'Subscribed to topic', { topic: state.selectedTopic.name, session_id: sessionId });
  } catch (error) {
    $('#topic-subscription-state').textContent = 'ОШИБКА';
    $('#topic-subscription-state').className = 'subscription-state';
    toast(error.message, 'error');
  }
}

function unsubscribeSelectedTopic() {
  if (state.topicSubscriptionId && isRosConnected() && ros) {
    try { ros.unsubscribe(state.topicSubscriptionId); } catch { /* disconnected */ }
  }
  state.topicSubscriptionId = null;
  if ($('#topic-subscription-state')) {
    $('#topic-subscription-state').textContent = 'НЕ ПОДПИСАН';
    $('#topic-subscription-state').className = 'subscription-state';
  }
}

async function refreshDiagnostics() {
  await refreshStatus();
  const diagnostics = state.status?.diagnostics?.items || [];
  const details = $('#diagnostic-details');
  details.replaceChildren();
  for (const item of diagnostics) {
    const card = document.createElement('div');
    card.className = 'diagnostic-item';
    const header = document.createElement('header');
    const name = document.createElement('strong'); name.textContent = item.name;
    const level = document.createElement('span');
    level.className = `status-value ${item.level === 0 ? 'ok' : item.level === 1 ? 'warn' : 'error'}`;
    level.textContent = ['OK', 'WARN', 'ERROR', 'STALE'][item.level] || item.level;
    header.append(name, level);
    const message = document.createElement('p'); message.textContent = item.message;
    const list = document.createElement('dl');
    for (const [key, value] of Object.entries(item.values || {})) {
      const dt = document.createElement('dt'); dt.textContent = key;
      const dd = document.createElement('dd'); dd.textContent = value;
      list.append(dt, dd);
    }
    card.append(header, message, list);
    details.append(card);
  }
  if (!diagnostics.length) details.textContent = 'Нет сообщений /diagnostics.';

  try {
    const activity = await api('/api/activity?limit=200');
    const container = $('#activity-list');
    container.replaceChildren();
    for (const item of activity.items) {
      const card = document.createElement('div');
      card.className = 'activity-item';
      const header = document.createElement('header');
      const source = document.createElement('strong'); source.textContent = item.source;
      const date = document.createElement('small'); date.textContent = new Date(item.timestamp * 1000).toLocaleString();
      header.append(source, date);
      const message = document.createElement('p'); message.textContent = item.message;
      const detail = document.createElement('pre'); detail.textContent = JSON.stringify(item.details || {}, null, 2);
      card.append(header, message, detail);
      container.append(card);
    }
  } catch (error) {
    toast(`Журнал: ${error.message}`, 'error');
  }
}

function bindSettings() {
  $('#compact-mode').addEventListener('change', (event) => {
    document.body.classList.toggle('compact', event.target.checked);
    storageSet('localStorage', 'sverhCompact', String(event.target.checked));
  });
}

window.addEventListener('beforeunload', () => {
  stopDrive('unload');
  stopVisualization();
  unsubscribeSelectedTopic();
});

initialize();
