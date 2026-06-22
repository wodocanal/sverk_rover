'use strict';

export class RosbridgeClient extends EventTarget {
  constructor(url) {
    super();
    this.url = url;
    this.socket = null;
    this.connected = false;
    this.manualClose = false;
    this.sequence = 0;
    this.reconnectDelay = 1000;
    this.pendingServices = new Map();
    this.subscriptions = new Map();
    this.actionGoals = new Map();
    this.advertisements = new Map();
  }

  nextId(prefix = 'web') {
    this.sequence += 1;
    return `${prefix}:${Date.now()}:${this.sequence}`;
  }

  connect() {
    this.manualClose = false;
    if (this.socket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(this.socket.readyState)) {
      return;
    }
    this.dispatchEvent(new CustomEvent('state', { detail: 'connecting' }));
    const socket = new WebSocket(this.url);
    this.socket = socket;

    socket.addEventListener('open', () => {
      this.connected = true;
      this.reconnectDelay = 1000;
      this.dispatchEvent(new CustomEvent('state', { detail: 'connected' }));
    });

    socket.addEventListener('message', (event) => this.handleMessage(event.data));

    socket.addEventListener('close', () => {
      this.connected = false;
      this.rejectPending(new Error('ROS WebSocket disconnected'));
      this.subscriptions.clear();
      this.advertisements.clear();
      this.dispatchEvent(new CustomEvent('state', { detail: 'disconnected' }));
      if (!this.manualClose) {
        window.setTimeout(() => this.connect(), this.reconnectDelay);
        this.reconnectDelay = Math.min(this.reconnectDelay * 1.7, 10000);
      }
    });

    socket.addEventListener('error', () => {
      this.dispatchEvent(new CustomEvent('state', { detail: 'error' }));
    });
  }

  close() {
    this.manualClose = true;
    this.socket?.close();
  }

  send(payload) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      throw new Error('ROS WebSocket is not connected');
    }
    this.socket.send(JSON.stringify(payload));
  }

  handleMessage(raw) {
    let message;
    try {
      message = JSON.parse(raw);
    } catch {
      return;
    }

    if (message.op === 'publish' && message.id && this.subscriptions.has(message.id)) {
      this.subscriptions.get(message.id).callback(message.msg, message);
      return;
    }

    if (message.op === 'service_response' && message.id && this.pendingServices.has(message.id)) {
      const pending = this.pendingServices.get(message.id);
      this.pendingServices.delete(message.id);
      window.clearTimeout(pending.timeout);
      if (message.result === false) {
        pending.reject(new Error(typeof message.values === 'string' ? message.values : 'ROS service call failed'));
      } else {
        pending.resolve(message.values ?? {});
      }
      return;
    }

    if (['action_feedback', 'action_result'].includes(message.op) && message.id) {
      const goal = this.actionGoals.get(message.id);
      if (goal) {
        goal.callback(message);
        if (message.op === 'action_result') {
          this.actionGoals.delete(message.id);
        }
      }
      return;
    }

    if (message.op === 'status') {
      this.dispatchEvent(new CustomEvent('status', { detail: message }));
    }
  }

  rejectPending(error) {
    for (const pending of this.pendingServices.values()) {
      window.clearTimeout(pending.timeout);
      pending.reject(error);
    }
    this.pendingServices.clear();
  }

  subscribe(topic, type, callback, options = {}) {
    const id = this.nextId('subscribe');
    const payload = {
      op: 'subscribe',
      id,
      topic,
      type: type || undefined,
      throttle_rate: options.throttleRate ?? 0,
      queue_length: options.queueLength ?? 1,
      compression: options.compression ?? 'none',
    };
    if (options.qos) payload.qos = options.qos;
    this.subscriptions.set(id, { topic, callback });
    this.send(payload);
    return id;
  }

  unsubscribe(id) {
    const subscription = this.subscriptions.get(id);
    if (!subscription) return;
    this.send({ op: 'unsubscribe', id, topic: subscription.topic });
    this.subscriptions.delete(id);
  }

  advertise(topic, type, qos = undefined) {
    const key = `${topic}|${type}`;
    if (this.advertisements.has(key)) return this.advertisements.get(key);
    const id = this.nextId('advertise');
    const payload = { op: 'advertise', id, topic, type };
    if (qos) payload.qos = qos;
    this.send(payload);
    this.advertisements.set(key, id);
    return id;
  }

  unadvertise(topic, type) {
    const key = `${topic}|${type}`;
    const id = this.advertisements.get(key);
    if (!id) return;
    this.send({ op: 'unadvertise', id, topic });
    this.advertisements.delete(key);
  }

  publish(topic, type, msg, qos = undefined) {
    this.advertise(topic, type, qos);
    const payload = { op: 'publish', topic, msg };
    if (qos) payload.qos = qos;
    this.send(payload);
  }

  callService(service, args = {}, type = undefined, timeoutMs = 7000) {
    const id = this.nextId('service');
    return new Promise((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        this.pendingServices.delete(id);
        reject(new Error(`Service timeout: ${service}`));
      }, timeoutMs);
      this.pendingServices.set(id, { resolve, reject, timeout });
      const payload = { op: 'call_service', id, service, args };
      if (type) payload.type = type;
      try {
        this.send(payload);
      } catch (error) {
        window.clearTimeout(timeout);
        this.pendingServices.delete(id);
        reject(error);
      }
    });
  }

  sendActionGoal(action, actionType, args, callback) {
    const id = this.nextId('action');
    this.actionGoals.set(id, { action, callback });
    this.send({
      op: 'send_action_goal',
      id,
      action,
      action_type: actionType,
      args,
      feedback: true,
    });
    return id;
  }

  cancelActionGoal(id) {
    const goal = this.actionGoals.get(id);
    if (!goal) throw new Error('Unknown action goal');
    this.send({ op: 'cancel_action_goal', id, action: goal.action });
  }
}
