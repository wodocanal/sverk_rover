(function (root) {
  'use strict';

  class MapViewport {
    constructor() {
      this.reset();
    }

    reset() {
      this.centerX = 0;
      this.centerY = 0;
      this.scale = 120;
      this.key = null;
    }

    fit(key, bounds, width, height) {
      if (this.key === key) return;
      this.key = key;
      this.centerX = (bounds.minX + bounds.maxX) / 2;
      this.centerY = (bounds.minY + bounds.maxY) / 2;
      this.scale = Math.max(5, Math.min(2000, 0.85 * Math.min(
        width / Math.max(1, bounds.maxX - bounds.minX),
        height / Math.max(1, bounds.maxY - bounds.minY),
      )));
    }

    world(point, width, height) {
      return {
        x: this.centerX + (point.x - width / 2) / this.scale,
        y: this.centerY - (point.y - height / 2) / this.scale,
      };
    }

    move(dx, dy) {
      this.centerX -= dx / this.scale;
      this.centerY += dy / this.scale;
    }

    zoomAt(factor, x, y, width, height) {
      if (!Number.isFinite(factor) || factor <= 0) return;
      const anchor = this.world({ x, y }, width, height);
      this.scale = Math.max(5, Math.min(2000, this.scale * factor));
      this.centerX = anchor.x - (x - width / 2) / this.scale;
      this.centerY = anchor.y + (y - height / 2) / this.scale;
    }
  }

  function bindMapViewport(canvas, view, redraw, selection) {
    const pointers = new Map();
    let draft = null;
    const local = event => {
      const rect = canvas.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    };
    const world = point => view.world(point, canvas.clientWidth, canvas.clientHeight);
    const gesture = () => {
      const [a, b] = [...pointers.values()];
      return b ? { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2,
        distance: Math.hypot(a.x - b.x, a.y - b.y) } : { ...a, distance: 0 };
    };
    const clearDraft = () => {
      draft = null;
      selection.preview(null);
    };
    const cancel = () => {
      clearDraft();
      const ids = [...pointers.keys()];
      pointers.clear();
      ids.forEach(id => { if (canvas.hasPointerCapture(id)) canvas.releasePointerCapture(id); });
      canvas.classList.remove('is-dragging');
      redraw();
    };
    const updateDraft = point => {
      const end = world(point);
      const moved = Math.hypot(point.x - draft.start.x, point.y - draft.start.y) >= 4;
      draft.pose.yaw = moved ? Math.atan2(end.y - draft.pose.y, end.x - draft.pose.x) : draft.initialYaw;
      selection.preview({ mode: draft.mode, pose: { ...draft.pose }, end: moved ? end : null });
    };
    canvas.addEventListener('pointerdown', event => {
      if (event.pointerType === 'mouse' && event.button !== 0) return;
      event.preventDefault();
      canvas.focus({ preventScroll: true });
      const point = local(event);
      pointers.set(event.pointerId, point);
      canvas.setPointerCapture(event.pointerId);
      if (pointers.size === 1 && selection.mode()) {
        const mode = selection.mode();
        const initialYaw = selection.yaw(mode) || 0;
        draft = { id: event.pointerId, mode, start: point, initialYaw,
          pose: { ...world(point), yaw: initialYaw } };
        updateDraft(point);
      } else {
        clearDraft();
        canvas.classList.add('is-dragging');
      }
      redraw();
    });
    canvas.addEventListener('pointermove', event => {
      if (!pointers.has(event.pointerId)) return;
      const before = gesture();
      const point = local(event);
      pointers.set(event.pointerId, point);
      if (draft) {
        updateDraft(point);
      } else {
        const after = gesture();
        view.move(after.x - before.x, after.y - before.y);
        if (before.distance > 0 && after.distance > 0) {
          view.zoomAt(after.distance / before.distance, after.x, after.y, canvas.clientWidth, canvas.clientHeight);
        }
      }
      redraw();
    });
    const release = event => {
      if (!pointers.has(event.pointerId)) return;
      let result = null;
      if (draft?.id === event.pointerId) {
        if (event.type === 'pointerup' && draft.mode === selection.mode()) {
          updateDraft(local(event));
          result = { mode: draft.mode, pose: { ...draft.pose } };
        }
        clearDraft();
      }
      pointers.delete(event.pointerId);
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      canvas.classList.toggle('is-dragging', pointers.size > 0 && !draft);
      if (result) selection.commit(result.mode, result.pose);
      redraw();
    };
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(name => canvas.addEventListener(name, release));
    canvas.addEventListener('wheel', event => {
      event.preventDefault();
      if (pointers.size) return;
      const point = local(event);
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? canvas.clientHeight : 1;
      view.zoomAt(Math.exp(-Math.max(-500, Math.min(500, event.deltaY * unit)) * 0.002),
        point.x, point.y, canvas.clientWidth, canvas.clientHeight);
      redraw();
    }, { passive: false });
    canvas.addEventListener('dblclick', () => {
      if (selection.mode()) return;
      view.reset();
      redraw();
    });
    canvas.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        cancel();
        selection.cancel();
      } else if (pointers.size) return;
      else if (['+', '=', '-'].includes(event.key)) {
        view.zoomAt(event.key === '-' ? 0.8 : 1.25, canvas.clientWidth / 2,
          canvas.clientHeight / 2, canvas.clientWidth, canvas.clientHeight);
      } else if (event.key === 'Home' || event.key === '0') view.reset();
      else {
        const offsets = { ArrowLeft: [-30, 0], ArrowRight: [30, 0], ArrowUp: [0, -30], ArrowDown: [0, 30] };
        if (!offsets[event.key]) return;
        view.move(...offsets[event.key]);
      }
      event.preventDefault();
      redraw();
    });
    canvas.addEventListener('blur', cancel);
    return cancel;
  }

  const api = { MapViewport, bindMapViewport };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.RoverMapView = api;
})(typeof window === 'undefined' ? globalThis : window);
