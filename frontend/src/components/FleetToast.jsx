import React, { useState, useEffect, useRef } from 'react';
import { streamFleetEvents } from '../api/client';

const TOAST_TTL = 5000;

function Toast({ toast, onDismiss }) {
  const colors = {
    mission_completed: { bg: 'var(--success-soft)', border: 'var(--success)', icon: '✓' },
    mission_failed:    { bg: 'var(--danger-soft)',  border: 'var(--danger)',  icon: '✕' },
    mission_cancelled: { bg: 'rgba(113,113,122,0.12)', border: '#71717a', icon: '–' },
    mission_dispatched: { bg: 'var(--warning-soft)', border: 'var(--warning)', icon: '▶' },
  };
  const c = colors[toast.type] || colors.mission_dispatched;

  return (
    <div
      onClick={() => onDismiss(toast.id)}
      style={{
        display: 'flex', alignItems: 'flex-start', gap: 10,
        padding: '10px 14px',
        background: c.bg,
        border: `1px solid ${c.border}`,
        borderLeft: `3px solid ${c.border}`,
        borderRadius: 'var(--radius-md)',
        cursor: 'pointer',
        fontSize: 13,
        maxWidth: 320,
        animation: 'toast-in 0.2s ease',
      }}
    >
      <span style={{ fontWeight: 700, flexShrink: 0, color: c.border }}>{c.icon}</span>
      <div>
        <div style={{ fontWeight: 600, marginBottom: 2 }}>
          {toast.type === 'mission_completed' && 'Mission complete'}
          {toast.type === 'mission_failed' && 'Mission failed'}
          {toast.type === 'mission_cancelled' && 'Mission cancelled'}
          {toast.type === 'mission_dispatched' && 'Agent dispatched'}
        </div>
        <div style={{ color: 'var(--text-muted)', fontSize: 12, lineHeight: 1.4 }}>
          {toast.mission_title || toast.mission_id}
        </div>
      </div>
    </div>
  );
}

export default function FleetToast({ onFleetEvent }) {
  const [toasts, setToasts] = useState([]);
  const timers = useRef({});

  useEffect(() => {
    const close = streamFleetEvents({
      onEvent: (ev) => {
        if (!['mission_completed', 'mission_failed', 'mission_cancelled', 'mission_dispatched'].includes(ev.type)) return;

        const id = `${ev.type}-${ev.session_id || Date.now()}`;
        const toast = { ...ev, id };
        setToasts(prev => [...prev.slice(-4), toast]);

        timers.current[id] = setTimeout(() => {
          setToasts(prev => prev.filter(t => t.id !== id));
          delete timers.current[id];
        }, TOAST_TTL);

        onFleetEvent?.(ev);
      },
    });
    return () => {
      close();
      Object.values(timers.current).forEach(clearTimeout);
    };
  }, []);

  const dismiss = (id) => {
    setToasts(prev => prev.filter(t => t.id !== id));
    clearTimeout(timers.current[id]);
    delete timers.current[id];
  };

  if (toasts.length === 0) return null;

  return (
    <div style={{
      position: 'fixed', bottom: 20, right: 20,
      display: 'flex', flexDirection: 'column', gap: 8,
      zIndex: 9999,
    }}>
      {toasts.map(t => <Toast key={t.id} toast={t} onDismiss={dismiss} />)}
    </div>
  );
}
