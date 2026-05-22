import React, { useState, useEffect, useRef } from 'react';
import { projectChat, getBotHistory, createMission } from '../api/client';
import Moofasa from './Moofasa';
import PlanActions from './PlanActions';

function parseMissionBlock(content) {
  const m = content.match(/```mission\s*\n([\s\S]*?)\n```/);
  if (!m) return null;
  try { return JSON.parse(m[1]); } catch { return null; }
}

function MessageContent({ msg, projectId, onCreateMission }) {
  const draft = parseMissionBlock(msg.content);
  const displayText = msg.content.replace(/```mission[\s\S]*?```/g, '').trim();
  return (
    <>
      {displayText && (
        <div style={{ whiteSpace: 'pre-wrap' }}>{displayText}</div>
      )}
      {draft && (
        <div className="moofasa-draft">
          <div className="moofasa-draft__label">Mission Draft</div>
          <div className="moofasa-draft__title">{draft.title}</div>
          {draft.acceptance_criteria && (
            <div className="moofasa-draft__criteria">{draft.acceptance_criteria}</div>
          )}
          <button
            className="btn btn-primary"
            style={{ fontSize: 12, padding: '5px 12px' }}
            onClick={() => onCreateMission(draft)}
          >
            Create Mission →
          </button>
        </div>
      )}
      {msg.is_plan && msg.id && (
        <PlanActions projectId={projectId} planId={msg.id} planTitle={msg.plan_title} />
      )}
    </>
  );
}

export default function ProjectBot({ projectId, projectName, onClose }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [plannerMode, setPlannerMode] = useState(false);
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  const welcomeMsg = `Hi, I'm Moofasa — your DevFleet assistant for ${projectName}. Tell me what to build and I'll draft a mission, or flip Planner mode for a full roadmap.`;

  useEffect(() => {
    getBotHistory(projectId)
      .then((rows) => {
        if (rows.length === 0) {
          setMessages([{ role: 'assistant', content: welcomeMsg }]);
        } else {
          setMessages(rows.map(r => ({
            id: r.id,
            role: r.role,
            content: r.content,
            is_plan: !!r.is_plan,
            plan_title: r.plan_title,
          })));
        }
      })
      .catch(() => {
        setMessages([{ role: 'assistant', content: welcomeMsg }]);
      })
      .finally(() => {
        setLoading(false);
        // Focus input after first paint so the user can type immediately.
        requestAnimationFrame(() => inputRef.current?.focus());
      });
  }, [projectId, projectName]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const sendMessage = () => {
    const text = input.trim();
    if (!text || streaming) return;
    if (plannerMode && !window.confirm(
      'Planner mode uses Opus and may take 30+ seconds. Continue?'
    )) {
      return;
    }
    const wasPlanner = plannerMode;
    setInput('');
    setError(null);
    setMessages(prev => [...prev, { role: 'user', content: text }]);
    setStreaming(true);

    let botMsg = '';
    setMessages(prev => [...prev, { role: 'assistant', content: '', _streaming: true }]);

    projectChat(projectId, text, {
      planner_mode: wasPlanner,
      onText: (chunk) => {
        botMsg += chunk;
        setMessages(prev => {
          const updated = [...prev];
          updated[updated.length - 1] = { role: 'assistant', content: botMsg, _streaming: true };
          return updated;
        });
      },
      onPlanMeta: (meta) => {
        setMessages(prev => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          updated[updated.length - 1] = {
            ...last,
            id: meta.id,
            is_plan: true,
            plan_title: meta.title,
          };
          return updated;
        });
      },
      onDone: () => {
        setStreaming(false);
        setMessages(prev => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          updated[updated.length - 1] = { ...last, content: botMsg, _streaming: false };
          return updated;
        });
        requestAnimationFrame(() => inputRef.current?.focus());
      },
      onError: (err) => {
        setStreaming(false);
        setError(String(err));
        setMessages(prev => prev.filter(m => !m._streaming));
      },
    });

    if (wasPlanner) setPlannerMode(false);
  };

  const handleCreateMission = async (draft) => {
    try {
      await createMission({ ...draft, project_id: projectId, status: 'draft' });
      setMessages(prev => [
        ...prev,
        { role: 'assistant', content: '✓ Mission created as a draft. Dispatch it from the mission board when ready.' },
      ]);
    } catch (e) {
      setError(e.message || 'Failed to create mission');
    }
  };

  if (loading) {
    return (
      <div className="moofasa-panel" style={{ alignItems: 'center', justifyContent: 'center' }}>
        <span style={{ color: 'var(--text-muted)', fontSize: 13 }}>Loading…</span>
      </div>
    );
  }

  return (
    <div className="moofasa-panel">
      <div className="moofasa-panel__header">
        <span className="moofasa-panel__title">
          <Moofasa size={20} state={streaming ? 'thinking' : 'idle'} />
          <span>Moofasa</span>
        </span>
        <button
          className="moofasa-panel__close"
          onClick={onClose}
          title="Close Moofasa"
          aria-label="Close"
        >×</button>
      </div>

      <div className="moofasa-panel__messages">
        {messages.map((msg, i) => (
          <div
            key={msg.id ?? i}
            className={`moofasa-bubble moofasa-bubble--${msg.role}`}
          >
            {msg._streaming ? (
              <span style={{ opacity: 0.92 }}>
                {msg.content}
                <span className="moofasa-cursor" />
              </span>
            ) : (
              <MessageContent
                msg={msg}
                projectId={projectId}
                onCreateMission={handleCreateMission}
              />
            )}
          </div>
        ))}
        {error && <div className="moofasa-error">{error}</div>}
        <div ref={bottomRef} />
      </div>

      <div className="moofasa-panel__inputcol">
        <div className="moofasa-toggler">
          <label
            className="planner-switch"
            title="Use Opus to produce a full multi-phase markdown plan (~30s, higher cost)"
          >
            <input
              type="checkbox"
              checked={plannerMode}
              onChange={e => setPlannerMode(e.target.checked)}
              disabled={streaming}
            />
            <span className="planner-switch__track" />
            <span>Planner mode</span>
          </label>
          {plannerMode && (
            <span className="moofasa-toggler__cost">Opus · slower · costlier</span>
          )}
        </div>
        <div className="moofasa-panel__inputrow">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
              }
            }}
            placeholder={plannerMode
              ? 'Describe the plan you need…'
              : 'Ask Moofasa to draft a mission…'}
            disabled={streaming}
            rows={2}
            className="moofasa-input"
          />
          <button
            className="btn btn-primary moofasa-send"
            onClick={sendMessage}
            disabled={streaming || !input.trim()}
          >
            →
          </button>
        </div>
      </div>
    </div>
  );
}
