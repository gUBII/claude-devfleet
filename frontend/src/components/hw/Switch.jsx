import React from 'react';

/**
 * Switch — hardware rocker toggle.
 *
 *   OFF [████   ]   ON  [   ████]
 *
 * Two-position switch with a tactile slide. Looks like a real amp toggle.
 *
 * Props:
 *   checked   — boolean
 *   onChange  — (next: boolean) => void
 *   label     — optional text rendered to the left
 *   tone      — 'amber' (default) | 'g' | 'r'
 *   disabled  — boolean
 */
export default function Switch({
  checked,
  onChange,
  label,
  tone = 'amber',
  disabled = false,
  ariaLabel,
}) {
  const handleClick = () => {
    if (disabled) return;
    onChange?.(!checked);
  };

  const handleKey = (e) => {
    if (disabled) return;
    if (e.key === ' ' || e.key === 'Enter') {
      e.preventDefault();
      onChange?.(!checked);
    }
    if (e.key === 'ArrowLeft') onChange?.(false);
    if (e.key === 'ArrowRight') onChange?.(true);
  };

  return (
    <span className={`ws-switch-wrap ${disabled ? 'is-disabled' : ''}`}>
      {label && <span className="ws-switch-label">{label}</span>}
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={ariaLabel || label || 'toggle'}
        disabled={disabled}
        onClick={handleClick}
        onKeyDown={handleKey}
        className={`ws-switch ws-switch--${tone} ${checked ? 'is-on' : 'is-off'}`}
      >
        <span className="ws-switch__track">
          <span className="ws-switch__mark ws-switch__mark--off">O</span>
          <span className="ws-switch__mark ws-switch__mark--on">I</span>
        </span>
        <span className="ws-switch__knob" />
      </button>
    </span>
  );
}
