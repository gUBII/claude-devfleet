import { useEffect, useRef } from 'react';

/**
 * Singleton fleet-event bus. One EventSource shared across the whole app.
 * Components subscribe via useFleetEvents(handler); the connection opens on
 * first subscriber and closes on the last unsubscribe.
 *
 * Backend: GET /api/events (SSE). AuthMiddleware accepts ?token=<jwt> for SSE.
 * Event shape: { type, mission_id?, mission_title?, session_id?, ... }
 *   types: connected | ping | mission_dispatched | mission_completed |
 *          mission_cancelled | mission_failed | hitl_question |
 *          mission_cancelled_no_approval
 */

const API_BASE = (import.meta.env.VITE_API_URL || '') + '/api';
const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 30000;

let _es = null;
let _backoff = RECONNECT_MIN_MS;
let _reconnectTimer = null;
const _handlers = new Set();

function _dispatch(evt) {
  for (const h of _handlers) {
    try { h(evt); } catch (e) { console.error('[fleet-events] handler threw:', e); }
  }
}

function _open() {
  if (_es) return;
  const token = localStorage.getItem('devfleet_token');
  if (!token) {
    // No auth → don't open; useFleetEvents will retry when token appears.
    return;
  }
  const url = `${API_BASE}/events?token=${encodeURIComponent(token)}`;
  const es = new EventSource(url);
  _es = es;

  es.onopen = () => { _backoff = RECONNECT_MIN_MS; };

  es.onmessage = (e) => {
    if (!e.data) return;
    try {
      const evt = JSON.parse(e.data);
      _dispatch(evt);
    } catch (err) {
      // Non-JSON keepalive — ignore.
    }
  };

  es.onerror = () => {
    // EventSource auto-reconnects on transient errors. For auth/permanent
    // failures the browser closes it (readyState === 2); we then schedule a
    // manual reconnect with exponential backoff so a paused dev server or a
    // token rotation doesn't leave us dead.
    if (es.readyState === 2) {
      try { es.close(); } catch {}
      if (_es === es) _es = null;
      if (_handlers.size > 0 && !_reconnectTimer) {
        _reconnectTimer = setTimeout(() => {
          _reconnectTimer = null;
          _open();
        }, _backoff);
        _backoff = Math.min(_backoff * 2, RECONNECT_MAX_MS);
      }
    }
  };
}

function _close() {
  if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null; }
  if (_es) { try { _es.close(); } catch {} _es = null; }
}

/**
 * Subscribe a handler to fleet events. Handler is invoked synchronously with
 * each event payload. Returns nothing; cleanup is automatic on unmount.
 *
 * @param {(evt: { type: string } & Record<string, unknown>) => void} handler
 */
export function useFleetEvents(handler) {
  const ref = useRef(handler);
  ref.current = handler;

  useEffect(() => {
    const wrapped = (evt) => ref.current && ref.current(evt);
    _handlers.add(wrapped);
    _open();
    return () => {
      _handlers.delete(wrapped);
      if (_handlers.size === 0) _close();
    };
  }, []);
}

/** Force-close + reopen — call after login so a fresh token is used. */
export function resetFleetEvents() {
  _close();
  if (_handlers.size > 0) _open();
}
