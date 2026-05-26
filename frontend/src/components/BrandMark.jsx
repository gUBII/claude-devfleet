import React from 'react';

/**
 * BrandMark — the locked DevFleet logo.
 *
 * Four amber bars (decreasing width) + wordmark in Space Mono.
 * Crisp at any size via SVG. Drop-in for sidebar, login, splash, print.
 *
 * Sizes:
 *   sm  → wordmark hidden, just the glyph (collapsed sidebar / favicon)
 *   md  → standard sidebar size
 *   lg  → splash / login hero
 */
export default function BrandMark({ size = 'md', wordmark = true, color }) {
  const heights = { sm: 18, md: 22, lg: 36 };
  const fontSizes = { sm: 12, md: 15, lg: 26 };
  const gaps = { sm: 8, md: 10, lg: 14 };
  const h = heights[size] || heights.md;
  const fs = fontSizes[size] || fontSizes.md;
  const gap = gaps[size] || gaps.md;
  const inkColor = color || 'var(--brand-mark, #d4a017)';

  // Bar widths decreasing — visually weighted left-to-right
  // Spacing tuned so the bars feel like a single glyph, not 4 rectangles
  const barW = h * 0.18;
  const bars = [
    { x: 0,                   w: barW * 1.05, h },
    { x: barW * 1.4,          w: barW * 0.85, h },
    { x: barW * 2.55,         w: barW * 0.65, h },
    { x: barW * 3.5,          w: barW * 0.45, h },
  ];
  const glyphW = barW * 4.5;
  const sepX = glyphW + h * 0.4;
  const wordmarkX = sepX + h * 0.5;

  return (
    <span
      className={`brand-mark brand-mark--${size}`}
      style={{ display: 'inline-flex', alignItems: 'center', gap: `${gap}px`, color: inkColor }}
    >
      <svg
        viewBox={`0 0 ${wordmark ? '180' : glyphW + 2} ${h + 2}`}
        height={h}
        width={wordmark ? 'auto' : glyphW + 2}
        preserveAspectRatio="xMinYMid meet"
        aria-label="Farhan's DevFleet"
        role="img"
        style={{ flexShrink: 0 }}
      >
        {bars.map((b, i) => (
          <rect key={i} x={b.x} y={1} width={b.w} height={b.h} fill="currentColor" />
        ))}
        {wordmark && (
          <line
            x1={sepX} y1={2}
            x2={sepX} y2={h}
            stroke="currentColor"
            strokeWidth="1"
            opacity="0.45"
          />
        )}
      </svg>
      {wordmark && (
        <span
          className="brand-mark__wordmark"
          style={{
            fontFamily: '"Space Mono", "JetBrains Mono", ui-monospace, monospace',
            fontWeight: 700,
            fontSize: `${fs}px`,
            letterSpacing: '0.04em',
            color: inkColor,
            whiteSpace: 'nowrap',
            lineHeight: 1,
          }}
        >
          FARHAN'S DEVFLEET
          <sup
            style={{
              fontSize: '0.5em',
              marginLeft: 1,
              opacity: 0.7,
              verticalAlign: 'super',
              fontWeight: 500,
            }}
          >TM</sup>
        </span>
      )}
    </span>
  );
}
