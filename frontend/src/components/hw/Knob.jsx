import React, { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Knob — rotary control. SVG-based with tick marks around the circumference.
 * Drag vertically or scroll to rotate. Center label shows current value.
 *
 *      ╭─┴─╮
 *     ╱  •  ╲     ← indicator dot
 *    │   N   │    ← center value
 *     ╲     ╱
 *      ╰───╯
 *
 * Props:
 *   value     — current numeric value
 *   min       — minimum (default 0)
 *   max       — maximum (default 10)
 *   step      — step (default 1)
 *   onChange  — (next: number) => void
 *   label     — small label above
 *   suffix    — unit shown after value
 *   size      — 'sm' | 'md' | 'lg'
 *   disabled  — boolean
 */
const SIZES = {
  sm: { d: 44, stroke: 2, font: 11 },
  md: { d: 64, stroke: 2.5, font: 14 },
  lg: { d: 88, stroke: 3, font: 18 },
};

// Range of rotation in degrees: -135° (min) → +135° (max), so 270° total.
const SWEEP = 270;
const START = -135;

export default function Knob({
  value,
  min = 0,
  max = 10,
  step = 1,
  onChange,
  label,
  suffix,
  size = 'md',
  disabled = false,
  ticks = 11,
}) {
  const cfg = SIZES[size] || SIZES.md;
  const ref = useRef(null);
  const dragRef = useRef(null);
  const [, force] = useState(0);

  const clamp = useCallback((n) => Math.min(max, Math.max(min, n)), [min, max]);
  const snap = useCallback((n) => Math.round(n / step) * step, [step]);

  const setValue = useCallback(
    (next) => {
      const snapped = clamp(snap(next));
      if (snapped !== value) onChange?.(snapped);
    },
    [clamp, snap, value, onChange],
  );

  // pointer drag — vertical drag, up = increase
  const onPointerDown = (e) => {
    if (disabled) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { startY: e.clientY, startV: value };
    force((n) => n + 1);
  };

  const onPointerMove = (e) => {
    if (!dragRef.current) return;
    const dy = dragRef.current.startY - e.clientY;
    const range = max - min;
    // 100px drag = full range
    const delta = (dy / 100) * range;
    setValue(dragRef.current.startV + delta);
  };

  const onPointerUp = (e) => {
    if (!dragRef.current) return;
    try { e.currentTarget.releasePointerCapture(e.pointerId); } catch {}
    dragRef.current = null;
    force((n) => n + 1);
  };

  const onWheel = (e) => {
    if (disabled) return;
    e.preventDefault();
    const dir = e.deltaY > 0 ? -1 : 1;
    setValue(value + dir * step);
  };

  const onKey = (e) => {
    if (disabled) return;
    if (e.key === 'ArrowUp' || e.key === 'ArrowRight') { e.preventDefault(); setValue(value + step); }
    if (e.key === 'ArrowDown' || e.key === 'ArrowLeft') { e.preventDefault(); setValue(value - step); }
    if (e.key === 'Home') { e.preventDefault(); setValue(min); }
    if (e.key === 'End') { e.preventDefault(); setValue(max); }
  };

  const norm = (clamp(value) - min) / (max - min || 1);
  const angle = START + norm * SWEEP;

  const r = cfg.d / 2;
  const c = cfg.d / 2;
  const tickR = r - 3;
  const innerR = r - 9;

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const handler = (e) => onWheel(e);
    el.addEventListener('wheel', handler, { passive: false });
    return () => el.removeEventListener('wheel', handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, disabled, step, min, max]);

  return (
    <span className={`ws-knob-wrap ws-knob-wrap--${size} ${disabled ? 'is-disabled' : ''}`}>
      {label && <span className="ws-knob-label">{label}</span>}
      <span
        ref={ref}
        role="slider"
        tabIndex={disabled ? -1 : 0}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={value}
        aria-label={label || 'knob'}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onKeyDown={onKey}
        className="ws-knob"
        style={{ width: cfg.d, height: cfg.d }}
      >
        <svg width={cfg.d} height={cfg.d} viewBox={`0 0 ${cfg.d} ${cfg.d}`}>
          <defs>
            <radialGradient id={`knob-grad-${size}`} cx="50%" cy="35%" r="60%">
              <stop offset="0%" stopColor="#3a3a3e" />
              <stop offset="55%" stopColor="#22222a" />
              <stop offset="100%" stopColor="#0e0e12" />
            </radialGradient>
          </defs>

          {/* Tick marks around outside */}
          {Array.from({ length: ticks }).map((_, i) => {
            const t = (i / (ticks - 1)) * SWEEP + START;
            const rad = (t * Math.PI) / 180;
            const x1 = c + Math.cos(rad) * (tickR);
            const y1 = c + Math.sin(rad) * (tickR);
            const x2 = c + Math.cos(rad) * (tickR - 3);
            const y2 = c + Math.sin(rad) * (tickR - 3);
            const lit = (i / (ticks - 1)) <= norm;
            return (
              <line
                key={i}
                x1={x1} y1={y1} x2={x2} y2={y2}
                stroke={lit ? 'var(--brand-mark)' : 'var(--ink-3)'}
                strokeWidth={1.5}
                strokeLinecap="round"
              />
            );
          })}

          {/* Body */}
          <circle
            cx={c} cy={c} r={innerR}
            fill={`url(#knob-grad-${size})`}
            stroke="rgba(0,0,0,0.6)"
            strokeWidth={cfg.stroke}
          />
          {/* Inner highlight ring */}
          <circle
            cx={c} cy={c} r={innerR - 1.5}
            fill="none"
            stroke="rgba(255,255,255,0.04)"
            strokeWidth={1}
          />

          {/* Indicator pointer */}
          <g transform={`rotate(${angle} ${c} ${c})`}>
            <line
              x1={c} y1={c - innerR + 4}
              x2={c} y2={c - innerR + innerR * 0.55}
              stroke="var(--brand-mark)"
              strokeWidth={2.5}
              strokeLinecap="round"
            />
            <circle
              cx={c} cy={c - innerR + 5}
              r={2}
              fill="var(--brand-mark)"
            />
          </g>
        </svg>
        <span className="ws-knob__value" style={{ fontSize: cfg.font }}>
          {value}{suffix && <span className="ws-knob__suffix">{suffix}</span>}
        </span>
      </span>
    </span>
  );
}
