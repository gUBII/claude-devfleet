import React, { useState, useEffect } from 'react';
import Moofasa from './Moofasa';

/**
 * Floating Moofasa widget — matches the Nexis chat-bot pattern.
 * Mascot peeks up from the bottom-right corner with a "Let's talk!" bubble.
 * Click anywhere on the widget → onOpen() to reveal the full ProjectBot panel.
 *
 * Hidden when `hidden` prop is true (i.e. while the panel is open).
 */
export default function MoofasaFloater({ onOpen, hidden = false, projectName }) {
  const [bubbleVisible, setBubbleVisible] = useState(false);

  // Stagger: mascot peeks first, then the bubble pops in.
  useEffect(() => {
    if (hidden) {
      setBubbleVisible(false);
      return;
    }
    const t = setTimeout(() => setBubbleVisible(true), 450);
    return () => clearTimeout(t);
  }, [hidden]);

  if (hidden) return null;

  return (
    <button
      className="moofasa-floater"
      onClick={onOpen}
      aria-label={`Open Moofasa, the assistant for ${projectName || 'this project'}`}
      title="Talk to Moofasa"
    >
      <span
        className={`moofasa-floater__bubble ${bubbleVisible ? 'is-visible' : ''}`}
        aria-hidden="true"
      >
        Let's talk!
      </span>
      <span className="moofasa-floater__mascot">
        <Moofasa size={68} state="idle" />
      </span>
    </button>
  );
}
