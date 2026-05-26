import React from 'react';

/**
 * BrandMark — the locked DevFleet logo.
 *
 * Renders the ASCII block-letter art from start.sh (the terminal banner)
 * as <pre> text. Same source of truth across CLI + Web.
 *
 *   ███████╗ █████╗ ██████╗ ██╗  ██╗ █████╗ ███╗   ██╗'s
 *   ██████╗ ███████╗██╗   ██╗███████╗██╗     ███████╗███████╗████████╗
 *
 * Props:
 *   size      — 'sm' | 'md' | 'lg'
 *   wordmark  — if false, render the compact wordmark instead of full ASCII
 *   className — optional extra class
 */

// FARHAN with a small block-letter ' s tacked to the top-right corner.
// The full block letters are 6 rows tall; the possessive is a 3-row mini-block
// aligned to the top of the FARHAN block so it reads as a superscript "'s".
const FARHAN = [
  "███████╗ █████╗ ██████╗ ██╗  ██╗ █████╗ ███╗   ██╗ █ ▄▀▀╗",
  "██╔════╝██╔══██╗██╔══██╗██║  ██║██╔══██╗████╗  ██║   ╚═╗ ",
  "█████╗  ███████║██████╔╝███████║███████║██╔██╗ ██║   ▀▄╝ ",
  "██╔══╝  ██╔══██║██╔══██╗██╔══██║██╔══██║██║╚██╗██║       ",
  "██║     ██║  ██║██║  ██║██║  ██║██║  ██║██║ ╚████║       ",
  "╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝       ",
].join('\n');

const DEVFLEET = [
  "██████╗ ███████╗██╗   ██╗███████╗██╗     ███████╗███████╗████████╗",
  "██╔══██╗██╔════╝██║   ██║██╔════╝██║     ██╔════╝██╔════╝╚══██╔══╝",
  "██║  ██║█████╗  ██║   ██║█████╗  ██║     █████╗  █████╗     ██║   ",
  "██║  ██║██╔══╝  ╚██╗ ██╔╝██╔══╝  ██║     ██╔══╝  ██╔══╝     ██║   ",
  "██████╔╝███████╗ ╚████╔╝ ██║     ███████╗███████╗███████╗   ██║   ",
  "╚═════╝ ╚══════╝  ╚═══╝  ╚═╝     ╚══════╝╚══════╝╚══════╝   ╚═╝   ",
].join('\n');

const FONT_SIZE = {
  sm: 5,      // sidebar — fits 240px column
  md: 8,
  lg: 11,     // login card
};

/**
 * State-driven props (all optional, decorative-only — no auth info leaked):
 *   state     — 'idle' | 'armed' | 'typing' (drives the animation register)
 *   intensity — 0..1, scales glow + opacity for length-based ramp
 *   pulseKey  — change this number on every keystroke to trigger a flicker pulse
 */
export default function BrandMark({
  size = 'md',
  wordmark = false,
  className = '',
  state = 'idle',
  intensity = 1,
  pulseKey = 0,
}) {
  const fs = FONT_SIZE[size] || FONT_SIZE.md;
  const styleVars = {
    '--brand-intensity': Math.max(0.35, Math.min(1, intensity)),
  };

  // For the smallest size, render just a tight compact wordmark rather than
  // the full block letters — sidebar column is too narrow for the ASCII art.
  if (size === 'sm') {
    return (
      <span className={`brand-mark brand-mark--sm ${className}`}>
        <span className="brand-mark__bar" aria-hidden="true">▌▍▎▏</span>
        <span className="brand-mark__sep" aria-hidden="true">│</span>
        <span className="brand-mark__wordmark">
          FARHAN<span className="brand-mark__apos">'S</span> DEVFLEET<span className="brand-mark__tm">™</span>
        </span>
      </span>
    );
  }

  return (
    <pre
      key={`pulse-${pulseKey}`}
      className={`brand-mark brand-mark--${size} brand-mark--ascii is-${state} ${className}`}
      style={{ fontSize: `${fs}px`, lineHeight: 1.05, ...styleVars }}
      aria-label="Farhan's DevFleet"
    >
{FARHAN}
{'\n'}
{DEVFLEET}
    </pre>
  );
}
