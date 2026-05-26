import React, { useEffect } from 'react';
import BrandMark from '../components/BrandMark';

export default function Splash({ navigate }) {
  useEffect(() => {
    const t = setTimeout(() => navigate('dashboard'), 1800);
    return () => clearTimeout(t);
  }, [navigate]);

  return (
    <div className="splash-page">
      <div className="splash-inner">
        <div className="splash-spinner-ring" />
        <div style={{ margin: '12px 0 6px' }}>
          <BrandMark size="lg" />
        </div>
        <p className="splash-label">INITIALIZING WORKSTATION…</p>
        <a
          className="splash-portfolio"
          href="https://4han.life"
          target="_blank"
          rel="noopener noreferrer"
        >
          Built by Farhan Rashid · 4han.life ↗
        </a>
      </div>
    </div>
  );
}
