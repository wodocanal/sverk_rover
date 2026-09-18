(function (root) {
  'use strict';

  class LidarViewport {
    constructor() {
      this.reset();
    }

    reset() {
      this.zoom = 1;
      this.panX = 0;
      this.panY = 0;
      this.radius = null;
    }

    fit(points) {
      if (this.radius !== null || !points.length) return;
      // Fit observed returns, not the sensor's maximum advertised range.
      this.radius = Math.max(0.5, ...points.map(([x, y]) => Math.hypot(x, y)));
    }

    transform(width, height) {
      return {
        x: width / 2 + this.panX,
        y: height / 2 + this.panY,
        scale: Math.min(width, height) * 0.40 / (this.radius || 5) * this.zoom,
      };
    }

    project(point, width, height) {
      const view = this.transform(width, height);
      return { x: view.x - point[1] * view.scale, y: view.y - point[0] * view.scale };
    }

    move(dx, dy) {
      this.panX += dx;
      this.panY += dy;
    }

    zoomAt(factor, x, y, width, height) {
      if (!Number.isFinite(factor) || factor <= 0) return;
      const next = Math.max(0.25, Math.min(32, this.zoom * factor));
      const ratio = next / this.zoom;
      // Keep the world point under the cursor/fingers stationary while zooming.
      this.panX = x - width / 2 - (x - width / 2 - this.panX) * ratio;
      this.panY = y - height / 2 - (y - height / 2 - this.panY) * ratio;
      this.zoom = next;
    }
  }

  function bindLidarViewport(canvas, view, redraw) {
    const pointers = new Map();
    const local = (event) => {
      const rect = canvas.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    };
    const gesture = () => {
      const values = [...pointers.values()].slice(0, 2);
      if (values.length < 2) return { ...values[0], distance: 0 };
      return {
        x: (values[0].x + values[1].x) / 2,
        y: (values[0].y + values[1].y) / 2,
        distance: Math.hypot(values[1].x - values[0].x, values[1].y - values[0].y),
      };
    };
    canvas.addEventListener('wheel', (event) => {
      event.preventDefault();
      const point = local(event);
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? canvas.clientHeight : 1;
      const delta = Math.max(-500, Math.min(500, event.deltaY * unit));
      view.zoomAt(Math.exp(-delta * 0.002), point.x, point.y, canvas.clientWidth, canvas.clientHeight);
      redraw();
    }, { passive: false });
    canvas.addEventListener('pointerdown', (event) => {
      if (event.pointerType === 'mouse' && event.button !== 0) return;
      event.preventDefault();
      canvas.focus({ preventScroll: true });
      pointers.set(event.pointerId, local(event));
      canvas.setPointerCapture(event.pointerId);
      canvas.classList.add('is-dragging');
    });
    canvas.addEventListener('pointermove', (event) => {
      if (!pointers.has(event.pointerId)) return;
      const before = gesture();
      pointers.set(event.pointerId, local(event));
      const after = gesture();
      view.move(after.x - before.x, after.y - before.y);
      if (before.distance > 0 && after.distance > 0) {
        view.zoomAt(after.distance / before.distance, after.x, after.y, canvas.clientWidth, canvas.clientHeight);
      }
      redraw();
    });
    const release = (event) => {
      pointers.delete(event.pointerId);
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
      canvas.classList.toggle('is-dragging', pointers.size > 0);
    };
    ['pointerup', 'pointercancel', 'lostpointercapture'].forEach((name) => canvas.addEventListener(name, release));
    canvas.addEventListener('dblclick', () => { view.reset(); redraw(); });
    canvas.addEventListener('keydown', (event) => {
      const offsets = { ArrowLeft: [-30, 0], ArrowRight: [30, 0], ArrowUp: [0, -30], ArrowDown: [0, 30] };
      if (offsets[event.key]) view.move(...offsets[event.key]);
      else if (['+', '=', '-'].includes(event.key)) {
        view.zoomAt(event.key === '-' ? 1 / 1.25 : 1.25,
          canvas.clientWidth / 2, canvas.clientHeight / 2, canvas.clientWidth, canvas.clientHeight);
      } else if (event.key === '0' || event.key === 'Home') view.reset();
      else return;
      event.preventDefault();
      redraw();
    });
  }

  const api = { LidarViewport, bindLidarViewport };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.RoverLidarView = api;
})(typeof window === 'undefined' ? globalThis : window);
