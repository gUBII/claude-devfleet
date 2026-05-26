import React from 'react';

/**
 * LED — tiny status indicator dot.
 *
 *   ●  ←  RAG-colored, optional pulse for "running" / live state.
 *
 * Props:
 *   tone    — 'g' | 'a' | 'r' | 'off' (gray)
 *   pulse   — boolean (animated heartbeat)
 *   size    — 'sm' | 'md' (default sm = 7px, md = 10px)
 *   label   — optional small caption to the right
 */
const DIAM = { sm: 7, md: 10, lg: 14 };

export default function LED({ tone = 'off', pulse = false, size = 'sm', label, title }) {
  const d = DIAM[size] || DIAM.sm;
  return (
    <span className={`ws-led-wrap ${label ? 'has-label' : ''}`} title={title}>
      <span
        className={`ws-led ws-led--${tone} ${pulse ? 'is-pulsing' : ''}`}
        style={{ width: d, height: d }}
        aria-hidden="true"
      />
      {label && <span className="ws-led-label">{label}</span>}
    </span>
  );
}
