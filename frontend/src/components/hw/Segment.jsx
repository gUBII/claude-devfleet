import React from 'react';

/**
 * Segment — row of hardware buttons where exactly one is depressed.
 * Replaces stock <select> for short, mutually-exclusive option lists.
 *
 * Props:
 *   value     — current option id
 *   onChange  — (next) => void
 *   options   — Array<{ value: string, label: string, tone?: 'amber'|'g'|'r' }>
 *   size      — 'sm' | 'md'
 *   ariaLabel — for the group
 */
export default function Segment({
  value,
  onChange,
  options = [],
  size = 'md',
  ariaLabel,
  disabled = false,
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className={`ws-segment ws-segment--${size} ${disabled ? 'is-disabled' : ''}`}
    >
      {options.map((opt) => {
        const isActive = value === opt.value;
        return (
          <button
            key={opt.value}
            type="button"
            role="radio"
            aria-checked={isActive}
            disabled={disabled}
            onClick={() => !disabled && onChange?.(opt.value)}
            className={`ws-segment__btn ${isActive ? 'is-active' : ''} ${opt.tone ? `ws-segment__btn--${opt.tone}` : ''}`}
          >
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
