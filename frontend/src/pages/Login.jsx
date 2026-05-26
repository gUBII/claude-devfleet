import React, { useState } from 'react';
import { login as loginApi } from '../api/client';
import { useAuth } from '../auth';
import BrandMark from '../components/BrandMark';

export default function Login({ navigate }) {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true); setError(null);
    try {
      const res = await loginApi({ email, password });
      login(res.access_token, res.user);
      navigate('splash');
    } catch (err) { setError(err.message); }
    finally { setSubmitting(false); }
  };

  return (
    <div className="auth-page">
      <div className="auth-gate-card">
        <div className="auth-nexis-logo" style={{ display: 'flex', justifyContent: 'center', marginBottom: 4 }}>
          <BrandMark size="lg" />
        </div>
        <div className="auth-gate-divider" />
        <p className="auth-gate-sub">Workstation Sign-In</p>

        <form onSubmit={handleSubmit} className="auth-form" style={{ marginTop: 18 }}>
          {error && <div className="auth-error">{error}</div>}
          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            required
            className="auth-input"
            autoComplete="email"
            autoFocus
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            className="auth-input"
            autoComplete="current-password"
          />
          <button type="submit" disabled={submitting} className="auth-btn">
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
