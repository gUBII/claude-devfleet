import React, { useState, useEffect, useCallback } from 'react';
import {
  adminListUsers,
  adminListUserProjects,
  adminGrantProjectAccess,
  adminRevokeProjectAccess,
  adminGetUserActivity,
  listProjects,
  createInvite,
} from '../api/client';
import { useFleetEvents } from '../hooks/useFleetEvents';
import { useAuth } from '../auth';

function StatPill({ label, value, tone }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{ fontSize: 18, fontWeight: 700, color: tone || 'var(--text)' }}>{value}</span>
      <span className="text-sm text-muted" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</span>
    </div>
  );
}

function UserCard({ user, allProjects, onChanged }) {
  const [expanded, setExpanded] = useState(false);
  const [bindings, setBindings] = useState(null);
  const [activity, setActivity] = useState(null);
  const [grantPid, setGrantPid] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const loadDetail = useCallback(async () => {
    setError(null);
    try {
      const [b, a] = await Promise.all([
        adminListUserProjects(user.id),
        adminGetUserActivity(user.id),
      ]);
      setBindings(b.bindings || []);
      setActivity(a);
    } catch (e) {
      setError(e.message);
    }
  }, [user.id]);

  useEffect(() => {
    if (expanded && bindings === null) loadDetail();
  }, [expanded, bindings, loadDetail]);

  const handleGrant = async () => {
    if (!grantPid) return;
    setBusy(true);
    setError(null);
    try {
      await adminGrantProjectAccess(user.id, grantPid);
      setGrantPid('');
      await loadDetail();
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const handleRevoke = async (pid) => {
    setBusy(true);
    setError(null);
    try {
      await adminRevokeProjectAccess(user.id, pid);
      await loadDetail();
      onChanged();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const boundIds = new Set((bindings || []).map(b => b.project_id));
  const grantable = allProjects.filter(p => !boundIds.has(p.id));

  return (
    <div className="card" style={{ marginBottom: 14 }}>
      <div className="flex justify-between items-center" style={{ gap: 12 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 15, fontWeight: 600 }}>{user.email}</span>
            <span
              className="text-sm"
              style={{
                fontSize: 11, padding: '1px 8px', borderRadius: 999,
                background: user.role === 'admin' ? 'var(--accent-dim, rgba(120,120,255,0.15))' : 'var(--surface-2, #1a1a1a)',
                color: user.role === 'admin' ? 'var(--accent, #8a8aff)' : 'var(--text-muted)',
                textTransform: 'uppercase', letterSpacing: '0.05em',
              }}
            >
              {user.role}
            </span>
          </div>
          {user.role === 'admin' ? (
            <span className="text-sm text-muted">Implicit access to all projects</span>
          ) : (
            <span className="text-sm text-muted">
              {user.bound_project_count || 0} project{user.bound_project_count === 1 ? '' : 's'} bound
            </span>
          )}
        </div>

        {user.role !== 'admin' && (
          <div className="flex items-center" style={{ gap: 22 }}>
            <StatPill label="Running" value={user.running_agents || 0}
                      tone={user.running_agents > 0 ? 'var(--warning)' : undefined} />
            <StatPill label="Today $" value={`$${(user.cost_today_usd || 0).toFixed(2)}`} />
            <StatPill label="Done" value={user.missions_completed || 0} tone="var(--success)" />
            <button className="btn btn-ghost btn-sm" onClick={() => setExpanded(e => !e)}>
              {expanded ? 'Hide' : 'Manage'}
            </button>
          </div>
        )}
      </div>

      {expanded && user.role !== 'admin' && (
        <div style={{ marginTop: 16, borderTop: '1px solid var(--border, #222)', paddingTop: 16 }}>
          {error && <div style={{ color: 'var(--danger)', marginBottom: 10 }}>{error}</div>}

          <div className="text-sm text-muted" style={{ marginBottom: 8, fontWeight: 600 }}>Bound projects</div>
          {bindings === null ? (
            <div className="text-sm text-muted">Loading…</div>
          ) : bindings.length === 0 ? (
            <div className="text-sm text-muted" style={{ marginBottom: 12 }}>No projects bound — this user sees nothing.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
              {bindings.map(b => (
                <div key={b.project_id} className="flex justify-between items-center"
                     style={{ padding: '6px 10px', background: 'var(--surface-2, #141414)', borderRadius: 6 }}>
                  <div style={{ display: 'flex', flexDirection: 'column' }}>
                    <span className="text-sm" style={{ fontWeight: 500 }}>{b.project_name}</span>
                    <span className="text-sm text-muted font-mono" style={{ fontSize: 11, wordBreak: 'break-all' }}>{b.project_path}</span>
                  </div>
                  <button className="btn btn-ghost btn-sm" disabled={busy}
                          onClick={() => handleRevoke(b.project_id)}>Revoke</button>
                </div>
              ))}
            </div>
          )}

          {grantable.length > 0 && (
            <div className="flex items-center" style={{ gap: 8, marginBottom: 16 }}>
              <select
                value={grantPid}
                onChange={e => setGrantPid(e.target.value)}
                style={{ flex: 1, padding: '6px 10px', background: 'var(--surface-2, #141414)',
                         border: '1px solid var(--border, #222)', borderRadius: 6, color: 'var(--text)' }}
              >
                <option value="">+ Grant project access…</option>
                {grantable.map(p => <option key={p.id} value={p.id}>{p.name} — {p.path}</option>)}
              </select>
              <button className="btn btn-primary btn-sm" disabled={!grantPid || busy} onClick={handleGrant}>Grant</button>
            </div>
          )}

          {activity && (
            <div style={{ display: 'flex', gap: 28, flexWrap: 'wrap', paddingTop: 4 }}>
              <StatPill label="Total missions" value={activity.stats?.total || 0} />
              <StatPill label="Running" value={activity.stats?.running || 0}
                        tone={activity.stats?.running > 0 ? 'var(--warning)' : undefined} />
              <StatPill label="Completed" value={activity.stats?.completed || 0} tone="var(--success)" />
              <StatPill label="Failed" value={activity.stats?.failed || 0}
                        tone={activity.stats?.failed > 0 ? 'var(--danger)' : undefined} />
              <StatPill label="Total cost" value={`$${(activity.stats?.total_cost_usd || 0).toFixed(2)}`} />
              <StatPill label="Tokens" value={(activity.stats?.total_tokens || 0).toLocaleString()} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

const inputStyle = {
  padding: '6px 10px', background: 'var(--surface-2, #141414)',
  border: '1px solid var(--border, #222)', borderRadius: 6, color: 'var(--text)',
};

function InviteGenerator() {
  const [name, setName] = useState('');
  const [folder, setFolder] = useState('');
  const [link, setLink] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [copied, setCopied] = useState(false);

  const generate = async () => {
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    setCopied(false);
    setLink('');
    try {
      const res = await createInvite(name.trim(), folder.trim());
      // The API returns a relative path; the absolute URL is composed here from
      // the admin's own origin (SPA + API may live on different origins).
      setLink(window.location.origin + res.invite_path);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked — the field is selectable for manual copy */
    }
  };

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>Invite a teammate</div>
      <p className="text-sm text-muted" style={{ marginBottom: 12 }}>
        Their name seeds a personal project folder and their leaderboard identity on signup. The folder slug is optional.
      </p>
      {error && <div style={{ color: 'var(--danger)', marginBottom: 10 }}>{error}</div>}
      <div className="flex items-center" style={{ gap: 8, flexWrap: 'wrap' }}>
        <input
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="Full name (e.g. Alice Wong)"
          style={{ ...inputStyle, flex: '2 1 220px' }}
        />
        <input
          value={folder}
          onChange={e => setFolder(e.target.value)}
          placeholder="Folder slug (optional)"
          style={{ ...inputStyle, flex: '1 1 160px' }}
        />
        <button className="btn btn-primary btn-sm" disabled={!name.trim() || busy} onClick={generate}>
          {busy ? 'Generating…' : 'Generate link'}
        </button>
      </div>
      {link && (
        <div className="flex items-center" style={{ gap: 8, marginTop: 12 }}>
          <input
            readOnly
            value={link}
            onFocus={e => e.target.select()}
            style={{ ...inputStyle, flex: 1, fontFamily: 'monospace', fontSize: 12 }}
          />
          <button className="btn btn-ghost btn-sm" onClick={copy}>{copied ? 'Copied!' : 'Copy'}</button>
        </div>
      )}
    </div>
  );
}

export default function AdminUsers({ navigate }) {
  const { isAdmin } = useAuth();
  const [users, setUsers] = useState([]);
  const [allProjects, setAllProjects] = useState([]);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    try {
      const [u, p] = await Promise.all([adminListUsers(), listProjects()]);
      setUsers(u);
      setAllProjects(p);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => { if (isAdmin) load(); }, [isAdmin, load]);

  // Live refresh of the top-line rollup (running agents, cost) on fleet events.
  useFleetEvents((evt) => {
    switch (evt.type) {
      case 'mission_dispatched':
      case 'mission_completed':
      case 'mission_failed':
      case 'mission_cancelled':
        load();
        break;
      default:
        break;
    }
  });

  if (!isAdmin) {
    return (
      <div className="empty-state">
        <h3>Admins only</h3>
        <p>This page is restricted to administrators.</p>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h2>Admin · Users &amp; Access</h2>
          <p>Bind each developer to the project folders they may see and dispatch agents into.</p>
        </div>
      </div>

      <InviteGenerator />

      {error && <div style={{ color: 'var(--danger)', marginBottom: 16 }}>{error}</div>}

      {users.length === 0 ? (
        <div className="empty-state"><h3>No users</h3></div>
      ) : (
        users.map(u => (
          <UserCard key={u.id} user={u} allProjects={allProjects} onChanged={load} />
        ))
      )}
    </div>
  );
}
