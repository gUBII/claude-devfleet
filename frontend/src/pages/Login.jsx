import React, { useEffect, useRef, useState } from 'react';
import { login as loginApi } from '../api/client';
import { useAuth } from '../auth';
import BrandMark from '../components/BrandMark';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const TARGET_LEN = 12;          // length at which intensity hits full

export default function Login({ navigate }) {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [pulseKey, setPulseKey] = useState(0);
  const [intensity, setIntensity] = useState(1);
  const idleTimer = useRef(null);

  const emailValid = EMAIL_RE.test(email);

  // Decide brand-mark state — purely cosmetic, derived from UI state, never
  // from the password content.
  let brandState = 'idle';
  if (emailValid && password.length > 0) brandState = 'typing';
  else if (emailValid) brandState = 'armed';

  // Length-based ramp: 0 chars = idle (1.0 = full bright), grows toward
  // TARGET_LEN as user types. Stays at full brightness past target.
  useEffect(() => {
    if (!emailValid) {
      setIntensity(1);          // idle full-bright on the hero
      return;
    }
    if (password.length === 0) {
      setIntensity(1);
      return;
    }
    const ramp = Math.min(1, 0.45 + (password.length / TARGET_LEN) * 0.55);
    setIntensity(ramp);
  }, [password.length, emailValid]);

  // After a brief pause in typing, dim the brand mark — "stop typing → light
  // fades" feel. Tied to RHYTHM, not correctness. No leak.
  useEffect(() => {
    if (idleTimer.current) {
      clearTimeout(idleTimer.current);
      idleTimer.current = null;
    }
    if (!emailValid || password.length === 0) return;
    idleTimer.current = setTimeout(() => {
      setIntensity((cur) => Math.max(0.35, cur * 0.55));
    }, 900);
    return () => {
      if (idleTimer.current) clearTimeout(idleTimer.current);
      idleTimer.current = null;
    };
  }, [password, emailValid]);

  const handlePasswordChange = (e) => {
    const next = e.target.value;
    const prev = password;
    setPassword(next);
    if (!emailValid) return;
    // Skip the per-keystroke effects when the field is becoming empty — the
    // length-ramp effect immediately restores intensity to 1, and a strike
    // pulse on an empty field looks like a glitch.
    if (next.length === 0) return;
    setPulseKey((k) => k + 1);                // trigger flicker pulse
    if (next.length < prev.length) {
      // backspace dims briefly (only when characters remain)
      setIntensity((cur) => Math.max(0.4, cur * 0.7));
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true); setError(null);
    try {
      const res = await loginApi({ email, password });
      login(res.access_token, res.user);
      navigate('splash');
    } catch (err) {
      setError(err.message);
      setIntensity(0.35);                     // failed → light dies
    }
    finally { setSubmitting(false); }
  };

  return (
    <div className="auth-page">
      <div className="auth-gate-card">
        <div className="auth-nexis-logo" style={{ display: 'flex', justifyContent: 'center', marginBottom: 4 }}>
          <BrandMark
            size="lg"
            state={brandState}
            intensity={intensity}
            pulseKey={pulseKey}
          />
        </div>
        <div className="auth-gate-divider" />
        <p className="auth-gate-sub">Workstation Sign-In</p>

        <form onSubmit={handleSubmit} className="auth-form" style={{ marginTop: 18 }}>
          {error && <div className="auth-error">{error}</div>}
          <div style={{ position: 'relative', width: '100%' }}>
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              className="auth-input"
              autoComplete="email"
              autoFocus
              style={{ width: '100%', paddingRight: 32 }}
            />
            {emailValid && (
              <span
                aria-hidden="true"
                style={{
                  position: 'absolute', right: 10, top: '50%',
                  transform: 'translateY(-50%)',
                  color: 'var(--rag-g)', fontSize: 14,
                  textShadow: '0 0 8px rgba(110,163,88,0.65)',
                }}
                title="Email format ok"
              >✓</span>
            )}
          </div>
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={handlePasswordChange}
            required
            disabled={!emailValid}
            className="auth-input"
            autoComplete="current-password"
          />
          <button type="submit" disabled={submitting || !emailValid} className="auth-btn">
            {submitting ? 'SIGNING IN…' : 'SIGN IN →'}
          </button>
        </form>

        <p className="auth-footer">
          Need access?{' '}
          <button className="auth-link" onClick={() => navigate('register')} type="button">
            Use an invite link
          </button>
        </p>
      </div>
    </div>
  );
}
