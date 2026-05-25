import React, { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { projectChat, getBotHistory, createMission } from '../api/client';
import { useAuth } from '../auth';
import Moofasa from './Moofasa';
import PlanActions from './PlanActions';

function parseMissionBlock(content) {
  const m = content.match(/```mission\s*\n([\s\S]*?)\n```/);
  if (!m) return null;
  try { return JSON.parse(m[1]); } catch { return null; }
}

const PERSONA_META = {
  researcher: { label: 'Researcher', model: 'Haiku', color: '#5bb8a6' },
  git_operator: { label: 'Git Operator', model: 'Sonnet', color: '#d49a3a' },
  architect: { label: 'Architect', model: 'Opus', color: '#7a6cd0' },
};

function PersonaBadge({ persona }) {
  const meta = PERSONA_META[persona];
  if (!meta) return null;
  return (
    <span
      title={`${meta.label} (${meta.model})`}
      style={{
        display: 'inline-block',
        fontSize: 10,
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: 0.4,
        padding: '2px 6px',
        marginRight: 6,
        borderRadius: 4,
        color: meta.color,
        border: `1px solid ${meta.color}55`,
        background: `${meta.color}1a`,
      }}
    >
      {meta.label}
    </span>
  );
}

function HandoffCard({ handoff, onOpen }) {
  return (
    <div className="moofasa-draft">
      <div className="moofasa-draft__label">Git Operator handoff</div>
      <div className="moofasa-draft__criteria">
        This turn runs as an agent session so you can watch tool calls and approve
        destructive operations in the Live Agent view.
      </div>
      <button
        className="btn btn-primary"
        style={{ fontSize: 12, padding: '5px 12px' }}
        onClick={() => onOpen(handoff.session_id)}
      >
        Open Live Agent →
      </button>
    </div>
  );
}

function UserLabel({ email, githubLogin, currentEmail }) {
  if (!email && !githubLogin) return null;
  const isYou = currentEmail && email === currentEmail;
  const display = isYou
    ? 'You'
    : (githubLogin || (email ? email.split('@')[0] : ''));
  if (!display) return null;
  return (
    <div style={{
      fontSize: 10, opacity: 0.65, marginBottom: 4,
      textTransform: 'uppercase', letterSpacing: 0.4, fontWeight: 600,
      color: 'var(--text-muted)',
    }}>{display}</div>
  );
}

function MessageContent({ msg, projectId, onCreateMission, onOpenSession, currentEmail }) {
  const content = msg.content || '';
  const draft = parseMissionBlock(content);
  const displayText = content.replace(/```mission[\s\S]*?```/g, '').trim();
  const isAssistant = msg.role === 'assistant';
  return (
    <>
      {isAssistant && msg.persona && (
        <div style={{ marginBottom: 6 }}>
          <PersonaBadge persona={msg.persona} />
        </div>
      )}
      {!isAssistant && (
        <UserLabel
          email={msg.user_email}
          githubLogin={msg.github_login}
          currentEmail={currentEmail}
        />
      )}
      {displayText && (
        isAssistant ? (
          <div className="moofasa-markdown">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayText}</ReactMarkdown>
          </div>
        ) : (
          <div style={{ whiteSpace: 'pre-wrap' }}>{displayText}</div>
        )
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
      {msg.handoff && (
        <HandoffCard handoff={msg.handoff} onOpen={onOpenSession} />
      )}
      {msg.is_plan && msg.id && (
        <PlanActions projectId={projectId} planId={msg.id} planTitle={msg.plan_title} />
      )}
    </>
  );
}

export default function ProjectBot({ projectId, projectName, onClose, navigate }) {
  const { user } = useAuth();
  const currentEmail = user?.email || null;
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
          setMessages(rows.map(r => {
            const content = r.handoff_session_id ? '' : (r.content || '');
            // TEMP DEBUG: surface rows that come in with content but render empty
            if (r.role === 'user' && (r.content || '').length > 0 && content.length === 0) {
              // Should be unreachable for non-handoff user rows
              // eslint-disable-next-line no-console
              console.warn('[ProjectBot] user row blanked at load', {
                id: r.id, hsid: r.handoff_session_id, raw_len: r.content.length,
              });
            }
            return {
              id: r.id,
              role: r.role,
              content,
              is_plan: !!r.is_plan,
              plan_title: r.plan_title,
              persona: r.persona || null,
              user_email: r.user_email || null,
              github_login: r.github_login || null,
              handoff: r.handoff_session_id
                ? { session_id: r.handoff_session_id }
                : undefined,
            };
          }));
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
    setMessages(prev => [...prev, { role: 'user', content: text, user_email: currentEmail }]);
    setStreaming(true);

    let botMsg = '';
    setMessages(prev => [...prev, { role: 'assistant', content: '', _streaming: true }]);

    let currentPersona = null;
    let handoff = null;
    let errored = false;

    projectChat(projectId, text, {
      planner_mode: wasPlanner,
      onPersona: (data) => {
        currentPersona = data.persona;
        setMessages(prev => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (!last?._streaming) return prev;
          updated[updated.length - 1] = { ...last, persona: currentPersona };
          return updated;
        });
      },
      onSessionHandoff: (data) => {
        handoff = data;
      },
      onText: (chunk) => {
        botMsg += chunk;
        setMessages(prev => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (!last?._streaming) return prev;
          updated[updated.length - 1] = {
            role: 'assistant',
            content: botMsg,
            persona: currentPersona,
            _streaming: true,
          };
          return updated;
        });
      },
      onPlanMeta: (meta) => {
        setMessages(prev => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (!last?._streaming) return prev;
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
        if (errored) return; // onError already cleaned up; never touch the user bubble
        setMessages(prev => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (!last?._streaming) return prev;
          updated[updated.length - 1] = {
            ...last,
            content: handoff ? '' : botMsg,
            persona: currentPersona,
            handoff: handoff || undefined,
            _streaming: false,
          };
          return updated;
        });
        requestAnimationFrame(() => inputRef.current?.focus());
      },
      onError: (err) => {
        errored = true;
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
                {msg.persona && <PersonaBadge persona={msg.persona} />}
                {msg.content}
                <span className="moofasa-cursor" />
              </span>
            ) : (
              <MessageContent
                msg={msg}
                projectId={projectId}
                onCreateMission={handleCreateMission}
                onOpenSession={(sid) => navigate?.('live', sid)}
                currentEmail={currentEmail}
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
          {!plannerMode && (
            <span
              className="moofasa-toggler__cost"
              title="Prefix your message with a slash to pick a persona"
              style={{ opacity: 0.6 }}
            >
              /haiku · /sonnet · /opus
            </span>
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
