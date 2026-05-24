import React, { useState } from 'react';
import { changePassword } from '../api/client';

export default function ChangePassword({ onClose }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    if (!current || !next) { setError('All fields are required'); return; }
    if (next !== confirm) { setError('New passwords do not match'); return; }
    setBusy(true);
    try {
      await changePassword({ current_password: current, new_password: next });
      setDone(true);
      setTimeout(onClose, 1500);
    } catch (e) {
      setError(e.message || 'Failed to change password');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 420 }}>
        <h3>Change password</h3>
        {done ? (
          <div style={{ color: 'var(--accent-success, #5bb8a6)', fontSize: 14, padding: '12px 0' }}>
            ✓ Password updated.
          </div>
        ) : (
          <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <input
              type="password"
              placeholder="Current password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              autoComplete="current-password"
              required
              className="auth-input"
              maxLength={72}
            />
            <input
              type="password"
              placeholder="New password (max 72 chars)"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              autoComplete="new-password"
              required
              className="auth-input"
              maxLength={72}
            />
            <input
              type="password"
              placeholder="Confirm new password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
              required
              className="auth-input"
              maxLength={72}
            />
            {error && (
              <div style={{
                color: 'var(--accent-danger, #d4533a)',
                fontSize: 13,
                padding: '4px 0',
              }}>{error}</div>
            )}
            <div className="modal-actions">
              <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>
                Cancel
              </button>
              <button type="submit" className="btn btn-primary" disabled={busy}>
                {busy ? 'Saving…' : 'Save'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
