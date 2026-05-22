import React from 'react';
import { useReducedMotion } from '../hooks/useReducedMotion';

export default function Moofasa({ size = 28, state = 'idle', className = '', style = {} }) {
  const reduced = useReducedMotion();
  const animation = reduced
    ? 'none'
    : state === 'thinking'
      ? 'moofasa-think 1.6s ease-in-out infinite'
      : 'moofasa-float 4s ease-in-out infinite';
  return (
    <img
      src="/moofasa.png"
      alt="Moofasa"
      className={className}
      style={{
        width: size,
        height: size,
        objectFit: 'contain',
        animation,
        willChange: reduced ? 'auto' : 'transform',
        ...style,
      }}
    />
  );
}
