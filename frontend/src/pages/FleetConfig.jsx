import React, { useEffect, useState, useCallback } from 'react';
import {
  getSystemStatus, setGlobalCeiling, listLanes, updateLane,
  createLane, deleteLane,
} from '../api/client';

const MODELS = [
  'claude-sonnet-4-6',
  'claude-opus-4-7',
  'claude-haiku-4-5-20251001',
];

const LANE_NAME_RE = /^[a-z][a-z0-9_]{1,30}$/;

function LaneEditor({ lane, onSave, onClose, onDeleted, navigate }) {
  // Capacity / model / enabled only. Prompt authoring lives in Prompt Studio —
  // a single source of truth avoids divergent edits across two surfaces.
  const [form, setForm] = useState({
    max_agents: lane.max_agents ?? 1,
    default_model: lane.default_model ?? 'claude-sonnet-4-6',
    enabled: lane.enabled ?? true,
  });
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState(null);

  // Built-ins are protected at the backend (lanes.delete_lane refuses any
  // name in LANE_DEFAULTS), so we hide the button rather than letting users
  // click into a guaranteed 409.
  const canDelete = Boolean(lane.user_created);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await updateLane(lane.name, form);
      onSave(updated);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm(`Delete lane '${lane.name}'? This removes its prompt and MCP tool config. This cannot be undone.`)) return;
    setDeleting(true);
    setError(null);
    try {
      await deleteLane(lane.name);
      if (onDeleted) onDeleted(lane.name);
    } catch (e) {
      setError(e.message);
      setDeleting(false);
    }
  };

  const goToPromptStudio = () => {
    // Pass the lane via sessionStorage so PromptStudio can preselect it on mount.
    // Keeps the App.jsx navigate API (pageName, id) untouched.
    try {
      sessionStorage.setItem('devfleet:prompt-studio:lane', lane.name);
    } catch { /* sessionStorage may be unavailable in some embedded contexts */ }
    onClose();
    if (navigate) navigate('prompt-studio');
  };

  return (
    <div className="lane-editor-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="lane-editor-modal">
        <div className="lane-editor-header">
          <span style={{ fontSize: '1.5rem' }}>{lane.icon}</span>
          <h2>{lane.name.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase())} Lane</h2>
          <button className="close-btn" onClick={onClose}>✕</button>
        </div>

        <div className="lane-editor-body">
          <div className="field-row">
            <label>Max Concurrent Agents</label>
            <input
              type="number"
              min={0}
              max={10}
              value={form.max_agents}
              onChange={e => setForm(f => ({ ...f, max_agents: parseInt(e.target.value) || 0 }))}
            />
          </div>

          <div className="field-row">
            <label>Default Model</label>
            <select
              value={form.default_model}
              onChange={e => setForm(f => ({ ...f, default_model: e.target.value }))}
            >
              {MODELS.map(m => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>

          <div className="field-row">
            <label>
              <input
                type="checkbox"
                checked={form.enabled}
                onChange={e => setForm(f => ({ ...f, enabled: e.target.checked }))}
              />
              {' '}Lane enabled
            </label>
          </div>

          <div className="lane-editor-prompt-link">
            <div>
              <div className="lane-editor-prompt-link__title">System prompt + MCP tools</div>
              <div className="lane-editor-prompt-link__hint">
                Authored in Prompt Studio — structured rules, quality gates, tool allowlist, Opus critique.
              </div>
            </div>
            <button className="btn btn-secondary" onClick={goToPromptStudio}>
              Edit full prompt →
            </button>
          </div>

          {error && <div className="editor-error">{error}</div>}
        </div>

        <div className="lane-editor-footer" style={{ display: 'flex', justifyContent: 'space-between' }}>
          <div>
            {canDelete && (
              <button
                onClick={handleDelete}
                disabled={deleting || saving}
                title="Delete this user-created lane"
                style={{
                  background: 'transparent',
                  color: 'var(--danger, #e54)',
                  border: '1px solid var(--danger, #e54)',
                  padding: '6px 12px',
                  borderRadius: 6,
                  cursor: deleting ? 'wait' : 'pointer',
                  fontSize: 13,
                }}
              >
                {deleting ? 'Deleting…' : '🗑  Delete Lane'}
              </button>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn-cancel" onClick={onClose}>Cancel</button>
            <button className="btn-save" onClick={handleSave} disabled={saving || deleting}>
              {saving ? 'Saving…' : 'Save Changes'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function NewLaneModal({ onCreated, onClose, navigate }) {
  const [form, setForm] = useState({
    name: '',
    icon: '🧩',
    max_agents: 1,
    default_model: 'claude-sonnet-4-6',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const nameValid = LANE_NAME_RE.test(form.name);
  const canSave = nameValid && form.max_agents >= 1 && !saving;

  const handleCreate = async () => {
    setSaving(true);
    setError(null);
    try {
      const created = await createLane(form);
      try {
        sessionStorage.setItem('devfleet:prompt-studio:lane', created.name);
      } catch { /* sessionStorage may be unavailable */ }
      onCreated(created);
      if (navigate) navigate('prompt-studio');
    } catch (e) {
      setError(e.message || 'Failed to create lane');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="lane-editor-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="lane-editor-modal">
        <div className="lane-editor-header">
          <span style={{ fontSize: '1.5rem' }}>{form.icon || '🧩'}</span>
          <h2>New Lane</h2>
          <button className="close-btn" onClick={onClose}>✕</button>
        </div>

        <div className="lane-editor-body">
          <div className="field-row">
            <label>Name</label>
            <input
              type="text"
              value={form.name}
              onChange={e => setForm(f => ({ ...f, name: e.target.value.toLowerCase() }))}
              placeholder="docs_writer"
              autoFocus
            />
            <div className="field-hint">
              Lowercase letters, digits, underscores. Starts with a letter. e.g. <code>docs_writer</code>, <code>migrator</code>.
              {form.name && !nameValid && (
                <span style={{ color: 'var(--danger, #e54)', marginLeft: 8 }}>
                  Invalid format
                </span>
              )}
            </div>
          </div>

          <div className="field-row">
            <label>Icon (emoji)</label>
            <input
              type="text"
              value={form.icon}
              onChange={e => setForm(f => ({ ...f, icon: e.target.value.slice(0, 4) }))}
              maxLength={4}
              style={{ width: 80, fontSize: 20, textAlign: 'center' }}
            />
          </div>

          <div className="field-row">
            <label>Max Concurrent Agents</label>
            <input
              type="number"
              min={1}
              max={10}
              value={form.max_agents}
              onChange={e => setForm(f => ({ ...f, max_agents: parseInt(e.target.value) || 1 }))}
            />
          </div>

          <div className="field-row">
            <label>Default Model</label>
            <select
              value={form.default_model}
              onChange={e => setForm(f => ({ ...f, default_model: e.target.value }))}
            >
              {MODELS.map(m => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>

          <div className="field-hint" style={{ marginTop: 12, opacity: 0.7 }}>
            System prompt starts blank — you'll be sent to Prompt Studio to author it after Save.
          </div>

          {error && <div className="editor-error">{error}</div>}
        </div>

        <div className="lane-editor-footer">
          <button className="btn-cancel" onClick={onClose}>Cancel</button>
          <button className="btn-save" onClick={handleCreate} disabled={!canSave}>
            {saving ? 'Creating…' : 'Create + Author Prompt →'}
          </button>
        </div>
      </div>
    </div>
  );
}

const CEILING_PRESETS = [0, 1, 2, 3, 4, 6, 8, 12, 18];

function CeilingPicker({ ceiling, onChange }) {
  const [saving, setSaving] = useState(false);

  const pick = async (n) => {
    setSaving(true);
    try {
      await setGlobalCeiling(n);
      onChange(n);
    } catch (e) {
      console.error('Failed to set ceiling', e);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="ceiling-picker-section">
      <div className="ceiling-picker-label">
        <span className="ceiling-title">Global Agent Ceiling</span>
        <span className="ceiling-hint">
          {ceiling === 0
            ? 'Off — each lane enforces its own cap'
            : `Hard cap: max ${ceiling} agent${ceiling === 1 ? '' : 's'} running at once across all lanes`}
        </span>
      </div>
      <div className="ceiling-btn-row">
        {CEILING_PRESETS.map(n => (
          <button
            key={n}
            className={`ceiling-btn ${ceiling === n ? 'active' : ''}`}
            onClick={() => pick(n)}
            disabled={saving}
            title={n === 0 ? 'No global cap' : `Max ${n} agents`}
          >
            {n === 0 ? 'Off' : n}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function FleetConfig({ navigate }) {
  const [lanes, setLanes] = useState([]);
  const [ceiling, setCeiling] = useState(0);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [lanesRes, statusRes] = await Promise.all([
        listLanes(),
        getSystemStatus(),
      ]);
      setLanes(lanesRes);
      setCeiling(statusRes.max_agents ?? 0);
    } catch (e) {
      console.error('Failed to load fleet config', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleSaved = (updated) => {
    setLanes(ls => ls.map(l => l.name === updated.name ? { ...l, ...updated } : l));
    setEditing(null);
  };

  const totalSlots = lanes.reduce((s, l) => s + (l.enabled ? (l.max_agents ?? 0) : 0), 0);

  if (loading) return <div className="page-loading">Loading fleet config…</div>;

  return (
    <div className="fleet-config-page">
      <div className="fleet-config-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
        <div>
          <h1>Fleet Configuration</h1>
          <p className="subtitle">{lanes.length} lanes · {totalSlots} total slots · click any lane to edit capacity &amp; model (prompt lives in Prompt Studio)</p>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => setCreating(true)}
          title="Create a new lane"
          style={{ whiteSpace: 'nowrap' }}
        >
          + New Lane
        </button>
      </div>

      <CeilingPicker ceiling={ceiling} onChange={setCeiling} />

      <div className="lane-grid">
        {lanes.map(lane => (
          <div
            key={lane.name}
            className={`lane-card ${!lane.enabled ? 'disabled' : ''}`}
            style={{ '--lane-color': lane.color || '#888' }}
            onClick={() => setEditing(lane)}
          >
            <div className="lane-card-top">
              <span className="lane-icon">{lane.icon}</span>
              <div className="lane-meta">
                <div className="lane-name">{lane.name.replace('_', ' ')}</div>
                <div className="lane-model">{lane.default_model?.replace('claude-', '').replace('-4-', ' 4.')}</div>
              </div>
              <div className="lane-slots">
                <span className="slot-running">{lane.running ?? 0}</span>
                <span className="slot-sep">/</span>
                <span className="slot-max">{lane.max_agents}</span>
              </div>
            </div>
            {/* Prompt preview removed — Prompt Studio is the authoring surface.
                Card now stays focused on capacity + status. */}
            <div className="lane-card-footer">
              <span className={`lane-status-dot ${lane.enabled ? 'active' : 'inactive'}`} />
              <span>{lane.enabled ? 'active' : 'disabled'}</span>
              <span className="edit-hint">✎ edit</span>
            </div>
          </div>
        ))}
      </div>

      {editing && (
        <LaneEditor
          lane={editing}
          onSave={handleSaved}
          onClose={() => setEditing(null)}
          onDeleted={(name) => {
            setLanes(ls => ls.filter(l => l.name !== name));
            setEditing(null);
          }}
          navigate={navigate}
        />
      )}

      {creating && (
        <NewLaneModal
          onCreated={() => { setCreating(false); load(); }}
          onClose={() => setCreating(false)}
          navigate={navigate}
        />
      )}
    </div>
  );
}
