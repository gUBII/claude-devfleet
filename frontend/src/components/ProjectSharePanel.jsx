import React, { useState, useEffect, useCallback } from 'react';
import {
  listProjectShares,
  shareProject,
  unshareProject,
  listDevProfiles,
  listProjects,
  listLanes,
  shareWorker,
} from '../api/client';
import { useAuth } from '../auth';

const inputStyle = {
  padding: '6px 10px',
  background: 'var(--surface-2, #141414)',
  border: '1px solid var(--border, #222)',
  borderRadius: 6,
  color: 'var(--text)',
};

const nameOf = (p) => p.display_name || p.github_login || (p.email || '').split('@')[0];

export default function ProjectSharePanel({ projectId, project }) {
  const { user, isAdmin } = useAuth();
  // null = still probing authority; false = not owner/admin (hide); true = show.
  const [allowed, setAllowed] = useState(null);
  const [shares, setShares] = useState([]);
  const [people, setPeople] = useState([]);
  const [pickUser, setPickUser] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const [workers, setWorkers] = useState([]);
  const [targets, setTargets] = useState([]);
  const [pickWorker, setPickWorker] = useState('');
  const [pickTarget, setPickTarget] = useState('');
  const [wBusy, setWBusy] = useState(false);
  const [wMsg, setWMsg] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const s = await listProjectShares(projectId);
      setAllowed(true);
      setShares(s);
    } catch (e) {
      // 403 → caller isn't the owner or an admin: hide the whole panel quietly.
      if (e?.status === 403) {
        setAllowed(false);
        return;
      }
      // Transient (500 / network): don't silently hide sharing — show the panel
      // with an error so the owner knows it failed to load, not that they lack access.
      setAllowed(true);
      setError(`Couldn't load sharing settings — ${e?.message || 'please retry'}`);
    }
    try {
      const [profiles, projs, lanes] = await Promise.all([
        listDevProfiles(),
        listProjects(),
        listLanes(projectId),
      ]);
      setPeople(profiles);
      // Targets you may add a worker to: projects you own (or any, if admin),
      // excluding this one. The backend re-checks owner-or-admin authority.
      setTargets(projs.filter((p) => p.id !== projectId && (isAdmin || p.created_by === user?.id)));
      // This project's own Workers (project-scoped lanes; globals have null project_id).
      setWorkers(lanes.filter((l) => l.project_id === projectId));
    } catch (e) {
      setError(e.message);
    }
  }, [projectId, isAdmin, user?.id]);

  useEffect(() => {
    load();
  }, [load]);

  if (allowed !== true) return null;

  const ownerId = project?.created_by;
  const sharedIds = new Set(shares.map((s) => s.user_id));
  const shareable = people.filter((p) => p.user_id !== ownerId && !sharedIds.has(p.user_id));

  const doShare = async () => {
    if (!pickUser) return;
    setBusy(true);
    setError(null);
    try {
      await shareProject(projectId, pickUser);
      setPickUser('');
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const doUnshare = async (uid) => {
    setBusy(true);
    setError(null);
    try {
      await unshareProject(projectId, uid);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };

  const doShareWorker = async () => {
    if (!pickWorker || !pickTarget) return;
    setWBusy(true);
    setWMsg(null);
    setError(null);
    try {
      const res = await shareWorker(projectId, pickWorker, pickTarget);
      setWMsg(`Cloned as “${res.cloned_lane}”.`);
      setPickWorker('');
      setPickTarget('');
    } catch (e) {
      setError(e.message);
    } finally {
      setWBusy(false);
    }
  };

  return (
    <div className="card" style={{ marginBottom: 24 }}>
      <div className="text-sm" style={{ fontWeight: 600, marginBottom: 4 }}>Sharing</div>
      <p className="text-sm text-muted" style={{ marginBottom: 12 }}>
        Give a teammate access to this project, or clone one of its Workers into a project you own.
      </p>
      {error && <div style={{ color: 'var(--danger)', marginBottom: 10 }}>{error}</div>}

      {shares.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 12 }}>
          {shares.map((s) => (
            <div
              key={s.user_id}
              className="flex justify-between items-center"
              style={{ padding: '6px 10px', background: 'var(--surface-2, #141414)', borderRadius: 6 }}
            >
              <span className="text-sm">
                {s.display_name || s.email}
                {s.user_id === ownerId && (
                  <span className="text-muted" style={{ marginLeft: 8, fontSize: 11 }}>owner</span>
                )}
              </span>
              {s.user_id !== ownerId && (
                <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => doUnshare(s.user_id)}>
                  Remove
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center" style={{ gap: 8, marginBottom: 18 }}>
        <select value={pickUser} onChange={(e) => setPickUser(e.target.value)} style={{ ...inputStyle, flex: 1 }}>
          <option value="">+ Share with a teammate…</option>
          {shareable.map((p) => (
            <option key={p.user_id} value={p.user_id}>{nameOf(p)} — {p.email}</option>
          ))}
        </select>
        <button className="btn btn-primary btn-sm" disabled={!pickUser || busy} onClick={doShare}>Share</button>
      </div>

      {workers.length > 0 && targets.length > 0 && (
        <div style={{ borderTop: '1px solid var(--border, #222)', paddingTop: 14 }}>
          <div className="text-sm" style={{ fontWeight: 600, marginBottom: 8 }}>Clone a Worker into another project</div>
          {wMsg && <div className="text-sm" style={{ color: 'var(--success)', marginBottom: 8 }}>{wMsg}</div>}
          <div className="flex items-center" style={{ gap: 8, flexWrap: 'wrap' }}>
            <select value={pickWorker} onChange={(e) => setPickWorker(e.target.value)} style={{ ...inputStyle, flex: '1 1 160px' }}>
              <option value="">Worker…</option>
              {workers.map((w) => (
                <option key={w.name} value={w.name}>{w.icon ? `${w.icon} ` : ''}{w.name}</option>
              ))}
            </select>
            <span className="text-muted text-sm">→</span>
            <select value={pickTarget} onChange={(e) => setPickTarget(e.target.value)} style={{ ...inputStyle, flex: '1 1 160px' }}>
              <option value="">Target project…</option>
              {targets.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
            <button className="btn btn-primary btn-sm" disabled={!pickWorker || !pickTarget || wBusy} onClick={doShareWorker}>
              Clone
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
