import React from 'react';

/**
 * BrandMark — the locked DevFleet logo.
 *
 *   ▌▍▎▏ │ FARHAN'S DEVFLEET™
 *
 * Renders a designed PNG asset generated via Gemini Nano Banana
 * (frontend/public/brand/farhan-devfleet-logo.png). Heights are fixed
 * tiers so the image stays crisp at any zoom; width auto-scales by
 * preserving aspect ratio. The asset already includes the dark
 * charcoal background, so callers don't need to wrap it.
 *
 * Props:
 *   size      — 'sm' | 'md' | 'lg'   (height tier)
 *   wordmark  — false to render the glyph-only crop (sidebar/favicon)
 *   className — optional extra class
 */
const HEIGHTS = { sm: 28, md: 42, lg: 80 };

export default function BrandMark({ size = 'md', wordmark = true, className = '' }) {
  const h = HEIGHTS[size] || HEIGHTS.md;

  // Full lockup vs glyph-only. Both are the same source — we crop via CSS.
  const srcWebp = '/brand/farhan-devfleet-logo.webp';
  const srcPng  = '/brand/farhan-devfleet-logo.png';

  if (wordmark) {
    return (
      <picture className={`brand-mark brand-mark--${size} ${className}`}>
        <source srcSet={srcWebp} type="image/webp" />
        <img
          src={srcPng}
          alt="Farhan's DevFleet"
          style={{
            height: `${h}px`,
            width: 'auto',
            display: 'block',
            maxWidth: '100%',
            objectFit: 'contain',
          }}
          draggable={false}
        />
      </picture>
    );
  }

  // Glyph-only — crop to the left ~22% of the image where the four bars live.
  // Done with object-position + a fixed aspect-ratio container.
  return (
    <span
      className={`brand-mark brand-mark--${size} brand-mark--glyph ${className}`}
      style={{
        display: 'inline-block',
        height: `${h}px`,
        width: `${h * 0.95}px`,
        overflow: 'hidden',
        flexShrink: 0,
      }}
    >
      <picture>
        <source srcSet={srcWebp} type="image/webp" />
        <img
          src={srcPng}
          alt="Farhan's DevFleet"
          style={{
            height: '100%',
            width: 'auto',
            display: 'block',
            objectFit: 'cover',
            objectPosition: 'left center',
            transform: 'scale(1.6) translateX(8%)',
            transformOrigin: 'left center',
          }}
          draggable={false}
        />
      </picture>
    </span>
  );
}
