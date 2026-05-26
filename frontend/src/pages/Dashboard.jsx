import React, { useState, useEffect, useCallback } from 'react';
import { listLanes, listMissions, listSessions, getDashboardStats, getLanesStudioSummary, getSystemStatus } from '../api/client';
import TunnelStatus from '../components/TunnelStatus';
import BrandMark from '../components/BrandMark';

const _API_BASE = (import.meta.env.VITE_API_URL || '') + '/api';

function timeAgo(d) {
  if (!d) return '';
  const s = d.includes('T') ? d : d.replace(' ', 'T');
  const ms = Date.now() - new Date(s.endsWith('Z') ? s : s + 'Z').getTime();
  const m = Math.floor(ms / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function fmt(n) {
  if (n === undefined || n === null) return '—';
  if (n >= 1000000) return `$${(n / 1000000).toFixed(2)}M`;
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}k`;
  if (n >= 1) return `$${n.toFixed(2)}`;
  return `$${n.toFixed(4)}`;
}

// RAG palette + neutral for inactive/drafted states. Status colors are the
// only chromatic tokens on the workstation — everything else stays neutral.
const STATUS_COLOR = {
  completed:   'var(--rag-g)',
  running:     'var(--rag-a)',
  failed:      'var(--rag-r)',
  interrupted: 'var(--rag-r)',
  draft:       'var(--text-muted)',
  cancelled:   'var(--text-muted)',
};

// 2-letter mono tags — replace the prior emojis. Industrial, monospaced,
// renders the same at every zoom level. Derived deterministically from the
// lane key so new lanes work without a lookup table edit.
function laneTag(name) {
  const k = (name || '?').toLowerCase().replace(/[^a-z]/g, '');
  if (k.length >= 2) return (k[0] + k[k.length - 1]).toUpperCase();
  return k.toUpperCase().padEnd(2, '·');
}

export default function Dashboard({ navigate }) {
  const [summary, setSummary]       = useState(null);
  const [lanes, setLanes]           = useState([]);
  const [missions, setMissions]     = useState([]);
  const [sessions, setSessions]     = useState([]);
  const [studioSummary, setStudio]  = useState(null);
  const [tunnel, setTunnel]         = useState(null);
  const [clock, setClock]           = useState('');
  const [error, setError]           = useState(null);

  const tick = () => {
    const n = new Date();
    setClock(n.toLocaleDateString('en-AU', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })
      + '  ·  ' + n.toLocaleTimeString('en-AU', { hour: '2-digit', minute: '2-digit' }));
  };

  const load = useCallback(async () => {
    try {
      const [sum, lns, mis, ses, studio, sys] = await Promise.all([
        getDashboardStats(),
        listLanes(),
        listMissions(),
        listSessions(),
        getLanesStudioSummary().catch(() => null),
        getSystemStatus().catch(() => null),
      ]);
      setSummary(sum);
      setLanes(Array.isArray(lns) ? lns : []);
      setMissions(Array.isArray(mis) ? mis : []);
      setSessions(Array.isArray(ses) ? ses : []);
      setStudio(studio);
      setTunnel(sys?.tunnel ?? null);
      setError(null);
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => { tick(); load(); const i = setInterval(load, 5000); const t = setInterval(tick, 30000); return () => { clearInterval(i); clearInterval(t); }; }, [load]);

  // Workstation keyboard shortcuts — only fire when no input/textarea has focus.
  useEffect(() => {
    const SHORTCUTS = {
      p: 'projects',     m: 'missions',      f: 'fleet-config',
      s: 'prompt-studio', r: 'reports',     i: 'integrations',
      h: 'status',
    };
    function onKey(e) {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const tag = (e.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || e.target.isContentEditable) return;
      const dest = SHORTCUTS[e.key.toLowerCase()];
      if (dest) { e.preventDefault(); navigate(dest); }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [navigate]);

  if (error) return (
    <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-secondary)' }}>
      <div style={{ fontSize: 32, marginBottom: 12 }}>⚠️</div>
      <h3 style={{ color: 'var(--text-primary)', marginBottom: 8 }}>Cannot connect to API</h3>
      <p style={{ fontSize: 13 }}>{error}</p>
    </div>
  );

  if (!summary) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh', color: 'var(--text-secondary)', fontSize: 14 }}>
      Connecting to fleet…
    </div>
  );

  // ── Derived data ──────────────────────────────────────────────────────
  const byStatus = missions.reduce((a, m) => { a[m.status] = (a[m.status] || 0) + 1; return a; }, {});
  const running  = sessions.filter(s => s.status === 'running');
  const recent   = [...missions].sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || '')).slice(0, 8);
  const costTotal = sessions.reduce((s, x) => s + (x.total_cost_usd || 0), 0);
  const activeLanes = lanes.filter(l => l.running > 0);

  const fleetRag = summary.running_agents === 0 ? 'g'
                 : summary.free_slots === 0    ? 'r' : 'a';
  const fleetRagLabel = fleetRag === 'g' ? 'IDLE · ALL SYSTEMS GREEN'
                     : fleetRag === 'r' ? 'AT CAPACITY · QUEUE LIVE'
                                        : `${summary.running_agents} RUNNING · ${summary.free_slots} FREE`;

  return (
    <div className="dashboard-page ws">

      {/* ── Workstation toolbar — distinct CTAs ── */}
      <div className="ws-toolbar">
        <div className="ws-crumb">
          <b>WORKSTATION</b>
          <span className="ws-sep">/</span>
          <span>FLEET-01</span>
          <span className="ws-sep">/</span>
          <span>MISSION CONTROL</span>
          <span className={`ws-pill ws-pill--${fleetRag}`}>● {fleetRagLabel}</span>
        </div>
        <div className="ws-actions">
          <button className="ws-btn"            onClick={() => navigate('reports')}>REPORTS</button>
          <button className="ws-btn"            onClick={() => navigate('fleet-config')}>FLEET CONFIG</button>
          <button className="ws-btn"            onClick={() => navigate('prompt-studio')}>PROMPT STUDIO</button>
          <button className="ws-btn ws-btn--primary" onClick={() => navigate('missions')}>OPEN MISSION BOARD</button>
        </div>
      </div>

      {/* ── Workstation heading — fluid type, no decorative gradient ── */}
      <div className="ws-heading">
        <div>
          <div className="ws-pre">FLEET STATE · {new Date().toISOString().slice(0,10)}</div>
          <h1 className="ws-h1">
            FLEET{' '}
            <span className={`ws-h1-accent ws-h1-accent--${fleetRag}`}>
              {fleetRag === 'g' ? 'IDLE.' : fleetRag === 'r' ? 'AT CAPACITY.' : 'RUNNING.'}
            </span>
            <br/>
            <span className="ws-h1-dim">
              {summary.running_agents} OF {summary.total_slots} SLOTS LIVE.
            </span>
          </h1>
        </div>
        <div className="ws-corner">
          <div>{clock}</div>
          <div>SPEND TODAY · <b>{fmt(summary.cost_today_usd)}</b></div>
          <div>TOTAL SPEND · <b>{fmt(costTotal)}</b></div>
          {tunnel && (
            <div>
              TUNNEL ·{' '}
              <span className={tunnel.connected ? 'ws-ok' : 'ws-err'}>
                ● {tunnel.connected ? 'LIVE' : 'DOWN'}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* ── Tunnel status ── */}
      <TunnelStatus tunnel={tunnel} />

      {/* ── Active agents alert ── */}
      {running.length > 0 && (
        <div className="dash-alert" onClick={() => navigate('missions')}>
          <span className="pulse-dot" />
          <span><b>{running.length} agent{running.length > 1 ? 's' : ''} running</b> — click to view missions</span>
          <span className="dash-alert-arrow">→</span>
        </div>
      )}

      {/* ── KPI strip — RAG/neutral only ── */}
      <div className="dash-stats">
        {[
          { label: 'Projects',   val: missions.length ? [...new Set(missions.map(m => m.project_id))].length : 0, tone: 'neutral', click: 'projects' },
          { label: 'Missions',   val: missions.length, tone: 'neutral', click: 'missions' },
          { label: 'Completed',  val: byStatus.completed || 0, tone: 'g', click: 'missions' },
          { label: 'Running',    val: summary.running_agents, tone: summary.running_agents > 0 ? 'a' : 'neutral', click: 'missions' },
          { label: 'Free Slots', val: summary.free_slots ?? 0, tone: 'neutral', click: 'fleet-config' },
          { label: 'Cost Today', val: fmt(summary.cost_today_usd), tone: 'neutral', click: null },
        ].map(({ label, val, tone, click }) => (
          <div
            key={label}
            className={`dash-stat-card dash-stat-card--${tone}`}
            onClick={click ? () => navigate(click) : undefined}
            style={{ cursor: click ? 'pointer' : 'default' }}
          >
            <div className="dash-stat-val">{val}</div>
            <div className="dash-stat-label">{label}</div>
          </div>
        ))}
      </div>

      {/* ── Main grid ── */}
      <div className="dash-grid">

        {/* Lane topology */}
        <div className="dash-card">
          <div className="dash-card-header">
            <span>Fleet Lanes</span>
            <button className="dash-card-btn" onClick={() => navigate('fleet-config')}>Configure →</button>
          </div>
          <div className="lane-topology">
            {lanes.map(l => {
              const ratio = l.max_agents ? l.running / l.max_agents : 0;
              const rag = l.running === 0 ? 'g' : ratio >= 1 ? 'r' : 'a';
              return (
                <div key={l.name} className={`lane-row lane-row--${rag}`}>
                  <span className="lane-row-tag">{laneTag(l.name)}</span>
                  <span className="lane-row-name">{l.name.replace('_', ' ')}</span>
                  <div className="lane-row-bar">
                    <div className="lane-row-fill" style={{ width: `${ratio * 100}%` }} />
                  </div>
                  <span className="lane-row-count">{l.running}/{l.max_agents}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Recent missions */}
        <div className="dash-card">
          <div className="dash-card-header">
            <span>Recent Missions</span>
            <button className="dash-card-btn" onClick={() => navigate('missions')}>All →</button>
          </div>
          <div className="mission-list">
            {recent.map(m => (
              <div key={m.id} className="mission-row" onClick={() => navigate('mission', m.id)}>
                <span className="mission-row-dot" style={{ background: STATUS_COLOR[m.status] || '#888' }} />
                <span className="mission-row-title">{m.title}</span>
                <span className="mission-row-time">{timeAgo(m.updated_at)}</span>
              </div>
            ))}
            {recent.length === 0 && <div className="dash-empty">No missions yet — create a project to start</div>}
          </div>
        </div>

        {/* Mission status breakdown */}
        <div className="dash-card">
          <div className="dash-card-header"><span>Mission Status</span></div>
          <div className="status-breakdown">
            {Object.entries(STATUS_COLOR).map(([s, c]) => byStatus[s] ? (
              <div key={s} className="status-row" onClick={() => navigate('missions')}>
                <span className="status-dot" style={{ background: c }} />
                <span className="status-name">{s}</span>
                <span className="status-bar-wrap">
                  <span className="status-bar-fill" style={{ width: `${(byStatus[s] / missions.length) * 100}%`, background: c + '40', borderRight: `2px solid ${c}` }} />
                </span>
                <span className="status-count" style={{ color: c }}>{byStatus[s]}</span>
              </div>
            ) : null)}
          </div>
        </div>

        {/* Quick actions — typographic, no emoji */}
        <div className="dash-card">
          <div className="dash-card-header"><span>Quick Actions</span></div>
          <div className="quick-actions">
            {[
              { kbd: 'P', label: 'New Project',    sub: 'Start a new codebase or task group',   page: 'projects' },
              { kbd: 'M', label: 'Mission Board',  sub: 'Browse and dispatch pending missions', page: 'missions' },
              { kbd: 'F', label: 'Fleet Config',   sub: 'Lane capacity, models, presets',       page: 'fleet-config' },
              { kbd: 'S', label: 'Prompt Studio',  sub: 'Lane prompts and MCP tool toggles',    page: 'prompt-studio' },
              { kbd: 'R', label: 'Reports',        sub: 'Browse filed agent reports',            page: 'reports' },
              { kbd: 'I', label: 'Integrations',   sub: 'MCP servers, external tool wiring',     page: 'integrations' },
              { kbd: 'H', label: 'System Status',  sub: 'Health monitor and incident log',       page: 'status' },
            ].map(({ kbd, label, sub, page }) => (
              <div key={label} className="quick-action-row" onClick={() => navigate(page)}>
                <span className="qa-kbd">{kbd}</span>
                <div className="qa-text">
                  <div className="qa-label">{label}</div>
                  <div className="qa-sub">{sub}</div>
                </div>
                <span className="qa-arrow">→</span>
              </div>
            ))}
          </div>
        </div>

        {/* Prompt Studio summary */}
        {studioSummary && (
          <div className="dash-card">
            <div className="dash-card-header">
              <span>Prompt Studio</span>
              <button className="dash-card-btn" onClick={() => navigate('prompt-studio')}>Open Studio →</button>
            </div>
            <div className="studio-summary">
              <div className="studio-stat">
                <span className="studio-stat-val">{studioSummary.customized_count}</span>
                <span className="studio-stat-label">/ {studioSummary.total_lanes} lanes customised</span>
              </div>
              <div className="studio-stat">
                <span className="studio-stat-val">{studioSummary.disabled_tools_count}</span>
                <span className="studio-stat-label"> MCP tools disabled</span>
              </div>
              <div className="studio-stat">
                <span className="studio-stat-val">{studioSummary.critiques_available}</span>
                <span className="studio-stat-label"> Opus critiques stored</span>
              </div>
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
