import React, { useEffect, useState } from 'react';
import { listDevProfiles } from '../api/client';

const MEDAL_BY_RANK = { 1: '🥇', 2: '🥈', 3: '🥉' };

function initialsFromEmail(email) {
  const local = (email || '').split('@')[0] || '?';
  const parts = local.split(/[._-]/).filter(Boolean);
  if (parts.length === 0) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

function Avatar({ url, fallback }) {
  const [errored, setErrored] = useState(false);
  if (url && !errored) {
    return (
      <img
        src={url}
        alt=""
        className="devprofile-avatar"
        onError={() => setErrored(true)}
      />
    );
  }
  return (
    <div className="devprofile-avatar devprofile-avatar--initials">
      {fallback}
    </div>
  );
}

function ProfileCard({ profile, rank }) {
  const medal = MEDAL_BY_RANK[rank] || `#${rank}`;
  const displayName =
    profile.display_name || profile.github_login || profile.email.split('@')[0];
  const sub = profile.github_name || profile.email;

  return (
    <div className="devprofile-card">
      <div className="devprofile-rank">{medal}</div>
      <Avatar
        url={profile.avatar_url}
        fallback={initialsFromEmail(profile.email)}
      />
      <div className="devprofile-meta">
        <div className="devprofile-name">{displayName}</div>
        <div className="devprofile-sub">{sub}</div>
      </div>
      <div className="devprofile-stats">
        <div className="devprofile-stat">
          <span className="devprofile-stat-value">{profile.likeness_points}</span>
          <span className="devprofile-stat-label">Likeness</span>
        </div>
        <div className="devprofile-stat">
          <span className="devprofile-stat-value">
            ${profile.dollars_saved_routing.toFixed(2)}
          </span>
          <span className="devprofile-stat-label">Saved Farhan</span>
        </div>
        <div className="devprofile-stat">
          <span className="devprofile-stat-value">
            {profile.current_clean_streak}
          </span>
          <span className="devprofile-stat-label">
            Clean streak{profile.longest_clean_streak > profile.current_clean_streak
              ? ` (best ${profile.longest_clean_streak})`
              : ''}
          </span>
        </div>
        <div className="devprofile-stat">
          <span className="devprofile-stat-value">
            {profile.pr_merges_clean}/{profile.pr_merges_total || 0}
          </span>
          <span className="devprofile-stat-label">Clean PR merges</span>
        </div>
      </div>
    </div>
  );
}

export default function DevProfiles() {
  const [profiles, setProfiles] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const rows = await listDevProfiles();
        if (!cancelled) setProfiles(rows);
      } catch (e) {
        if (!cancelled) setError(e.message || 'Failed to load profiles');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  if (loading) return <div className="page-loading">Loading dev profiles…</div>;

  return (
    <div className="devprofile-page">
      <div className="devprofile-header">
        <h1>Dev Profiles</h1>
        <p className="subtitle">
          Likeness rewards thoughtful behaviour — clean merges, model routing wins,
          consistent shipping. Admins aren't tracked.
        </p>
      </div>

      {error && <div className="editor-error">{error}</div>}

      {profiles.length === 0 ? (
        <div className="empty-state" style={{ padding: '3rem 1rem', textAlign: 'center', opacity: 0.7 }}>
          No dev profiles yet — invite a non-admin teammate to start the board.
        </div>
      ) : (
        <div className="devprofile-grid">
          {profiles.map((p, i) => (
            <ProfileCard key={p.user_id} profile={p} rank={i + 1} />
          ))}
        </div>
      )}
    </div>
  );
}
