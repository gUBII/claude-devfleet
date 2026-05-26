import React from 'react';

/**
 * Meter — stepped LED level bar. Looks like real hardware capacity meters.
 *
 *   ▮▮▮▮▮▯▯▯▯▯   5 / 10
 *
 * Props:
 *   value     — current numeric value
 *   max       — maximum (default 10)
 *   segments  — number of lit segments (default 10)
 *   tone      — 'amber' (default) | 'g' | 'r' — but threshold may override
 *   thresholds — { amber: 0.6, red: 0.85 } — auto-tone at filled fraction
 *   label     — optional small label rendered above
 *   showCount — boolean, render "value / max" to the right
 *   size      — 'sm' | 'md'
 */
const SIZES = {
  sm: { h: 8, gap: 2 },
  md: { h: 12, gap: 3 },
};

export default function Meter({
  value = 0,
  max = 10,
  segments = 10,
  tone = 'amber',
  thresholds = { amber: 0.6, red: 0.85 },
  label,
  showCount = true,
  size = 'sm',
}) {
  const cfg = SIZES[size] || SIZES.sm;
  const safeMax = max || 1;
  const ratio = Math.min(1, Math.max(0, value / safeMax));
  const lit = Math.round(ratio * segments);

  // Auto-tone based on fill ratio if thresholds given.
  let effectiveTone = tone;
  if (thresholds) {
    if (ratio >= (thresholds.red ?? 0.85)) effectiveTone = 'r';
    else if (ratio >= (thresholds.amber ?? 0.6)) effectiveTone = 'a';
    else effectiveTone = 'g';
  }

  return (
    <span className={`ws-meter-wrap ws-meter-wrap--${size}`}>
      {label && <span className="ws-meter-label">{label}</span>}
      <span className="ws-meter-row">
        <span className="ws-meter" style={{ gap: cfg.gap, height: cfg.h }}>
          {Array.from({ length: segments }).map((_, i) => (
            <span
              key={i}
              className={`ws-meter__seg ${i < lit ? `ws-meter__seg--on ws-meter__seg--${effectiveTone}` : ''}`}
            />
          ))}
        </span>
        {showCount && (
          <span className="ws-meter-count">
            <b>{value}</b><span>/{max}</span>
          </span>
        )}
      </span>
    </span>
  );
}
